# Independent evaluation protocol

This protocol is for a third party, such as a university laboratory or a standards body, that assesses an AEGIS deployment before an institutional pilot.

1. **Freeze the system under test.** Record the git commit, container image digests, the model registry export (`GET /api/v1/models`) and the calibration profiles.
2. **Use evaluator-held data.** The evaluator supplies datasets the developers and operators have never seen, including held-out generators, domains and languages, and documented transformations. The data never enters the operators' training or calibration.
3. **Fix the operating points in advance.** Decide thresholds from the operator's validation profiles before seeing the test data. Do not tune them on the test data.
4. **Run.** Register each dataset as `locally_measured` in an isolated AEGIS instance, or run the methods offline and import scores. Archive the run manifests.
5. **Measure.** Report TPR at 1% and 0.1% FPR with exact intervals, AUROC, subgroup FPR/FNR, robustness per transform, short-text slices and calibration (ECE, reliability). State n for every number.
6. **Test the workflow.** Run the end-to-end tests (`make test-e2e`), the security tests, and the permission-denied, unsupported-media, corrupted-file, provider-outage and integrity-mismatch scenarios.
7. **Review governance.** Check the compliance mapping, threat model, audit-chain anchoring practice, retention configuration, and human review and appeal procedure against the institution's policies.
8. **Report.** Publish the findings, including negative results, with the manifests needed to reproduce them. Any capability the evaluation did not cover must be marked unverified.
