# Day 14 Router held-out evaluation report
- Backend: `semantic_offline`
- Evalset: `router_evalset.jsonl`
- Total examples: `372`
- Accuracy: `1.000000`
- MAE all: `0.000000`
- MAE valid exact/semantic: `0.000000`
- Fallback accuracy: `1.000000`

## Category metrics

| category | n | correct | accuracy |
|---|---:|---:|---:|
| ambiguous | 24 | 24 | 1.000000 |
| exact_decimal | 40 | 40 | 1.000000 |
| exact_fraction | 40 | 40 | 1.000000 |
| exact_percent | 60 | 60 | 1.000000 |
| exact_phrase | 18 | 18 | 1.000000 |
| semantic_offline | 160 | 160 | 1.000000 |
| unparsed | 30 | 30 | 1.000000 |

## Mode breakdown

- `exact`: 158
- `fallback_ambiguous`: 24
- `fallback_unparsed`: 30
- `semantic_offline`: 160

## Failures

No failures.
