"""A searchable dialogue index: find every line where a word or name is said, with its timecode.

Every run of `python -m gulf_srt` writes <name>.index.json next to the SRT. You can also
index subtitle files you already have (a back catalogue's delivered SRTs need no Whisper):

    python -m gulf_srt.archive build out/ old_subtitles/ -o archive.json
    python -m gulf_srt.archive search archive.json "عبود"
    python -m gulf_srt.archive search out/ "الديرة" --word

Search ignores diacritics, punctuation and the أ/إ/ا, ة/ه, ى/ي spelling variants (the same
normalization the WER score uses), so «أبو حمد» also finds «ابو حمد».
By default it matches inside words, because Arabic attaches و/ب/ل/ال to the front of a
word: searching «عبود» also finds «لعبود». Use --word to match whole words only.
"""

import argparse
import json
import sys
from pathlib import Path

from gulf_srt.evaluate import normalize
from gulf_srt.segment import Cue
from gulf_srt.srt import format_timestamp, read_srt

INDEX_FORMAT = "gulf-srt-dialogue-index"


def entries_from_cues(cues: list[Cue], file: str) -> list[dict]:
    return [
        {"file": file, "cue": n, "start": round(c.start, 3), "end": round(c.end, 3), "text": c.text}
        for n, c in enumerate(cues, start=1)
    ]


def make_index(entries: list[dict]) -> dict:
    return {"format": INDEX_FORMAT, "version": 1, "entries": entries}


def write_index(index: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def build_from_subtitles(paths: list[str | Path], pattern: str = "*.srt") -> dict:
    """Index subtitle files, or every file matching `pattern` inside the given folders."""
    entries = []
    for path in map(Path, paths):
        files = sorted(path.rglob(pattern)) if path.is_dir() else [path]
        for file in files:
            entries += entries_from_cues(read_srt(file), file.as_posix())
    return make_index(entries)


def load_entries(path: str | Path) -> list[dict]:
    """One index file, or every *.index.json / archive file found in a folder."""
    path = Path(path)
    files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    entries = []
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("format") == INDEX_FORMAT:
            entries += data["entries"]
    return entries


def search(entries: list[dict], query: str, whole_word: bool = False) -> list[dict]:
    wanted = normalize(query)
    if not wanted:
        return []
    hits = []
    for entry in entries:
        text = normalize(entry["text"])
        found = f" {wanted} " in f" {text} " if whole_word else wanted in text
        if found:
            hits.append(entry)
    return hits


def format_hit(entry: dict) -> str:
    return f"{entry['file']}  {format_timestamp(entry['start'])}  #{entry['cue']}  {entry['text']}"


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build or search a dialogue index.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="index subtitle files or folders of them")
    build.add_argument("paths", nargs="+")
    build.add_argument("-o", "--output", default="archive.json")
    build.add_argument("--pattern", default="*.srt", help="which files to read inside folders")
    find = sub.add_parser("search", help="find every line where a word or name is said")
    find.add_argument("index", help="an index .json file, or a folder of them")
    find.add_argument("query")
    find.add_argument("--word", action="store_true", help="whole words only")
    args = parser.parse_args(argv)

    if args.command == "build":
        index = build_from_subtitles(args.paths, args.pattern)
        write_index(index, args.output)
        files = len({e["file"] for e in index["entries"]})
        print(f"{len(index['entries'])} lines from {files} files -> {args.output}")
        return

    hits = search(load_entries(args.index), args.query, whole_word=args.word)
    for hit in hits:
        print(format_hit(hit))
    files = len({h["file"] for h in hits})
    print(f"{len(hits)} lines in {files} files" + ("" if hits else f" (nothing found for «{args.query}»)"))


if __name__ == "__main__":
    main()
