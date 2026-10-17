"""Image forensics: decoding, metadata, frequency spectrum, noise residual, error level analysis.

All outputs are media-forensic *observations*. None of them is an AI-generation detector, and the
visualisations explain what they can and cannot establish.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import ExifTags, Image, ImageCms
from scipy import ndimage

from aegis_ml.core import (
    AnalysisInput,
    AnalysisMethod,
    Artifact,
    EvidenceClass,
    ImplementationStatus,
    MethodInfo,
    MethodResult,
    Modality,
    RunStatus,
)
from aegis_ml.visual import heat_png, normalise, png_bytes

Image.MAX_IMAGE_PIXELS = 80_000_000  # decompression-bomb guard (Pillow raises above 2x this)
ANALYSIS_MAX_SIDE = 1024

# Standard JPEG (Annex K) luminance quantisation table, natural order.
_STD_LUMA = np.array(
    [
        16,
        11,
        10,
        16,
        24,
        40,
        51,
        61,
        12,
        12,
        14,
        19,
        26,
        58,
        60,
        55,
        14,
        13,
        16,
        24,
        40,
        57,
        69,
        56,
        14,
        17,
        22,
        29,
        51,
        87,
        80,
        62,
        18,
        22,
        37,
        56,
        68,
        109,
        103,
        77,
        24,
        35,
        55,
        64,
        81,
        104,
        113,
        92,
        49,
        64,
        78,
        87,
        103,
        121,
        120,
        101,
        72,
        92,
        95,
        98,
        112,
        100,
        103,
        99,
    ],
    dtype=float,
)

_SENSITIVE_EXIF = {"GPSInfo", "BodySerialNumber", "CameraOwnerName", "LensSerialNumber", "ImageUniqueID"}


def open_image(path: Path) -> Image.Image:
    with Image.open(path) as probe:
        probe.verify()  # structural check; image must be reopened afterwards
    img = Image.open(path)
    img.load()
    return img


def estimate_jpeg_quality(img: Image.Image) -> dict[str, Any] | None:
    q = getattr(img, "quantization", None)
    if not q or 0 not in q:
        return None
    table = np.array(q[0], dtype=float)
    if table.size != 64:
        return None
    # Invert IJG scaling: scale = table/std*100; quality from scale. Tables may be in zigzag order;
    # the mean ratio is order-insensitive, which is sufficient for an estimate.
    scale = float(np.mean(table / _STD_LUMA) * 100)
    quality = (200 - scale) / 2 if scale <= 100 else 5000 / scale
    return {
        "estimated_quality": int(round(max(1, min(100, quality)))),
        "method": "IJG luminance-table inversion (estimate; non-IJG encoders deviate)",
        "tables": len(q),
    }


def _gray(img: Image.Image) -> np.ndarray:
    g = img.convert("L")
    if max(g.size) > ANALYSIS_MAX_SIDE:
        g.thumbnail((ANALYSIS_MAX_SIDE, ANALYSIS_MAX_SIDE), Image.Resampling.LANCZOS)
    return np.asarray(g, dtype=np.float32)


def exif_summary(img: Image.Image, redact_sensitive: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        exif = img.getexif()
    except Exception:  # noqa: BLE001 - malformed EXIF is reported, not fatal
        return {"_status": "malformed"}
    if not exif:
        return {}
    items = dict(exif.items())
    try:
        items.update(exif.get_ifd(ExifTags.IFD.Exif))
    except Exception:  # noqa: BLE001
        out["_exif_ifd"] = "malformed"
    for tag, value in items.items():
        name = ExifTags.TAGS.get(tag, f"tag_{tag}")
        if name in ("MakerNote", "PrintImageMatching") or name.startswith("tag_"):
            continue
        if name in _SENSITIVE_EXIF:
            out[name] = "[present — redacted]" if redact_sensitive else str(value)
            continue
        if isinstance(value, bytes):
            value = value[:64].decode("utf-8", errors="replace").strip("\x00 ")
        out[name] = str(value)[:300]
    return out


class ImageMetadataMethod(AnalysisMethod):
    info = MethodInfo(
        id="image.metadata",
        name="Image structure and metadata",
        version="1.0.0",
        modalities=(Modality.IMAGE,),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Format, dimensions, colour profile, orientation, EXIF, JPEG quantisation estimate.",
        output_semantics="Descriptive observations about the file. Metadata is unsigned and trivially editable.",
        limitations=(
            "Missing metadata is common (social media strips it) and indicates nothing about generation.",
            "Present metadata can be forged; only signed provenance can be cryptographically verified.",
        ),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        img = open_image(inp.original_path)
        icc = img.info.get("icc_profile")
        icc_desc = None
        if icc:
            try:
                icc_desc = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
            except Exception:  # noqa: BLE001
                icc_desc = "present (unparseable)"
        exif = exif_summary(img)
        jpeg = estimate_jpeg_quality(img) if img.format == "JPEG" else None
        out = {
            "format": img.format,
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "megapixels": round(img.width * img.height / 1e6, 3),
            "frames": getattr(img, "n_frames", 1),
            "orientation": exif.get("Orientation"),
            "icc_profile": icc_desc,
            "has_alpha": "A" in img.getbands(),
            "exif_status": "absent" if not exif else ("malformed" if exif.get("_status") == "malformed" else "present"),
            "exif": exif,
            "jpeg": jpeg,
            "progressive": bool(img.info.get("progressive") or img.info.get("progression")),
            "dpi": img.info.get("dpi"),
            "xmp_present": bool(img.info.get("xmp") or img.info.get("XML:com.adobe.xmp")),
        }
        warnings = []
        if any(v == "[present — redacted]" for v in exif.values()):
            warnings.append("Sensitive EXIF fields (e.g. GPS, serial numbers) are present and redacted in this view.")
        return self.result(
            RunStatus.COMPLETED,
            f"{img.format} {img.width}x{img.height}; EXIF {out['exif_status']}.",
            output=out,
            warnings=warnings,
        )


class FrequencySpectrumMethod(AnalysisMethod):
    info = MethodInfo(
        id="image.frequency_spectrum",
        name="Frequency-domain spectrum",
        version="1.0.0",
        modalities=(Modality.IMAGE,),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Centred log-magnitude 2-D Fourier spectrum with radial power profile and periodic-peak measure.",
        output_semantics=(
            "Upsampling and some generators leave periodic peaks; resizing, JPEG and screenshots do too. "
            "The spectrum is an observation for an analyst, not a classifier."
        ),
        limitations=(
            "Periodic peaks have many benign causes (resampling, compression grids, halftone, textures).",
            "Absence of peaks does not indicate an authentic camera image.",
        ),
        references=("Durall et al. (2020); Frank et al. (2020) on spectral artefacts of generative upsampling.",),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        g = _gray(open_image(inp.original_path))
        g = g - g.mean()
        win = np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1]))
        spec = np.fft.fftshift(np.abs(np.fft.fft2(g * win)))
        logspec = np.log1p(spec)
        h, w = logspec.shape
        yy, xx = np.indices(logspec.shape)
        r = np.hypot(yy - h / 2, xx - w / 2)
        rmax = int(min(h, w) / 2)
        radial = ndimage.mean(spec**2, labels=r.astype(int), index=np.arange(1, rmax))
        freqs = np.arange(1, rmax) / rmax
        valid = radial > 0
        slope = float(np.polyfit(np.log(freqs[valid]), np.log(radial[valid]), 1)[0]) if valid.sum() > 5 else None
        hf = float(radial[freqs > 0.5].sum() / radial.sum()) if radial.sum() else None
        # Periodic-peak measure: strongest local maximum (away from centre and axes) relative to the
        # median of its radial ring.
        resid = logspec - ndimage.median_filter(logspec, size=9)
        mask = (r > rmax * 0.15) & (np.abs(yy - h / 2) > 2) & (np.abs(xx - w / 2) > 2)
        peak = float(resid[mask].max()) if mask.any() else 0.0
        return self.result(
            RunStatus.COMPLETED,
            "Spectrum computed; review the visualisation alongside other observations.",
            output={
                "analysis_size": [w, h],
                "radial_power_slope": slope,
                "high_frequency_energy_fraction": hf,
                "periodic_peak_strength": round(peak, 3),
                "radial_profile": [round(float(v), 4) for v in np.log10(radial[:: max(1, len(radial) // 64)] + 1e-12)],
            },
            artifacts=[
                Artifact(
                    "frequency_spectrum.png",
                    "image/png",
                    heat_png(logspec),
                    "Centred log-magnitude spectrum; centre = low frequencies, edges = high frequencies.",
                    "Cannot establish that an image is synthetic or authentic; periodic patterns have benign causes.",
                )
            ],
            config={"window": "hann", "analysis_max_side": ANALYSIS_MAX_SIDE},
        )


class NoiseResidualMethod(AnalysisMethod):
    info = MethodInfo(
        id="image.noise_residual",
        name="Noise residual and local consistency",
        version="1.0.0",
        modalities=(Modality.IMAGE,),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description="High-pass residual (image minus 3x3 median) and block-wise residual variance map.",
        output_semantics=(
            "Spatial variation of fine-grain noise. Regions with very different residual energy may merit review."
        ),
        limitations=(
            "Residual energy varies with texture, focus, denoising and "
            "compression; inconsistency is not proof of splicing.",
            "Not a PRNU camera fingerprint; no device attribution is attempted.",
        ),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        g = _gray(open_image(inp.original_path))
        resid = g - ndimage.median_filter(g, size=3)
        b = 32
        hb, wb = g.shape[0] // b, g.shape[1] // b
        if hb < 2 or wb < 2:
            return self.result(RunStatus.INSUFFICIENT_INPUT, "Image too small for block-wise residual analysis.")
        blocks = resid[: hb * b, : wb * b].reshape(hb, b, wb, b).std(axis=(1, 3))
        cv = float(blocks.std() / blocks.mean()) if blocks.mean() else None
        outlier = np.abs(blocks - np.median(blocks)) > 4 * (np.median(np.abs(blocks - np.median(blocks))) + 1e-6)
        return self.result(
            RunStatus.COMPLETED,
            f"Residual computed; {int(outlier.sum())} of {outlier.size} blocks deviate strongly from the median.",
            output={
                "residual_std": float(resid.std()),
                "block_size": b,
                "block_grid": [wb, hb],
                "block_std_coefficient_of_variation": cv,
                "outlier_blocks": int(outlier.sum()),
                "outlier_block_fraction": float(outlier.mean()),
            },
            artifacts=[
                Artifact(
                    "noise_residual.png",
                    "image/png",
                    png_bytes((normalise(np.abs(resid)) * 255).clip(0, 255).astype(np.uint8)),
                    "Absolute high-pass residual (amplified). Bright = strong fine-grain detail or noise.",
                    "Cannot localise manipulation by itself; textured regions are naturally bright.",
                ),
                Artifact(
                    "residual_block_map.png",
                    "image/png",
                    heat_png(np.kron(blocks, np.ones((8, 8)))),
                    "Residual standard deviation per 32x32 block.",
                    "Differences can reflect content, focus or compression rather than editing.",
                ),
            ],
        )


class ErrorLevelAnalysisMethod(AnalysisMethod):
    info = MethodInfo(
        id="image.error_level_analysis",
        name="Error level analysis (JPEG)",
        version="1.0.0",
        modalities=(Modality.IMAGE,),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Difference between the JPEG and a re-compression at quality 90.",
        output_semantics="Regions recompressing differently may have a different compression history.",
        limitations=(
            "ELA is widely misinterpreted: edges, text and saturated colours always stand out.",
            "Only meaningful for JPEG inputs; results are qualitative.",
        ),
        references=("Krawetz (2007), A Picture's Worth.",),
    )

    def supports(self, inp: AnalysisInput) -> bool:
        return inp.mime_type == "image/jpeg"

    def _run(self, inp: AnalysisInput) -> MethodResult:
        img = open_image(inp.original_path).convert("RGB")
        if max(img.size) > ANALYSIS_MAX_SIDE:
            img.thumbnail((ANALYSIS_MAX_SIDE, ANALYSIS_MAX_SIDE), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        re = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
        diff = np.abs(np.asarray(img, dtype=np.int16) - np.asarray(re, dtype=np.int16)).max(axis=2)
        return self.result(
            RunStatus.COMPLETED,
            "Error level map computed (qualitative).",
            output={
                "mean_error_level": float(diff.mean()),
                "p99_error_level": float(np.percentile(diff, 99)),
                "recompression_quality": 90,
            },
            artifacts=[
                Artifact(
                    "error_level.png",
                    "image/png",
                    heat_png(diff.astype(float)),
                    "Per-pixel maximum channel difference after re-compression at quality 90.",
                    "Cannot establish manipulation; high-contrast edges and text are always bright.",
                )
            ],
            config={"quality": 90},
        )
