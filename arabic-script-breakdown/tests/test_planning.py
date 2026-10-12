"""Schedule, call times, budget summary and the HTML/CSV files. No API calls: uses the saved example breakdown."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from breakdown import plan
from breakdown.planning import (
    DAY_SHIFT,
    NIGHT_SHIFT,
    Availability,
    LocationEntry,
    Schedule,
    Settings,
    ShootDay,
    Site,
    Strip,
    budget_summary,
    build_schedule,
    call_times,
    find_entry,
    load_availability,
    load_locations,
)
from breakdown.production_docs import call_sheet_html, pages, schedule_html, write_schedule_csv
from breakdown.schema import SceneBreakdown

ROOT = Path(__file__).parent.parent
SCENES = plan.load_breakdown(ROOT / "examples" / "breakdown.jsonl")
LOCATIONS = load_locations(ROOT / "data" / "kamera_jaddi.locations.csv")
AVAILABILITY = load_availability(ROOT / "data" / "kamera_jaddi.availability.csv")
SETTINGS = Settings(start=date(2026, 11, 1))


@pytest.fixture(scope="module")
def schedule():
    return build_schedule(SCENES, LOCATIONS, AVAILABILITY, SETTINGS)


def scene(n, location, characters, time="نهار", eighths=2, **extra):
    return SceneBreakdown(scene_number=n, heading=f"مشهد {n}", int_ext="داخلي", time_of_day=time, location=location,
                          characters=characters, props=[], costume_makeup=[], vehicles=[], animals=[], extras=[],
                          sfx=[], is_flashback=False, continuous=False, length_eighths=eighths, **extra)


def test_every_scene_is_scheduled_exactly_once(schedule):
    numbers = [s.number for d in schedule.days for s in d.strips]
    assert sorted(numbers) == list(range(1, 27))
    assert schedule.unscheduled == []


def test_day_limits_hold_and_a_day_is_one_shift(schedule):
    for d in schedule.days:
        assert len(d.strips) <= SETTINGS.max_scenes
        assert d.eighths <= SETTINGS.max_eighths
        assert len(d.sites) <= SETTINGS.max_sites
        assert {s.shift for s in d.strips} == {d.shift}
        assert d.date.weekday() != 4  # Friday is the day off


def test_cast_availability_is_respected(schedule):
    for d in schedule.days:
        if d.date in (date(2026, 11, 1), date(2026, 11, 2)):
            assert "أبو فهد" not in d.cast            # busy on another show the first two days
        if "الجدة لطيفة" in d.cast:
            assert d.date in (date(2026, 11, 5), date(2026, 11, 7))  # only here two days
        if "فهد الصغير" in d.cast:
            assert d.shift == DAY_SHIFT                # child actor: day shift only


def test_scenes_at_one_site_are_kept_together(schedule):
    # The four night scenes in Fahd's room are shot on the same day.
    room_days = {d.number for d in schedule.days for s in d.strips if s.scene.location == "غرفة فهد"
                 and s.shift == NIGHT_SHIFT}
    assert len(room_days) == 1


def test_dawn_is_shot_after_night_on_the_same_day(schedule):
    for d in schedule.days:
        times = [s.scene.time_of_day for s in d.strips]
        if "فجر" in times:
            assert times.index("فجر") > max(i for i, t in enumerate(times) if t == "ليل")


def test_same_input_gives_the_same_schedule(schedule):
    again = build_schedule(SCENES, LOCATIONS, AVAILABILITY, SETTINGS)
    assert [[s.number for s in d.strips] for d in again.days] == [[s.number for s in d.strips] for d in schedule.days]


def test_most_specific_location_entry_wins():
    assert find_entry("سطح بيت أبو فهد", LOCATIONS).site.name == "فيلا التصوير"
    assert find_entry("موقف سيارات المدرسة", LOCATIONS).site.name == "مدرسة التصوير"
    assert find_entry("سيارة أبو فهد", LOCATIONS).note.startswith("السيارة")
    assert find_entry("مطار الملك خالد", LOCATIONS) is None


def test_unknown_place_and_two_sites_are_flagged_not_hidden():
    entries = [LocationEntry("البيت", Site("الفيلا")), LocationEntry("المكتب", Site("البرج"))]
    s = build_schedule([scene(1, "البيت / المكتب", ["أ"]), scene(2, "المطار", ["أ"])], entries, {},
                       Settings(start=date(2026, 11, 1)))
    flags = {st.number: st.flags for d in s.days for st in d.strips}
    assert any("أكثر من موقع" in f for f in flags[1])
    assert any("غير موجود في ملف المواقع" in f for f in flags[2])


def test_an_actor_with_no_free_date_leaves_the_scene_unscheduled_with_a_reason():
    friday = date(2026, 11, 6)
    availability = {"أ": Availability(only_on={friday})}
    s = build_schedule([scene(1, "البيت", ["أ"])], [], availability, Settings(start=date(2026, 11, 1)))
    assert s.days == []
    assert "أ" in s.unscheduled[0][1]


def test_hardest_scene_goes_first_on_its_only_free_date():
    # Two scenes compete for one day slot; the one whose actor is free only that day must get it.
    availability = {"ضيف": Availability(only_on={date(2026, 11, 1)})}
    scenes = [scene(1, "البيت", ["بطل"]), scene(2, "البرج", ["ضيف"])]
    s = build_schedule(scenes, [], availability, Settings(start=date(2026, 11, 1), max_scenes=1))
    assert [st.number for st in s.days[0].strips] == [2]


def test_budget_summary_on_the_example(schedule):
    b = budget_summary(schedule)
    assert (b.shoot_days, b.night_shifts, b.night_scenes) == (len(schedule.days), 2, 12)
    assert b.company_moves == sum(d.moves for d in schedule.days)
    assert b.actors[0].name == "فهد"                       # the lead is cast number 1
    adel = next(a for a in b.actors if a.name == "الأستاذ عادل")
    assert adel.hold_days == (adel.days[-1] - adel.days[0] + 1) - len(adel.days)
    assert "خيل عربي" in [x for _, items in b.animal_days for x in items]


def test_hold_days_count_the_gaps():
    days = [ShootDay(i, date(2026, 11, i), DAY_SHIFT, [Strip(scene(i, "البيت", cast), DAY_SHIFT, "الفيلا", "بيت", [])])
            for i, cast in ((1, ["أ"]), (2, ["ب"]), (3, ["ب"]), (4, ["أ"]))]
    b = budget_summary(Schedule(days, [], SETTINGS, {}, {}))
    assert {a.name: a.hold_days for a in b.actors} == {"أ": 2, "ب": 0}


def test_call_times_add_moves_meal_and_makeup():
    strips = [Strip(scene(n, "x", cast, eighths=8), DAY_SHIFT, site, "x", [])
              for n, cast, site in ((1, ["أ"], "الفيلا"), (2, ["ب"], "البرج"), (3, ["أ"], "البرج"))]
    ct = call_times(ShootDay(1, date(2026, 11, 1), DAY_SHIFT, strips))
    start = ct.crew_call + timedelta(hours=1)
    assert ct.scene_start[1] == start                                      # 07:00 call + 1h first setup
    assert ct.scene_start[2] == start + timedelta(minutes=45 + 120 + 60)   # scene 1 + a company move
    assert ct.meal is not None and ct.scene_start[3] > ct.meal              # meal after 6 hours
    assert ct.actor_call["أ"] == ct.scene_start[1] - timedelta(minutes=90)  # makeup and wardrobe


def test_pages_are_written_in_eighths():
    assert (pages(8), pages(11), pages(3)) == ("1", "1 3/8", "3/8")


def test_call_sheet_is_a_draft_until_someone_approves_it(schedule):
    draft = call_sheet_html(schedule, 2, "تجربة")
    assert 'dir="rtl"' in draft and "مسودة" in draft and "watermark" in draft
    assert "ممثل طفل" in draft and "تصريح تصوير" in draft and "الغروب" in draft
    approved = call_sheet_html(schedule, 2, "تجربة", approved_by="مساعد المخرج")
    assert '<div class="watermark">' not in approved and "معتمدة من: مساعد المخرج" in approved
    with pytest.raises(ValueError):
        call_sheet_html(schedule, 99, "تجربة")


def test_review_flags_reach_the_schedule_and_the_call_sheet():
    flagged = scene(1, "البيت", ["سلمان"], review_flags=["الاسم «سلمان» يطابق أكثر من شخصية"])
    s = build_schedule([flagged], [LocationEntry("البيت", Site("الفيلا"))], {}, Settings(start=date(2026, 11, 1)))
    assert "يطابق أكثر من شخصية" in schedule_html(s, "تجربة")
    assert "يطابق أكثر من شخصية" in call_sheet_html(s, 1, "تجربة")
    assert budget_summary(s).flagged_scenes == [1]


def test_schedule_csv_has_bom_and_one_row_per_scene(schedule, tmp_path):
    path = tmp_path / "schedule.csv"
    write_schedule_csv(schedule, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert len(raw.decode("utf-8-sig").strip().splitlines()) == 1 + 26


def test_plan_command_writes_all_files(tmp_path):
    assert plan.main([str(ROOT / "examples" / "breakdown.jsonl"), "--out", str(tmp_path), "--call-sheet-day", "2"]) == 0
    for name in ("schedule.html", "schedule.csv", "budget_summary.md", "cast_days.csv", "call_sheet_day_2.html"):
        assert (tmp_path / name).exists(), name
