# Multilingual evaluation plan (English first, then Indian languages)

**Current status.** Language and script identification works for English, Hindi and the major Indic scripts, and is covered by tests. **No detector has been evaluated for any language in this build.** Displaying text in a language does not mean any detector supports it.

## Phase A: English baseline
1. Assemble a licensed, consented corpus across at least four domains (academic, news, administrative, informal) with at least 3,000 human-written negatives per evaluation slice, so that 0.1% FPR is estimable.
2. Collect AI samples from several generator families; hold at least one family out of validation.
3. Include non-native English writers, with consent and an explicit `group` field. Report subgroup FPR before any deployment.

## Phase B: Hindi and other Indian languages (Bengali, Marathi, Tamil, Telugu, Gujarati, Kannada, Malayalam, Punjabi, Odia, Urdu)
1. Work with native-speaker annotators and institutional partners. Record dialect and register where it is relevant and consented.
2. Cover code-mixed text (for example Hinglish) and transliterated (Romanised) text as separate slices. Script detection flags mixed-script input.
3. Evaluate translation-sensitivity: human text machine-translated into the language, and AI text in English translated into it, as documented transforms.
4. Measure the tokenizer's effect. Token counts differ greatly by script, so the 50-token minimum must be revalidated per language.
5. Add a language code to a model's `languages_evaluated` only after a locally measured run on that language with estimable operating points. Until then, AEGIS removes calibration and warns that the language is out of distribution.

## Reporting
For each language and slice, report n, TPR at 1% and 0.1% FPR with intervals, AUROC, subgroup FPR, and robustness to translation and paraphrase. Publish negative results as well.
