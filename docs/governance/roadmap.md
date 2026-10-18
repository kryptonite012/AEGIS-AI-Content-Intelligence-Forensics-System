# Roadmap

1. **Validated text detection (English):** procure a licensed model, build a consented evaluation corpus with at least 3,000 negatives per slice, calibrate and validate through the Benchmark Laboratory.
2. **Indian-language evaluation:** follow the [multilingual plan](../research/multilingual-evaluation-plan.md), Hindi first.
3. **Provider watermark verification:** integrations under authorised agreements (SynthID-Text and media watermarks), using the existing plugin boundary.
4. **Learned media detectors:** image (UnivFD-class), synthetic speech (AASIST-class) and frame-level deepfake models as ONNX adapters with model cards.
5. **OCR** with per-token confidence, labelled separately from extracted text.
6. **Identity:** SAML/OIDC single sign-on, enforced MFA, recovery codes.
7. **Audit anchoring:** automatic RFC 3161 timestamping of the chain head.
8. **Retrieval-based corroboration** against authorised reference corpora.
9. **Evaluated fusion:** a learned combiner, only with held-out joint validation and documented dependence analysis.
10. **Scale-out:** separate GPU worker queue, object-lock S3 by default, read replicas.
