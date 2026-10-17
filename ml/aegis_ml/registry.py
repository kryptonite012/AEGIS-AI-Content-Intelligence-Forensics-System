"""Method registry and analysis profiles."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aegis_ml.audio.analysis import AudioSignalMethod, TranscriptionPlaceholder
from aegis_ml.core import AnalysisInput, AnalysisMethod, EvidenceClass, ImplementationStatus, MethodInfo
from aegis_ml.core import MethodResult, Modality, RunStatus, Segment
from aegis_ml.image.analysis import (
    ErrorLevelAnalysisMethod,
    FrequencySpectrumMethod,
    ImageMetadataMethod,
    NoiseResidualMethod,
)
from aegis_ml.provenance.c2pa_verifier import C2PAVerifier, DeclaredMetadataMethod
from aegis_ml.providers import HttpDetectorProvider, LocalOnnxClassifier, run_tool
from aegis_ml.text.features import DescriptiveTextStatistics
from aegis_ml.text.model_detectors import (
    BinocularsMethod,
    FastDetectGPTMethod,
    SupervisedClassifierAdapter,
    TokenStatisticsMethod,
)
from aegis_ml.text.reference_watermark import ReferenceWatermarkVerifier, SynthIDTextAdapter
from aegis_ml.video.analysis import TemporalConsistencyMethod, VideoContainerMethod


class VideoFrameModelMethod(AnalysisMethod):
    """Applies the configured local image model to sampled frames. Produces per-frame findings only;
    no video-level verdict is derived from frame scores."""

    def __init__(self, image_model: LocalOnnxClassifier) -> None:
        self.image_model = image_model
        self.info = MethodInfo(
            id="video.frame_model",
            name="Per-frame image model (sampled frames)",
            version="1.0.0",
            modalities=(Modality.VIDEO,),
            evidence_class=EvidenceClass.STATISTICAL_INFERENCE,
            implementation=ImplementationStatus.REQUIRES_CONFIGURATION,
            description="Runs the configured local image model on frames sampled at 1 fps (max 60).",
            output_semantics="Per-frame model outputs. A synthetic-looking frame does not show the whole video is fabricated.",
            limitations=(
                "Image models trained on still images degrade on compressed video frames.",
                "No face recognition or identity inference is performed.",
            ),
            requires=image_model.info.requires,
        )

    def availability(self) -> tuple[bool, str]:
        return self.image_model.availability()

    def _run(self, inp: AnalysisInput) -> MethodResult:
        exe = shutil.which("ffmpeg")
        if not exe:
            return self.result(RunStatus.UNAVAILABLE, "ffmpeg not installed.")
        segs: list[Segment] = []
        with tempfile.TemporaryDirectory(prefix="aegis-vf-") as td:
            run_tool([exe, "-v", "error", "-nostdin", "-i", str(inp.original_path), "-map", "0:v:0", "-vf", "fps=1",
                      "-frames:v", "60", str(Path(td) / "f_%04d.png")], timeout=600)
            for i, f in enumerate(sorted(Path(td).glob("f_*.png"))):
                r = self.image_model.run(AnalysisInput(Modality.IMAGE, "image/png", f, inp.sha256))
                segs.append(Segment(float(i), float(i + 1), "seconds", "frame_model_output", r.score,
                                    {"status": str(r.status)}))
        scored = [s.score for s in segs if s.score is not None]
        return self.result(
            RunStatus.COMPLETED if scored else RunStatus.FAILED,
            f"{len(scored)} frames scored; outputs are per-frame observations, not a video-level conclusion.",
            segments=segs, output={"frames_scored": len(scored),
                                   "max_frame_output": max(scored) if scored else None},
        )


def build_registry() -> dict[str, AnalysisMethod]:
    image_model = LocalOnnxClassifier(
        "image.local_model", Modality.IMAGE, "AEGIS_IMAGE_MODEL_DIR", "Local image generation classifier (ONNX)",
        ("Wang et al. (2020), CNN-generated images are surprisingly easy to spot... for now; Ojha et al. (2023).",),
    )
    methods: list[AnalysisMethod] = [
        DescriptiveTextStatistics(),
        SupervisedClassifierAdapter(),
        TokenStatisticsMethod(),
        FastDetectGPTMethod(),
        BinocularsMethod(),
        ReferenceWatermarkVerifier(),
        SynthIDTextAdapter(),
        ImageMetadataMethod(),
        FrequencySpectrumMethod(),
        NoiseResidualMethod(),
        ErrorLevelAnalysisMethod(),
        image_model,
        HttpDetectorProvider("image_detector", Modality.IMAGE, "External image detection service"),
        AudioSignalMethod(),
        LocalOnnxClassifier(
            "audio.synthetic_speech_model", Modality.AUDIO, "AEGIS_SPEECH_MODEL_DIR",
            "Local synthetic-speech classifier (ONNX)",
            ("Jung et al. (2022), AASIST; ASVspoof challenge series.",),
        ),
        HttpDetectorProvider("audio_detector", Modality.AUDIO, "External synthetic-speech detection service"),
        TranscriptionPlaceholder(),
        VideoContainerMethod(),
        TemporalConsistencyMethod(),
        VideoFrameModelMethod(image_model),
        HttpDetectorProvider("video_detector", Modality.VIDEO, "External deepfake detection service"),
        C2PAVerifier(),
        DeclaredMetadataMethod(),
    ]
    return {m.info.id: m for m in methods}


@dataclass(frozen=True)
class AnalysisProfile:
    id: str
    name: str
    description: str
    modalities: tuple[Modality, ...]
    methods: tuple[str, ...]
    resources: str
    limitations: tuple[str, ...]


_TEXT = ("text.descriptive_statistics", "text.supervised_classifier", "text.token_statistics",
         "text.fast_detectgpt_analytic", "text.binoculars", "watermark.aegis_reference_text", "watermark.synthid_text")
_IMAGE = ("image.metadata", "metadata.declared_generation_claims", "provenance.c2pa", "image.frequency_spectrum",
          "image.noise_residual", "image.error_level_analysis", "image.local_model", "provider.image_detector")
_AUDIO = ("audio.signal_analysis", "metadata.declared_generation_claims", "provenance.c2pa",
          "audio.synthetic_speech_model", "provider.audio_detector", "audio.transcription")
_VIDEO = ("video.container", "video.temporal_consistency", "audio.signal_analysis",
          "metadata.declared_generation_claims", "provenance.c2pa", "video.frame_model", "provider.video_detector")

PROFILES: dict[str, AnalysisProfile] = {p.id: p for p in [
    AnalysisProfile("text_triage", "Text authenticity triage", "Extraction, descriptive statistics, configured text "
                    "detectors and watermark verification.", (Modality.TEXT, Modality.DOCUMENT), _TEXT + ("provenance.c2pa",),
                    "CPU: seconds. Transformer detectors: ~1-4 GB RAM per model; GPU optional.",
                    ("Unreliable below ~50 tokens.", "No detector is validated for non-English text unless its card says so.")),
    AnalysisProfile("image_investigation", "Image authenticity investigation", "Structure, metadata, provenance and "
                    "forensic visualisations, plus configured image models.", (Modality.IMAGE,), _IMAGE,
                    "CPU: a few seconds per image (analysis downsampled to 1024 px).",
                    ("Forensic visualisations are observations for an analyst, not classifiers.",)),
    AnalysisProfile("synthetic_speech", "Synthetic speech investigation", "Signal analysis, provenance and configured "
                    "synthetic-speech models.", (Modality.AUDIO,), _AUDIO, "CPU: ~1-5 s per minute of audio.",
                    ("No speaker identification is performed.", "Telephony and transcoding degrade every method.")),
    AnalysisProfile("deepfake_video", "Deepfake video investigation", "Container inspection, temporal consistency, "
                    "audio track analysis, provenance and configured frame models.", (Modality.VIDEO,), _VIDEO,
                    "CPU: ~10-60 s per minute of video at 2 fps sampling.",
                    ("Frame-level observations do not establish that a whole video is fabricated.",)),
    AnalysisProfile("provenance_verification", "Provenance verification", "Content Credentials, declared metadata "
                    "and supported watermark verifiers only.",
                    (Modality.IMAGE, Modality.AUDIO, Modality.VIDEO, Modality.DOCUMENT, Modality.TEXT),
                    ("provenance.c2pa", "metadata.declared_generation_claims", "watermark.aegis_reference_text",
                     "watermark.synthid_text"), "CPU: under a second for most files.",
                    ("Missing provenance is not evidence of AI generation or human creation.",)),
    AnalysisProfile("comprehensive", "Comprehensive multimodal examination", "Every method applicable to the evidence "
                    "type.", (Modality.TEXT, Modality.DOCUMENT, Modality.IMAGE, Modality.AUDIO, Modality.VIDEO),
                    tuple(dict.fromkeys(_TEXT + _IMAGE + _AUDIO + _VIDEO)), "Sum of the modality profiles.",
                    ("Methods not applicable to a file are reported as unsupported, not as negative results.",)),
]}


def methods_for(profile_id: str, modality: Modality, registry: dict[str, AnalysisMethod]) -> list[AnalysisMethod]:
    """Methods of a profile that apply to the modality (text methods also apply to documents)."""
    profile = PROFILES[profile_id]
    out = []
    for mid in profile.methods:
        m = registry.get(mid)
        if m is None:
            continue
        mods = set(m.info.modalities)
        if modality in mods or (modality == Modality.DOCUMENT and Modality.TEXT in mods):
            out.append(m)
    return out
