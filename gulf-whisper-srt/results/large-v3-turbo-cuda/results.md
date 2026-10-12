Model `large-v3-turbo` on `cuda`.

| Clip | Variety | Length (s) | WER light | WER Arabic-norm | CER Arabic-norm | RTF |
|---|---|---|---|---|---|---|
| fleurs_ar_007 | MSA (read) | 23.8 | 8.3% | 5.6% | 0.9% | 0.056 |
| fleurs_ar_066 | MSA (read) | 25.7 | 6.9% | 6.9% | 2.6% | 0.025 |
| fleurs_ar_184 | MSA (read) | 23.8 | 45.8% | 45.8% | 10.2% | 0.024 |
| fleurs_ar_263 | MSA (read) | 21.5 | 8.3% | 0.0% | 0.0% | 0.028 |
| sada_scene_a | Saudi/Gulf dialect (TV comedy) | 48.9 | 45.7% | 36.2% | 13.8% | 0.037 |
| sada_scene_b | Saudi/Gulf dialect (TV comedy) | 60.9 | 52.1% | 47.9% | 21.6% | 0.038 |
| sada_demo_scene | Saudi/Gulf dialect (TV comedy) | 55.0 | n/a (no reference) | n/a (no reference) | n/a (no reference) | 0.040 |

| Variety (pooled) | Ref words | WER Arabic-norm | CER Arabic-norm |
|---|---|---|---|
| MSA (read) | 113 | 13.3% | 3.2% |
| Saudi/Gulf dialect (TV comedy) | 190 | 42.1% | 17.8% |
