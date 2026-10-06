# postMeter

Sketch for testing whether poetic meter/rhythm predicts social media engagement.

`score_meter.py` converts each post into a syllable stress string using the CMU
Pronouncing Dictionary and computes rhythm features:

| feature | meaning |
|---|---|
| `stress_pattern` | `S` stressed, `u` unstressed, `?` unknown word |
| `alternation` | share of adjacent syllables that alternate stress |
| `clash_rate`, `lapse_count` | stressed-stressed pairs / runs of 3+ unstressed (verse avoids both) |
| `beat_regularity` | 1 − CV of gaps between stresses (1 = perfectly even beat) |
| `fit_iambic` … `fit_dactylic`, `best_meter` | best match to a repeating foot |
| `final_stressed` | ends on a stressed syllable ("punchy" ending) |
| `segment_balance` | how equal in syllables the phrases are (parallelism) |
| `end_rhyme` | two phrase-final words rhyme |
| `pentameter_line` | a phrase is 10 syllables of near-iambic verse (à la Pentametron) |

```
pip install pronouncing
python score_meter.py sample_posts.csv --engagement-col likes -o scored.csv
```

With `--engagement-col` it prints Spearman correlations against log engagement.
The bundled sample is for checking the script runs; its correlations mean nothing.

## Known limitations

- Stress is dictionary stress, not performed stress. Monosyllables are stressed
  unless on a function-word list, so runs of content words ("some days the bear")
  read as clashes.
- Only the first CMUdict pronunciation is used; slang, numbers and names are `?`.
- Raw correlations are confounded by author, follower count, topic and length.
  For a real test, compare paired posts (same author, same link/topic, different
  wording, as in Tan, Lee & Pang 2014) or regress with those controls.
