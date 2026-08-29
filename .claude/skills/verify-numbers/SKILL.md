---
name: verify-numbers
description: Check every figure in REPORT.md against results/dev_results.jsonl. Use before editing the report, after any documentation change that touches a number, and any time a figure is quoted somewhere new.
---

# verify-numbers

`REPORT.md` states figures. `results/dev_results.jsonl` is where they came from. This checks the
first against the second, because a report figure that no longer matches its artifact is the
defect class this project has caught most often.

## Run it

```bash
make recompute-dev
```

That imports the real `score_turn` from `src/domain/scorer.py` rather than reimplementing the
rules, so the script cannot quietly disagree with the evaluator.

## Compare

Read the output against `REPORT.md`'s Results section. Every one of these must match exactly:

| Figure | Expected |
|---|---|
| tolerant | 1130/1490 = 75.84% |
| strict | 855/1490 = 57.38% |
| conversation exact match | 271/421 = 64.37% |
| reasons | ok 1130, wrong_value 335, parse_error 25 |
| scale_flip | 10 |
| by turn index | 77.67 / 77.43 / 74.10 / 74.41 / 70.37 / 75.00 |
| literal vs computation | 374/487 = 76.80% vs 756/1003 = 75.37% |
| step count, within computation | 408/530, 295/396, 53/77 |
| type1 vs type2 | 823/1052 = 78.23% vs 307/438 = 70.09% |

**If a figure disagrees, the artifact is right and the report is wrong.** Fix the report. Do not
adjust the script to match the report, and do not regenerate the artifact — it is the frozen
record of a measurement that was taken once.

## Also worth grepping

Numbers that have drifted before, each in a different direction:

```bash
grep -nE '352|411|945|1486|0\.074|206|369' REPORT.md
```

- **352, not 411** — exposure counts top-level `divide` only; 411 is the raw magnitude bucket and
  59 of those cannot exhibit the error.
- **206 of 369** legitimately uses 369, because that probe defined its own population. If both
  numbers appear, the text must make clear why.
- **945/1486** is the exact-match count behind the 63.6% ceiling claim.

## After editing prose

A rewrite is where a digit moves. Re-run `make recompute-dev` after any edit to the Results
section, not before.
