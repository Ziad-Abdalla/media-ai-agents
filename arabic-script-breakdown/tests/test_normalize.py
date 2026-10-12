from breakdown.normalize import ALIASES, canonical_character, normalize_arabic, same_item


def test_tashkeel_and_tatweel_removed():
    assert normalize_arabic("كـــامِيرَا") == "كاميرا"


def test_letter_variants_unified():
    assert normalize_arabic("أحمد") == normalize_arabic("احمد")
    assert normalize_arabic("مدرسة") == normalize_arabic("مدرسه")
    assert normalize_arabic("مستشفى") == normalize_arabic("مستشفي")


def test_digits_and_punctuation():
    assert normalize_arabic("فصل ٣ ثانوي") == "فصل 3 ثانوي"
    assert normalize_arabic("بيت أبو فهد - الصالة") == "بيت ابو فهد الصاله"


def test_same_item_allows_al_and_extra_words():
    assert same_item("الكاميرا القديمة", "كاميرا قديمة")
    assert same_item("جوال", "جوال أبو فهد")
    assert not same_item("لابتوب", "جوال")


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
