# Clips that need a human reference transcript

The dialect score in the README comes from SADA, which has official transcripts but a
non-commercial license, and whose segments are short and pre-cut. These clips would make
the evaluation stronger, but they don't have an exact transcript for a short window, and
we don't invent one. A native speaker can transcribe ~30-60 s of each.

## How to add a reference

1. Listen to the clip and type exactly what is said, in Arabic, into a UTF-8 text file.
   Write what you hear (dialect spelling is fine), no diacritics needed, skip laughter and music.
2. Save it as `data/samples/<clip id>.ref.txt`.
3. Run `python scripts/run_eval.py`. Any clip with a `.ref.txt` file gets scored.

For a clip that is not in `fetch_samples.py`, score it directly:

```
python -m gulf_srt clip.ogg -o clip.srt
python -m gulf_srt.evaluate clip.ref.txt clip.srt
```

## Candidates

### 1. `sada_demo_scene` (Saudi/Gulf dialect, CC BY-NC-SA 4.0), first priority
- Already downloaded by `fetch_samples.py` as `data/samples/sada_demo_scene.wav` (55 s, continuous).
- SADA's own transcript skips two parts it marks as unclear and the laughter, so it can't be
  used for a continuous scene. A full human transcript gives a score on real, uncut dialogue,
  which is what an editor would actually feed in.
- Save as `data/samples/sada_demo_scene.ref.txt`.

### 2. LibriVox, «طبائع الاستبداد» by al-Kawakibi, section 00 (MSA, public domain)
- Audio: https://archive.org/download/tabai_al-istibdad_wa-masari_al-istibad_1903_librivox/tabaialistibdad_00_alkawakibi_64kb.mp3 (3.2 MB, 6:25)
- License: public domain (LibriVox). Source: https://librivox.org/tabai-al-istibdad-wa-masari-al-istibad-by-abd-al-rahman-al-kawakibi/
- The book text is on Arabic Wikisource (public domain), but the reader used a different edition
  and the recording opens with a spoken LibriVox notice, so the reference for a window
  (about 0:20-1:30) must be checked by ear against the text.

### 3. Wikimedia Commons, "Programming.ogg" (MSA, CC-BY-SA)
- Audio: https://upload.wikimedia.org/wikipedia/commons/7/79/Programming.ogg (1.8 MB, 112 s)
- License: CC-BY-SA (all versions) / GFDL. Attribution: "Programming.ogg" by Yousry753, Wikimedia Commons.
- A spoken reading of the Arabic Wikipedia article «برمجة» as it was in 2009. The article
  text is a starting point, but the reading may not match it word for word.

## Dialect clips with an open (CC0/CC-BY) license

None found with a transcript. Two Emirati datasets on Hugging Face have transcripts
(`eabayed/EmiratiDialictShowsAudioTranscription`, `FatimahEmadEldin/alsanaa-emirati-arabic-asr`),
but their audio comes from TV/radio/YouTube with unclear rights, so they are not used here.
