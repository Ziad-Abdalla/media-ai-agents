Model `large-v3-turbo` on `cpu`.

| Clip | Variety | Length (s) | WER light | WER Arabic-norm | CER Arabic-norm | RTF |
|---|---|---|---|---|---|---|
| fleurs_ar_007 | MSA (read) | 23.8 | 8.3% | 5.6% | 0.9% | 0.409 |
| fleurs_ar_066 | MSA (read) | 25.7 | 10.3% | 10.3% | 3.9% | 0.372 |
| fleurs_ar_184 | MSA (read) | 23.8 | 45.8% | 45.8% | 10.9% | 0.511 |
| fleurs_ar_263 | MSA (read) | 21.5 | 16.7% | 0.0% | 0.0% | 0.687 |
| sada_scene_a | Saudi/Gulf dialect (TV show) | 48.9 | 48.9% | 40.4% | 16.0% | 0.583 |
| sada_scene_b | Saudi/Gulf dialect (TV show) | 60.9 | 44.8% | 42.7% | 17.7% | 0.655 |
| sada_demo_scene | Saudi/Gulf dialect (TV show) | 55.0 | n/a (no reference) | n/a (no reference) | n/a (no reference) | 0.774 |

| Variety (pooled) | Ref words | WER Arabic-norm | CER Arabic-norm |
|---|---|---|---|
| MSA (read) | 113 | 14.2% | 3.7% |
| Saudi/Gulf dialect (TV show) | 190 | 41.6% | 16.9% |
