# Routing Decisions for the Five Demos

Each demo's natural-language input mapped to its 4-tier routing decision and target progress p*. Modes are dumped from `route_instruction` at file-generation time, not hand-edited.

| # | User input | Routing mode | p* | Demo (mp4) | Animation (6x GIF) |
|---|-----------|--------------|------|-----------|--------------------|
| 1 | `insert 25%` | `exact` | 0.25 | `demos/insert_25__p025__seed41.mp4` | `gifs/insert_25__p025__seed41_6x.gif` |
| 2 | `halfway` | `exact` | 0.50 | `demos/halfway__p050__seed41.mp4` | `gifs/halfway__p050__seed41_6x.gif` |
| 3 | `insert a little bit` | `semantic_offline` | 0.25 | `demos/insert_a_little_bit__p025__seed41.mp4` | `gifs/insert_a_little_bit__p025__seed41_6x.gif` |
| 4 | `insert a litlle bitt` *(double typo)* | `semantic_offline` | 0.25 | `demos/insert_a_litlle_bitt__p025__seed41.mp4` | `gifs/insert_a_litlle_bitt__p025__seed41_6x.gif` |
| 5 | `most of the way` | `semantic_offline` | 0.75 | `demos/most_of_the_way__p075__seed41.mp4` | `gifs/most_of_the_way__p075__seed41_6x.gif` |

## Routing tiers (priority order)

1. **`exact`**: numeric percents (`25%`, `0.25`, `1/4`) AND the fixed phrase map (`halfway`, `quarter`, `fully`, ...).
2. **`semantic_offline`**: regex anchors covering common informal phrasings (`a little`, `most of the way`, `bottom out`, ...). Run BEFORE the embedding tier so known idioms are deterministic.
3. **`semantic_embedding`**: sentence-transformers MiniLM-L6-v2 zero-shot cosine vs per-anchor exemplars. Only consulted if 1 and 2 do not resolve.
4. **`fallback_unparsed`**: returns p*=0.5 with explicit `mode` tag, so callers can detect 'router did not understand'.

Typos are corrected via `difflib.get_close_matches` (cutoff 0.85) before any tier matches. Demo 4 (`insert a litlle bitt`) is the regression case for this typo path.
