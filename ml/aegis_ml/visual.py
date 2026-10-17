"""Small rendering helpers for forensic visualisations (no matplotlib dependency in the API)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageDraw

# Perceptually ordered dark-to-bright ramp (midnight -> blue -> cyan -> near white).
_STOPS = np.array([[8, 12, 28], [22, 40, 98], [37, 99, 235], [34, 211, 238], [224, 250, 255]], dtype=float)


def colormap(values: np.ndarray) -> np.ndarray:
    v = np.clip(np.nan_to_num(values.astype(float)), 0, 1)
    pos = v * (len(_STOPS) - 1)
    lo = np.floor(pos).astype(int).clip(0, len(_STOPS) - 2)
    frac = (pos - lo)[..., None]
    return (_STOPS[lo] * (1 - frac) + _STOPS[lo + 1] * frac).astype(np.uint8)


def normalise(a: np.ndarray, lo_pct: float = 1, hi_pct: float = 99.5) -> np.ndarray:
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a, dtype=float)


def png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def heat_png(values: np.ndarray) -> bytes:
    return png_bytes(colormap(normalise(values)))


def waveform_png(samples: np.ndarray, width: int = 1200, height: int = 220) -> bytes:
    img = Image.new("RGB", (width, height), (8, 12, 28))
    d = ImageDraw.Draw(img)
    mid = height // 2
    d.line([(0, mid), (width, mid)], fill=(40, 52, 80))
    if len(samples):
        chunks = np.array_split(samples, width)
        for x, c in enumerate(chunks):
            if len(c):
                lo, hi = float(c.min()), float(c.max())
                d.line([(x, mid - hi * (mid - 4)), (x, mid - lo * (mid - 4))], fill=(34, 211, 238))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
