# Router Design

Single page on how `route_instruction(text)` works internally and why it is
structured as a 4-tier waterfall rather than a single embedding lookup or
a single rule book. Companion to `docs/system_architecture.md` (where the
router fits in the pipeline).

## The 4-tier waterfall

`route_instruction(text)` evaluates four checks in order. The first one
that returns a non-`None` `RouteResult` wins; remaining tiers are skipped.

| Tier | Mode label             | What it matches                                                       |
|------|------------------------|-----------------------------------------------------------------------|
| 1    | `exact`                | numeric formats and the static phrase map                             |
| 2    | `semantic_offline`     | hand-curated regex anchors, with `difflib` fuzzy correction up-front  |
| 3    | `semantic_embedding`   | sentence-transformers MiniLM-L6-v2 cosine vs anchor exemplar sentences |
| 4    | `fallback_unparsed` / `fallback_ambiguous` | explicit failure mode, returns tagged 0.5    |

The cost ordering is also right-to-left (Tier 1 cheapest, Tier 3 most
expensive). The contract is that any well-formed numeric or known-phrase
input bypasses the embedding model entirely.

## Why Tier 2 (regex) is **above** Tier 3 (embedding)

This is the key design choice and worth a paragraph.

We initially had embedding-only as the fallback after exact match. On the
18-case OOV/typo set, this routed `"shove it in just a hair"` to 0.5 (no
strong cosine similarity to any anchor) and `"nearly bottom out"` to 1.0
(strong similarity to "bottom out" exemplars, but the user said "nearly").
Both are wrong. The fix was to add a deterministic regex layer above the
embedding tier, with two specific patterns:

- An idiom anchor for `"a hair"` -> 0.25.
- A soft-full suppression pattern: when the input contains
  `(almost|nearly|mostly) (full|fully|complete|all the way|bottom|seated|home)`,
  the 1.0 anchors are skipped and the 0.75 anchor is preferred.

The general principle: **regex anchors give 0 % error on the idioms they
target; embedding gives a soft similarity that is good in expectation but
silently wrong on edge cases**. Putting regex above embedding keeps the
known idioms deterministic, lets embedding handle the genuinely
out-of-distribution cases, and makes failures visible as
`fallback_unparsed` rather than as "looks plausible but wrong".

In the current evalset and OOV set, the embedding tier never has to fire.
It exists for future inputs that miss every regex anchor.

## Fuzzy typo correction

Implemented in `_fuzzy_correct(text_norm)` using
`difflib.get_close_matches(token, _FUZZY_TARGETS, cutoff=0.85)`. This runs
inside `_normalize_text` **before** any tier 1-3 check. So a typo like
`"insrt halfway"` is rewritten to `"insert halfway"` and then resolves at
Tier 1 (exact). Multiple typos in one sentence (`"insert a litlle bitt"`)
are corrected token-by-token.

The cutoff 0.85 is set so that:

- Real typos within 1-2 char distance of a target word are corrected.
- Unrelated short words are not "corrected" into anchor vocabulary by
  accident.

The fuzzy step is the single intervention that lets Tier 1 + Tier 2
handle 18 out of 18 OOV/typo cases without needing embeddings at all.

## What goes into `RouteResult`

`RouteResult` is a dataclass with the following fields populated by
`route_instruction`:

- `p_star: float` -- the discrete target depth in {0.0, 0.25, 0.5, 0.75, 1.0}
- `mode: str` -- one of `'exact'`, `'semantic_offline'`,
  `'semantic_embedding'`, `'fallback_ambiguous'`, `'fallback_unparsed'`
- additional fields used internally to record which tier fired and which
  anchor matched

Downstream callers can use `mode` to log routing decisions
(`results/demos/routing_summary.md`) or to refuse to act on a fallback
case (a partial-stop demo run on `fallback_unparsed` would not be
meaningful).

## Anchor vocabulary

Three sources, in increasing fuzziness:

1. `PHRASE_MAP` (Tier 1) -- a fixed dict of phrase -> p\* (e.g.
   `'halfway' -> 0.5`, `'three quarters' -> 0.75`). Exact match required
   after normalisation. About 25 entries.
2. Regex anchors inside `_direct_semantic_result` (Tier 2) -- per-anchor
   regex lists for {0.0, 0.25, 0.5, 0.75, 1.0}. Examples:
   `r'\b(barely|just\s+a\s+hair|just\s+a\s+bit)\b'` -> 0.25;
   `r'\b(most\s+of\s+the\s+way|almost\s+fully|deep\s+but\s+stop\s+short)\b'` -> 0.75.
3. `SEMANTIC_ANCHOR_EXEMPLARS` (Tier 3) -- per-anchor list of exemplar
   sentences used by the embedding tier. About 6-8 sentences per anchor.

Soft-full suppression (`SOFT_FULL_PATTERNS`) is applied inside Tier 2 to
prevent matches like `"almost fully"` from triggering the 1.0 regex.

## Known limitations

A short, honest list. We did not optimise for these.

- **English only.** PHRASE_MAP is English. A Chinese instruction like
  `"插一半"` lands in fallback. Adding multilingual support would mean
  per-language phrase maps and anchor exemplars, plus a normalisation
  step that strips diacritics consistently.
- **Conflicting signals are not resolved.** An input like
  `"halfway, actually no, all the way"` is a contradiction. The router
  matches whichever anchor fires first under the priority order; it does
  not detect or warn about contradictions. A safer behaviour would be to
  return `fallback_ambiguous` whenever two distinct anchors match.
- **Highly idiomatic English not in the regex list.** `"send it"` (slang
  for full insertion) is not in the anchor set and would fall through to
  embeddings or fallback. The mitigation is to grow the regex list as
  failure modes are observed in deployment.
- **No multi-step instructions.** `"insert halfway, then back out a bit"`
  is parsed as a single static target. The pipeline does not represent
  trajectories, only final depths.

These are real but acceptable for a class project whose scope is
"naturally phrase a discrete target depth, robustly". For a production
system one would want telemetry on how often each fallback fires in the
wild, and to grow the anchor vocabulary based on that.
