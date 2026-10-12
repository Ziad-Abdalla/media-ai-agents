Model `large-v3-turbo` on `cuda`.

| Clip | Variety | Length (s) | WER light | WER Arabic-norm | CER Arabic-norm | RTF |
|---|---|---|---|---|---|---|
| fleurs_ar_007 | MSA (read) | 23.8 | 8.3% | 5.6% | 0.9% | 0.036 |
| fleurs_ar_066 | MSA (read) | 25.7 | 10.3% | 10.3% | 3.2% | 0.024 |
| fleurs_ar_184 | MSA (read) | 23.8 | 45.8% | 45.8% | 10.2% | 0.023 |
| fleurs_ar_263 | MSA (read) | 21.5 | 8.3% | 0.0% | 0.0% | 0.024 |
| sada_scene_a | Saudi/Gulf dialect (TV show) | 48.9 | 37.2% | 34.0% | 13.8% | 0.032 |
| sada_scene_b | Saudi/Gulf dialect (TV show) | 60.9 | 52.1% | 47.9% | 20.2% | 0.032 |
| sada_demo_scene | Saudi/Gulf dialect (TV show) | 55.0 | n/a (no reference) | n/a (no reference) | n/a (no reference) | 0.037 |

| Variety (pooled) | Ref words | WER Arabic-norm | CER Arabic-norm |
|---|---|---|---|
| MSA (read) | 113 | 14.2% | 3.3% |
| Saudi/Gulf dialect (TV show) | 190 | 41.1% | 17.1% |
