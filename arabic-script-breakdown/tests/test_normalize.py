from breakdown.normalize import ALIASES, canonical_character, normalize_arabic, same_place, same_prop


def test_tashkeel_and_tatweel_removed():
    assert normalize_arabic("كـــامِيرَا") == "كاميرا"


def test_letter_variants_unified():
    assert normalize_arabic("أحمد") == normalize_arabic("احمد")
    assert normalize_arabic("مدرسة") == normalize_arabic("مدرسه")
    assert normalize_arabic("مستشفى") == normalize_arabic("مستشفي")


def test_digits_and_punctuation():
    assert normalize_arabic("فصل ٣ ثانوي") == "فصل 3 ثانوي"
    assert normalize_arabic("بيت أبو فهد - الصالة") == "بيت ابو فهد الصاله"


def test_same_place_allows_spelling_and_extra_words():
    assert same_place("بيت ابو فهد، المجلس", "بيت أبو فهد - المجلس")
    assert same_place("غرفة فهد", "غرفه فهد")
    assert not same_place("بيت أبو فهد - المطبخ", "بيت أبو فهد - المجلس")


def test_same_prop_uses_main_noun_and_synonyms():
    assert same_prop("الكاميرا القديمة", "كاميرا سينما قديمة")   # same main noun
    assert same_prop("هاتف", "جوال")                            # MSA vs Gulf word
    assert same_prop("فنجان قهوة", "فنجال قهوة")                 # spelling variant
    assert same_prop("سماعة", "سماعات")                         # singular vs plural
    assert not same_prop("لابتوب", "جوال")


def test_aliases_map_to_cast_names():
    assert canonical_character("سعد") == "أبو فهد"
    assert canonical_character("فهود") == "فهد"
    assert canonical_character("الأستاذ خالد الزهراني") == "المدير"
    assert canonical_character("ابو فهد") == "أبو فهد"      # spelling without hamza
    assert canonical_character("شخص جديد") == "شخص جديد"   # unknown names pass through


def test_no_alias_points_to_two_people():
    seen = {}
    for canonical, aliases in ALIASES.items():
        for alias in [canonical, *aliases]:
            key = normalize_arabic(alias)
            assert seen.setdefault(key, canonical) == canonical, f"{alias} is used twice"
