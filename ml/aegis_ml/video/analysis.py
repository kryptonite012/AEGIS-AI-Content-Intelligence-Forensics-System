"""Video forensics: container/stream inspection, keyframes, sampled-frame temporal consistency and
container-level audio/video alignment. No facial recognition or identity inference is performed."""

from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from aegis_ml.audio.analysis import ffprobe, tools_available
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
    Segment,
)
from aegis_ml.providers import run_tool
from aegis_ml.visual import png_bytes

MAX_SAMPLED_FRAMES = 240


def _rate(s: str | None) -> float | None:
    if not s or s in ("0/0",):
        return None
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else None
    return float(s)


class VideoContainerMethod(AnalysisMethod):
    info = MethodInfo(
        id="video.container",
        name="Video container and stream inspection",
        version="1.0.0",
        modalities=(Modality.VIDEO,),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Container, codecs, duration, frame rate, dimensions, encoder tags and A/V stream alignment.",
        output_semantics="Structural observations. Encoder tags are unsigned and editable.",
        limitations=(
            "Re-encoding by platforms rewrites most container metadata.",
            "Stream alignment is container-level only; lip-sync analysis is not implemented.",
        ),
    )

    def availability(self) -> tuple[bool, str]:
        return tools_available()

    def _run(self, inp: AnalysisInput) -> MethodResult:
        probe = ffprobe(inp.original_path)
        fmt = probe.get("format", {})
        streams: list[dict[str, Any]] = []
        for s in probe.get("streams", []):
            streams.append(
                {
                    "index": s.get("index"),
                    "type": s.get("codec_type"),
                    "codec": s.get("codec_name"),
                    "profile": s.get("profile"),
                    "width": s.get("width"),
                    "height": s.get("height"),
                    "pix_fmt": s.get("pix_fmt"),
                    "avg_frame_rate": _rate(s.get("avg_frame_rate")),
                    "r_frame_rate": _rate(s.get("r_frame_rate")),
                    "nb_frames": s.get("nb_frames"),
                    "sample_rate": s.get("sample_rate"),
                    "channels": s.get("channels"),
                    "start_time": float(s["start_time"]) if s.get("start_time") else None,
                    "duration": float(s["duration"]) if s.get("duration") else None,
                    "tags": {k: str(v)[:200] for k, v in (s.get("tags") or {}).items()},
                }
            )
        v = next((s for s in streams if s["type"] == "video"), None)
        a = next((s for s in streams if s["type"] == "audio"), None)
        if v is None:
            return self.result(RunStatus.UNSUPPORTED_INPUT, "No video stream found.")
        warnings, findings = [], []
        av: dict[str, Any] | None = None
        if a is not None:
            av = {
                "start_offset_seconds": None
                if a["start_time"] is None or v["start_time"] is None
                else round(a["start_time"] - v["start_time"], 4),
                "duration_difference_seconds": None
                if a["duration"] is None or v["duration"] is None
                else round(a["duration"] - v["duration"], 4),
            }
            if av["start_offset_seconds"] is not None and abs(av["start_offset_seconds"]) > 0.2:
                findings.append("Audio and video streams start more than 200 ms apart (container level).")
            if av["duration_difference_seconds"] is not None and abs(av["duration_difference_seconds"]) > 1.0:
                findings.append("Audio and video stream durations differ by more than 1 s.")
        else:
            warnings.append("No audio stream; audio methods will be skipped.")
        if v["avg_frame_rate"] and v["r_frame_rate"] and abs(v["avg_frame_rate"] - v["r_frame_rate"]) > 0.5:
            findings.append("Average and nominal frame rates differ (variable frame rate or edited timeline).")
        return self.result(
            RunStatus.COMPLETED,
            f"{fmt.get('format_name')} {v['codec']} {v['width']}x{v['height']} @ {v['avg_frame_rate'] or '?'} fps, "
            f"{float(fmt.get('duration', 0)):.1f} s.",
            output={
                "format": fmt.get("format_name"),
                "duration_seconds": float(fmt.get("duration", 0) or 0),
                "bit_rate": fmt.get("bit_rate"),
                "tags": {k: str(x)[:200] for k, x in (fmt.get("tags") or {}).items()},
                "streams": streams,
                "av_alignment": av,
                "structural_findings": findings,
            },
            warnings=warnings,
        )


class TemporalConsistencyMethod(AnalysisMethod):
    info = MethodInfo(
        id="video.temporal_consistency",
        name="Sampled-frame temporal consistency",
        version="1.0.0",
        modalities=(Modality.VIDEO,),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description=(
            "Samples frames at a configurable rate, measures inter-frame change and per-frame noise residual, "
            "lists keyframes, duplicate frames and abrupt discontinuities."
        ),
        output_semantics="A timeline of observations for an analyst. Not a deepfake detector.",
        limitations=(
            "Scene cuts, camera motion and compression cause discontinuities in authentic footage.",
            "A frame that looks unusual does not show that the whole video is fabricated.",
        ),
    )

    def availability(self) -> tuple[bool, str]:
        return tools_available()

    def _run(self, inp: AnalysisInput) -> MethodResult:
        fps = float(inp.options.get("sample_fps", 2.0))
        fps = min(max(fps, 0.1), 10.0)
        exe = shutil.which("ffmpeg")
        assert exe
        with tempfile.TemporaryDirectory(prefix="aegis-frames-") as td:
            run_tool(
                [
                    exe,
                    "-v",
                    "error",
                    "-nostdin",
                    "-i",
                    str(inp.original_path),
                    "-map",
                    "0:v:0",
                    "-vf",
                    f"fps={fps},scale=320:-2",
                    "-frames:v",
                    str(MAX_SAMPLED_FRAMES),
                    str(Path(td) / "f_%05d.png"),
                ],
                timeout=600,
            )
            files = sorted(Path(td).glob("f_*.png"))
            frames = [np.asarray(Image.open(f).convert("L"), dtype=np.float32) for f in files]
            thumbs = [Image.open(f).convert("RGB") for f in files[:: max(1, len(files) // 12)][:12]]
        if len(frames) < 2:
            return self.result(RunStatus.INSUFFICIENT_INPUT, "Fewer than two frames could be sampled.")
        diffs = np.array([float(np.abs(frames[i] - frames[i - 1]).mean()) for i in range(1, len(frames))])
        resid = np.array([float((f - ndimage.median_filter(f, 3)).std()) for f in frames])
        med, mad = float(np.median(diffs)), float(np.median(np.abs(diffs - np.median(diffs)))) + 1e-6
        segments: list[Segment] = []
        for i, d in enumerate(diffs, start=1):
            t = i / fps
            if d < 0.05:
                segments.append(Segment(t - 1 / fps, t, "seconds", "duplicate_or_frozen_frame", d))
            elif d > med + 8 * mad and d > 8:
                segments.append(Segment(t - 1 / fps, t, "seconds", "abrupt_discontinuity", d))
        rmed = float(np.median(resid))
        for i, r in enumerate(resid):
            if rmed and abs(r - rmed) / rmed > 0.6:
                segments.append(Segment(i / fps, (i + 1) / fps, "seconds", "noise_level_shift", r))
        keyframes: list[float] = []
        probe_exe = shutil.which("ffprobe")
        if probe_exe:
            out = run_tool(
                [
                    probe_exe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-skip_frame",
                    "nokey",
                    "-show_entries",
                    "frame=pts_time",
                    "-of",
                    "csv=p=0",
                    "-read_intervals",
                    "%+600",
                    str(inp.original_path),
                ],
                timeout=300,
            )
            for line in out.decode().split():
                value = line.strip().strip(",")
                if value.replace(".", "", 1).isdigit():
                    keyframes.append(float(value))
            keyframes = keyframes[:2000]
        sheet = Image.new("RGB", (4 * 320, 3 * max(t.height for t in thumbs)), (8, 12, 28))
        for k, t in enumerate(thumbs):
            sheet.paste(t, ((k % 4) * 320, (k // 4) * t.height))
        buf = io.BytesIO()
        sheet.save(buf, "PNG", optimize=True)
        diff_strip = np.tile((np.clip(diffs / (diffs.max() + 1e-6), 0, 1) * 255).astype(np.uint8), (24, 1))
        return self.result(
            RunStatus.COMPLETED,
            f"{len(frames)} frames sampled at {fps:g} fps; {len(segments)} timeline observations.",
            output={
                "sampled_frames": len(frames),
                "sample_fps": fps,
                "mean_interframe_change": float(diffs.mean()),
                "interframe_change_series": [round(float(d), 3) for d in diffs],
                "residual_series": [round(float(r), 3) for r in resid],
                "keyframe_times": keyframes[:500],
                "keyframe_count": len(keyframes),
            },
            segments=segments[:1000],
            artifacts=[
                Artifact(
                    "contact_sheet.png",
                    "image/png",
                    buf.getvalue(),
                    "Evenly spaced sampled frames.",
                    "Frames are for orientation; visual impressions are not findings.",
                ),
                Artifact(
                    "interframe_change.png",
                    "image/png",
                    png_bytes(diff_strip),
                    "Inter-frame change over time (bright = large change).",
                    "Cuts and motion are normal; discontinuities are prompts for review.",
                ),
            ],
            config={"sample_fps": fps, "max_frames": MAX_SAMPLED_FRAMES, "analysis_width": 320},
            warnings=["Analysis covers sampled frames only."] if len(frames) >= MAX_SAMPLED_FRAMES else [],
        )
