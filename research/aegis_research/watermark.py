"""Reference green-list watermark (Kirchenbauer et al., 2023, "A Watermark for Large Language
Models") over integer token ids, plus a synthetic Markov language model for simulations.

Scope and honesty notes
-----------------------
* This is AEGIS's own reference implementation of the published *scheme* (context-seeded green
  list of fraction gamma, logit bias delta, one-proportion z-test). It is not any vendor's
  production watermark and cannot verify content from commercial generators.
* :class:`SyntheticLM` is a toy Markov model used only for simulations. Results produced with it
  are labeled ``simulated`` everywhere in AEGIS.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class WatermarkConfig:
    vocab_size: int = 2048
    gamma: float = 0.25  # fraction of vocabulary placed on the green list
    delta: float = 2.0  # logit bias added to green tokens during generation
    context_width: int = 1  # number of preceding tokens that seed the green list

    def __post_init__(self) -> None:
        if not (0 < self.gamma < 1):
            raise ValueError("gamma must be in (0, 1)")
        if self.vocab_size < 2:
            raise ValueError("vocab_size must be >= 2")
        if self.context_width < 1:
            raise ValueError("context_width must be >= 1")


class GreenListWatermark:
    """Keyed green-list partition. The key never leaves the server process."""

    def __init__(self, key: bytes, config: WatermarkConfig | None = None) -> None:
        if len(key) < 16:
            raise ValueError("watermark key must be at least 16 bytes")
        self._key = key
        self.config = config or WatermarkConfig()
        self._green_size = int(round(self.config.gamma * self.config.vocab_size))
        self._cache: dict[tuple[int, ...], np.ndarray] = {}

    @property
    def key_fingerprint(self) -> str:
        """Non-reversible identifier of the key, safe to show in reports."""
        return hashlib.sha256(b"aegis-wm-fp:" + self._key).hexdigest()[:16]

    def green_mask(self, context: Sequence[int]) -> np.ndarray:
        ctx = tuple(int(t) for t in context[-self.config.context_width :])
        cached = self._cache.get(ctx)
        if cached is not None:
            return cached
        digest = hmac.new(self._key, repr(ctx).encode(), hashlib.sha256).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        perm = rng.permutation(self.config.vocab_size)
        mask = np.zeros(self.config.vocab_size, dtype=bool)
        mask[perm[: self._green_size]] = True
        if len(self._cache) < 200_000:
            self._cache[ctx] = mask
        return mask

    def bias_logits(self, logits: np.ndarray, context: Sequence[int]) -> np.ndarray:
        return logits + self.config.delta * self.green_mask(context)

    def detect(self, tokens: Sequence[int], z_threshold: float = 4.0, dedupe: bool = False) -> WatermarkDetection:
        """One-proportion z-test on green-token counts.

        ``dedupe=True`` scores each distinct (context, token) pair once, which restores the
        independence assumption behind the p-value for natural text with repeated phrases.
        """
        w = self.config.context_width
        if len(tokens) <= w:
            return WatermarkDetection.insufficient(len(tokens), self.config.gamma, z_threshold)
        seen: set[tuple[int, ...]] = set()
        green = scored = 0
        for i in range(w, len(tokens)):
            ctx = tuple(int(t) for t in tokens[i - w : i])
            tok = int(tokens[i]) % self.config.vocab_size
            if dedupe:
                if (*ctx, tok) in seen:
                    continue
                seen.add((*ctx, tok))
            scored += 1
            green += bool(self.green_mask(ctx)[tok])
        if scored == 0:
            return WatermarkDetection.insufficient(0, self.config.gamma, z_threshold)
        return WatermarkDetection.from_counts(green, scored, self.config.gamma, z_threshold)


@dataclass
class WatermarkDetection:
    scored_tokens: int
    green_tokens: int
    gamma: float
    z_score: float | None
    p_value_exact: float | None
    p_value_normal_approx: float | None
    z_threshold: float
    detected: bool
    sufficient_length: bool

    @staticmethod
    def insufficient(n: int, gamma: float, z_threshold: float) -> WatermarkDetection:
        return WatermarkDetection(max(n - 1, 0), 0, gamma, None, None, None, z_threshold, False, False)

    @staticmethod
    def from_counts(green: int, scored: int, gamma: float, z_threshold: float) -> WatermarkDetection:
        z = (green - gamma * scored) / math.sqrt(scored * gamma * (1 - gamma))
        p_exact = float(stats.binom.sf(green - 1, scored, gamma))  # P(X >= green) under H0
        p_norm = float(stats.norm.sf(z))
        return WatermarkDetection(
            scored_tokens=scored,
            green_tokens=green,
            gamma=gamma,
            z_score=float(z),
            p_value_exact=p_exact,
            p_value_normal_approx=p_norm,
            z_threshold=z_threshold,
            detected=bool(z >= z_threshold),
            # Fewer than ~16 scored tokens cannot reach z>=4 even if every token is green at gamma=.25.
            sufficient_length=scored >= minimum_tokens_for_detection(gamma, z_threshold),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def minimum_tokens_for_detection(gamma: float, z_threshold: float) -> int:
    """Smallest T at which an all-green sequence reaches the z threshold."""
    # all green: z = T(1-gamma)/sqrt(T gamma (1-gamma)) = sqrt(T (1-gamma)/gamma)
    return math.ceil(z_threshold**2 * gamma / (1 - gamma))


def exact_false_positive_rate(n_tokens: int, gamma: float, z_threshold: float) -> float:
    """Exact P(z >= threshold | unwatermarked) for i.i.d. Bernoulli(gamma) green indicators."""
    k_min = math.ceil(gamma * n_tokens + z_threshold * math.sqrt(n_tokens * gamma * (1 - gamma)))
    return float(stats.binom.sf(k_min - 1, n_tokens, gamma))


class SyntheticLM:
    """Toy first-order Markov language model with controllable entropy.

    For each context token, next-token logits are a Zipf profile ``-s*log(rank)`` placed on a
    context-specific random permutation of the vocabulary. Larger ``zipf_exponent`` -> lower
    entropy. Used ONLY for clearly labeled simulations.
    """

    def __init__(self, vocab_size: int, zipf_exponent: float, seed: int) -> None:
        self.vocab_size = vocab_size
        self.zipf_exponent = zipf_exponent
        self.seed = seed
        self._profile = -zipf_exponent * np.log(np.arange(1, vocab_size + 1))

    def logits(self, context: Sequence[int]) -> np.ndarray:
        prev = int(context[-1]) if len(context) else 0
        rng = np.random.default_rng((self.seed * 1_000_003 + prev) & 0xFFFFFFFF)
        out = np.empty(self.vocab_size)
        out[rng.permutation(self.vocab_size)] = self._profile
        return out

    def mean_entropy(self) -> float:
        p = _softmax(self._profile)
        return float(-(p * np.log(p + 1e-300)).sum())


def _softmax(x: np.ndarray) -> np.ndarray:
    z = np.exp(x - x.max())
    return z / z.sum()


def generate(
    lm: SyntheticLM,
    length: int,
    rng: np.random.Generator,
    watermark: GreenListWatermark | None = None,
    start_token: int = 0,
) -> list[int]:
    tokens = [start_token]
    for _ in range(length):
        logits = lm.logits(tokens)
        if watermark is not None:
            logits = watermark.bias_logits(logits, tokens)
        tokens.append(int(rng.choice(lm.vocab_size, p=_softmax(logits))))
    return tokens


def replace_tokens(tokens: Sequence[int], fraction: float, vocab_size: int, rng: np.random.Generator) -> list[int]:
    """Controlled corruption: replace a fraction of positions (excluding the start token) with
    uniformly random tokens. Used for defensive robustness measurement."""
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be in [0, 1]")
    out = list(tokens)
    n = len(out) - 1
    k = int(round(fraction * n))
    for i in rng.choice(np.arange(1, len(out)), size=k, replace=False):
        out[i] = int(rng.integers(vocab_size))
    return out


def watermark_distortion(lm: SyntheticLM, watermark: GreenListWatermark, contexts: int, seed: int) -> dict:
    """Average per-step KL(watermarked || base) and entropy change over random contexts.
    A low KL does not demonstrate preserved semantic quality."""
    rng = np.random.default_rng(seed)
    kls, h_base, h_wm = [], [], []
    for _ in range(contexts):
        ctx = [int(rng.integers(lm.vocab_size))]
        base = _softmax(lm.logits(ctx))
        wm = _softmax(watermark.bias_logits(lm.logits(ctx), ctx))
        kls.append(float((wm * (np.log(wm + 1e-300) - np.log(base + 1e-300))).sum()))
        h_base.append(float(-(base * np.log(base + 1e-300)).sum()))
        h_wm.append(float(-(wm * np.log(wm + 1e-300)).sum()))
    return {
        "mean_kl_nats": float(np.mean(kls)),
        "mean_entropy_base_nats": float(np.mean(h_base)),
        "mean_entropy_watermarked_nats": float(np.mean(h_wm)),
        "contexts": contexts,
    }
