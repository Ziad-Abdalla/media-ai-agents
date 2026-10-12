"""Arabic text normalization.

Why this exists: the same word can be typed many ways in Arabic.
"أحمد", "احمد" and "أحْمَد" are one name to a human, but three different
strings to Python. Before we compare the model's answer with the gold answer,
we squash those spelling differences away so we only count real mistakes.
"""

import re

# Arabic-Indic (٠-٩) and Persian (۰-۹) digits -> Western digits.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")  # harakat, shadda, sukun...
_TATWEEL = "ـ"  # the stretching character: "كـــاميرا"
_PUNCT = re.compile(r"[^\w\s]")  # anything that is not a letter, digit or space


def normalize_digits(text: str) -> str:
    return text.translate(_DIGITS)


def normalize_arabic(text: str) -> str:
    """Make two spellings of the same Arabic word compare equal."""
    text = normalize_digits(text)
    text = _TASHKEEL.sub("", text)
    text = text.replace(_TATWEEL, "")
    text = re.sub("[أإآٱ]", "ا", text)  # all alef forms -> bare alef
    text = text.replace("ى", "ي")  # alef maqsura -> ya   (على / علي)
    text = text.replace("ة", "ه")  # ta marbuta -> ha     (مدرسة / مدرسه)
    text = text.replace("ؤ", "و").replace("ئ", "ي")
    text = _PUNCT.sub(" ", text)  # "-", "/", "(", "،" ... become spaces
    return " ".join(text.split())  # collapse repeated spaces


def strip_al(word: str) -> str:
    """Drop the definite article: "الكاميرا" -> "كاميرا"."""
    return word[2:] if word.startswith("ال") and len(word) > 3 else word


def item_key(text: str) -> str:
    """Key used to compare props/locations: normalized, without "ال" on each word."""
    return " ".join(strip_al(w) for w in normalize_arabic(text).split())


def same_place(predicted: str, gold: str) -> bool:
    """Location match: every word of the gold location must be in the predicted one.

    Spelling and punctuation don't matter, and extra words are allowed:
    "بيت ابو فهد، المجلس" matches "بيت أبو فهد - المجلس".
    A missing word is a mistake: "المدرسة" does not match "ممر المدرسة".
    """
    pred_words, gold_words = set(item_key(predicted).split()), set(item_key(gold).split())
    return bool(gold_words) and gold_words <= pred_words


# Words that name the same object. Some are Gulf dialect vs Modern Standard Arabic
# (جوال / هاتف), some are spelling variants (فنجال / فنجان), some are plural vs singular.
# All keys and values are already normalized (no hamza, ة -> ه).
WORD_SYNONYMS = {
    "هاتف": "جوال", "موبايل": "جوال", "تلفون": "جوال",
    "فنجان": "فنجال",
    "سماعه": "سماعات",
    "حقيبه": "شنطه",
    "كوب": "كاسه",
    "فلاش": "ذاكره",
}


def head_noun(text: str) -> str:
    """The first word of an Arabic noun phrase is the main noun.

    "كاميرا سينما قديمة", "الكاميرا القديمة" and "كاميرا سينمائية" are all a كاميرا.
    """
    words = item_key(text).split()
    return WORD_SYNONYMS.get(words[0], words[0]) if words else ""


def same_prop(a: str, b: str) -> bool:
    """Two prop names match if they share the same main noun (first word)."""
    return bool(head_noun(a)) and head_noun(a) == head_noun(b)
