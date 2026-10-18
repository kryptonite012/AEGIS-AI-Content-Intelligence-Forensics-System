# Institutional pilot readiness package

AEGIS is **not** approved, certified, classified or adopted by any government body, and claims no such status. This package collects what an institution needs to assess it for a controlled pilot. Its intended use is investigative assistance and evidence triage under qualified human review.

| Item | Document |
| --- | --- |
| System architecture | [architecture/overview.md](../architecture/overview.md) |
| Data-flow diagram | [architecture/overview.md#evidence-and-analysis-data-flow](../architecture/overview.md#evidence-and-analysis-data-flow) |
| Data model | [architecture/data-model.md](../architecture/data-model.md) |
| Threat model | [security/threat-model.md](../security/threat-model.md) |
| Security controls matrix | [security/security-controls.md](../security/security-controls.md) · [compliance-mapping.json](compliance-mapping.json) |
| Model and dataset registry | Administration → Model registry · [research/model-cards.md](../research/model-cards.md) · [research/dataset-cards.md](../research/dataset-cards.md) |
| Evaluation methodology | [research/evaluation-methodology.md](../research/evaluation-methodology.md) |
| False-positive / false-negative analysis and calibration | [research/experiments.md](../research/experiments.md). No real-data calibration exists in this build. |
| Multilingual evaluation plan | [research/multilingual-evaluation-plan.md](../research/multilingual-evaluation-plan.md) |
| Bias and robustness results | Simulated only ([experiments.md](../research/experiments.md)); the Fairness and Robustness laboratories are ready for real data |
| Evidence-handling procedure | [security/audit-chain.md](../security/audit-chain.md) · [evidence-handling-procedure.md](evidence-handling-procedure.md) |
| Audit and accountability design | [security/audit-chain.md](../security/audit-chain.md) |
| Privacy impact assessment template | [privacy-impact-assessment-template.md](privacy-impact-assessment-template.md) |
| Data-retention policy template | [data-retention-policy-template.md](data-retention-policy-template.md) |
| Incident-response plan | [operations/incident-response.md](../operations/incident-response.md) |
| Backup and recovery plan | [operations/backup-and-recovery.md](../operations/backup-and-recovery.md) |
| Software bill of materials | [sbom/](sbom/) (regenerate with `make security-check`) |
| Deployment and rollback plan | [operations/deployment.md](../operations/deployment.md) |
| Limitations and residual risks | [limitations-and-residual-risks.md](limitations-and-residual-risks.md) |
| Independent evaluation protocol | [research/independent-evaluation-protocol.md](../research/independent-evaluation-protocol.md) |
| Human review and appeal procedure | [human-review-and-appeal-procedure.md](human-review-and-appeal-procedure.md) |

For high-stakes decisions involving a person's rights, reputation, employment, education, liberty or access to services, the institution must require independent corroboration and qualified human review. A detector score alone must never trigger punishment, rejection, prosecution or any other adverse decision.
