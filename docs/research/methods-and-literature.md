# Methods and literature map

> **Source note.** The project brief refers to three supporting research documents: a technical report, a 2019–2026 literature review, and the paper "When Can an AI-Content Flag Be Trusted?". Those documents were not attached to this repository. AEGIS implements the principles, formulas and nine experiment categories exactly as the brief describes them. The references below are to the public literature. Each method has the status stated, and nothing more is claimed.

## Status legend

- **Implemented**: the real algorithm runs in AEGIS on bundled dependencies.
- **Adapter**: the real algorithm is implemented but needs operator-supplied model weights. It is `unavailable` until configured.
- **Boundary**: an integration point only. It never produces results.

| Family | Method in AEGIS | Status | Notes and references |
| --- | --- | --- | --- |
| Supervised AI-text classifiers | `text.supervised_classifier` | Adapter | Any local HF sequence-classification model; the operator must name the AI label. Solaiman et al. 2019 (GPT-2 output detector); Uchendu et al. 2020. Known to generalise poorly to unseen generators and domains. |
| Perplexity and token rank | `text.token_statistics` | Adapter | Log-likelihood, perplexity, log-rank and top-k fractions under a local causal LM. GLTR (Gehrmann et al., 2019). Reports features, never a verdict. |
| DetectGPT-style curvature | — | Not implemented | Mitchell et al. 2023. Needs a perturbation model and many forward passes; superseded in AEGIS by the analytic variant below. |
| Fast-DetectGPT | `text.fast_detectgpt_analytic` | Adapter | Bao et al. 2024, analytic conditional curvature. **AEGIS uses one model for both sampling and scoring.** That is a valid configuration of the method but not the paper's best model pair, so the paper's results are not claimed. |
| Binoculars | `text.binoculars` | Adapter | Hans et al. 2024. Performer log-perplexity divided by observer/performer cross-perplexity, matching the reference implementation. The published threshold applies only to the published Falcon-7B pair; it is not used. |
| Watermark verification | `watermark.aegis_reference_text` | Implemented | Kirchenbauer et al. 2023 green-list scheme with exact binomial p-values and per-(context, token) deduplication. Verifies only the AEGIS reference generator's text under this deployment's key. |
| Provider watermarks | `watermark.synthid_text` | Boundary | Dathathri et al. 2024 (SynthID-Text). Needs a provider agreement, keys and detector weights. |
| Signed provenance | `provenance.c2pa` | Implemented | C2PA 2.x through official `c2pa-python` / `c2pa-rs`. Reports manifest presence, signature and hash validity, and signer trust (against configured anchors) separately. |
| Declared metadata | `metadata.declared_generation_claims` | Implemented | PNG text chunks (for example, Stable Diffusion `parameters`), EXIF Software/Comment, XMP `DigitalSourceType`, container encoder tags. Treated as unverified claims. |
| Image forensics | `image.metadata`, `image.frequency_spectrum`, `image.noise_residual`, `image.error_level_analysis` | Implemented | Observations for an analyst: spectral artefacts of upsampling (Durall et al. 2020; Frank et al. 2020), noise residuals, ELA (Krawetz 2007). None of these is a classifier. |
| Image generation classifiers | `image.local_model`, `provider.image_detector` | Adapter / boundary | For example, CNNDetection (Wang et al. 2020) or UnivFD (Ojha et al. 2023) exported to ONNX by the operator. |
| Synthetic speech | `audio.signal_analysis` (implemented); `audio.synthetic_speech_model` (adapter); `provider.audio_detector` (boundary) | Mixed | Signal-quality observations are implemented. Classifiers such as AASIST (Jung et al. 2022) need ONNX weights. No speaker identification is performed. |
| Video manipulation & temporal consistency | `video.container`, `video.temporal_consistency` (implemented); `video.frame_model` (adapter); `provider.video_detector` (boundary) | Mixed | Container/stream inspection, keyframes, inter-frame change, duplicate/frozen frames, discontinuities, noise-level shifts, container-level A/V alignment. Lip-sync analysis is not implemented. |
| Adversarial robustness evaluation | Benchmark `transform` field; experiment 6 | Implemented | Defensive measurement of documented transformations only. |
| Retrieval-based corroboration | — | Not implemented | Needs authorised reference corpora; on the roadmap. |
| Process evidence | `process_evidence` evidence role | Implemented | Recorded as a separate evidence class; never scored automatically. |

## Unresolved problems the platform is built around

| Problem | How AEGIS responds |
| --- | --- |
| Generalisation to unseen generators | Held-out evaluation (`holdout_field=generator`) in the Benchmark Laboratory; no detector counts as validated without locally measured evidence. |
| Edited / paraphrased material | Robustness transforms in benchmarks; mixed-authorship segment scores withheld unless validated at that granularity. |
| Multilingual robustness, Indian languages | Language and script identification (Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada, Malayalam); per-model `languages_evaluated`; an out-of-distribution warning removes calibration for unevaluated languages. See the [multilingual plan](multilingual-evaluation-plan.md). |
| Fairness across writer populations | Fairness laboratory over consented evaluation-data fields only, with exact intervals and small-group suppression. |
| Mixed human–AI authorship | No binary label is forced. Outcome categories describe evidence. |
| Low false-positive operating points | TPR at 1% and 0.1% FPR with exact bounds and an estimability check (at least ⌈ln 0.05 / ln(1−FPR)⌉ negatives). |
| Short-text reliability | A 50-token minimum for text detectors; watermark minimum-length checks; experiment 9. |
| Watermark interoperability and key management | Plugin interface per provider; keys server-side, fingerprints only in outputs. |
| Prevalence and calibration | Bayes PPV calculator with labelled sources; Platt calibration fitted only on a validation split; the threshold explorer projects to a stated deployment prevalence. |
