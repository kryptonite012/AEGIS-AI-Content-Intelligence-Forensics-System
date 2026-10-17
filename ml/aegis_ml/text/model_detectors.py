"""Model-based text detectors (supervised classifier, token statistics, Fast-DetectGPT, Binoculars).

These are real implementations that run when compatible model weights are present on local disk.
AEGIS does not bundle or download weights. Without configuration every method here returns
``unavailable``. Raw scores are never presented as probabilities: a method only sets ``flagged``
or ``calibrated`` when a calibration file validated on held-out data accompanies the model.

Calibration file (``aegis_calibration.json`` in the model directory), written by the Benchmark
Laboratory or by an evaluator::

    {"method": "platt", "a": 3.1, "b": -1.2, "threshold": 0.97, "direction": "higher_is_ai",
     "dataset": "...", "benchmark_run_id": "...", "validated": true,
     "languages_evaluated": ["en"], "validated_granularity": ["document"]}
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from aegis_ml.core import AnalysisInput, AnalysisMethod, EvidenceClass, ImplementationStatus, MethodInfo
from aegis_ml.core import MethodResult, Modality, RunStatus, Segment
from aegis_ml.text.extract import MIN_TOKENS_FOR_ANALYSIS
from aegis_ml.text.segment import paragraphs

MAX_MODEL_TOKENS = 512


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _device() -> str:
    pref = os.environ.get("AEGIS_INFERENCE_DEVICE", "cpu")
    if pref == "cuda":
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cpu"


@lru_cache(maxsize=4)
def _load_classifier(path: str):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True)
    return tok, model.eval().to(_device())


@lru_cache(maxsize=4)
def _load_causal_lm(path: str):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(path, local_files_only=True)
    return tok, model.eval().to(_device())


def load_calibration(model_dir: str | None) -> dict[str, Any] | None:
    if not model_dir:
        return None
    p = Path(model_dir) / "aegis_calibration.json"
    if not p.is_file():
        return None
    cal = json.loads(p.read_text())
    return cal if cal.get("validated") is True else None


def _model_identity(path: str) -> dict[str, Any]:
    p = Path(path)
    cfg = p / "config.json"
    ident: dict[str, Any] = {"path_name": p.name}
    if cfg.is_file():
        c = json.loads(cfg.read_text())
        ident.update({k: c.get(k) for k in ("_name_or_path", "model_type", "architectures") if k in c})
    weights = sorted(p.glob("*.safetensors")) or sorted(p.glob("*.bin"))
    if weights:
        import hashlib

        h = hashlib.sha256()
        with weights[0].open("rb") as f:
            h.update(f.read(1 << 20))  # first MiB: fast fingerprint, documented as partial
        ident["weights_fingerprint_first_mib_sha256"] = h.hexdigest()[:32]
    return ident


def _apply_calibration(score: float, cal: dict[str, Any] | None) -> tuple[float | None, bool | None]:
    if not cal:
        return None, None
    if cal.get("method") == "platt":
        prob = 1 / (1 + math.exp(-(cal["a"] * score + cal["b"])))
    else:
        prob = None
    direction = cal.get("direction", "higher_is_ai")
    thr = cal.get("threshold")
    flagged = None
    if thr is not None:
        flagged = score >= thr if direction == "higher_is_ai" else score <= thr
    return prob, flagged


def _language_ok(inp: AnalysisInput, cal: dict[str, Any] | None) -> list[str]:
    warnings = []
    langs = (cal or {}).get("languages_evaluated")
    if langs and inp.language and inp.language not in langs:
        warnings.append(
            f"Out-of-distribution: language '{inp.language}' was not in this model's evaluation "
            f"({', '.join(langs)}). Calibration and operating threshold do not apply."
        )
    return warnings


class _TextModelMethod(AnalysisMethod):
    env_key = ""

    def model_path(self) -> str | None:
        return os.environ.get(self.env_key) or None

    def availability(self) -> tuple[bool, str]:
        path = self.model_path()
        if not path:
            return False, f"No model configured ({self.env_key} is unset)."
        if not Path(path).is_dir():
            return False, f"Configured model directory does not exist ({self.env_key})."
        if not _torch_available():
            return False, "Optional dependencies missing: install aegis-ml[transformers] (torch, transformers)."
        return True, "available"

    def _precheck(self, inp: AnalysisInput) -> MethodResult | None:
        tokens = (inp.extraction or {}).get("token_count", 0)
        if not inp.text or tokens < MIN_TOKENS_FOR_ANALYSIS:
            return self.result(
                RunStatus.INSUFFICIENT_INPUT,
                f"Text has {tokens} tokens; at least {MIN_TOKENS_FOR_ANALYSIS} are required for this method.",
            )
        return None


class SupervisedClassifierAdapter(_TextModelMethod):
    env_key = "AEGIS_TEXT_CLASSIFIER_PATH"
    info = MethodInfo(
        id="text.supervised_classifier",
        name="Supervised AI-text classifier (local transformer)",
        version="1.0.0",
        modalities=(Modality.TEXT, Modality.DOCUMENT),
        evidence_class=EvidenceClass.STATISTICAL_INFERENCE,
        implementation=ImplementationStatus.REQUIRES_CONFIGURATION,
        description="Runs a locally stored sequence-classification model trained to separate human and AI text.",
        output_semantics=(
            "Raw classifier output for the configured AI label. Not a probability unless a validated "
            "calibration profile is attached."
        ),
        limitations=(
            "Supervised detectors generalise poorly to generators, domains and languages absent from training.",
            "Paraphrasing and editing can reduce scores; non-native writing can raise false positives.",
        ),
        references=("Solaiman et al. (2019); Uchendu et al. (2020); see docs/research/literature-map.md",),
        requires=("AEGIS_TEXT_CLASSIFIER_PATH", "AEGIS_TEXT_CLASSIFIER_AI_LABEL", "aegis-ml[transformers]"),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        if (early := self._precheck(inp)) is not None:
            return early
        import torch

        path = self.model_path()
        assert path
        tok, model = _load_classifier(path)
        ai_label = os.environ.get("AEGIS_TEXT_CLASSIFIER_AI_LABEL", "")
        label2id = {str(k).lower(): v for k, v in (model.config.label2id or {}).items()}
        if ai_label.lower() not in label2id:
            return self.result(
                RunStatus.FAILED,
                "AEGIS_TEXT_CLASSIFIER_AI_LABEL does not match a model label; refusing to guess which output is 'AI'.",
                output={"model_labels": list(label2id)},
            )
        ai_idx = label2id[ai_label.lower()]
        cal = load_calibration(path)

        def score(text: str) -> float:
            enc = tok(text, truncation=True, max_length=MAX_MODEL_TOKENS, return_tensors="pt").to(model.device)
            with torch.no_grad():
                probs = torch.softmax(model(**enc).logits[0], dim=-1)
            return float(probs[ai_idx])

        enc_all = tok(inp.text, add_special_tokens=False)["input_ids"]
        chunks = [enc_all[i : i + MAX_MODEL_TOKENS - 2] for i in range(0, len(enc_all), MAX_MODEL_TOKENS - 2)][:16]
        chunk_scores = [score(tok.decode(c)) for c in chunks]
        doc_score = sum(chunk_scores) / len(chunk_scores)
        prob, flagged = _apply_calibration(doc_score, cal)
        warnings = _language_ok(inp, cal)
        if warnings:
            prob, flagged = None, None
        segments: list[Segment] = []
        if cal and "paragraph" in cal.get("validated_granularity", []):
            for p in paragraphs(inp.text)[:200]:
                segments.append(Segment(p.start, p.end, "char", "paragraph", score(p.text)))
        elif len(paragraphs(inp.text)) > 1:
            warnings.append("Segment-level scores withheld: the model is not validated at paragraph granularity.")
        if len(enc_all) > len(chunks) * (MAX_MODEL_TOKENS - 2):
            warnings.append("Only the first 16 chunks were scored.")
        summary = (
            "Classifier output recorded; no validated operating threshold, so the output is not interpreted."
            if flagged is None
            else ("Classifier output exceeds the validated threshold (consistent with AI generation)."
                  if flagged else "Classifier output below the validated threshold. This does not prove human authorship.")
        )
        return self.result(
            RunStatus.COMPLETED, summary, score=doc_score,
            score_semantics=f"mean softmax output for label '{ai_label}' over {len(chunks)} chunk(s)",
            calibrated=prob is not None, flagged=flagged,
            output={"chunk_scores": chunk_scores, "calibrated_probability": prob, "model": _model_identity(path),
                    "calibration_profile": cal, "model_tokens": len(enc_all)},
            uncertainty={"chunk_score_range": [min(chunk_scores), max(chunk_scores)]},
            warnings=warnings, segments=segments,
            config={"max_tokens": MAX_MODEL_TOKENS, "ai_label": ai_label, "device": str(model.device)},
        )


def _token_logprobs(tok, model, text: str):
    """Per-position log-probabilities from a causal LM (first window only)."""
    import torch

    ids = tok(text, return_tensors="pt", truncation=True, max_length=MAX_MODEL_TOKENS)["input_ids"].to(model.device)
    with torch.no_grad():
        logits = model(ids).logits[0, :-1].float()
    targets = ids[0, 1:]
    return torch.log_softmax(logits, dim=-1), targets


class TokenStatisticsMethod(_TextModelMethod):
    env_key = "AEGIS_SCORING_LM_PATH"
    info = MethodInfo(
        id="text.token_statistics",
        name="Language-model token statistics (log-likelihood, perplexity, token rank)",
        version="1.0.0",
        modalities=(Modality.TEXT, Modality.DOCUMENT),
        evidence_class=EvidenceClass.STATISTICAL_INFERENCE,
        implementation=ImplementationStatus.REQUIRES_CONFIGURATION,
        description="Scores the text with a local causal language model and reports likelihood and rank features.",
        output_semantics="Feature values under the configured scoring model. None of them is a detection score.",
        limitations=(
            "Values depend strongly on the scoring model, domain and language.",
            "Formulaic human writing (legal, technical, non-native) can be highly predictable.",
        ),
        references=("Gehrmann et al. (2019), GLTR; Mitchell et al. (2023) discuss likelihood baselines.",),
        requires=("AEGIS_SCORING_LM_PATH", "aegis-ml[transformers]"),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        if (early := self._precheck(inp)) is not None:
            return early
        import torch

        path = self.model_path()
        assert path
        tok, model = _load_causal_lm(path)
        lp, targets = _token_logprobs(tok, model, inp.text or "")
        tgt_lp = lp.gather(1, targets[:, None])[:, 0]
        ranks = (lp > tgt_lp[:, None]).sum(dim=1) + 1
        mean_ll = float(tgt_lp.mean())
        return self.result(
            RunStatus.COMPLETED,
            f"Token statistics computed over {len(targets)} model tokens; features are not a verdict.",
            output={
                "model_tokens_scored": int(len(targets)),
                "mean_log_likelihood": mean_ll,
                "perplexity": math.exp(-mean_ll),
                "log_likelihood_stdev": float(tgt_lp.std()),
                "mean_log_rank": float(torch.log(ranks.float()).mean()),
                "fraction_top1": float((ranks == 1).float().mean()),
                "fraction_top10": float((ranks <= 10).float().mean()),
                "model": _model_identity(path),
            },
            config={"max_tokens": MAX_MODEL_TOKENS},
            warnings=["Only the first window of tokens was scored."] if len(targets) >= MAX_MODEL_TOKENS - 1 else [],
        )


class FastDetectGPTMethod(_TextModelMethod):
    env_key = "AEGIS_SCORING_LM_PATH"
    info = MethodInfo(
        id="text.fast_detectgpt_analytic",
        name="Fast-DetectGPT (analytic, single scoring model)",
        version="1.0.0",
        modalities=(Modality.TEXT, Modality.DOCUMENT),
        evidence_class=EvidenceClass.STATISTICAL_INFERENCE,
        implementation=ImplementationStatus.REQUIRES_CONFIGURATION,
        description=(
            "Conditional probability curvature computed analytically, using the same local model for "
            "sampling and scoring."
        ),
        output_semantics="Normalised curvature criterion; larger values are more consistent with model-generated text.",
        limitations=(
            "Uses one model for sampling and scoring. The paper's strongest results use specific model pairs; "
            "this configuration is not a reproduction of those results.",
            "Performance depends on the scoring model matching the (unknown) source generator.",
        ),
        references=("Bao et al. (2024), Fast-DetectGPT, ICLR.", "Mitchell et al. (2023), DetectGPT, ICML."),
        requires=("AEGIS_SCORING_LM_PATH", "aegis-ml[transformers]"),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        if (early := self._precheck(inp)) is not None:
            return early
        path = self.model_path()
        assert path
        tok, model = _load_causal_lm(path)
        lp, targets = _token_logprobs(tok, model, inp.text or "")
        p = lp.exp()
        ll = lp.gather(1, targets[:, None])[:, 0].sum()
        mu = (p * lp).sum(dim=1)
        var = (p * lp.pow(2)).sum(dim=1) - mu.pow(2)
        crit = float((ll - mu.sum()) / var.sum().sqrt())
        cal = load_calibration(path)
        prob, flagged = _apply_calibration(crit, cal)
        warnings = _language_ok(inp, cal)
        if warnings:
            prob, flagged = None, None
        return self.result(
            RunStatus.COMPLETED,
            "Curvature criterion computed; " + ("interpreted against a validated threshold." if flagged is not None
                                                 else "no validated threshold, so it is not interpreted."),
            score=crit, score_semantics="Fast-DetectGPT analytic criterion (sampling model = scoring model)",
            calibrated=prob is not None, flagged=flagged,
            output={"criterion": crit, "model_tokens_scored": int(len(targets)), "calibrated_probability": prob,
                    "model": _model_identity(path), "calibration_profile": cal},
            warnings=warnings, config={"max_tokens": MAX_MODEL_TOKENS, "sampling_model": "same as scoring"},
        )


class BinocularsMethod(_TextModelMethod):
    env_key = "AEGIS_BINOCULARS_OBSERVER_PATH"
    info = MethodInfo(
        id="text.binoculars",
        name="Binoculars (observer/performer cross-perplexity)",
        version="1.0.0",
        modalities=(Modality.TEXT, Modality.DOCUMENT),
        evidence_class=EvidenceClass.STATISTICAL_INFERENCE,
        implementation=ImplementationStatus.REQUIRES_CONFIGURATION,
        description="Ratio of observer log-perplexity to observer/performer cross-perplexity.",
        output_semantics="Binoculars score; LOWER values are more consistent with model-generated text.",
        limitations=(
            "Requires two models sharing a tokenizer; the published threshold applies only to the published pair.",
            "Not validated by AEGIS for any language unless a calibration profile says so.",
        ),
        references=("Hans et al. (2024), Spotting LLMs With Binoculars, ICML.",),
        requires=("AEGIS_BINOCULARS_OBSERVER_PATH", "AEGIS_BINOCULARS_PERFORMER_PATH", "aegis-ml[transformers]"),
    )

    def availability(self) -> tuple[bool, str]:
        ok, reason = super().availability()
        if not ok:
            return ok, reason
        perf = os.environ.get("AEGIS_BINOCULARS_PERFORMER_PATH")
        if not perf or not Path(perf).is_dir():
            return False, "Performer model not configured (AEGIS_BINOCULARS_PERFORMER_PATH)."
        return True, "available"

    def _run(self, inp: AnalysisInput) -> MethodResult:
        if (early := self._precheck(inp)) is not None:
            return early
        import torch

        obs_path = self.model_path()
        perf_path = os.environ["AEGIS_BINOCULARS_PERFORMER_PATH"]
        assert obs_path
        tok, observer = _load_causal_lm(obs_path)
        tok2, performer = _load_causal_lm(perf_path)
        if tok.get_vocab() != tok2.get_vocab():
            return self.result(RunStatus.FAILED, "Observer and performer tokenizers differ; Binoculars requires a shared vocabulary.")
        ids = tok(inp.text, return_tensors="pt", truncation=True, max_length=MAX_MODEL_TOKENS)["input_ids"]
        with torch.no_grad():
            lo = observer(ids.to(observer.device)).logits[0, :-1].float()
            lpf = performer(ids.to(performer.device)).logits[0, :-1].float().to(lo.device)
        targets = ids[0, 1:].to(lo.device)
        # Matches the reference implementation: log-perplexity under the performer, and
        # cross-perplexity = cross-entropy of performer log-probs against observer probabilities.
        lp_perf = torch.log_softmax(lpf, -1)
        log_ppl = float(-lp_perf.gather(1, targets[:, None]).mean())
        x_ppl = float(-(torch.softmax(lo, -1) * lp_perf).sum(-1).mean())
        score = log_ppl / x_ppl
        cal = load_calibration(obs_path)
        if cal:
            cal = {**cal, "direction": cal.get("direction", "lower_is_ai")}
        prob, flagged = _apply_calibration(score, cal)
        warnings = _language_ok(inp, cal)
        if warnings:
            prob, flagged = None, None
        return self.result(
            RunStatus.COMPLETED,
            "Binoculars score computed; " + ("interpreted against a validated threshold." if flagged is not None
                                              else "no validated threshold, so it is not interpreted."),
            score=score, score_semantics="log-perplexity / cross-perplexity (lower = more model-like)",
            calibrated=prob is not None, flagged=flagged,
            output={"log_perplexity": log_ppl, "cross_perplexity": x_ppl, "score": score,
                    "observer": _model_identity(obs_path), "performer": _model_identity(perf_path),
                    "calibration_profile": cal},
            warnings=warnings, config={"max_tokens": MAX_MODEL_TOKENS},
        )
