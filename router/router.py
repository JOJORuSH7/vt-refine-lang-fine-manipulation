from dataclasses import dataclass, field
from functools import lru_cache
import math
import os
import re
from typing import Dict, List, Optional, Tuple


ANCHORS = [0.0, 0.25, 0.5, 0.75, 1.0]
DEFAULT_FALLBACK = 0.5

SEMANTIC_BACKEND_ENV = "ROUTER_SEMANTIC_BACKEND"
EMBEDDING_MODEL_ENV = "ROUTER_EMBEDDING_MODEL"
EMBEDDING_CACHE_ENV = "ROUTER_EMBEDDING_CACHE_DIR"

DEFAULT_SEMANTIC_BACKEND = "auto"  # auto | embedding | offline | none
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

SEMANTIC_MIN_SCORE = 0.18
SEMANTIC_MIN_MARGIN = 0.03

PHRASE_MAP = {
    "not at all": 0.0,
    "none": 0.0,
    "zero": 0.0,
    "a quarter": 0.25,
    "one quarter": 0.25,
    "one fourth": 0.25,
    "quarter of the way": 0.25,
    "quarter way": 0.25,
    "quarter": 0.25,
    "half way": 0.5,
    "halfway": 0.5,
    "a half": 0.5,
    "one half": 0.5,
    "half": 0.5,
    "three quarters": 0.75,
    "three fourths": 0.75,
    "three quarter": 0.75,
    "all the way": 1.0,
    "full insertion": 1.0,
    "completely": 1.0,
    "complete": 1.0,
    "fully": 1.0,
    "full": 1.0,
}

SOFT_FULL_PHRASES = {
    "all the way",
    "full insertion",
    "completely",
    "complete",
    "fully",
    "full",
}

SOFT_FULL_PATTERNS = [
    r"\b(almost|nearly|mostly)\s+(full|fully|complete|completely|all the way)\b",
    r"\bnot\s+(quite\s+)?(full|fully|complete|completely|all the way)\b",
    r"\bjust\s+shy\s+of\s+(full|fully|complete|completely|all the way)\b",
    r"\bdeep\b.*\bnot\s+complete\b",
    r"\b(almost|nearly|mostly)\s+(bottom|seated|home)\b",
]

SEMANTIC_ANCHOR_EXEMPLARS = {
    0.0: [
        "do not insert",
        "no insertion",
        "leave it out",
        "keep it outside",
        "stop before inserting",
    ],
    0.25: [
        "insert a little",
        "just a bit",
        "barely insert",
        "shallow insertion",
        "start it in",
        "go in slightly",
    ],
    0.5: [
        "insert partway",
        "go halfway",
        "moderate insertion",
        "some amount",
        "middle depth",
        "about the middle",
    ],
    0.75: [
        "most of the way",
        "almost fully",
        "nearly all the way",
        "deep but not complete",
        "not quite all the way",
        "mostly inserted",
    ],
    1.0: [
        "fully insert",
        "complete insertion",
        "bottom it out",
        "finish insertion",
        "push until seated",
    ],
}

SEMANTIC_DIRECT_PATTERNS: List[Tuple[float, List[str]]] = [
    (
        0.0,
        [
            r"\bdo not insert\b",
            r"\bno insertion\b",
            r"\bleave it out\b",
            r"\bkeep it outside\b",
            r"\bstop before inserting\b",
        ],
    ),
    (
        0.25,
        [
            r"\ba little\b",
            r"\bjust a bit\b",
            r"\ba bit\b",
            r"\blittle bit\b",
            r"\bbarely\b",
            r"\bshallow\b",
            r"\bslightly\b",
            r"\bstart it in\b",
            r"\ba hair\b",
            r"\ba tiny bit\b",
            r"\btiny bit\b",
            r"\bjust enough\b",
            r"\bnudge\b",
        ],
    ),
    (
        0.5,
        [
            r"\bpartway\b",
            r"\bpart\s+way\b",
            r"\bsome amount\b",
            r"\bmoderate\b",
            r"\bmiddle\b",
            r"\bmidway\b",
        ],
    ),
    (
        0.75,
        [
            r"\bmost of the way\b",
            r"\balmost\s+(fully|full|complete|completely|all the way)\b",
            r"\bnearly\s+(all|fully|full|complete|completely)\b",
            r"\bnot quite all the way\b",
            r"\bmostly\b",
            r"\bdeep\b.*\bnot\s+complete\b",
            r"\bsnug\b",
            r"\bnearly\s+bottom\b",
            r"\balmost\s+bottom\b",
            r"\bnear\s+the\s+bottom\b",
            r"\bdeep\b.*\bstop\s+short\b",
        ],
    ),
    (
        1.0,
        [
            r"\bbottom it out\b",
            r"\bbottom out\b",
            r"\bfinish( the)? insertion\b",
            r"\bpush until seated\b",
            r"\bdrive (it )?home\b",
            r"\ball the way home\b",
        ],
    ),
]

SEMANTIC_INTENT_TERMS = {
    "insert",
    "insertion",
    "go",
    "push",
    "slide",
    "move",
    "advance",
    "seat",
    "seated",
    "depth",
    "way",
    "partway",
    "part",
    "amount",
    "fully",
    "full",
    "complete",
    "shallow",
    "deep",
    "outside",
    "inside",
}


@dataclass
class RouteResult:
    p_star: float
    mode: str
    reason: str
    candidates: List[float] = field(default_factory=list)



# Fuzzy lexical correction targets: only single-token typos with similarity
# >= 0.85 are replaced. Numbers, fractions, and short tokens are skipped.
_FUZZY_TARGETS = sorted(set([
    "quarter", "quarters", "fourth", "fourths", "third",
    "half", "halfway", "fully", "completely", "complete",
    "way", "all", "the",
    "insert", "insertion", "barely", "shallow", "slightly",
    "partway", "midway", "moderate", "middle",
    "almost", "nearly", "mostly", "bottom", "seated", "snug",
    "tiny", "hair", "nudge", "drive", "home", "deep", "shove",
    "engage", "enough", "feel", "until",
]))


def _fuzzy_correct(text_norm: str) -> str:
    import difflib
    tokens = text_norm.split()
    out = []
    for tok in tokens:
        if tok in _FUZZY_TARGETS:
            out.append(tok)
            continue
        if any(ch.isdigit() for ch in tok) or "/" in tok or "%" in tok or "." in tok:
            out.append(tok)
            continue
        if len(tok) < 4:
            out.append(tok)
            continue
        match = difflib.get_close_matches(tok, _FUZZY_TARGETS, n=1, cutoff=0.85)
        out.append(match[0] if match else tok)
    return " ".join(out)


def _normalize_text(text: str) -> str:
    text = (text or "").lower().strip()
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    text = _fuzzy_correct(text)
    return text


def _dedup(values: List[float], tol: float = 1e-9) -> List[float]:
    out = []
    for v in values:
        if not any(abs(v - x) <= tol for x in out):
            out.append(v)
    return out


def _in_range_01(x: float) -> bool:
    return 0.0 <= x <= 1.0


def _has_soft_full_modifier(text_norm: str) -> bool:
    return any(re.search(pat, text_norm) for pat in SOFT_FULL_PATTERNS)


def _exact_candidates(text_norm: str) -> List[float]:
    candidates = []

    # 1) phrase matches.
    # Prefer longer non-overlapping phrases so "three quarter" does not
    # also add the nested "quarter" candidate.
    used_phrase_spans = []
    for phrase, value in sorted(PHRASE_MAP.items(), key=lambda kv: -len(kv[0])):
        if phrase in SOFT_FULL_PHRASES and _has_soft_full_modifier(text_norm):
            continue

        pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
        for m in re.finditer(pattern, text_norm):
            span = m.span()
            overlaps = any(
                max(span[0], prev[0]) < min(span[1], prev[1])
                for prev in used_phrase_spans
            )
            if overlaps:
                continue

            used_phrase_spans.append(span)
            candidates.append(value)

    # 2) percentages: 25%, 25 percent, 62.5 percent
    for m in re.finditer(r"(?<![\d/])(\d+(?:\.\d+)?)\s*(?:%|percent)(?!\w)", text_norm):
        value = float(m.group(1)) / 100.0
        if _in_range_01(value):
            candidates.append(value)

    # 3) fractions: 1/4, 3/4, 1/2
    for m in re.finditer(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)", text_norm):
        num = int(m.group(1))
        den = int(m.group(2))
        if den != 0:
            value = num / den
            if _in_range_01(value):
                candidates.append(value)

    # 4) decimals or exact 0/1.
    # Do not treat the numerator/denominator of a spaced fraction like
    # "1 / 5" as a separate standalone "1" decimal candidate.
    for m in re.finditer(r"(?<![\d/])(?:0(?:\.\d+)?|1(?:\.0+)?|\.\d+)(?![\d/])", text_norm):
        before = text_norm[:m.start()].rstrip()
        after = text_norm[m.end():].lstrip()
        if before.endswith("/") or after.startswith("/"):
            continue

        value = float(m.group(0))
        if _in_range_01(value):
            candidates.append(value)

    return _dedup(candidates)


def _has_semantic_intent(text_norm: str) -> bool:
    tokens = set(re.findall(r"[a-z]+", text_norm))
    if tokens & SEMANTIC_INTENT_TERMS:
        return True
    return any(
        re.search(pat, text_norm)
        for _, patterns in SEMANTIC_DIRECT_PATTERNS
        for pat in patterns
    )


def _direct_semantic_result(text_norm: str) -> Optional[RouteResult]:
    soft_full = _has_soft_full_modifier(text_norm)
    hits = []
    for value, patterns in SEMANTIC_DIRECT_PATTERNS:
        # If text has a soft-full modifier (e.g. "nearly", "almost"), skip
        # the 1.0 anchor patterns so "nearly bottom out" doesn't co-fire 1.0
        # alongside the 0.75 "nearly bottom" pattern.
        if soft_full and value == 1.0:
            continue
        if any(re.search(pat, text_norm) for pat in patterns):
            hits.append(value)

    hits = _dedup(hits)

    if len(hits) == 1:
        return RouteResult(
            p_star=hits[0],
            mode="semantic_offline",
            reason="direct_semantic_pattern",
            candidates=hits,
        )

    if len(hits) > 1:
        return RouteResult(
            p_star=DEFAULT_FALLBACK,
            mode="fallback_ambiguous",
            reason="multiple_semantic_direct_patterns",
            candidates=hits,
        )

    return None


def _char_ngrams(text: str, ns=(3, 4, 5)) -> Dict[str, float]:
    compact = f" {text} "
    feats: Dict[str, float] = {}
    for n in ns:
        if len(compact) < n:
            continue
        for i in range(len(compact) - n + 1):
            gram = compact[i : i + n]
            feats[gram] = feats.get(gram, 0.0) + 1.0
    return feats


def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


@lru_cache(maxsize=1)
def _offline_exemplar_vectors():
    rows = []
    for value, texts in SEMANTIC_ANCHOR_EXEMPLARS.items():
        for exemplar in texts:
            rows.append((value, exemplar, _char_ngrams(_normalize_text(exemplar))))
    return rows


def _semantic_offline(text_norm: str) -> Optional[RouteResult]:
    if not _has_semantic_intent(text_norm):
        return None

    direct = _direct_semantic_result(text_norm)
    if direct is not None:
        return direct

    q = _char_ngrams(text_norm)
    scored = []
    for value, exemplar, vec in _offline_exemplar_vectors():
        scored.append((_cosine(q, vec), value, exemplar))

    scored.sort(reverse=True, key=lambda x: x[0])
    if not scored:
        return None

    best_score, best_value, best_exemplar = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    margin = best_score - second_score

    if best_score >= SEMANTIC_MIN_SCORE and margin >= SEMANTIC_MIN_MARGIN:
        return RouteResult(
            p_star=best_value,
            mode="semantic_offline",
            reason=f"char_ngram_nearest_exemplar:{best_exemplar};score={best_score:.4f};margin={margin:.4f}",
            candidates=[best_value],
        )

    return None


@lru_cache(maxsize=1)
def _embedding_payload():
    from sentence_transformers import SentenceTransformer

    model_name = os.environ.get(EMBEDDING_MODEL_ENV, DEFAULT_EMBEDDING_MODEL)
    cache_dir = os.environ.get(EMBEDDING_CACHE_ENV, None)

    model = SentenceTransformer(model_name, cache_folder=cache_dir)

    exemplar_texts = []
    exemplar_values = []
    for value, texts in SEMANTIC_ANCHOR_EXEMPLARS.items():
        for t in texts:
            exemplar_values.append(value)
            exemplar_texts.append(t)

    exemplar_embeddings = model.encode(exemplar_texts, normalize_embeddings=True)
    return model, exemplar_texts, exemplar_values, exemplar_embeddings


def _semantic_embedding(text_norm: str) -> Optional[RouteResult]:
    if not _has_semantic_intent(text_norm):
        return None

    try:
        model, exemplar_texts, exemplar_values, exemplar_embeddings = _embedding_payload()
        query_embedding = model.encode([text_norm], normalize_embeddings=True)[0]
        sims = exemplar_embeddings @ query_embedding
    except Exception:
        return None

    order = sims.argsort()[::-1]
    if len(order) == 0:
        return None

    best_i = int(order[0])
    second_score = float(sims[int(order[1])]) if len(order) > 1 else 0.0
    best_score = float(sims[best_i])
    margin = best_score - second_score
    best_value = exemplar_values[best_i]
    best_text = exemplar_texts[best_i]

    if best_score >= 0.45 and margin >= 0.03:
        return RouteResult(
            p_star=best_value,
            mode="semantic_embedding",
            reason=f"embedding_nearest_exemplar:{best_text};score={best_score:.4f};margin={margin:.4f}",
            candidates=[best_value],
        )

    return None


def route_instruction(text: str, semantic_backend: str = None) -> RouteResult:
    text_norm = _normalize_text(text)

    if not text_norm:
        return RouteResult(
            p_star=DEFAULT_FALLBACK,
            mode="fallback_unparsed",
            reason="empty_input",
            candidates=[DEFAULT_FALLBACK],
        )

    candidates = _exact_candidates(text_norm)

    if len(candidates) == 1:
        return RouteResult(
            p_star=candidates[0],
            mode="exact",
            reason="single_parse",
            candidates=candidates,
        )

    if len(candidates) > 1:
        return RouteResult(
            p_star=DEFAULT_FALLBACK,
            mode="fallback_ambiguous",
            reason="multiple_conflicting_parses",
            candidates=candidates,
        )

    # Deterministic semantic anchor patterns take priority over embedding,
    # because regex anchors are zero-error hard rules whereas embeddings are
    # soft similarity. This ensures "insert most of the way" -> 0.75 even if
    # SBERT would have judged it 1.0.
    direct = _direct_semantic_result(text_norm)
    if direct is not None:
        return direct

    backend = semantic_backend or os.environ.get(SEMANTIC_BACKEND_ENV, DEFAULT_SEMANTIC_BACKEND)

    if backend in ("auto", "embedding"):
        semantic = _semantic_embedding(text_norm)
        if semantic is not None:
            return semantic

        if backend == "embedding":
            return RouteResult(
                p_star=DEFAULT_FALLBACK,
                mode="fallback_unparsed",
                reason="embedding_backend_unavailable_or_low_confidence",
                candidates=[DEFAULT_FALLBACK],
            )

    if backend in ("auto", "offline"):
        semantic = _semantic_offline(text_norm)
        if semantic is not None:
            return semantic

    return RouteResult(
        p_star=DEFAULT_FALLBACK,
        mode="fallback_unparsed",
        reason="no_supported_parse",
        candidates=[DEFAULT_FALLBACK],
    )
