"""Stand in for an editor: lay the human reference transcript onto the draft's subtitle timings.

There are no real editor-corrected subtitles for the evaluation clips, but there is a human
reference transcript. This aligns the reference words with Whisper's words and puts each
reference word into the subtitle of the Whisper word it lines up with, keeping the draft's
timings. The result is what the SRT would look like if an editor had typed the reference in,
which lets `python -m gulf_srt.edits` measure "lines changed" on real dialect audio.

    python scripts/reference_as_final.py results/large-v3-turbo-cuda/sada_scene_a.words.json \
        data/samples/sada_scene_a.ref.txt -o examples/editor_loop/final/sada_scene_a.srt

It is an approximation: it never retimes or re-splits lines the way a real editor might.
"""

import argparse
import difflib
from pathlib import Path

from gulf_srt.evaluate import normalize
from gulf_srt.qc import words_by_cue
from gulf_srt.segment import Cue, build_cues, wrap_lines
from gulf_srt.srt import write_srt
from gulf_srt.transcript import load_transcript


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("words", help="a .words.json")
    parser.add_argument("reference", help="the human transcript (.txt)")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    transcript = load_transcript(args.words)
    cues = build_cues(transcript.words)
    # Which cue each Whisper token belongs to (a word can normalize to 0, 1 or 2 tokens).
    hyp, cue_of = [], []
    for n, own in enumerate(words_by_cue(cues, transcript.words)):
        for word in own:
            for token in normalize(word.text).split():
                hyp.append(token)
                cue_of.append(n)
    ref_words = Path(args.reference).read_text(encoding="utf-8-sig").split()
    ref = [normalize(w) for w in ref_words]

    placed: list[list[str]] = [[] for _ in cues]
    for op, h1, h2, r1, r2 in difflib.SequenceMatcher(None, hyp, ref, autojunk=False).get_opcodes():
        if r1 == r2:
            continue  # Whisper words with no reference word: the editor deleted them
        for k in range(r2 - r1):
            if h2 > h1:  # spread the reference words over the Whisper words they replace
                target = cue_of[h1 + k * (h2 - h1) // (r2 - r1)]
            else:  # words Whisper missed go with the word before them
                target = cue_of[max(h1 - 1, 0)]
            placed[target].append(ref_words[r1 + k])

    final = []
    for cue, words in zip(cues, placed):
        if words:
            text = " ".join(words)
            final.append(Cue(cue.start, cue.end, wrap_lines(text) or [text]))
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    write_srt(final, args.output)
    print(f"{len(final)} lines -> {args.output}")


if __name__ == "__main__":
    main()
