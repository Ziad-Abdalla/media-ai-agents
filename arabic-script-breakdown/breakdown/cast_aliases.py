"""Character aliases for THIS script's cast (data/kamera_jaddi.txt).

This map is written by hand for one episode. A new script needs its own map,
built from its cast list. Short keys like "خالد" or "الأب" are only safe here
because this cast has one Khalid and one father.
"""

from .normalize import normalize_arabic

# In a drama script one person has many names: the father is "سعد" in the
# action lines, "أبو فهد" in the dialogue, and "الأب" in someone's notes.
# A scheduler needs ONE row per actor, so every alias is mapped to the name
# used in the cast list. The model is told to use cast names, and this map is
# the safety net when it doesn't.
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
