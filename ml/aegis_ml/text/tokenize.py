"""Documented, dependency-free tokenizer used for length estimates and descriptive statistics.

``aegis-regex-v1``: Unicode word runs (letters, marks, digits, including Indic combining marks)
and individual punctuation symbols. It is NOT the tokenizer of any language model; model-based
detectors use their own tokenizer and report counts separately.
"""

from __future__ import annotations

import re

TOKENIZER_ID = "aegis-regex-v1"
# \w misses Indic vowel signs / viramas (category Mc/Mn); include the combining-mark range explicitly.
_TOKEN = re.compile(r"[\ẁ-ͯऀ-෿‌‍]+|[^\w\s]", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text)


def count_tokens(text: str) -> int:
    return len(tokenize(text))


def words(text: str) -> list[str]:
    return [t for t in tokenize(text) if re.match(r"[\wऀ-෿]", t)]
