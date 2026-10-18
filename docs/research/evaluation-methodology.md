# Evaluation methodology

## Principles

1. Report **sensitivity at strict false-positive rates** (1% and 0.1%), with sample sizes and exact (Clopper–Pearson) intervals. AUROC is reported but never on its own.
2. A strict FPR is **estimable** only when the evaluation has enough negatives. With zero observed false positives, the 95% upper bound is below the target only if `n ≥ ln(0.05)/ln(1 − FPR)`: 299 negatives for 1% and 2,995 for 0.1%. AEGIS marks operating points that fall short as "not validated".
3. Choose **thresholds on a validation split** and evaluate on a separate test split. A run without a validation split reports only threshold-free metrics.
4. Exclude **cross-split duplicates** before evaluation. Texts are normalised by case and whitespace and hashed; matches are excluded and counted in the manifest.
5. Use **held-out evaluation**. Restricting the test split to values of `generator`, `domain` or `language` that are absent from validation measures generalisation instead of memorisation.
6. Keep result kinds separate: `locally_measured`, `simulated`, `published`, `reproduced` and `vendor_reported` are stored in a constrained column and labelled in every view. A published number can be stored only with a citation.
7. **Calibration** (Platt) is fitted on the validation split. A profile counts as *validated* only for locally measured runs where the target operating point is estimable. Probabilities apply only to the population described in the profile.
8. **Deployment PPV** is computed from TPR/FPR at the chosen threshold and a stated prevalence (threshold explorer, base-rate calculator). The source of each input is shown.

## Metrics computed (`research/aegis_research/reliability.py`)

TPR, TNR, FPR, FNR, sample precision, NPV, accuracy and F1, each with exact intervals and counts. AUROC (Mann–Whitney) with a stratified bootstrap CI. ROC and PR curves. TPR at fixed FPR with an estimability check. Brier score, expected calibration error and reliability bins. Threshold sweeps projected to a deployment population. Subgroup FPR/FNR with suppression. Empirical joint rates for two-signal rules, compared against the independence assumption.

## Dataset format

JSONL with one record per line:

```json
{"id": "s1", "text": "...", "label": 1, "split": "validation", "group": "L2-writers", "generator": "model-x",
 "domain": "news", "language": "hi", "transform": "original"}
```

- `label`: 1 = AI-generated, 0 = human-written.
- `transform`: names a documented transformation applied to the same `id`, for example `paraphrase_v1` or `truncate_50`.
- Registration requires provenance, licence and a consent or lawful basis. The file's SHA-256 is recorded, and runs verify it before use.

## Run manifest

Every run stores the dataset name, version, SHA-256, licence and synthetic flag; the method id and version; the full configuration and seed; the hold-out definition; Python, platform and library versions; timestamps; scored-sample counts; and excluded duplicates. Exports through `/benchmarks/runs/{id}` and the UI are reproducible from the manifest.

## Scoring imported results

`/benchmarks/imported-scores` accepts `label,score[,group,transform]` CSV files. AEGIS computes metrics from the supplied scores but did not run the detector, and every view says so.
