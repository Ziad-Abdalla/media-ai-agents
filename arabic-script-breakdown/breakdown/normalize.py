"""Arabic text normalization and character-name aliases.

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


def same_place(a: str, b: str) -> bool:
    """Loose match for locations: same after normalizing, or one contained in the other.

    "بيت ابو فهد، المجلس" matches "بيت أبو فهد - المجلس".
    """
    ka, kb = item_key(a), item_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka


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


# ---------------------------------------------------------------------------
# Character aliases
#
# In a drama script one person has many names: the father is "سعد" in the
# action lines, "أبو فهد" in the dialogue, and "الأب" in someone's notes.
# A scheduler needs ONE row per actor, so every alias is mapped to the name
# used in the cast list. The model is told to use cast names, and this map is
# the safety net when it doesn't.
# ---------------------------------------------------------------------------
ALIASES: dict[str, list[str]] = {
    "فهد": ["فهد العتيبي", "فهود", "فهد (17 سنة)"],
    "فهد الصغير": ["فهد صغير", "فهد (طفل)", "فهد طفل", "فهد بعمر 7 سنوات", "فهد (7 سنوات)"],
    "ريان": ["ريون", "ريّون"],
    "ماجد": [],
    "أبو فهد": ["سعد", "سعد العتيبي", "الأب", "ابو فهد", "والد فهد", "سعد العتيبي (أبو فهد)"],
    "أم فهد": ["نورة", "الأم", "ام فهد", "والدة فهد", "نورة (أم فهد)"],
    "سارة": ["ساره", "أخت فهد"],
    "المدير": ["الأستاذ خالد", "الأستاذ خالد الزهراني", "خالد الزهراني", "خالد", "مدير المدرسة",
               "الأستاذ خالد الزهراني (المدير)"],
    "الأستاذ عادل": ["عادل", "مدرس الكيمياء", "الاستاذ عادل"],
    "عم بندر": ["بندر", "الحارس", "حارس المدرسة"],
    "الجدة لطيفة": ["لطيفة", "الجدة", "يمه لطيفة", "جدة فهد"],
    "الجد عبدالله": ["عبدالله", "الجد", "جد فهد", "الجد عبد الله"],
}

# normalized alias -> canonical name (canonical names map to themselves)
_ALIAS_INDEX = {
    normalize_arabic(alias): canonical
    for canonical, aliases in ALIASES.items()
    for alias in [canonical, *aliases]
}


def canonical_character(name: str) -> str:
    """Map any spelling or nickname to the cast-list name. Unknown names pass through."""
    return _ALIAS_INDEX.get(normalize_arabic(name), name.strip())
