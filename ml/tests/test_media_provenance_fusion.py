import json

import pytest

from aegis_ml import fixtures
from aegis_ml.audio.analysis import AudioSignalMethod
from aegis_ml.core import Modality, RunStatus
from aegis_ml.fusion import fuse
from aegis_ml.image.analysis import (ErrorLevelAnalysisMethod, FrequencySpectrumMethod, ImageMetadataMethod,
                                     NoiseResidualMethod)
from aegis_ml.provenance.c2pa_verifier import C2PAVerifier, DeclaredMetadataMethod
from aegis_ml.providers import HttpDetectorProvider, ProviderResponseError, validate_provider_response
from aegis_ml.registry import PROFILES, build_registry, methods_for
from aegis_ml.video.analysis import TemporalConsistencyMethod, VideoContainerMethod


def test_image_methods(jpeg, make_input):
    inp = make_input(jpeg, Modality.IMAGE, "image/jpeg")
    meta = ImageMetadataMethod().run(inp)
    assert meta.status == RunStatus.COMPLETED and meta.output["width"] == 640
    assert meta.output["exif"]["Software"] == "DemoCam 1.0"
    assert 80 <= meta.output["jpeg"]["estimated_quality"] <= 95
    for m in (FrequencySpectrumMethod(), NoiseResidualMethod(), ErrorLevelAnalysisMethod()):
        r = m.run(inp)
        assert r.status == RunStatus.COMPLETED, r.error
        assert r.artifacts and r.artifacts[0].data.startswith(b"\x89PNG")
        assert r.score is None and r.flagged is None  # observations, never scores
        assert r.artifacts[0].cannot_establish


def test_ela_skips_png(tmp_path, make_input):
    png = fixtures.make_png_with_declaration(tmp_path / "a.png")
    r = ErrorLevelAnalysisMethod().run(make_input(png, Modality.IMAGE, "image/png"))
    assert r.status == RunStatus.UNSUPPORTED_INPUT


def test_declared_metadata(tmp_path, make_input):
    png = fixtures.make_png_with_declaration(tmp_path / "a.png")
    r = DeclaredMetadataMethod().run(make_input(png, Modality.IMAGE, "image/png"))
    assert "stable diffusion" in r.output["generator_markers"]
    assert r.evidence_class == "declared_metadata"


def test_corrupt_image_fails_explicitly(tmp_path, make_input):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)
    r = ImageMetadataMethod().run(make_input(bad, Modality.IMAGE, "image/jpeg"))
    assert r.status == RunStatus.FAILED and r.error


def test_audio_signal(wav, make_input):
    r = AudioSignalMethod().run(make_input(wav, Modality.AUDIO, "audio/wav"))
    assert r.status == RunStatus.COMPLETED, r.error
    assert r.output["native_sample_rate"] == 16000 and abs(r.output["duration_seconds"] - 3.0) < 0.05
    assert r.output["silence_fraction"] > 0.1
    assert {a.name for a in r.artifacts} == {"waveform.png", "spectrogram.png"}


def test_corrupt_audio_fails(tmp_path, make_input):
    p = fixtures.wav_header_only(tmp_path / "x.wav")
    r = AudioSignalMethod().run(make_input(p, Modality.AUDIO, "audio/wav"))
    assert r.status in (RunStatus.FAILED, RunStatus.INSUFFICIENT_INPUT, RunStatus.UNSUPPORTED_INPUT)


def test_video_methods(mp4, make_input):
    inp = make_input(mp4, Modality.VIDEO, "video/mp4", options={"sample_fps": 4})
    c = VideoContainerMethod().run(inp)
    assert c.status == RunStatus.COMPLETED, c.error
    assert {s["type"] for s in c.output["streams"]} == {"video", "audio"}
    t = TemporalConsistencyMethod().run(inp)
    assert t.status == RunStatus.COMPLETED, t.error
    assert t.output["sampled_frames"] >= 10 and t.output["keyframe_count"] >= 1
    a = AudioSignalMethod().run(inp)
    assert a.status == RunStatus.COMPLETED


def test_c2pa_states(tmp_path, make_input, jpeg, monkeypatch):
    signed = tmp_path / "signed.jpg"
    ca = fixtures.make_c2pa_signed_jpeg(signed, tmp_path)
    v = C2PAVerifier()
    monkeypatch.delenv("AEGIS_C2PA_TRUST_ANCHORS", raising=False)
    r = v.run(make_input(signed, Modality.IMAGE, "image/jpeg"))
    assert r.output["state"] == "signature_valid_signer_untrusted", r.output
    assert r.output["declared_ai_source"] is True
    monkeypatch.setenv("AEGIS_C2PA_TRUST_ANCHORS", str(ca))
    r = v.run(make_input(signed, Modality.IMAGE, "image/jpeg"))
    assert r.output["state"] == "signature_valid_signer_trusted"
    assert "Verification succeeded for the supported provenance record" in r.summary
    bad = fixtures.tamper(signed, tmp_path / "tampered.jpg")
    r = v.run(make_input(bad, Modality.IMAGE, "image/jpeg"))
    assert r.output["state"] == "verification_failed"
    assert "assertion.dataHash.mismatch" in r.output["failure_codes"]
    r = v.run(make_input(jpeg, Modality.IMAGE, "image/jpeg"))
    assert r.output["state"] == "no_manifest" and r.summary == "No supported provenance record found."


def test_provider_contract_validation(monkeypatch, jpeg, make_input):
    assert validate_provider_response({"score": 0.3, "model_version": "v1"})["score"] == 0.3
    for bad in ({"score": "x", "model_version": "v"}, {"score": float("nan"), "model_version": "v"},
                {"score": 1, "model_version": ""}, {"score": 1, "model_version": "v", "request_id": "<script>"},
                [], {"score": True, "model_version": "v"}):
        with pytest.raises(ProviderResponseError):
            validate_provider_response(bad)
    p = HttpDetectorProvider("image_detector", Modality.IMAGE, "x")
    inp = make_input(jpeg, Modality.IMAGE, "image/jpeg")
    assert p.run(inp).status == RunStatus.BLOCKED_BY_POLICY  # external processing off by default
    inp.allow_external_processing = True
    monkeypatch.delenv("AEGIS_PROVIDER_IMAGE_DETECTOR_URL", raising=False)
    assert p.run(inp).status == RunStatus.UNAVAILABLE
    monkeypatch.setenv("AEGIS_PROVIDER_IMAGE_DETECTOR_URL", "http://insecure.example")
    assert p.run(inp).status == RunStatus.UNAVAILABLE


def test_profiles_reference_registered_methods():
    reg = build_registry()
    for p in PROFILES.values():
        assert set(p.methods) <= set(reg), p.id
    doc = [m.info.id for m in methods_for("text_triage", Modality.DOCUMENT, reg)]
    assert "text.descriptive_statistics" in doc and "provenance.c2pa" in doc
    assert all(json.dumps(m.info.to_dict()) for m in reg.values())


def _r(mid, cls, status="completed", flagged=None, output=None, calibrated=False):
    return {"method_id": mid, "evidence_class": cls, "status": status, "flagged": flagged,
            "output": output or {}, "summary": "", "calibrated": calibrated}


def test_fusion_never_treats_failure_or_unavailable_as_negative():
    f = fuse([_r("a", "statistical_inference", "failed"), _r("b", "statistical_inference", "unavailable")])
    assert f.primary_outcome == "no_reliable_conclusion"
    assert f.failed and f.missing


def test_fusion_uninterpreted_scores_do_not_flag():
    f = fuse([_r("a", "statistical_inference", flagged=None)])
    assert f.primary_outcome == "no_reliable_conclusion" and f.not_interpreted == ["a"]


def test_fusion_categories_and_contradiction():
    f = fuse([_r("a", "statistical_inference", flagged=True, calibrated=True)])
    assert f.primary_outcome == "some_signals_consistent_with_ai" and "human_review_required" in f.categories
    f = fuse([_r("a", "statistical_inference", flagged=True), _r("b", "statistical_inference", flagged=True)])
    assert f.primary_outcome == "multiple_compatible_signals_consistent_with_ai"
    assert any("dependence is unknown" in r for r in f.uncertainty_reasons)
    f = fuse([_r("w", "verified_watermark", flagged=False)])
    assert f.primary_outcome == "inconclusive"
    assert any("does not indicate human authorship" in r for r in f.uncertainty_reasons)
    prov = _r("p", "cryptographic_provenance", output={"state": "signature_valid_signer_trusted",
                                                     "declared_capture_source": True})
    f = fuse([prov, _r("a", "statistical_inference", flagged=True)])
    assert f.primary_outcome == "contradictory_evidence"
    assert "provenance_record_verified" in f.categories  # provenance is not rejected automatically
    f = fuse([_r("p", "cryptographic_provenance", output={"state": "no_manifest"})])
    assert f.primary_outcome == "no_reliable_conclusion"
    f = fuse([_r("p", "cryptographic_provenance", output={"state": "verification_failed"})])
    assert f.primary_outcome == "provenance_verification_failed"
