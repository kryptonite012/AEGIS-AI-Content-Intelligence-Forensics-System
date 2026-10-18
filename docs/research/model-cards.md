# Model cards

AEGIS **bundles no learned detection model weights**. This build environment had no access to model hubs, so no third-party model was downloaded, evaluated or validated. The cards below describe each method as it ships, and they double as the template to fill in when an operator configures a model. Record the completed card in the model registry (Administration → Model registry), together with its licence and evaluated languages.

## Template (fill in for every configured model)

| Field | Content |
| --- | --- |
| Model identifier / source | e.g. publisher, repository, commit or release |
| Weights checksum | SHA-256 of each weight file, verified against the publisher |
| Licence | |
| Intended use | Triage signal for human review only |
| Supported media / languages evaluated | |
| Minimum input | e.g. ≥ 50 tokens, ≥ 2 s audio, ≥ 256 px |
| Training data documentation | as published by the developer |
| Evaluation in AEGIS | Benchmark run id(s), result kind, dataset version, TPR at 1%/0.1% FPR with intervals |
| Calibration | Profile id, population, target FPR, validated yes/no |
| Known limitations | |
| Out-of-scope uses | Any decision about a person based on this score alone |

## Methods shipped with AEGIS

### AEGIS reference text watermark verifier (`watermark.aegis_reference_text` v1.0.0)
- **Algorithm:** green-list z-test (Kirchenbauer et al., 2023) with γ = 0.25, δ = 2.0 and a one-token context, over a public 2,048 pseudo-word vocabulary. It uses the exact binomial p-value and deduplicates (context, token) pairs. The threshold is z ≥ 4.
- **Key:** `AEGIS_REFERENCE_WATERMARK_KEY` (at least 16 bytes). Only a non-reversible fingerprint appears in outputs.
- **Evaluation:** simulated only. See the built-in benchmark in [experiments.md](experiments.md) (AUROC 0.9999 on 180 synthetic test samples; strict-FPR operating points not estimable).
- **Limitations:** verifies only AEGIS-generated reference text, and detection weakens under replacement (TPR 45.6% at 40% replacement). Absence of the watermark says nothing about authorship.

### C2PA verifier (`provenance.c2pa` v1.0.0)
- **Implementation:** `c2pa-python` 0.38 (c2pa-rs 0.91), with no network access for remote manifests. Trust comes from `AEGIS_C2PA_TRUST_ANCHORS`.
- **Tested with:** valid untrusted, valid trusted, tampered (data-hash mismatch) and absent manifests on JPEG.
- **Limitations:** trust depends on the configured anchors. Platforms strip manifests. A valid signature does not establish that the claims are true.

### Text adapters (`text.supervised_classifier`, `text.token_statistics`, `text.fast_detectgpt_analytic`, `text.binoculars`)
- **Status:** not operational in this build because no weights are configured.
- **Loading:** `transformers` with `local_files_only=True`. Inference is truncated to 512 tokens; the classifier scores up to 16 chunks. A partial weight fingerprint (first MiB) is recorded per run.
- **Interpretation:** outputs are never treated as probabilities. `flagged` is set only with a validated calibration profile, and calibration is dropped for languages outside `languages_evaluated`.

### ONNX adapters (`image.local_model`, `audio.synthetic_speech_model`, `video.frame_model`)
- **Status:** not operational in this build. They need `model.onnx` plus `aegis_model.json` (input specification, positive index, licence, optional validated calibration) and `onnxruntime`.

### Forensic observation methods (image, audio, video, text statistics)
- These are deterministic signal-processing measurements. They are not trained models, so the card fields for training data and calibration do not apply. Each states what it cannot establish.
