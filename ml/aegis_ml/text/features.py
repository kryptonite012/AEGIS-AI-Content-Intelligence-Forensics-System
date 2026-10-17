"""Descriptive text statistics.

These are descriptive measurements of the text (length, lexical diversity, sentence-length
variation). They are reported to help reviewers judge input suitability and out-of-distribution
risk. They are NOT an AI-detection signal and AEGIS never converts them into a score.
"""

from __future__ import annotations

import math
import statistics
import zlib
from collections import Counter

from aegis_ml.core import AnalysisInput, AnalysisMethod, EvidenceClass, ImplementationStatus, MethodInfo
from aegis_ml.core import MethodResult, Modality, RunStatus, Segment
from aegis_ml.text.segment import paragraphs, sentences
from aegis_ml.text.tokenize import TOKENIZER_ID, tokenize, words


def describe(text: str) -> dict:
    toks = tokenize(text)
    ws = [w.lower() for w in words(text)]
    sents = sentences(text)
    sent_lens = [len(words(s.text)) for s in sents] or [0]
    counts = Counter(ws)
    n = len(ws)
    raw = text.encode("utf-8")
    return {
        "tokenizer": TOKENIZER_ID,
        "characters": len(text),
        "tokens": len(toks),
        "words": n,
        "sentences": len(sents),
        "paragraphs": len(paragraphs(text)),
        "type_token_ratio": round(len(counts) / n, 4) if n else None,
        # Moving-average TTR over 50-word windows is less length-dependent than raw TTR.
        "mattr_50": _mattr(ws, 50),
        "hapax_ratio": round(sum(1 for c in counts.values() if c == 1) / n, 4) if n else None,
        "mean_sentence_words": round(statistics.fmean(sent_lens), 2),
        "sentence_words_stdev": round(statistics.pstdev(sent_lens), 2),
        "sentence_length_cv": round(statistics.pstdev(sent_lens) / statistics.fmean(sent_lens), 4)
        if statistics.fmean(sent_lens)
        else None,
        "mean_word_length": round(statistics.fmean(len(w) for w in ws), 2) if ws else None,
        "zlib_compression_ratio": round(len(zlib.compress(raw, 9)) / len(raw), 4) if raw else None,
        "punctuation_per_100_tokens": round(100 * sum(1 for t in toks if not t[0].isalnum()) / len(toks), 2)
        if toks
        else None,
        "unigram_entropy_bits": round(-sum(c / n * math.log2(c / n) for c in counts.values()), 4) if n else None,
    }


def _mattr(ws: list[str], window: int) -> float | None:
    if len(ws) < window:
        return None
    vals = [len(set(ws[i : i + window])) / window for i in range(0, len(ws) - window + 1)]
    return round(statistics.fmean(vals), 4)


class DescriptiveTextStatistics(AnalysisMethod):
    info = MethodInfo(
        id="text.descriptive_statistics",
        name="Descriptive text statistics",
        version="1.0.0",
        modalities=(Modality.TEXT, Modality.DOCUMENT),
        evidence_class=EvidenceClass.MEDIA_FORENSIC_OBSERVATION,
        implementation=ImplementationStatus.OPERATIONAL,
        description="Length, lexical diversity, sentence-length variation and compressibility.",
        output_semantics="Descriptive measurements only. No score; not an indicator of authorship.",
        limitations=(
            "Features vary with genre, proficiency, language and editing; they cannot attribute authorship.",
            "Low sentence-length variation or lexical diversity occurs naturally in many human texts.",
        ),
    )

    def _run(self, inp: AnalysisInput) -> MethodResult:
        if not inp.text:
            return self.result(RunStatus.INSUFFICIENT_INPUT, "No extracted text available.")
        stats = describe(inp.text)
        segs = [
            Segment(p.start, p.end, "char", "paragraph", None, {"words": len(words(p.text))})
            for p in paragraphs(inp.text)[:500]
        ]
        return self.result(
            RunStatus.COMPLETED,
            f"{stats['words']} words in {stats['sentences']} sentences; descriptive only.",
            output=stats,
            segments=segs,
        )
