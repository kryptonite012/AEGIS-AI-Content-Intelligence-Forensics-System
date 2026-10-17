"""Text extraction from TXT, PDF and DOCX with preserved original and explicit warnings.

Extracted text is untrusted input: it is only ever treated as data to analyse. Nothing in a
document can change AEGIS behaviour.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from aegis_ml.text.language import identify_language
from aegis_ml.text.segment import paragraphs, sentences
from aegis_ml.text.tokenize import TOKENIZER_ID, count_tokens

MAX_EXTRACTED_CHARS = 2_000_000
MIN_TOKENS_FOR_ANALYSIS = 50  # below this AEGIS reports insufficient evidence for text detectors

_INJECTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous |prior |the above )?(instructions|prompts)|system prompt|you are (now )?an? (ai|assistant)|"
    r"disregard (the )?(above|previous))",
    re.IGNORECASE,
)


@dataclass
class ExtractionResult:
    text: str  # normalised text used for analysis
    original_text: str  # text exactly as extracted (pre-normalisation)
    method: str
    source_mime: str
    ocr_derived: bool = False
    extraction_confidence: str = "direct"  # "direct" for embedded text; OCR would report a measure
    language: dict = field(default_factory=dict)
    token_count: int = 0
    tokenizer: str = TOKENIZER_ID
    char_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0
    pages: int | None = None
    warnings: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    sufficient_for_detection: bool = False

    def to_dict(self, include_text: bool = False) -> dict:
        d = asdict(self)
        if not include_text:
            d.pop("text")
            d.pop("original_text")
        return d


def _decode_text(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), "utf-8 (with replacement characters)"


def normalise(text: str) -> tuple[str, list[str]]:
    steps = []
    n = unicodedata.normalize("NFC", text)
    if n != text:
        steps.append("unicode NFC normalisation")
    n2 = n.replace("\r\n", "\n").replace("\r", "\n")
    if n2 != n:
        steps.append("line endings normalised to LF")
    n3 = re.sub(r"[​‌‍⁠﻿]", "", n2)
    if n3 != n2:
        steps.append("zero-width characters removed (counted in warnings)")
    n4 = re.sub(r"[ \t]+", " ", n3)
    n4 = re.sub(r"\n{3,}", "\n\n", n4).strip()
    if n4 != n3:
        steps.append("whitespace runs collapsed")
    return n4, steps


def extract_text(path: Path, mime: str) -> ExtractionResult:
    warnings: list[str] = []
    pages = None
    if mime == "text/plain":
        raw, enc = _decode_text(path.read_bytes())
        method = f"plain-text decode ({enc})"
        if "replacement" in enc:
            warnings.append("File was not valid UTF-8; undecodable bytes were replaced.")
    elif mime == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ValueError("encrypted PDFs are not supported")
        pages = len(reader.pages)
        parts = [(p.extract_text() or "") for p in reader.pages]
        raw = "\n\n".join(parts)
        method = "pypdf embedded-text extraction"
        empty = sum(1 for p in parts if not p.strip())
        if empty:
            warnings.append(
                f"{empty} of {pages} pages contain no embedded text (possibly scanned). OCR is not "
                "applied automatically; OCR-derived text would be labelled separately."
            )
        warnings.append("PDF extraction may reorder columns, drop ligatures or merge hyphenated words.")
    elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        import docx

        d = docx.Document(str(path))
        paras = [p.text for p in d.paragraphs]
        for table in d.tables:
            for row in table.rows:
                paras.append(" | ".join(c.text for c in row.cells))
        raw = "\n\n".join(p for p in paras if p.strip())
        method = "python-docx paragraph and table extraction"
        if d.tables:
            warnings.append("Table cell text was appended after body paragraphs.")
    else:
        raise ValueError(f"no text extractor for {mime}")

    if len(raw) > MAX_EXTRACTED_CHARS:
        raw = raw[:MAX_EXTRACTED_CHARS]
        warnings.append(f"Extracted text truncated to {MAX_EXTRACTED_CHARS} characters.")
    zero_width = len(re.findall(r"[​‌‍⁠]", raw))
    if zero_width:
        warnings.append(f"{zero_width} zero-width characters found (possible formatting artefacts or obfuscation).")
    if _INJECTION_PATTERNS.search(raw):
        warnings.append(
            "Text contains instruction-like phrases addressed to AI systems. AEGIS treats document "
            "content as data only; this is recorded as an observation, not as evidence of authorship."
        )
    text, steps = normalise(raw)
    lang = identify_language(text)
    tokens = count_tokens(text)
    if tokens < MIN_TOKENS_FOR_ANALYSIS:
        warnings.append(
            f"Only {tokens} tokens; statistical text detectors are unreliable on short text and will "
            "report insufficient input."
        )
    if lang.get("note"):
        warnings.append(lang["note"])
    return ExtractionResult(
        text=text,
        original_text=raw,
        method=method,
        source_mime=mime,
        language=lang,
        token_count=tokens,
        char_count=len(text),
        sentence_count=len(sentences(text)),
        paragraph_count=len(paragraphs(text)),
        pages=pages,
        warnings=warnings,
        transformations=steps,
        sufficient_for_detection=tokens >= MIN_TOKENS_FOR_ANALYSIS,
    )
