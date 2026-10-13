"""A searchable dialogue index: find every line where a word or name is said, with its timecode.

Every run of `python -m gulf_srt` writes <name>.index.json next to the SRT. You can also
index subtitle files you already have (a back catalogue's delivered SRTs need no Whisper):

    python -m gulf_srt.archive build out/ old_subtitles/ -o archive.json
    python -m gulf_srt.archive search archive.json "عبود"
    python -m gulf_srt.archive search out/ "الديرة" --word

How search matches, and why it differs from the WER score:

- It ignores diacritics, punctuation and the أ/إ/ا and ة/ه spelling variants, so «ابو حمد»
  finds «أبو حمد». Unlike the WER score it keeps ى and ي apart, because «على» ("on") and
  «علي» (a name) are different words.
- By default it matches whole words, also when و/ف/ب/ل/ك is attached to the front, because
  speech attaches them to names: «عبود» finds «لعبود» and «وعبود», but not «معبود», and
  «حمد» doesn't find «محمد» or «الحمد». Type ال if the word has it («الديرة»).
- A one-word search of 3 letters or fewer matches the exact word only, because a short word
  plus an attached letter is often another word: «ريم» would find «كريم», «مال» «كمال», and
  «ليد» «وليد». Use --anywhere if you do want those.
- --word matches the exact word only; --anywhere matches inside words too.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from gulf_srt.evaluate import normalize
from gulf_srt.replace import allows_attached
from gulf_srt.segment import Cue
from gulf_srt.srt import format_timestamp, read_srt

INDEX_FORMAT = "gulf-srt-dialogue-index"
# Letters spoken attached to the front of a name: and, so, with, to, like (and pairs of them).
ATTACHED = ("وب", "ول", "وك", "فب", "فل", "و", "ف", "ب", "ل", "ك")


def entries_from_cues(cues: list[Cue], file: str) -> list[dict]:
    """`file` is the subtitle file's path relative to the folder the index is saved in."""
    return [
        {"file": file, "cue": n, "start": round(c.start, 3), "end": round(c.end, 3), "text": c.text}
        for n, c in enumerate(cues, start=1)
    ]


def make_index(entries: list[dict]) -> dict:
    return {"format": INDEX_FORMAT, "version": 1, "entries": entries}


def write_index(index: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def _relative(path: Path, folder: Path) -> str:
    try:
        return Path(os.path.relpath(path.resolve(), folder.resolve())).as_posix()
    except ValueError:  # on another drive (Windows): keep the full path
        return path.resolve().as_posix()


def build_from_subtitles(paths: list[str | Path], pattern: str = "*.srt", index_folder: str | Path = ".") -> dict:
    """Index subtitle files, or every file matching `pattern` inside the given folders.
    File paths are stored relative to `index_folder`, where the index will be saved."""
    entries = []
    for path in map(Path, paths):
        files = sorted(path.rglob(pattern)) if path.is_dir() else [path]
        for file in files:
            entries += entries_from_cues(read_srt(file), _relative(file, Path(index_folder)))
    return make_index(entries)


def load_entries(path: str | Path) -> list[dict]:
    """One index file, or every index found in a folder. Each line appears once, even when a
    folder holds both the per-episode .index.json files and an archive built from the same SRTs.
    File paths come back relative to the folder searched (or the index file's folder)."""
    path = Path(path)
    files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    base = path if path.is_dir() else path.parent
    entries, seen = [], set()
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        if not (isinstance(data, dict) and data.get("format") == INDEX_FORMAT):
            continue
        for entry in data["entries"]:
            subtitle = (file.parent / entry["file"]).resolve()
            key = (subtitle, entry["cue"], entry["start"])
            if key not in seen:
                seen.add(key)
                entries.append({**entry, "file": _relative(subtitle, base)})
    return entries


def _for_search(text: str) -> str:
    return normalize(text, merge_ya=False)


def search(entries: list[dict], query: str, mode: str = "attached") -> list[dict]:
    """mode: 'attached' (whole words, with و/ف/ب/ل/ك allowed in front unless the query is one
    short word), 'word' (exact whole words) or 'anywhere' (inside words too)."""
    wanted = _for_search(query)
    if not wanted:
        return []
    if mode == "anywhere":
        pattern = re.compile(re.escape(wanted))
    else:
        attached = mode == "attached" and allows_attached(wanted.split())
        front = f"(?:{'|'.join(ATTACHED)})?" if attached else ""
        pattern = re.compile(f"(?:^| ){front}{re.escape(wanted)}(?= |$)")
    return [entry for entry in entries if pattern.search(_for_search(entry["text"]))]


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
    how = find.add_mutually_exclusive_group()
    how.add_argument("--word", action="store_const", const="word", dest="mode", help="the exact word only")
    how.add_argument("--anywhere", action="store_const", const="anywhere", dest="mode", help="also inside other words")
    args = parser.parse_args(argv)

    if args.command == "build":
        output = Path(args.output)
        index = build_from_subtitles(args.paths, args.pattern, index_folder=output.parent)
        write_index(index, output)
        files = len({e["file"] for e in index["entries"]})
        print(f"{len(index['entries'])} lines from {files} files -> {output}")
        return

    hits = search(load_entries(args.index), args.query, mode=args.mode or "attached")
    for hit in hits:
        print(format_hit(hit))
    files = len({h["file"] for h in hits})
    print(f"{len(hits)} lines in {files} files" + ("" if hits else f" (nothing found for «{args.query}»)"))


if __name__ == "__main__":
    main()
