# Example outputs

Made with `python -m gulf_srt --from-json ...` from the saved Whisper words in `results/`, so
no GPU was needed to build them. Both come from the SADA evaluation clips (one episode of the
public Saudi series «الديرة نت», CC BY-NC-SA 4.0, see `data/sources.md`). None of it comes from any company's data.

- `sada_demo_scene/`: a 55-second continuous scene, every output file the tool writes.
- `hotwords_dropped_start/`: `sada_scene_b` transcribed with the cast-name hotwords. Whisper
  skipped the first 20 seconds of speech; the QC report's speech check catches it and lists it first.
- `editor_loop/`: the edits report on the two dialect clips. `draft/` is the tool's SRT; `final/`
  stands in for an editor's corrected file, made by `scripts/reference_as_final.py`, which lays the
  SADA human reference transcript onto the draft's timings. It is not a real editor's work.
  `edits.md` is the report and `suggested_replacements.txt` the suggested rules (all switched off;
  made with `--min-count 1` so the format is visible on two short clips).
- `archive.json`: a dialogue index built from the baseline SRTs in `results/large-v3-turbo-cuda/`.

The `.review.html` pages link to the audio in `data/samples/`, which you get with
`python scripts/fetch_samples.py`.
