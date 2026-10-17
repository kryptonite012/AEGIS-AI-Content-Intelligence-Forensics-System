"""Language identification.

Two layers: (1) Unicode script proportions (deterministic, exact), (2) ``langdetect`` (n-gram
naive Bayes, Nakatani Shuyo) with a fixed seed. Script detection distinguishes Devanagari, Bengali,
Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada and Malayalam; langdetect supports hi, bn, gu,
kn, ml, mr, ne, pa, ta, te, ur among Indian languages. Identifying a language does NOT mean any
detector has been validated for it; detector support is tracked separately per model.
"""

from __future__ import annotations

from collections import Counter

_SCRIPTS = [
    ("Devanagari", 0x0900, 0x097F),
    ("Bengali", 0x0980, 0x09FF),
    ("Gurmukhi", 0x0A00, 0x0A7F),
    ("Gujarati", 0x0A80, 0x0AFF),
    ("Oriya", 0x0B00, 0x0B7F),
    ("Tamil", 0x0B80, 0x0BFF),
    ("Telugu", 0x0C00, 0x0C7F),
    ("Kannada", 0x0C80, 0x0CFF),
    ("Malayalam", 0x0D00, 0x0D7F),
    ("Arabic", 0x0600, 0x06FF),
    ("Cyrillic", 0x0400, 0x04FF),
    ("CJK", 0x4E00, 0x9FFF),
]


def script_profile(text: str) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for ch in text:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        name = "Latin" if cp < 0x0250 else next((n for n, lo, hi in _SCRIPTS if lo <= cp <= hi), "Other")
        counts[name] += 1
    total = sum(counts.values())
    return {k: round(v / total, 4) for k, v in counts.most_common()} if total else {}


def identify_language(text: str) -> dict:
    scripts = script_profile(text)
    result: dict = {"scripts": scripts, "method": "unicode-script + langdetect 1.0.9 (seed 0)"}
    sample = text[:20_000]
    if len(sample.strip()) < 20:
        result.update(code=None, confidence=None, note="Text too short for language identification.")
        return result
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        cands = detect_langs(sample)
        result["candidates"] = [{"code": c.lang, "probability": round(c.prob, 4)} for c in cands[:3]]
        result["code"] = cands[0].lang
        result["confidence"] = round(cands[0].prob, 4)
    except Exception:  # noqa: BLE001 - langdetect raises a bare exception on featureless input
        result.update(code=None, confidence=None, note="Language could not be identified.")
        return result
    if len([s for s, v in scripts.items() if v > 0.15]) > 1:
        result["note"] = "Mixed scripts detected; language-specific detector validity may not apply."
    return result
