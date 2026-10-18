# Reliability experiments and results

The nine experiment categories are implemented in `research/aegis_research/experiments/catalog.py`. Each one returns a `kind` (`analytical` or `simulation`), its full configuration and the seeds it used. **None of these results measures a deployed detector on real content.** Simulations use a synthetic Markov language model and the AEGIS reference watermark.

To reproduce:

```bash
make experiments                     # JSON + PNG + manifest.json → research/results/
python -m aegis_research.experiments exp9_fpr_calibration --out /tmp/x
```

The numbers below come from the run recorded during this build (seeds fixed in the catalog; NumPy 2.x, SciPy 1.x). Re-running with the same versions reproduces them exactly. The Research Bench runs the same functions through `/api/v1/evaluation/experiments/{id}/runs` and stores each run with a content hash.

## 1. Base-rate effects (analytical)

This reproduces the research paper's **analytical example**: 90% sensitivity, 5% FPR, 5% prevalence, 10,000 items.

| Quantity | Value |
| --- | --- |
| PPV | **48.65%** |
| Expected true flags | 450 |
| Expected false flags | 475 |
| False flags per true flag | 1.06 |

Under these assumptions, more than half of all flags are false. This is a property of the assumed rates, not a measurement of AEGIS.

## 2. Subgroup error concentration (analytical, illustrative rates)

Assumed: group A is 90% of the population with FPR 2%; group B is 10% with FPR 10%.

| Group | Population share | Share of false flags |
| --- | --- | --- |
| A | 90% | 64.3% |
| B | 10% | **35.7%** |

A tenth of the population receives more than a third of the false accusations.

## 3. Corroborating evidence (simulation)

Two signals, (TPR 0.90, FPR 0.05) and (TPR 0.80, FPR 0.05), combined with an AND rule. Under conditional independence, the joint FPR would be 0.25%. The simulation uses binormal latent scores with within-class correlation ρ.

| ρ | Empirical joint FPR | × independence estimate | PPV at 5% prevalence (empirical / assumed) |
| --- | --- | --- | --- |
| 0.0 | 0.241% | 0.96 | 0.940 / 0.938 |
| 0.3 | 0.697% | 2.79 | 0.848 / 0.938 |
| 0.6 | 1.545% | 6.18 | 0.721 / 0.938 |
| 0.9 | 3.228% | **12.9** | 0.563 / 0.938 |

The product rule is valid only if the detectors are independent. For correlated detectors it overstates how much a second signal adds. This is why the fusion policy refuses to multiply rates.

## 4. AUROC versus strict operating points (simulation, 2,000 + 2,000 samples)

| Simulated detector | AUROC | TPR at 1% FPR | TPR at 0.1% FPR |
| --- | --- | --- | --- |
| Binormal, equal variance | 0.898 | 28.6% | 8.7% (**not estimable**: needs ≥ 2,995 negatives) |
| Heavy-tailed negatives (t₃) | 0.887 | **0.0%** | 0.0% (not estimable) |

These two detectors have nearly the same AUROC but behave completely differently at screening operating points.

## 5. Watermark detection vs length and entropy (simulation, 30 trials per cell, z ≥ 4)

Rows are the Zipf exponent and the mean next-token entropy in nats; columns are tokens.

| Zipf (entropy) | 10 | 25 | 50 | 100 | 200 |
| --- | --- | --- | --- | --- | --- |
| 0.6 (6.53) | 0.43 | 0.97 | 1.00 | 1.00 | 1.00 |
| 1.0 (5.21) | 0.47 | 0.83 | 1.00 | 1.00 | 1.00 |
| 1.5 (2.92) | 0.07 | 0.70 | 0.97 | 1.00 | 1.00 |
| 2.5 (1.02) | 0.03 | 0.13 | 0.27 | 0.63 | 1.00 |

Across every cell, the false-positive rate on unwatermarked text was 0/30. Low-entropy text needs far more tokens before the watermark can be detected.

## 6. Watermark robustness under random token replacement (simulation, 200 tokens)

| Fraction replaced | 0 | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 |
| --- | --- | --- | --- | --- | --- | --- |
| Detection rate | 1.00 | 1.00 | 1.00 | 1.00 | 0.97 | **0.47** |
| Mean z | 14.6 | 11.7 | 9.0 | 7.0 | 5.5 | 3.9 |

This measures one specific implementation against uniform random replacement. It is not a claim of robustness to paraphrasing.

## 7. Threshold selection (analytical, γ = 0.25)

| Target FPR | Tokens | z (normal) | Exact min. green count | Exact FPR achieved | True FPR of normal threshold |
| --- | --- | --- | --- | --- | --- |
| 1e-2 | 50 | 2.33 | 21 | 6.3e-3 | 1.4e-2 |
| 1e-3 | 50 | 3.09 | 24 | 3.7e-4 | **2.6e-3** |
| 1e-4 | 200 | 3.72 | 75 | 6.2e-5 | 2.0e-4 |
| 1e-6 | 200 | 4.75 | 82 | 5.1e-7 | 2.2e-6 |

Thresholds taken from the normal approximation **exceed** the FPR tolerance they were chosen for, by up to 2.6×. Exact binomial thresholds stay within it.

## 8. Watermark strength vs distortion (simulation, 100 tokens)

| δ | 0.5 | 1.0 | 2.0 | 4.0 | 8.0 |
| --- | --- | --- | --- | --- | --- |
| Detection rate | 0.03 | 0.77 | 1.00 | 1.00 | 1.00 |
| Mean KL from base (nats/token) | 0.026 | 0.113 | 0.455 | 1.139 | 1.418 |

KL divergence is one mathematical measure of distortion. A low value does not show that semantic quality is preserved.

## 9. Exact vs approximate false-positive calibration (analytical, γ = 0.25)

The table shows the ratio of exact FPR to the normal-approximation FPR at the z ≥ 4 threshold (the approximation is 3.17e-5):

| Tokens | 10 | 16 | 25 | 50 | 100 | 200 | 1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Exact / approx. | **13.1** | 9.0 | 6.8 | 3.9 | 2.0 | 1.9 | 1.5 |

For short texts, the z-test understates the false-positive rate by an order of magnitude. AEGIS therefore reports the exact binomial p-value alongside the z-score.

## Built-in benchmark of the reference watermark verifier (`make benchmark`)

| Item | Value |
| --- | --- |
| Result kind | **Simulated** (synthetic pseudo-word text, random key per run) |
| Test samples | 180 (90 / 90), lengths 20–160 tokens; threshold chosen on a separate validation split at a 1% FPR target |
| AUROC | 0.9999 (95% bootstrap CI 0.9996–1.0) |
| TPR at selected threshold | 98.9% (exact 95% CI 94.0–99.97%) |
| FPR at selected threshold | 0.0% (exact 95% CI 0.0–4.0%) |
| TPR at 1% / 0.1% FPR | 98.9%, **not estimable**: 90 negatives, at least 299 / 2,995 needed |
| 20% / 40% token replacement | AUROC 0.995 / 0.957; TPR 86.7% / 45.6% |

The interval reported for FPR is what this sample size actually supports. Observing zero false positives does not show that the FPR is zero.
