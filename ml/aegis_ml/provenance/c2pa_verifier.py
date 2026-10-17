"""Content Credentials (C2PA) verification using the official ``c2pa-python`` bindings (c2pa-rs).

Three things are kept distinct in every result:
  1. signature/integrity validity (the manifest is intact and its signature verifies),
  2. signer trust (the signing certificate chains to a configured trust anchor),
  3. truthfulness of the claims (NOT established by either of the above).
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from aegis_ml.core import AnalysisInput, AnalysisMethod, EvidenceClass, ImplementationStatus, MethodInfo
from aegis_ml.core import MethodResult, Modality, RunStatus

IPTC_AI_SOURCE_TYPES = {
    "trainedAlgorithmicMedia",
    "compositeWithTrainedAlgorithmicMedia",
    "algorithmicMedia",
    "compositeSynthetic",
}
IPTC_CAPTURE_SOURCE_TYPES = {"digitalCapture", "negativeFilm", "positiveFilm", "print", "minorHumanEdits"}

C2PA_MIME = {
    "image/jpeg", "image/png", "image/webp", "audio/wav", "audio/mpeg", "audio/mp4", "video/mp4", "application/pdf",
}


class ProvenanceState:
    NO_MANIFEST = "no_manifest"
    VALID_UNTRUSTED = "signature_valid_signer_untrusted"
    TRUSTED = "signature_valid_signer_trusted"
    INVALID = "verification_failed"
    UNSUPPORTED = "unsupported_format"


def _source_type_name(uri: str | None) -> str | None:
    return uri.rstrip("/").rsplit("/", 1)[-1] if uri else None


def _context():
    import c2pa

    anchors_path = os.environ.get("AEGIS_C2PA_TRUST_ANCHORS")
    if not anchors_path or not Path(anchors_path).is_file():
        return None, None
    pem = Path(anchors_path).read_text()
    settings = c2pa.Settings.from_json(json.dumps({"trust": {"trust_anchors": pem}, "verify": {"verify_trust": True}}))
    return c2pa.Context(settings), Path(anchors_path).name


def summarise_manifest_store(store: dict[str, Any], validation: dict[str, Any] | None, state: str | None) -> dict:
    active_label = store.get("active_manifest")
    manifests = store.get("manifests", {})
    active = manifests.get(active_label, {}) if active_label else {}
    actions: list[dict[str, Any]] = []
    for a in active.get("assertions", []):
        if a.get("label", "").startswith("c2pa.actions"):
            for act in (a.get("data") or {}).get("actions", []):
                actions.append({
                    "action": act.get("action"),
                    "digital_source_type": _source_type_name(act.get("digitalSourceType")),
                    "software_agent": (act.get("softwareAgent") or {}).get("name")
                    if isinstance(act.get("softwareAgent"), dict) else act.get("softwareAgent"),
                    "when": act.get("when"),
                })
    ingredients = [
        {"title": i.get("title"), "relationship": i.get("relationship"), "format": i.get("format"),
         "has_manifest": bool(i.get("active_manifest") or i.get("manifest_data"))}
        for i in active.get("ingredients", [])
    ]
    am = (validation or {}).get("activeManifest", {})
    failures = [f["code"] for f in am.get("failure", [])]
    sig = active.get("signature_info") or {}
    gen = active.get("claim_generator_info") or []
    source_types = {a["digital_source_type"] for a in actions if a["digital_source_type"]}
    return {
        "manifest_count": len(manifests),
        "active_manifest": active_label,
        "title": active.get("title"),
        "claim_generator": [{"name": g.get("name"), "version": g.get("version")} for g in gen]
        if isinstance(gen, list) else gen,
        "signature": {"algorithm": sig.get("alg"), "issuer": sig.get("issuer"), "common_name": sig.get("common_name"),
                      "time": sig.get("time")},
        "actions": actions,
        "ingredients": ingredients,
        "declared_ai_source": bool(source_types & IPTC_AI_SOURCE_TYPES),
        "declared_capture_source": bool(source_types & IPTC_CAPTURE_SOURCE_TYPES),
        "digital_source_types": sorted(source_types),
        "validation_state": state,
        "failure_codes": failures,
        "success_codes": sorted({s["code"] for s in am.get("success", [])}),
        "informational_codes": sorted({s["code"] for s in am.get("informational", [])}),
    }


class C2PAVerifier(AnalysisMethod):
    info = MethodInfo(
        id="provenance.c2pa",
        name="Content Credentials (C2PA) verification",
        version="1.0.0",
        modalities=(Modality.IMAGE, Modality.AUDIO, Modality.VIDEO, Modality.DOCUMENT),
        evidence_class=EvidenceClass.CRYPTOGRAPHIC_PROVENANCE,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Reads and validates embedded C2PA manifests with the official c2pa-rs library.",
        output_semantics=(
            "Whether a manifest exists, whether its signature and hashes validate, and whether the signer chains "
            "to a configured trust anchor. A valid signature does not make the manifest's claims true."
        ),
        limitations=(
            "'No supported provenance record found' is not evidence of AI generation or of human creation.",
            "Signer trust depends entirely on the configured trust anchors.",
            "Manifests are frequently stripped by re-encoding and platforms.",
            "Remote (cloud) manifests are not fetched; network access is disabled for verification.",
        ),
        references=("C2PA Technical Specification 2.x, https://c2pa.org/specifications/",),
        requires=("c2pa-python", "AEGIS_C2PA_TRUST_ANCHORS (optional, for signer trust)"),
    )

    def availability(self) -> tuple[bool, str]:
        try:
            import c2pa  # noqa: F401
        except ImportError:
            return False, "c2pa-python is not installed."
        return True, "available"

    def supports(self, inp: AnalysisInput) -> bool:
        return inp.mime_type in C2PA_MIME

    def _run(self, inp: AnalysisInput) -> MethodResult:
        import c2pa

        data = inp.original_path.read_bytes()
        ctx, anchors = _context()
        cfg = {"trust_anchors": anchors or "none configured", "remote_manifests": "not fetched",
               "sdk_version": c2pa.sdk_version()}
        try:
            reader = c2pa.Reader.try_create(inp.mime_type, io.BytesIO(data), context=ctx)
        except c2pa.C2paError.NotSupported:
            return self.result(RunStatus.UNSUPPORTED_INPUT, "The C2PA library cannot read this file's structure.",
                               output={"state": ProvenanceState.UNSUPPORTED}, config=cfg)
        except c2pa.C2paError as exc:
            # A manifest exists but is structurally broken: verification failed.
            return self.result(
                RunStatus.COMPLETED, "Provenance verification failed: the manifest could not be parsed.",
                output={"state": ProvenanceState.INVALID, "error": str(exc)[:500]}, flagged=None, config=cfg,
            )
        if reader is None:
            return self.result(RunStatus.COMPLETED, "No supported provenance record found.",
                                output={"state": ProvenanceState.NO_MANIFEST}, config=cfg)
        with reader:
            state = reader.get_validation_state()
            summary = summarise_manifest_store(json.loads(reader.json()), reader.get_validation_results(), state)
            summary["embedded"] = reader.is_embedded()
        integrity_failures = [c for c in summary["failure_codes"] if c != "signingCredential.untrusted"]
        if state == "Trusted" and not integrity_failures:
            pstate, text = ProvenanceState.TRUSTED, (
                "Verification succeeded for the supported provenance record; the signer chains to a configured trust anchor."
            )
        elif state in ("Valid", "Trusted") and not integrity_failures:
            pstate, text = ProvenanceState.VALID_UNTRUSTED, (
                "The manifest's signature and hashes validate, but the signer is not trusted by this deployment."
            )
        else:
            pstate, text = ProvenanceState.INVALID, (
                f"Provenance verification failed ({', '.join(integrity_failures) or state})."
            )
        summary["state"] = pstate
        warnings = []
        if pstate != ProvenanceState.INVALID and summary["declared_ai_source"]:
            warnings.append("The manifest declares AI-generated content (IPTC digital source type). "
                            "This is the signer's claim.")
        return self.result(RunStatus.COMPLETED, text, output=summary, config=cfg, warnings=warnings)


# ---------------------------------------------------------------------------

KNOWN_GENERATOR_MARKERS = (
    "stable diffusion", "midjourney", "dall-e", "dall·e", "firefly", "imagen", "novelai", "comfyui",
    "automatic1111", "invokeai", "flux", "elevenlabs", "sora", "runway", "pika", "leonardo",
)


class DeclaredMetadataMethod(AnalysisMethod):
    """Unsigned, embedded claims about how a file was made (PNG text chunks, EXIF Software, XMP
    DigitalSourceType, container encoder tags)."""

    info = MethodInfo(
        id="metadata.declared_generation_claims",
        name="Declared (unsigned) generation metadata",
        version="1.0.0",
        modalities=(Modality.IMAGE, Modality.AUDIO, Modality.VIDEO),
        evidence_class=EvidenceClass.DECLARED_METADATA,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Looks for unsigned tool and source-type declarations embedded in the file.",
        output_semantics="Lists declarations as found. They are claims, trivially added or removed, never verification.",
        limitations=(
            "Absence of declarations is the normal case and indicates nothing.",
            "Declarations can be forged or copied between files.",
        ),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        found: list[dict[str, str]] = []
        if inp.modality == Modality.IMAGE:
            from PIL import Image

            from aegis_ml.image.analysis import exif_summary

            img = Image.open(inp.original_path)
            for k, v in (img.info or {}).items():
                if isinstance(v, str) and k.lower() in ("parameters", "prompt", "workflow", "software", "comment",
                                                         "description", "source", "xml:com.adobe.xmp"):
                    found.append({"field": f"png/info:{k}", "value": v[:500]})
            xmp = img.info.get("xmp")
            if isinstance(xmp, bytes):
                xmp = xmp.decode("utf-8", errors="replace")
            if isinstance(xmp, str) and "DigitalSourceType" in xmp:
                found.append({"field": "xmp:DigitalSourceType", "value": xmp[xmp.find("DigitalSourceType"):][:300]})
            for k in ("Software", "ImageDescription", "Artist", "UserComment", "XPComment"):
                if v := exif_summary(img).get(k):
                    found.append({"field": f"exif:{k}", "value": v})
        else:
            from aegis_ml.audio.analysis import ffprobe

            probe = ffprobe(inp.original_path)
            tags = dict(probe.get("format", {}).get("tags") or {})
            for s in probe.get("streams", []):
                tags.update({f"stream{s.get('index')}:{k}": v for k, v in (s.get("tags") or {}).items()})
            for k, v in tags.items():
                if any(x in k.lower() for x in ("encoder", "comment", "software", "description", "title", "handler")):
                    found.append({"field": k, "value": str(v)[:300]})
        markers = sorted({m for f in found for m in KNOWN_GENERATOR_MARKERS if m in f["value"].lower()})
        ai_source = any(t in f["value"] for f in found for t in IPTC_AI_SOURCE_TYPES)
        if markers or ai_source:
            text = "Unsigned metadata declares generation by: " + ", ".join(markers or ["IPTC AI source type"]) + "."
        elif found:
            text = f"{len(found)} unsigned tool/description fields found; none names a known generator."
        else:
            text = "No declared generation metadata found (common; indicates nothing)."
        return self.result(RunStatus.COMPLETED, text,
                           output={"declarations": found, "generator_markers": markers, "declares_ai_source_type": ai_source})
