"""Integration boundaries for detectors that AEGIS does not bundle.

* :class:`HttpDetectorProvider` - a documented JSON contract for an external or self-hosted
  detection service. Evidence leaves the deployment, so it is blocked unless the investigation
  explicitly permits external processing. Secrets stay server-side.
* :class:`LocalOnnxClassifier` - runs a local ONNX classifier (image or audio) when an operator
  supplies weights and a model card JSON.

Neither ever fabricates a response: misconfiguration -> ``unavailable``; invalid provider output
-> ``failed``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from aegis_ml.core import (
    AnalysisInput,
    AnalysisMethod,
    EvidenceClass,
    ImplementationStatus,
    MethodInfo,
    MethodResult,
    Modality,
    RunStatus,
)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ProviderResponseError(ValueError):
    pass


def validate_provider_response(body: Any) -> dict[str, Any]:
    """Strict validation of the provider contract (see docs/api/provider-contract.md)."""
    if not isinstance(body, dict):
        raise ProviderResponseError("response is not a JSON object")
    score = body.get("score")
    if not isinstance(score, int | float) or isinstance(score, bool) or not np.isfinite(score):
        raise ProviderResponseError("'score' must be a finite number")
    version = body.get("model_version")
    if not isinstance(version, str) or not 0 < len(version) <= 128:
        raise ProviderResponseError("'model_version' must be a non-empty string")
    semantics = body.get("score_semantics", "provider-defined score")
    if not isinstance(semantics, str):
        raise ProviderResponseError("'score_semantics' must be a string")
    rid = body.get("request_id")
    if rid is not None and (not isinstance(rid, str) or not _SAFE_REQUEST_ID.match(rid)):
        raise ProviderResponseError("'request_id' has an invalid format")
    calibrated = body.get("calibrated_probability")
    if calibrated is not None and (not isinstance(calibrated, int | float) or not 0 <= calibrated <= 1):
        raise ProviderResponseError("'calibrated_probability' must be within [0, 1]")
    return {
        "score": float(score),
        "model_version": version,
        "score_semantics": semantics[:300],
        "request_id": rid,
        "provider_calibrated_probability": calibrated,  # vendor-reported; not validated by AEGIS
    }


class HttpDetectorProvider(AnalysisMethod):
    def __init__(self, provider_id: str, modality: Modality, name: str) -> None:
        self.provider_id = provider_id
        prefix = f"AEGIS_PROVIDER_{provider_id.upper()}"
        self._url_key, self._token_key, self._timeout_key = f"{prefix}_URL", f"{prefix}_TOKEN", f"{prefix}_TIMEOUT"
        self.info = MethodInfo(
            id=f"provider.{provider_id}",
            name=name,
            version="1.0.0",
            modalities=(modality,),
            evidence_class=EvidenceClass.STATISTICAL_INFERENCE,
            implementation=ImplementationStatus.REQUIRES_CONFIGURATION,
            description="Sends the evidence to a configured detection service using the AEGIS provider contract.",
            output_semantics=(
                "Provider score with the provider's stated semantics. Vendor claims are not AEGIS validation."
            ),
            limitations=(
                "Evidence leaves this deployment; requires an authorised configuration and data-processing terms.",
                "Provider accuracy is vendor-reported until measured in the Benchmark Laboratory.",
            ),
            requires=(self._url_key, self._token_key),
            external_processing=True,
        )

    def availability(self) -> tuple[bool, str]:
        url = os.environ.get(self._url_key)
        if not url:
            return False, f"Provider not configured ({self._url_key} unset)."
        if not url.startswith("https://") and os.environ.get("AEGIS_ALLOW_INSECURE_PROVIDERS") != "1":
            return False, "Provider URL must use HTTPS."
        return True, "available"

    def _run(self, inp: AnalysisInput) -> MethodResult:
        import httpx

        url = os.environ[self._url_key]
        headers = {"X-AEGIS-Evidence-SHA256": inp.sha256}
        if tok := os.environ.get(self._token_key):
            headers["Authorization"] = f"Bearer {tok}"
        timeout = float(os.environ.get(self._timeout_key, "60"))
        with inp.original_path.open("rb") as fh:
            resp = httpx.post(url, files={"file": ("evidence", fh, inp.mime_type)}, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return self.result(RunStatus.FAILED, f"Provider returned HTTP {resp.status_code}.")
        try:
            body = validate_provider_response(resp.json())
        except (ProviderResponseError, json.JSONDecodeError) as exc:
            return self.result(RunStatus.FAILED, f"Provider response rejected: {exc}")
        return self.result(
            RunStatus.COMPLETED,
            "Provider score recorded; not interpreted without a validated threshold.",
            score=body["score"],
            score_semantics=body["score_semantics"],
            output=body,
            config={"provider_id": self.provider_id, "timeout_s": timeout},
        )


class LocalOnnxClassifier(AnalysisMethod):
    """Model directory layout: ``model.onnx`` + ``aegis_model.json``::

    {"name": "...", "version": "...", "license": "...", "positive_index": 1,
     "input": {"kind": "image", "size": 224, "mean": [..], "std": [..]}   # or
     "input": {"kind": "audio", "sample_rate": 16000, "samples": 64600},
     "calibration": {...optional, validated: true, threshold: ...}}
    """

    def __init__(self, method_id: str, modality: Modality, env_key: str, name: str, refs: tuple[str, ...]) -> None:
        self.env_key = env_key
        self.info = MethodInfo(
            id=method_id,
            name=name,
            version="1.0.0",
            modalities=(modality,) if modality != Modality.AUDIO else (Modality.AUDIO, Modality.VIDEO),
            evidence_class=EvidenceClass.STATISTICAL_INFERENCE,
            implementation=ImplementationStatus.REQUIRES_CONFIGURATION,
            description=f"Local ONNX model configured via {env_key}.",
            output_semantics=(
                "Model output for the positive (synthetic) class; uncalibrated unless a validated profile exists."
            ),
            limitations=(
                "Learned detectors degrade on unseen generators, compression and re-recording.",
                "No identity, nationality or intent is inferred from any output.",
            ),
            references=refs,
            requires=(env_key, "onnxruntime"),
        )

    def _dir(self) -> Path | None:
        p = os.environ.get(self.env_key)
        return Path(p) if p else None

    def availability(self) -> tuple[bool, str]:
        d = self._dir()
        if d is None:
            return False, f"No model configured ({self.env_key} unset)."
        if not (d / "model.onnx").is_file() or not (d / "aegis_model.json").is_file():
            return False, "Model directory must contain model.onnx and aegis_model.json."
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return False, "onnxruntime is not installed."
        return True, "available"

    def _prepare(self, inp: AnalysisInput, spec: dict) -> np.ndarray:
        if spec["kind"] == "image":
            from PIL import Image

            img = Image.open(inp.original_path).convert("RGB").resize((spec["size"], spec["size"]))
            x = (np.asarray(img, dtype=np.float32) / 255 - np.array(spec["mean"])) / np.array(spec["std"])
            return x.transpose(2, 0, 1)[None].astype(np.float32)
        from aegis_ml.audio.analysis import decode_pcm

        pcm = decode_pcm(inp.original_path, spec["sample_rate"])[: spec["samples"]]
        pcm = np.pad(pcm, (0, max(0, spec["samples"] - len(pcm))))
        return pcm[None].astype(np.float32)

    def _run(self, inp: AnalysisInput) -> MethodResult:
        import onnxruntime as ort

        d = self._dir()
        assert d
        card = json.loads((d / "aegis_model.json").read_text())
        sess = ort.InferenceSession(str(d / "model.onnx"), providers=["CPUExecutionProvider"])
        out = sess.run(None, {sess.get_inputs()[0].name: self._prepare(inp, card["input"])})[0][0]
        probs = np.exp(out - out.max()) / np.exp(out - out.max()).sum()
        score = float(probs[card.get("positive_index", 1)])
        cal = card.get("calibration") if (card.get("calibration") or {}).get("validated") else None
        flagged = (score >= cal["threshold"]) if cal and "threshold" in cal else None
        return self.result(
            RunStatus.COMPLETED,
            "Model output recorded; "
            + (
                "compared with a validated threshold."
                if flagged is not None
                else "no validated threshold, so it is not interpreted."
            ),
            score=score,
            score_semantics="softmax output for the positive class",
            flagged=flagged,
            calibrated=False,
            output={"model": {k: card.get(k) for k in ("name", "version", "license")}, "calibration_profile": cal},
        )


def run_tool(args: list[str], timeout: int = 120, max_output: int = 50_000_000) -> bytes:
    """Run ffprobe/ffmpeg without a shell, with timeout and output cap."""
    proc = subprocess.run(args, capture_output=True, timeout=timeout, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise RuntimeError(
            f"{Path(args[0]).name} exited with {proc.returncode}: {proc.stderr[-400:].decode(errors='replace')}"
        )
    if len(proc.stdout) > max_output:
        raise RuntimeError("tool output exceeded the safety limit")
    return proc.stdout
