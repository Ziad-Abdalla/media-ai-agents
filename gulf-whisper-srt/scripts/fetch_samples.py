"""Download the evaluation clips listed in data/sources.md into data/samples/.

Nothing here is committed to git: the audio stays with its original source,
and this script rebuilds the same clips on any machine.

    python scripts/fetch_samples.py

Writes, for each clip: <id>.wav (16 kHz mono), <id>.ref.txt (reference
transcript, if the source has one), and data/samples/manifest.json.
"""

import io
import json
import sys
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
from faster_whisper import decode_audio

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
ROWS_API = "https://datasets-server.huggingface.co/rows"
SAMPLE_RATE = 16000

# google/fleurs, config ar_eg, split test (CC-BY-4.0). Modern Standard Arabic, read speech.
FLEURS_ROWS = [7, 66, 184, 263]
FLEURS_REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"  # dataset commit the clips were made from

# SADA (Saudi Audio Dataset for Arabic), via an unofficial, non-gated Hugging Face mirror
# (CC BY-NC-SA 4.0, see data/sources.md). Despite its name, rows 0-52 are one episode of
# the Saudi series "الديرة نت", labelled Khaliji (Gulf) by SADA, mostly male speakers.
# Each clip is a list of annotated segments (row numbers).
SADA_DATASET = "muaadh019/najdi-female-tts-small"
SADA_REVISION = "d6b1d1438c3385a8d449d367bf9b327cb005ddbc"
SADA_CLIPS = {
    "sada_scene_a": list(range(37, 46)),  # two speakers talking about getting up early
    "sada_scene_b": [3, 4, 5, 10, 11, 12, 13, 15, 18],  # one speaker making tea at the office
}
# A continuous stretch of the same episode with no reference: used only to show a real SRT.
SADA_DEMO = ("sada_demo_scene", 493.0, 548.0)
UNCLEAR = "غيرواضح"  # SADA marks inaudible speech with this word


def get(url: str, tries: int = 4) -> bytes:
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                return response.read()
        except Exception as error:  # the rows API sometimes returns 502; just retry
            if attempt == tries - 1:
                raise
            print(f"  retrying after error: {error}")
            time.sleep(3 * (attempt + 1))


def get_rows(dataset: str, config: str, split: str, offset: int, length: int) -> list[dict]:
    query = urllib.parse.urlencode(
        {"dataset": dataset, "config": config, "split": split, "offset": offset, "length": length}
    )
    return json.loads(get(f"{ROWS_API}?{query}"))["rows"]


def check_revision(dataset: str, expected: str) -> None:
    """The rows API always serves the latest version, so warn if the dataset changed."""
    sha = json.loads(get(f"https://huggingface.co/api/datasets/{dataset}"))["sha"]
    if sha != expected:
        print(f"  warning: {dataset} changed since the committed results (now {sha[:8]}); clips may differ")


def save_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm.tobytes())


def fetch_fleurs(manifest: list[dict]) -> None:
    check_revision("google/fleurs", FLEURS_REVISION)
    for row_index in FLEURS_ROWS:
        clip_id = f"fleurs_ar_{row_index:03d}"
        print(f"{clip_id}: FLEURS ar_eg test row {row_index}")
        row = get_rows("google/fleurs", "ar_eg", "test", row_index, 1)[0]["row"]
        audio = decode_audio(io.BytesIO(get(row["audio"][0]["src"])), sampling_rate=SAMPLE_RATE)
        save_wav(SAMPLES / f"{clip_id}.wav", audio)
        (SAMPLES / f"{clip_id}.ref.txt").write_text(row["raw_transcription"], encoding="utf-8")
        manifest.append(
            {"id": clip_id, "variety": "MSA (read)", "license": "CC-BY-4.0",
             "seconds": round(len(audio) / SAMPLE_RATE, 1), "has_reference": True}
        )


def fetch_sada(manifest: list[dict]) -> None:
    check_revision(SADA_DATASET, SADA_REVISION)
    rows = {r["row_idx"]: r["row"] for r in get_rows(SADA_DATASET, "default", "train", 0, 60)}
    # Every row links to the whole episode recording; rows 0-52 are the same episode.
    episode_url = rows[37]["audio"][0]["src"]
    episode_key = (rows[37]["ShowName"], rows[37]["FullFileLength"])
    print("SADA: downloading one episode (about 20 MB)")
    episode = decode_audio(io.BytesIO(get(episode_url)), sampling_rate=SAMPLE_RATE)
    pause = np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)

    for clip_id, row_numbers in SADA_CLIPS.items():
        pieces, texts = [], []
        for n in row_numbers:
            row = rows[n]
            if (row["ShowName"], row["FullFileLength"]) != episode_key:
                raise ValueError(f"row {n} is from a different episode")
            if UNCLEAR in row["ProcessedText"]:
                print(f"  {clip_id}: skipping row {n} (marked unclear)")
                continue
            start, end = float(row["SegmentStart"]), float(row["SegmentEnd"])
            pieces += [episode[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)], pause]
            texts.append(row["ProcessedText"].strip())
        audio = np.concatenate(pieces)
        save_wav(SAMPLES / f"{clip_id}.wav", audio)
        (SAMPLES / f"{clip_id}.ref.txt").write_text(" ".join(texts), encoding="utf-8")
        print(f"{clip_id}: {len(texts)} segments, {len(audio) / SAMPLE_RATE:.1f} s")
        manifest.append(
            {"id": clip_id, "variety": "Saudi/Gulf dialect (TV comedy)", "license": "CC BY-NC-SA 4.0",
             "seconds": round(len(audio) / SAMPLE_RATE, 1), "has_reference": True}
        )

    clip_id, start, end = SADA_DEMO
    audio = episode[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
    save_wav(SAMPLES / f"{clip_id}.wav", audio)
    print(f"{clip_id}: continuous {start:.0f}-{end:.0f} s, no reference (SRT demo only)")
    manifest.append(
        {"id": clip_id, "variety": "Saudi/Gulf dialect (TV comedy)", "license": "CC BY-NC-SA 4.0",
         "seconds": round(len(audio) / SAMPLE_RATE, 1), "has_reference": False}
    )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    SAMPLES.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    fetch_fleurs(manifest)
    fetch_sada(manifest)
    (SAMPLES / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"done: {len(manifest)} clips in {SAMPLES}")


if __name__ == "__main__":
    main()
