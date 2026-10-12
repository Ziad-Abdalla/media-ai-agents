"""Word error rate (WER) and character error rate (CER) for Arabic.

WER = (words substituted + deleted + inserted) / words in the reference.
CER is the same idea counted in characters, which is kinder to Arabic,
where one missing letter (like the "و" in "وقال") makes the whole word wrong.

The score depends a lot on normalization. Arabic is often written with or
without diacritics, and people swap أ/إ/ا, ة/ه and ى/ي freely, so we treat
those as the same before comparing. Report which normalization you used,
because the same transcript can score very differently.

Usage: python -m gulf_srt.evaluate reference.txt hypothesis.srt
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from gulf_srt.srt import RLM, srt_to_text

LRM = "\u200e"  # LEFT-TO-RIGHT MARK, the other invisible direction mark

_TASHKEEL = re.compile("[\u064b-\u0652\u0670]")  # short-vowel marks, shadda, sukun, dagger alef
_TATWEEL = "ـ"  # the stretching line in "مـــرحبا"
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _strip_punctuation(text: str) -> str:
    return "".join(" " if unicodedata.category(ch).startswith("P") else ch for ch in text)


def normalize(text: str, arabic: bool = True) -> str:
    """Light normalization always: no punctuation, lower case, single spaces.
    Arabic normalization (default on): also drop diacritics/tatweel and unify letter variants."""
    text = text.replace(RLM, "").replace(LRM, "")
    if arabic:
        text = _TASHKEEL.sub("", text)
        text = text.replace(_TATWEEL, "")
        text = re.sub("[أإآٱ]", "ا", text)  # alef forms -> bare alef
        text = text.replace("ة", "ه")  # ta marbuta -> ha
        text = text.replace("ى", "ي")  # alef maqsura -> ya
        text = text.translate(_ARABIC_DIGITS)
    text = _strip_punctuation(text).lower()
    return " ".join(text.split())


def edit_distance(reference: list, hypothesis: list) -> int:
    """Smallest number of substitutions, deletions and insertions (Levenshtein)."""
    previous = list(range(len(hypothesis) + 1))
    for i, ref_item in enumerate(reference, start=1):
        current = [i]
        for j, hyp_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ref_item != hyp_item),  # substitution (or match)
                )
            )
        previous = current
    return previous[-1]


def wer(reference: str, hypothesis: str) -> float:
    ref_words = reference.split()
    return edit_distance(ref_words, hypothesis.split()) / max(len(ref_words), 1)


def cer(reference: str, hypothesis: str) -> float:
    return edit_distance(list(reference), list(hypothesis)) / max(len(reference), 1)


def score(reference: str, hypothesis: str, arabic: bool = True) -> dict:
    ref, hyp = normalize(reference, arabic), normalize(hypothesis, arabic)
    return {"wer": wer(ref, hyp), "cer": cer(ref, hyp)}


def _read(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8-sig")
    return srt_to_text(text) if path.lower().endswith(".srt") else text


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="WER/CER of a transcript against a reference.")
    parser.add_argument("reference", help="reference .txt (or .srt)")
    parser.add_argument("hypothesis", help="hypothesis .txt or .srt")
    args = parser.parse_args(argv)
    reference, hypothesis = _read(args.reference), _read(args.hypothesis)
    for label, arabic in (("light normalization", False), ("Arabic normalization", True)):
        result = score(reference, hypothesis, arabic)
        print(f"{label:22s} WER {result['wer']:.1%}  CER {result['cer']:.1%}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
