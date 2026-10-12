"""A show's correction list: fix spellings Whisper keeps getting wrong, before subtitles are cut.

A replacements file has one rule per line, wrong spelling => right spelling:

    # names and words for this show
    ابو حمد => أبو حمد
    على شأن => علشان

Rules match whole words only, so «حمد» never changes inside «محمد». The first word may carry an
attached و/ف/ب/ل/ك/ال (and their combinations like وال، بال، لل), which is kept: with the rule
«على شأن => علشان», «وعلى شأن» becomes «وعلشان», and with «عبوود => عبود», «لعبوود» becomes «لعبود».

Attached letters are only allowed when the rule is long enough to be safe: two or more words, or
a first word of at least 4 letters. A short word plus one of those letters is often a different
word: with «ريم => ريما», «كريم» would become «كريما», and with «حمد => أحمد», «بحمد الله» would
become «بأحمد الله». So a one-word rule of 3 letters or fewer matches the exact word only; write
a separate rule for an attached form you want («لريم => لريما»). Punctuation around the words is kept.
A rule can join or split words; the new word gets the time span of the words it replaced and the
lowest of their confidence scores, so the QC report still flags it if Whisper was unsure.

Use it with: python -m gulf_srt episode01.mp4 --replacements show_fixes.txt
`python -m gulf_srt.edits` suggests rules from what editors changed; a person approves each one.
"""

import unicodedata
from pathlib import Path

from gulf_srt.segment import Word

# Attached particles, longest first so «وال» is tried before «و».
PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال", "وب", "ول", "وك", "فب", "فل", "و", "ف", "ب", "ل", "ك")
# A one-word rule needs at least this many letters before attached letters are allowed in front.
MIN_LETTERS_FOR_ATTACHED = 4

Rule = tuple[list[str], str]  # (the wrong words, the right text)


def read_replacements(file: str | Path) -> list[Rule]:
    """Read 'wrong => right' lines; empty lines and lines starting with # are skipped."""
    rules = []
    lines = Path(file).read_text(encoding="utf-8-sig").splitlines()
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        wrong, arrow, right = line.partition("=>")
        if not arrow or not wrong.split() or not right.strip():
            raise ValueError(f"{file}, line {number}: expected 'wrong => right', got {line!r}")
        rules.append((wrong.split(), right.strip()))
    return rules


def split_punctuation(text: str) -> tuple[str, str, str]:
    """'«عبود،' -> ('«', 'عبود', '،')"""
    def is_punct(ch: str) -> bool:
        return unicodedata.category(ch).startswith("P")

    start, end = 0, len(text)
    while start < end and is_punct(text[start]):
        start += 1
    while end > start and is_punct(text[end - 1]):
        end -= 1
    return text[:start], text[start:end], text[end:]


def letter_count(text: str) -> int:
    """Letters only: diacritics, tatweel and punctuation don't count."""
    return sum(ch.isalpha() and ch != "ـ" for ch in text)


def allows_attached(wrong: list[str]) -> bool:
    """Whether a rule (or search) may match with و/ف/ب/ل/ك/ال attached to its first word."""
    return len(wrong) > 1 or letter_count(wrong[0]) >= MIN_LETTERS_FOR_ATTACHED


def _match(words: list[Word], i: int, wrong: list[str]) -> str | None:
    """If the rule's words start at words[i], return the attached prefix ('' if none)."""
    if i + len(wrong) > len(words):
        return None
    parts = [split_punctuation(w.text) for w in words[i : i + len(wrong)]]
    for k, (lead, core, trail) in enumerate(parts):
        if (k > 0 and lead) or (k < len(parts) - 1 and trail):
            return None  # don't match across punctuation, like the end of a sentence
        if k > 0 and core != wrong[k]:
            return None
    first = parts[0][1]
    for prefix in ("",) + (PREFIXES if allows_attached(wrong) else ()):
        if first == prefix + wrong[0]:
            return prefix
    return None


def apply_replacements(words: list[Word], rules: list[Rule]) -> tuple[list[Word], int]:
    """Return the corrected words and how many replacements were made. Longer rules win."""
    rules = sorted(rules, key=lambda rule: len(rule[0]), reverse=True)
    result, count, i = [], 0, 0
    while i < len(words):
        for wrong, right in rules:
            prefix = _match(words, i, wrong)
            if prefix is not None:
                span = words[i : i + len(wrong)]
                lead, trail = split_punctuation(span[0].text)[0], split_punctuation(span[-1].text)[2]
                text = lead + prefix + right + trail
                result.append(Word(span[0].start, span[-1].end, text, min(w.probability for w in span)))
                count += text != " ".join(w.text for w in span)
                i += len(wrong)
                break
        else:
            result.append(words[i])
            i += 1
    return result, count
