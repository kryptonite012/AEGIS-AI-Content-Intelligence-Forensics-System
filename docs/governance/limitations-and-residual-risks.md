# Limitations and residual risks

## Scientific
- **No validated AI-content detector ships with this build.** The text and media classifier adapters are implemented, but no model weights were available in the build environment. Every statistical-inference output is therefore `unavailable` until an operator configures and validates a model.
- **No calibrated probabilities.** No detector has been benchmarked on locally measured real data, so nothing is flagged and nothing is presented as a probability.
- **All benchmark and experiment results in the repository are analytical or simulated.**
- **The reference watermark verifier can detect only AEGIS-generated reference text.** It provides no information about commercial models. Provider watermark verification (for example SynthID) is an unimplemented integration boundary.
- **Fast-DetectGPT uses one model for sampling and scoring, and Binoculars has no validated threshold.** Neither reproduces published results.
- **Mixed-authorship segment scores are withheld** unless a model is validated at paragraph granularity, and none is.
- **Forensic observations (spectrum, residual, ELA, temporal consistency) are not detectors.** They need expert interpretation.
- **Languages:** identification only. No detector has been evaluated for Hindi or any other language.
- **OCR is not implemented.** Scanned PDFs produce an extraction warning.
- **Lip-sync, face-swap and voice-cloning detectors are not implemented.**

## Security and operations
- The audit chain is tamper-evident, not tamper-proof, against privileged database access. External anchoring is a manual procedure.
- Encryption at rest for local storage and PostgreSQL depends on the host.
- The ClamAV integration has not been exercised against a live scanner in this build.
- MFA is optional, with no recovery codes; there is no SAML/OIDC integration.
- Backups and restore are documented but not executed here.
- Performance figures come from a single 4-vCPU development container.
- Container host port publishing was not verifiable in the build sandbox; the containers were tested over the Docker network.

## Governance
- Compliance with any law or standard is **not** claimed; see the compliance mapping.
- The chain-of-custody records are technical, not legally certified.
- The research documents named in the original brief were not supplied. The implementation follows the brief's descriptions of them.
