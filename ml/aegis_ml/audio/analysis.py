"""Audio forensics: container inspection (ffprobe), PCM decoding (ffmpeg), waveform/spectrogram and
signal-quality observations. No speaker identification or attribute inference is performed."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal

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
from aegis_ml.visual import heat_png, waveform_png

MAX_AUDIO_SECONDS = 900


def ffprobe(path: Path) -> dict[str, Any]:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("ffprobe not installed")
    out = run_tool(
        [exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60
    )
    return json.loads(out)


def tools_available() -> tuple[bool, str]:
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        return False, "ffmpeg/ffprobe are not installed on this worker."
    return True, "available"


def decode_pcm(path: Path, sample_rate: int, max_seconds: int = MAX_AUDIO_SECONDS) -> np.ndarray:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not installed")
    raw = run_tool(
        [
            exe,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-t",
            str(max_seconds),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "-",
        ],
        timeout=300,
    )
    return np.frombuffer(raw, dtype=np.float32).copy()


def _audio_stream(probe: dict) -> dict | None:
    return next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)


class AudioSignalMethod(AnalysisMethod):
    info = MethodInfo(
        id="audio.signal_analysis",
        name="Audio container, waveform and spectrogram",
        version="1.0.0",
        modalities=(Modality.AUDIO, Modality.VIDEO),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Codec, sample rate, channels, levels, clipping, silence, effective bandwidth, spectrogram.",
        output_semantics=(
            "Signal-quality observations. A narrow effective bandwidth can indicate resampling or transcoding; it is "
            "not evidence of synthesis on its own."
        ),
        limitations=(
            "Transcoding, telephony channels and noise reduction alter every measured quantity.",
            "No speaker identity, nationality, ethnicity or intent is inferred.",
        ),
    )

    def availability(self) -> tuple[bool, str]:
        return tools_available()

    def supports(self, inp: AnalysisInput) -> bool:
        return inp.modality in (Modality.AUDIO, Modality.VIDEO)

    def _run(self, inp: AnalysisInput) -> MethodResult:
        probe = ffprobe(inp.original_path)
        st = _audio_stream(probe)
        if st is None:
            return self.result(RunStatus.UNSUPPORTED_INPUT, "No audio stream found.")
        native_sr = int(st.get("sample_rate") or 16000)
        sr = min(native_sr, 48000)
        x = decode_pcm(inp.original_path, sr)
        duration = len(x) / sr if sr else 0
        if duration < 0.5:
            return self.result(RunStatus.INSUFFICIENT_INPUT, "Audio shorter than 0.5 s.")
        warnings: list[str] = []
        peak = float(np.abs(x).max()) or 1e-12
        rms = float(np.sqrt(np.mean(x**2))) or 1e-12
        frame = int(sr * 0.02)
        frames = x[: len(x) // frame * frame].reshape(-1, frame)
        frame_db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-12)
        silence = float((frame_db < -50).mean())
        clipping = float((np.abs(x) >= 0.999).mean())
        f, t, sxx = signal.spectrogram(x, fs=sr, nperseg=1024, noverlap=768, window="hann")
        power = sxx.mean(axis=1)
        cum = np.cumsum(power) / power.sum() if power.sum() else np.zeros_like(power)
        bw99 = float(f[np.searchsorted(cum, 0.99)]) if power.sum() else None
        flatness = float(np.mean(np.exp(np.mean(np.log(sxx + 1e-12), axis=0)) / (np.mean(sxx, axis=0) + 1e-12)))
        if native_sr < 16000:
            warnings.append(f"Low sample rate ({native_sr} Hz) limits spectral analysis.")
        if clipping > 0.001:
            warnings.append(f"{clipping:.2%} of samples are clipped.")
        if duration < 2:
            warnings.append("Very short recording; observations are unstable.")
        if bw99 is not None and bw99 < 0.6 * (sr / 2):
            warnings.append(
                f"99% of energy lies below {bw99:.0f} Hz (Nyquist {sr / 2:.0f} Hz): consistent with band-limiting, "
                "resampling or transcoding. Many benign causes exist."
            )
        if probe.get("format", {}).get("duration") and float(probe["format"]["duration"]) > MAX_AUDIO_SECONDS:
            warnings.append(f"Only the first {MAX_AUDIO_SECONDS} s were analysed.")
        # Loud/quiet segments for the timeline (non-silent runs).
        segs: list[Segment] = []
        active = frame_db >= -50
        start = None
        for i, a in enumerate(np.r_[active, False]):
            if a and start is None:
                start = i
            elif not a and start is not None:
                if (i - start) * 0.02 >= 0.3:
                    segs.append(Segment(start * 0.02, i * 0.02, "seconds", "active_signal"))
                start = None
        db = 10 * np.log10(sxx + 1e-12)
        tags = {**probe.get("format", {}).get("tags", {}), **st.get("tags", {})}
        return self.result(
            RunStatus.COMPLETED,
            f"{st.get('codec_name')} {native_sr} Hz, {st.get('channels')} ch, {duration:.1f} s analysed.",
            output={
                "codec": st.get("codec_name"),
                "codec_long_name": st.get("codec_long_name"),
                "native_sample_rate": native_sr,
                "analysis_sample_rate": sr,
                "channels": st.get("channels"),
                "channel_layout": st.get("channel_layout"),
                "bit_rate": st.get("bit_rate") or probe.get("format", {}).get("bit_rate"),
                "container": probe.get("format", {}).get("format_name"),
                "duration_seconds": round(duration, 3),
                "peak_dbfs": round(20 * np.log10(peak), 2),
                "rms_dbfs": round(20 * np.log10(rms), 2),
                "dc_offset": float(x.mean()),
                "clipping_fraction": clipping,
                "silence_fraction": silence,
                "effective_bandwidth_99_hz": bw99,
                "mean_spectral_flatness": flatness,
                "container_tags": {k: str(v)[:200] for k, v in tags.items()},
            },
            segments=segs[:500],
            warnings=warnings,
            artifacts=[
                Artifact(
                    "waveform.png",
                    "image/png",
                    waveform_png(x / peak),
                    "Peak-normalised waveform envelope.",
                    "Cannot establish authenticity or synthesis.",
                ),
                Artifact(
                    "spectrogram.png",
                    "image/png",
                    heat_png(np.flipud(db[:, :: max(1, db.shape[1] // 1600)])),
                    "Log-power spectrogram (1024-point Hann STFT); low frequencies at the bottom.",
                    "Spectral patterns have many benign causes (codecs, rooms, microphones).",
                ),
            ],
            config={"stft": {"nperseg": 1024, "noverlap": 768}, "silence_threshold_dbfs": -50},
        )


class TranscriptionPlaceholder(AnalysisMethod):
    info = MethodInfo(
        id="audio.transcription",
        name="Speech transcription (separate service)",
        version="0.0.0",
        modalities=(Modality.AUDIO, Modality.VIDEO),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.PLACEHOLDER,
        description=(
            "Optional transcription engine boundary. Transcripts are labelled separately from authenticity findings."
        ),
        output_semantics=(
            "Machine transcript with engine confidence; transcription errors are not authenticity findings."
        ),
        limitations=("No transcription engine is bundled.",),
        requires=("AEGIS_TRANSCRIPTION_ENGINE",),
    )

    def availability(self) -> tuple[bool, str]:
        return False, "No transcription engine configured."

    def _run(self, inp: AnalysisInput) -> MethodResult:  # pragma: no cover
        raise RuntimeError("unavailable")
