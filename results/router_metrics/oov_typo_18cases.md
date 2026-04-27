# 18-case OOV / Typo Robustness Test

Companion to `18_case_oov_typo_result.txt` (raw `unittest -v` stdout) with a human-readable case-by-case breakdown.

The test (`tests/test_router_typos.py`) runs the router on 18 inputs that were never seen during development of the regex anchors or phrase map. 16 cases must match a specific p* within tol=0.001; 2 cases must report `mode='fallback_unparsed'`.

## Numeric-expected cases (16 / 16 PASS)

| Input | Expected p* | Routing path |
|-------|-------------|--------------|
| `insert 25%`                    | 0.25 | `exact` (numeric) |
| `insert half`                   | 0.50 | `exact` (phrase map) |
| `go to 0.75`                    | 0.75 | `exact` (numeric) |
| `insert a little`               | 0.25 | `semantic_offline` (regex anchor) |
| `barely insert`                 | 0.25 | `semantic_offline` |
| `insert most of the way`        | 0.75 | `semantic_offline` |
| `insert a litlle bitt`          | 0.25 | typo -> fuzzy -> `semantic_offline` |
| `insrt halfway`                 | 0.50 | typo -> fuzzy -> `exact` |
| `barly insert`                  | 0.25 | typo -> fuzzy -> `semantic_offline` |
| `shove it in just a hair`       | 0.25 | `semantic_offline` ("a hair") |
| `drive it home`                 | 1.00 | `semantic_offline` |
| `nudge it in slightly`          | 0.25 | `semantic_offline` |
| `push deep but stop short`      | 0.75 | `semantic_offline` ("deep but ... short") |
| `engage just enough to feel it` | 0.25 | `semantic_offline` ("just enough") |
| `insert until snug`             | 0.75 | `semantic_offline` ("snug") |
| `nearly bottom out`             | 0.75 | `semantic_offline` + soft-full pattern suppress |

## Fallback-unparsed cases (2 / 2 PASS)

| Input | Expected mode | Reason |
|-------|---------------|--------|
| `asset 00081`     | `fallback_unparsed` | references a non-target concept (asset id) |
| `what time is it` | `fallback_unparsed` | unrelated to the insertion task |

These two MUST hit `fallback_unparsed` and not silently return p*=0.5 by numeric coincidence. The test asserts `result.mode == 'fallback_unparsed'`, not just p*.

## Reproduce

    cd ~/work/vt-refine
    ROUTER_SEMANTIC_BACKEND=auto python3 -m unittest tests.test_router_typos -v

Backends `offline` or `embedding` can be set via the env var. With `auto` the regex+typo path resolves all 16 numeric cases without consulting the embedding model.
