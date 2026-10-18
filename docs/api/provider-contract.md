# External detection provider contract

`HttpDetectorProvider` (`ml/aegis_ml/providers.py`) sends evidence to a configured service. Use it for a self-hosted model server or a vendor API wrapped behind an adapter you control. **Evidence leaves the deployment**, so the provider runs only when all three of these allow it:

1. Deployment: `AEGIS_ALLOW_EXTERNAL_PROCESSING=true`
2. Organisation: Administration → Settings → External processing (audited, reason required)
3. Case: `allow_external_processing` (only administrators can set it)

Otherwise the run is `blocked_by_policy` and nothing is sent.

## Configuration (server-side only)

```
AEGIS_PROVIDER_<ID>_URL=https://detector.internal/v1/score   # HTTPS required
AEGIS_PROVIDER_<ID>_TOKEN=...                                # sent as Bearer; never logged
AEGIS_PROVIDER_<ID>_TIMEOUT=60
```

Built-in provider IDs are `image_detector`, `audio_detector` and `video_detector`.

## Request

`POST` multipart form with field `file` (the original evidence bytes) and header `X-AEGIS-Evidence-SHA256`.

## Response (HTTP 200, JSON)

```json
{
  "score": 0.73,
  "model_version": "vendor-model-2026-05",
  "score_semantics": "probability-like output for class 'synthetic' (vendor-defined)",
  "request_id": "req_8f2a91",
  "calibrated_probability": 0.41
}
```

| Field | Rules |
| --- | --- |
| `score` | Required finite number (booleans are rejected) |
| `model_version` | Required, 1–128 characters |
| `score_semantics` | Optional, at most 300 characters |
| `request_id` | Optional, `[A-Za-z0-9._:-]{1,128}` |
| `calibrated_probability` | Optional, in [0, 1]. Stored as **vendor-reported** and never treated as AEGIS calibration |

Any other status code, malformed JSON or a field that violates these rules makes the run `failed` with the reason recorded. No score is stored. Provider scores are not interpreted (`flagged` stays empty) until the provider has been benchmarked locally and a validated calibration profile is attached in the model registry.
