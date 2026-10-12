# Evaluation audio: sources and licenses

No audio is committed to this repo. `python scripts/fetch_samples.py` downloads
the clips below from their original sources into `data/samples/` (git-ignored).
The `.srt`, `.hyp.txt` and `.words.json` files in `results/`, and everything in `examples/`, are machine transcripts of these
clips and carry the same license and attribution as the clip they come from.

## 1. FLEURS, Arabic (Modern Standard Arabic, read speech)

| Clip id | Dataset row | Length |
|---|---|---|
| `fleurs_ar_007` | `ar_eg` / test / row 7 | 23.8 s |
| `fleurs_ar_066` | `ar_eg` / test / row 66 | 25.7 s |
| `fleurs_ar_184` | `ar_eg` / test / row 184 | 23.8 s |
| `fleurs_ar_263` | `ar_eg` / test / row 263 | 21.5 s |

- **Source:** https://huggingface.co/datasets/google/fleurs (config `ar_eg`, split `test`).
  Single rows are fetched through the Hugging Face dataset viewer API
  (`https://datasets-server.huggingface.co/rows?dataset=google/fleurs&config=ar_eg&split=test&offset=<row>&length=1`),
  so we don't download the full 243 MB archive.
  The clips were built from dataset commit `70bb2e84b976b7e960aa89f1c648e09c59f894dd`.
- **License:** CC-BY-4.0.
- **Attribution:** Conneau et al., "FLEURS: Few-shot Learning Evaluation of Universal Representations of Speech" (2022), Google.
- **Reference transcript:** the dataset's own `raw_transcription` field (official, punctuated).
- **Note:** the `ar_eg` config is Modern Standard Arabic read aloud by Egyptian speakers, not Egyptian dialect.

## 2. SADA, Saudi/Gulf dialect (TV show, conversational)

| Clip id | What it is | Length |
|---|---|---|
| `sada_scene_a` | rows 37-45 of the episode, two speakers, rows marked "غيرواضح" (unclear) skipped, joined with 0.5 s silences | 48.9 s |
| `sada_scene_b` | rows 3, 4, 5, 10, 11, 12, 13, 15, 18, one speaker, joined the same way | 60.9 s |
| `sada_demo_scene` | continuous 493-548 s of the same episode, **no reference**; used only to show a real SRT | 55.0 s |

- **Source:** SADA (Saudi Audio Dataset for Arabic), released by SDAIA (Saudi Data and AI Authority)
  with the Saudi Broadcasting Authority. Official page: https://ieee-dataport.org/node/14747
  (DOI 10.21227/revt-pa41; the official IEEE DataPort and Kaggle copies need a login). We fetch
  from https://huggingface.co/datasets/muaadh019/najdi-female-tts-small, rows 0-52 of `train`,
  which are one episode of the series «الديرة نت».
- **This is an unofficial community mirror**, two hops from SDAIA (it says "Duplicated from
  m6011/sada2022", itself a re-upload). We have not checked it file by file against the official
  release. Its name is misleading: the rows we use are not Najdi or female. SADA's own labels on
  them say `SpeakerDialect = Khaliji` (Gulf) for 52 of 53 rows, mostly male speakers, and that
  Khaliji label is our evidence for calling these clips Gulf dialect. The clips were built from
  mirror commit `d6b1d1438c3385a8d449d367bf9b327cb005ddbc`; `fetch_samples.py` warns if the mirror
  has changed since then.
- **License:** **CC BY-NC-SA 4.0 (non-commercial).** The Hugging Face copy's metadata tag says
  CC-BY-4.0, but its card text and the official SADA release say CC BY-NC-SA 4.0, so we follow
  the stricter one. This repo is a non-commercial evaluation; don't use these clips commercially.
- **Attribution:** SADA, Saudi Data and AI Authority (SDAIA) / National Center for AI, with the Saudi Broadcasting Authority.
- **Reference transcript:** the dataset's `ProcessedText` field for each segment (official). It is
  written without diacritics and with alef forms already merged into ا, and it includes laughter
  written as words ("هاها"), which Whisper doesn't output, so it adds a few "errors" by design.

## Not used, and why

- **MASC** (CC-BY-4.0, includes dialects): audio only comes in ~10 GB archives.
- **Mixat, QASR**: gated or non-commercial with sign-up.
- **Common Voice Arabic**: needs an account to download.
- **Wikimedia Commons Spoken Arabic Wikipedia** and **LibriVox Arabic**: openly licensed, but no
  exact transcript for a short window. Listed as candidates in `needs_reference.md`.
- No CC0/CC-BY **Gulf** dialect clip with a reference transcript was found.
