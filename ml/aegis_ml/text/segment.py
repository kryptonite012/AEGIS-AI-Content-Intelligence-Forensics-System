"""Sentence and paragraph segmentation with character offsets.

Rule-based segmentation (documented, deterministic). Sentence terminators cover Latin scripts and
the Devanagari danda (U+0964/U+0965) used in Hindi, Marathi, Nepali and Sanskrit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ABBREV = {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "fig", "no", "vol"}
_SENT_END = re.compile(r"([.!?।॥]+[\"'”’)]*)(\s+)")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str


def paragraphs(text: str) -> list[Span]:
    out = []
    for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text):
        if m.group().strip():
            out.append(Span(m.start(), m.end(), m.group()))
    return out


def sentences(text: str) -> list[Span]:
    spans: list[Span] = []
    for para in paragraphs(text):
        start = 0
        body = para.text
        for m in _SENT_END.finditer(body):
            candidate = body[start : m.end(1)]
            last_word = re.findall(r"([\w.]+)[.!?]*$", candidate)
            if last_word and last_word[0].rstrip(".").lower() in _ABBREV and m.group(1) == ".":
                continue
            if candidate.strip():
                spans.append(Span(para.start + start, para.start + m.end(1), candidate.strip()))
            start = m.end()
        tail = body[start:]
        if tail.strip():
            spans.append(Span(para.start + start, para.start + len(body), tail.strip()))
    return spans
