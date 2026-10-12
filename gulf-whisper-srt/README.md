# gulf-whisper-srt

Turn Arabic speech, including Saudi/Gulf dialect, from an audio or video file into a clean
Arabic `.srt` subtitle file, on your own machine with no paid API. It runs Whisper
(`large-v3-turbo` through [faster-whisper](https://github.com/SYSTRAN/faster-whisper)) to get
every word with its timing, then cuts the words into subtitles that follow broadcast-style rules
(two lines of at most 42 characters, no overlaps, and it aims for 1 to 6 seconds on screen at no
more than 17 characters a second; when speech is too fast or back-to-back it keeps the spoken
timing and lists those cues for the editor to check), and writes them with the invisible right-to-left marks Arabic lines need to display correctly.
It also includes a small WER/CER evaluation, so accuracy claims come with numbers and say
what they were measured on.

## Why this is useful for a drama production house

- **Subtitle drafts for editors.** An editor gets a timed first draft to correct in their usual
  tool (Premiere, DaVinci Resolve, Subtitle Edit) instead of typing every line from zero.
  Correcting a draft is much faster than writing one.
- **Searchable dialogue for the archive.** Every episode, rush or interview becomes text with
  timecodes, so "find the scene where he says «الديرة»" is a text search.
- **Private and cheap.** Unreleased footage never leaves the machine, and there's no per-minute cost.

## Quickstart

```
git clone <this repo>
cd gulf-whisper-srt
python -m venv .venv
```

Activate the environment with the line for your shell:

- PowerShell: `.venv\Scripts\Activate.ps1` (if scripts are blocked, run
  `Set-ExecutionPolicy -Scope Process Bypass` first)
- cmd.exe: `.venv\Scripts\activate.bat`
- Git Bash on Windows: `source .venv/Scripts/activate`
- Linux or macOS: `source .venv/bin/activate`

Then:

```
pip install -e ".[dev]"
pip install -e ".[cuda]"     # optional, NVIDIA GPU: CUDA 12 cuBLAS + cuDNN 9 as pip packages

python -m gulf_srt episode01.mp4 -o out/episode01.srt --model large-v3-turbo
```

The first run downloads the model (~1.6 GB for `large-v3-turbo`). Video files work directly:
the audio track is decoded with PyAV, so ffmpeg doesn't need to be installed.

Options: `--device auto|cuda|cpu` (auto loads the model on the GPU and does a one-second test
run; if either fails, for example because the CUDA libraries are missing, it falls back to CPU int8),
`--max-line-chars 42`, `--no-rtl-marks`. The output folder is created if it doesn't exist.

Evaluate and test:

```bash
pytest                                            # 32 unit tests, no model download
python scripts/fetch_samples.py                   # downloads the licensed clips (data/sources.md)
python scripts/run_eval.py --model large-v3-turbo # SRTs + WER/CER table in results/<model>-<device>/
python -m gulf_srt.evaluate reference.txt hypothesis.srt
python scripts/noise_check.py                     # Whisper on 20 s of noise, VAD off vs on
```

`run_eval.py` names its folder after the device that actually ran (`-cuda` or `-cpu`), so a GPU
run can be compared directly with the committed `results/large-v3-turbo-cuda/`.

## Pipeline

```mermaid
flowchart LR
    A[audio / video file] --> B[transcribe.py<br/>Whisper, language=ar<br/>VAD filter<br/>word timestamps]
    B -->|words + times| C[segment.py<br/>group words into cues<br/>merge tiny cues<br/>fix timing]
    C -->|cues| D[srt.py<br/>numbering, timestamps<br/>RLM marks]
    D --> E[subtitles.srt]
    E -.-> F[evaluate.py<br/>WER / CER vs reference]
```

| File | What it does |
|---|---|
| `gulf_srt/transcribe.py` | Loads the model (GPU float16, or CPU int8) and returns every word with its start/end time. Forces `language="ar"`, turns on the VAD filter (skips stretches with no speech, like silence and most noise, where Whisper tends to invent text; songs and dialogue over music still go to Whisper), and turns off "condition on previous text" so one mistake doesn't repeat down the file. |
| `gulf_srt/segment.py` | The subtitle rules (below). Pure Python, fully unit-tested. |
| `gulf_srt/srt.py` | Writes the SRT file and adds U+200F marks to Arabic lines. |
| `gulf_srt/cli.py` | The `python -m gulf_srt` command. Prints the numbers of any cues that miss the reading-speed or minimum-duration target. |
| `gulf_srt/evaluate.py` | Arabic normalization, WER and CER. |
| `scripts/fetch_samples.py` | Downloads the evaluation clips from their original sources. |
| `scripts/run_eval.py` | Runs the pipeline on every clip and writes the results table. |
| `scripts/noise_check.py` | Reproduces the noise hallucination check in the hardware notes. |

## Subtitle rules, and why

| Rule | Default | Why |
|---|---|---|
| Max characters per line | 42 | Common broadcast/streaming limit (Netflix uses 42 for Arabic); longer lines are hard to read in one glance. |
| Max lines per cue | 2 | A third line covers the picture. |
| Line break | after punctuation if it fits, otherwise the most balanced split | Two even lines are easier to read than one long and one short. |
| Duration | at most 6.0 s; aims for at least 1.0 s | Under a second is a flash nobody can read; over six seconds people re-read the line. |
| Reading speed | aims for ≤ 17 characters per second | Adult reading-speed guideline. If a cue is too fast, its end time is stretched into the silence after it. If the next cue starts too soon to stretch, the cue keeps its timing and `python -m gulf_srt` lists it as one to check. |
| Where to cut | end of sentence, a pause ≥ 0.6 s, or a comma once the cue is a full line | Subtitles should follow the speaker's phrasing. When a hard limit (length or 6 s) forces a cut, the code looks back for the last comma or pause instead of cutting mid-phrase. |
| Tiny cues | under 8 characters or under 1 s get merged into a neighbour, if they are less than 1 s apart and the result still fits | One-word cues like «ايه.» flicker on screen. |
| Overlaps | never | Each cue ends at or before the next one starts. |

**Right-to-left marks.** Players guess each line's direction from its first "strong" letter, and
punctuation at the edges takes the direction of its neighbours, so every Arabic line is wrapped in
invisible U+200F (RIGHT-TO-LEFT MARK) characters to keep lines like «Netflix عرضت المسلسل؟» laid
out right-to-left. The words themselves are not reordered or changed, and the tests check both things.

## Sample output

From `results/large-v3-turbo-cuda/sada_demo_scene.srt` (Saudi dialect TV comedy, SADA, CC BY-NC-SA 4.0).
The Whisper mistakes are left in on purpose. This is what an editor would get as a first draft:

```srt
7
00:00:25,760 --> 00:00:31,240
‏تدري ليش، تعرف اللعب الأجنبي خليت؟‏

8
00:00:32,760 --> 00:00:38,660
‏خليت، كذا عبود،‏
‏تراك صدقت نفسك ومسوي عمرك أجنبي‏

9
00:00:38,660 --> 00:00:41,680
‏يا ابن الحلال انت بالنفسك لا تتمصع،‏

10
00:00:41,680 --> 00:00:45,040
‏تراك كلك عذب ما فيك ولا لحم حلوة،‏
```

## Results

Model `large-v3-turbo`, faster-whisper 1.2.1, beam size 5, VAD on. GPU: RTX 5060 Laptop (8 GB), float16.
RTF (real-time factor) = processing time ÷ audio length, so 0.03 means one minute of audio takes about 2 seconds.
The model load and a one-second warm-up are not counted. WER/CER columns are from the GPU run.
The CPU run (int8, same model) produces slightly different text; its full table is in
`results/large-v3-turbo-cpu/results.md` (pooled WER 14.2% MSA, 41.6% dialect).
GPU runs on other machines can differ by about 1 point of WER on the dialect clips (different CUDA
library versions, float16 rounding); the MSA numbers have reproduced exactly.
The `.hyp.txt` files next to each `.srt` are the raw Whisper text that was scored.

| Clip | Variety | Length (s) | WER light norm. | WER Arabic norm. | CER Arabic norm. | RTF (GPU) | RTF (CPU int8) |
|---|---|---|---|---|---|---|---|
| fleurs_ar_007 | MSA, read | 23.8 | 8.3% | 5.6% | 0.9% | 0.056 | 0.409 |
| fleurs_ar_066 | MSA, read | 25.7 | 6.9% | 6.9% | 2.6% | 0.025 | 0.372 |
| fleurs_ar_184 | MSA, read | 23.8 | 45.8% | 45.8% | 10.2% | 0.024 | 0.511 |
| fleurs_ar_263 | MSA, read | 21.5 | 8.3% | 0.0% | 0.0% | 0.028 | 0.687 |
| sada_scene_a | Saudi dialect, TV comedy | 48.9 | 45.7% | 36.2% | 13.8% | 0.037 | 0.583 |
| sada_scene_b | Saudi dialect, TV comedy | 60.9 | 52.1% | 47.9% | 21.6% | 0.038 | 0.655 |
| sada_demo_scene | Saudi dialect, TV comedy | 55.0 | no reference | no reference | no reference | 0.040 | 0.774 |

Pooled (all errors ÷ all reference words), Arabic normalization:

| Variety | Reference words | WER | CER |
|---|---|---|---|
| MSA, read (4 clips) | 113 | 13.3% | 3.2% |
| Saudi dialect, TV comedy (2 clips) | 190 | 42.1% | 17.8% |

**How to read this.**
- **"Light" normalization** only removes punctuation. **"Arabic" normalization** also removes
  diacritics and tatweel and treats أ/إ/آ/ا, ة/ه and ى/ي as the same letter. The same transcript
  scores 8.3% or 0.0% WER on `fleurs_ar_263` depending only on that choice, which is why any WER
  number should say how the text was normalized.
- **CER is much lower than WER** in Arabic because one wrong letter in a word with attached
  particles («والأسماك» vs «في الأسماك») makes the whole word wrong.
- **`fleurs_ar_184` is the bad MSA clip.** It is full of rare words: «الموزاصور» (mosasaur) became
  «الموز الصور», «السلاحف» became «السلاح في», and «اللحوم» became «الرحوم».
- **The dialect gap is mostly real.** Some errors are only spelling: Whisper often writes dialect
  in MSA spelling («علشان» → «على شأن») or spells a word differently from the reference
  («تاني» vs «ثاني»), and the SADA reference writes laughter as words («هاها»), which Whisper never
  outputs. A human would accept these, but WER doesn't. Laughter is small, though: it is 2 of the
  190 reference words, and taking it out only moves pooled dialect WER from 42.1% to 41.5%. The
  spelling cases weren't counted one by one. The draft is useful to correct, but dialect needs a
  human pass.

**Limits.** Measured on 6 short clips (about 3.4 minutes with references) from 2 sources. This is
not a general accuracy claim. The dialect numbers come from one episode of one Saudi show, so they
say nothing about other Gulf dialects, noisy sets, or overlapping speech. `data/needs_reference.md`
lists clips a native speaker could transcribe to widen the test.

**What it would take for production.**
- **Measure on the client's own shows.** A native speaker transcribes 10-15 minutes per show, and
  CER/WER is tracked per show and per dialect against an agreed acceptance threshold.
- **Custom vocabulary.** Character names, places and recurring slang go into faster-whisper's
  `hotwords`, which is added to every 30-second window (`initial_prompt` would only reach the first
  window here, because `condition_on_previous_text` is off), plus a find-and-replace pass for known
  spellings.
- **Fine-tuning on licensed Gulf audio**, for example the client's own subtitled back catalogue,
  where the delivered subtitles are ready-made labels. SADA can't be used for this commercially.
- **An editor in the loop.** Editors correct the draft in Subtitle Edit or Premiere; their
  corrections are logged and fed back as new hotwords and training data.

## Data licensing

The dialect clips come from SADA (SDAIA with the Saudi Broadcasting Authority) under
**CC BY-NC-SA 4.0: non-commercial, share-alike**. They are used here only for this public,
non-commercial evaluation. No audio is committed; `scripts/fetch_samples.py` downloads it, and the
SADA-derived transcripts in `results/` keep CC BY-NC-SA 4.0. Production use, or fine-tuning a model
for a commercial client, needs data licensed for that use: the client's own archive with rights
cleared, or a commercial agreement with SDAIA/SBA. Details and the source chain are in
`data/sources.md`.

## Hardware notes

Tested on Windows 11, NVIDIA GeForce RTX 5060 Laptop GPU (8 GB, Blackwell, compute capability 12.0,
driver 616.92), Python 3.13.7.

- **faster-whisper on the GPU works.** CTranslate2 4.8.2 (the inference engine under faster-whisper)
  saw the GPU and ran `large-v3-turbo` in float16 on the first try, with CUDA 12 libraries installed
  from pip (`nvidia-cublas-cu12` 12.9, `nvidia-cudnn-cu12` 9.27). There was no need to fall back to
  PyTorch or to the CPU.
- **Windows DLL path.** Those pip packages put their DLLs in `site-packages/nvidia/*/bin`, which
  Windows doesn't search, so `transcribe.py` adds those folders before loading the model.
- **PyAV 16+ breaks faster-whisper 1.2.1** (`open() got an unexpected keyword argument 'metadata_errors'`).
  PyAV is pinned below 16 (15.1.0 was used).
- **CPU fallback** (`--device cpu`, or `auto` when the GPU fails its one-second test run; int8) also works with the same model, at an RTF of about 0.4-0.8
  (a 45-minute episode in roughly 20-35 minutes) instead of about 0.03 on the GPU.
- **No ffmpeg needed.** Audio and video are decoded with PyAV, which bundles its own ffmpeg libraries.
- **Hallucination check** (`python scripts/noise_check.py`). Fed 20 s of random noise without the
  VAD filter, Whisper produced «اشتركوا في القناة» ("subscribe to the channel"), a well-known
  Whisper failure picked up from YouTube training data. With VAD on it produced nothing. That's
  why the VAD filter is on by default. VAD only removes stretches with no speech: a title song or
  dialogue over a music bed still goes to Whisper and can come out garbled. Separating speech from
  music first (for example with Demucs) would be the next step there.

## License

Code: MIT. Evaluation clips and the transcripts in `results/` keep their own licenses;
see `data/sources.md`.
