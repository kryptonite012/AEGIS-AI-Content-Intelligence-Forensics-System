# Configuring a real detector

Out of the box, AEGIS runs every method that needs no model weights: provenance, the reference watermark, metadata and forensic observations. Each learned detector reports `unavailable` until you configure it. Follow these steps for each one.

## 1. Obtain weights legitimately

Check the licence, the publisher's documentation and the intended use. Record the SHA-256 of every weight file. Place the files on the worker hosts; AEGIS never downloads models at runtime.

## 2. Install the optional runtime

```bash
uv sync --frozen --extra transformers      # torch + transformers for the text adapters
uv pip install onnxruntime                 # for the ONNX image/speech adapters
```

## 3. Point AEGIS at the model (worker environment)

| Method | Variables |
| --- | --- |
| Supervised text classifier | `AEGIS_TEXT_CLASSIFIER_PATH=/models/clf` and `AEGIS_TEXT_CLASSIFIER_AI_LABEL=<label name meaning AI>`. AEGIS refuses to guess the label. |
| Token statistics, Fast-DetectGPT | `AEGIS_SCORING_LM_PATH=/models/causal-lm` (a local Hugging Face causal LM directory) |
| Binoculars | `AEGIS_BINOCULARS_OBSERVER_PATH`, `AEGIS_BINOCULARS_PERFORMER_PATH` (the two models must share a tokenizer) |
| Image / speech classifier | `AEGIS_IMAGE_MODEL_DIR`, `AEGIS_SPEECH_MODEL_DIR`, each containing `model.onnx` and `aegis_model.json` |
| Device | `AEGIS_INFERENCE_DEVICE=cuda` (falls back to CPU if CUDA is unavailable) |

`aegis_model.json` for ONNX models:

```json
{"name": "my-speech-cm", "version": "2026.1", "license": "...", "positive_index": 1,
 "input": {"kind": "audio", "sample_rate": 16000, "samples": 64600}}
```

Restart the workers. System Health should now list the method as operational.

## 4. Benchmark it locally

Register a labelled dataset with validation and test splits in the Benchmark Laboratory and run the method on it. Include held-out generators or domains, the languages you intend to analyse, short texts and documented transformations.

## 5. Calibrate and validate

1. From the completed run, create a calibration profile. This fits a Platt model on the validation split and picks the threshold at the target FPR. A profile is marked validated only for locally measured runs whose operating point is estimable.
2. In Administration → Model registry, attach the run and the profile, enter the licence and the languages evaluated, and set the status to validated. A reason is required and the change is audited.

Until then, outputs are shown but never interpreted. They never flag evidence and are never presented as probabilities.

## 6. External providers

See the [provider contract](../api/provider-contract.md). Evidence leaves the deployment, so the deployment, the organisation and the case must all permit it.
