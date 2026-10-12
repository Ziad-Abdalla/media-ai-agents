# Example outputs

Made with `python -m gulf_srt --from-json ...` from the saved Whisper words in `results/`, so
no GPU was needed to build them. Both come from the SADA evaluation clips (one episode of the
public Saudi series «الديرة نت», CC BY-NC-SA 4.0, see `data/sources.md`). This is not Sadaf data.

- `sada_demo_scene/`: a 55-second continuous scene, every output file the tool writes.
- `hotwords_dropped_start/`: `sada_scene_b` transcribed with the cast-name hotwords. Whisper
  skipped the first 20 seconds of speech; the QC report's gap check is what catches it.

The `.review.html` pages link to the audio in `data/samples/`, which you get with
`python scripts/fetch_samples.py`.
