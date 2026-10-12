"""Character aliases, one map per script.

Each map is written by hand for one script's cast. A new script needs its own map,
built from its cast list. Short keys like "خالد" or "الأب" are only safe in the
main script because that cast has one Khalid and one father. The hard set has two
people called سلمان on purpose, so its map never has a bare "سلمان" key.
"""

from collections import defaultdict

from .normalize import normalize_arabic

# Main script (data/kamera_jaddi.txt).
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

# Hard set (data/hard_scenes.txt). Two people share the first name سلمان:
# the father (سلمان الحربي, called أبو راكان) and the family driver (سلمان السائق).
# A bare "سلمان" could be either, so it is deliberately NOT a key: it gets flagged for review.
HARD_SET_ALIASES: dict[str, list[str]] = {
    "راكان": ["راكان الحربي", "ركوني"],
    "أبو راكان": ["سلمان الحربي", "سلمان الحربي (أبو راكان)", "ابو راكان", "والد راكان", "الأب"],
    "سلمان السائق": ["السائق", "السواق", "السائق سلمان", "سلمان (السائق)"],
    "منى": ["منى الدوسري", "منى الدوسري (مديرة الإنتاج)"],
    "الجدة موضي": ["موضي", "الجدة", "يمه موضي", "جدة راكان"],
}


class CastNames:
    """Turns any name variant into the one cast name, and spots names it cannot place."""

    def __init__(self, aliases: dict[str, list[str]]):
        self.aliases = aliases
        # normalized alias -> canonical name (canonical names map to themselves)
        self._index = {
            normalize_arabic(alias): canonical
            for canonical, variants in aliases.items()
            for alias in [canonical, *variants]
        }
        # first word -> the cast members whose name or alias starts with it ("سلمان" -> two people)
        first_words: dict[str, set[str]] = defaultdict(set)
        for alias, canonical in self._index.items():
            first_words[alias.split()[0]].add(canonical)
        self._shared_first_names = {w: sorted(c) for w, c in first_words.items() if len(c) > 1}

    @property
    def cast(self) -> list[str]:
        return list(self.aliases)

    def canonical(self, name: str) -> str:
        """Map any spelling or nickname to the cast-list name. Unknown names pass through."""
        return self._index.get(normalize_arabic(name), name.strip())

    def is_known(self, name: str) -> bool:
        return normalize_arabic(name) in self._index

    def review_note(self, name: str) -> str | None:
        """Why a person needs a human to check this name, or None if the name is a known cast member."""
        if self.is_known(name):
            return None
        key = normalize_arabic(name)
        if key in self._shared_first_names:
            return f"الاسم «{name}» يطابق أكثر من شخصية: {' أو '.join(self._shared_first_names[key])}"
        return f"الاسم «{name}» غير موجود في قائمة الشخصيات"


KAMERA_JADDI = CastNames(ALIASES)
HARD_SET = CastNames(HARD_SET_ALIASES)


def canonical_character(name: str) -> str:
    """Main-script shortcut: map a name with the kamera_jaddi cast map."""
    return KAMERA_JADDI.canonical(name)
