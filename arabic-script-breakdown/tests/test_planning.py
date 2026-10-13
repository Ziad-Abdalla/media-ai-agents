"""Schedule, call times, budget summary and the HTML/CSV files. No API calls: uses the saved example breakdown."""

import json
from datetime import date, timedelta
from itertools import combinations
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
    TimeRules,
    budget_summary,
    build_schedule,
    call_times,
    find_entry,
    is_light,
    load_availability,
    load_locations,
    strip_free,
)
from breakdown.production_docs import (
    Approval,
    call_sheet_html,
    open_problems,
    pages,
    schedule_html,
    write_schedule_csv,
)
from breakdown.schema import SceneBreakdown

ROOT = Path(__file__).parent.parent
SCENES = plan.load_breakdown(ROOT / "examples" / "breakdown.jsonl")
LOCATIONS = load_locations(ROOT / "data" / "kamera_jaddi.locations.csv")
AVAILABILITY = load_availability(ROOT / "data" / "kamera_jaddi.availability.csv")
SETTINGS = Settings(start=date(2026, 10, 31))   # a Saturday: the example week runs Saturday to Thursday
SATURDAY = 5
RULES = TimeRules()


@pytest.fixture(scope="module")
def schedule():
    return build_schedule(SCENES, LOCATIONS, AVAILABILITY, SETTINGS)


def scene(n, location, characters, time="نهار", eighths=2, int_ext="داخلي", **extra):
    return SceneBreakdown(scene_number=n, heading=f"مشهد {n}", int_ext=int_ext, time_of_day=time, location=location,
                          characters=characters, props=[], costume_makeup=[], vehicles=[], animals=[], extras=[],
                          sfx=[], is_flashback=False, continuous=False, length_eighths=eighths, **extra)


def strip(n, site, cast=("أ",), time="نهار", eighths=2, int_ext="داخلي"):
    shift = DAY_SHIFT if time in ("نهار", "غروب") else NIGHT_SHIFT
    return Strip(scene(n, site, list(cast), time, eighths, int_ext), shift, site, site, [])


def minutes(rules, eighths):
    return rules.scene_setup_minutes + eighths * rules.minutes_per_eighth


# ---------- the schedule on the example ----------

def test_every_scene_is_scheduled_exactly_once(schedule):
    numbers = [s.number for d in schedule.days for s in d.strips]
    assert sorted(numbers) == list(range(1, 27))
    assert schedule.unscheduled == []


def test_day_limits_hold_and_a_day_is_one_shift(schedule):
    for d in schedule.days:
        assert len(d.strips) <= SETTINGS.max_scenes
        assert d.eighths <= SETTINGS.max_eighths
        assert len(d.sites) <= SETTINGS.max_sites + 1   # +1 only when two light days were joined
        assert {s.shift for s in d.strips} == {d.shift}
        assert d.date.weekday() != 4  # Friday is the day off


def test_cast_availability_is_respected(schedule):
    for d in schedule.days:
        if d.date in (date(2026, 11, 1), date(2026, 11, 2)):
            assert "أبو فهد" not in d.cast            # busy on another show these two days
        if "الجدة لطيفة" in d.cast:
            assert d.date in (date(2026, 11, 5), date(2026, 11, 7))  # only here two days
        if "الجد عبدالله" in d.cast:
            assert d.date != date(2026, 11, 1)


def test_school_day_scenes_are_only_on_saturday(schedule):
    # The locations file says: no filming in school hours, so a day shift at the school only on Saturday.
    school = [(d, s) for d in schedule.days for s in d.strips if s.site == "مدرسة التصوير"]
    assert school
    for d, s in school:
        if s.shift == DAY_SHIFT:
            assert d.date.weekday() == SATURDAY, s.number


def test_locations_file_reads_the_weekday_columns():
    school = find_entry("مكتب المدير", LOCATIONS).site
    assert school.day_weekdays == {SATURDAY} and school.night_weekdays == set()
    assert school is find_entry("ثانوية الأفق", LOCATIONS).site          # one Site object per site name
    assert school.open_on(date(2026, 10, 31), DAY_SHIFT) and not school.open_on(date(2026, 11, 1), DAY_SHIFT)
    assert school.open_on(date(2026, 11, 1), NIGHT_SHIFT)


def test_night_scenes_in_fahds_room_are_kept_together(schedule):
    room_days = {d.number for d in schedule.days for s in d.strips
                 if s.scene.location == "غرفة فهد" and s.scene.time_of_day == "ليل"}
    assert len(room_days) == 1


def test_dawn_is_shot_after_night_on_the_same_day(schedule):
    for d in schedule.days:
        times = [s.scene.time_of_day for s in d.strips]
        if "فجر" in times:
            assert times.index("فجر") > max(i for i, t in enumerate(times) if t == "ليل")


def test_same_input_gives_the_same_schedule(schedule):
    again = build_schedule(SCENES, LOCATIONS, AVAILABILITY, SETTINGS)
    assert [[s.number for s in d.strips] for d in again.days] == [[s.number for s in d.strips] for d in schedule.days]


def test_no_two_light_days_of_one_shift_could_still_be_joined(schedule):
    for a, b in combinations(schedule.days, 2):
        if a.shift != b.shift or not (is_light(a, SETTINGS) and is_light(b, SETTINGS)):
            continue
        strips = a.strips + b.strips
        fits = (len(strips) <= SETTINGS.max_scenes and a.eighths + b.eighths <= SETTINGS.max_eighths
                and len({s.site for s in strips}) <= SETTINGS.max_sites + 1)
        free = any(all(strip_free(s, d, AVAILABILITY) for s in strips) for d in (a.date, b.date))
        assert not (fits and free), (a.number, b.number)


# ---------- the schedule rules, one at a time ----------

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


def test_a_day_only_actor_is_never_put_on_a_night_shift():
    # The child actor rule: a night scene with a day-only actor is not scheduled, and the reason names him.
    availability = {"طفل": Availability(day_only=True)}
    scenes = [scene(1, "البيت", ["طفل"], time="ليل"), scene(2, "البيت", ["طفل"], time="نهار")]
    s = build_schedule(scenes, [], availability, Settings(start=date(2026, 11, 1)))
    assert [(d.shift, [st.number for st in d.strips]) for d in s.days] == [(DAY_SHIFT, [2])]
    assert [st.number for st, _ in s.unscheduled] == [1]
    assert "طفل" in s.unscheduled[0][1]


def test_a_closed_site_is_named_as_the_reason():
    school = Site("المدرسة", day_weekdays={SATURDAY})
    s = build_schedule([scene(1, "المدرسة", ["أ"])], [LocationEntry("المدرسة", school)], {},
                       Settings(start=date(2026, 11, 1), horizon_days=5))   # Sunday to Thursday: no Saturday
    assert s.days == [] and "المدرسة" in s.unscheduled[0][1]


def test_availability_names_are_matched_with_the_spelling_rules():
    # "ابو  فهد" (no hamza, two spaces) is still أبو فهد, so his blocked date still holds.
    sunday = date(2026, 11, 1)
    availability = {"ابو  فهد": Availability(unavailable={sunday})}
    s = build_schedule([scene(1, "البيت", ["أبو فهد"])], [], availability, Settings(start=sunday))
    assert s.days[0].date != sunday and s.unknown_availability == []


def test_an_availability_name_that_matches_no_character_is_reported():
    s = build_schedule([scene(1, "البيت", ["أبو فهد"])], [], {"أبو فهدد": Availability()},
                       Settings(start=date(2026, 11, 1)))
    assert s.unknown_availability == ["أبو فهدد"]


def test_a_flagged_name_says_its_availability_was_not_checked():
    flagged = scene(1, "البيت", ["سلمان"], review_flags=["الاسم «سلمان» يطابق أكثر من شخصية"])
    s = build_schedule([flagged], [], {}, Settings(start=date(2026, 11, 1)))
    assert any("لم يُفحص توفر «سلمان»" in f for f in s.days[0].strips[0].flags)


def test_hardest_scene_goes_first_on_its_only_free_date():
    # Two scenes compete for one day slot; the one whose actor is free only that day must get it.
    availability = {"ضيف": Availability(only_on={date(2026, 11, 1)})}
    scenes = [scene(1, "البيت", ["بطل"]), scene(2, "البرج", ["ضيف"])]
    s = build_schedule(scenes, [], availability, Settings(start=date(2026, 11, 1), max_scenes=1))
    assert [st.number for st in s.days[0].strips] == [2]


def test_a_new_site_is_the_one_that_fills_the_day():
    # The day starts at site أ. ب sorts first but has one scene; ت has three. The company move goes to ت.
    scenes = [scene(1, "أ", ["س"], eighths=4), scene(2, "ب", ["س"], eighths=4)]
    scenes += [scene(n, "ت", ["س"], eighths=4) for n in (3, 4, 5)]
    s = build_schedule(scenes, [], {}, Settings(start=date(2026, 11, 1)))
    assert s.days[0].sites == ["أ", "ت"]
    assert [st.number for st in s.days[0].strips] == [1, 3, 4, 5]


def test_two_light_days_are_joined_into_one():
    # Three short scenes at three sites: the first pass makes two light days; the second pass joins them,
    # paying one extra company move instead of a whole crew day.
    scenes = [scene(1, "أ", ["س"], eighths=1), scene(2, "ب", ["س"], eighths=1), scene(3, "ت", ["س"], eighths=1)]
    s = build_schedule(scenes, [], {}, Settings(start=date(2026, 11, 1)))
    assert len(s.days) == 1 and len(s.days[0].sites) == 3


def test_light_days_are_not_joined_when_an_actor_is_free_on_neither_date():
    availability = {"ص": Availability(only_on={date(2026, 11, 2)}), "س": Availability(unavailable={date(2026, 11, 2)})}
    scenes = [scene(1, "أ", ["س"], eighths=1), scene(2, "ب", ["ص"], eighths=1)]
    s = build_schedule(scenes, [], availability, Settings(start=date(2026, 11, 1)))
    assert len(s.days) == 2


# ---------- call times and the real light ----------

def test_call_times_add_moves_meal_and_makeup():
    strips = [Strip(scene(n, "x", cast, eighths=8), DAY_SHIFT, site, "x", [])
              for n, cast, site in ((1, ["أ"], "الفيلا"), (2, ["ب"], "البرج"), (3, ["أ"], "البرج"))]
    ct = call_times(ShootDay(1, date(2026, 11, 1), DAY_SHIFT, strips))
    start = ct.crew_call + timedelta(hours=1)
    assert ct.crew_call.strftime("%H:%M") == "07:00"
    assert ct.scene_start[1] == start                                      # 07:00 call + 1h first setup
    assert ct.scene_start[2] == start + timedelta(minutes=45 + 120 + 60)   # scene 1 + a company move
    assert ct.meal is not None and ct.scene_start[3] > ct.meal              # meal after 6 hours
    assert ct.actor_call["أ"] == ct.scene_start[1] - timedelta(minutes=90)  # makeup and wardrobe


def test_light_bound_scenes_are_shot_in_the_real_light_on_every_example_day(schedule):
    window = timedelta(minutes=RULES.light_window_minutes)
    for d in schedule.days:
        ct = call_times(d, RULES)
        assert ct.warnings == [], (d.number, ct.warnings)
        for s in d.strips:
            start = ct.scene_start[s.number]
            end = start + timedelta(minutes=minutes(RULES, s.scene.length_eighths))
            if s.scene.time_of_day == "غروب":
                assert ct.sunset - window <= start and end <= ct.sunset, s.number
            elif s.scene.time_of_day == "فجر":
                assert ct.sunrise - window <= start and end <= ct.sunrise, s.number
            elif s.scene.time_of_day == "ليل":
                assert start >= ct.sunset + timedelta(minutes=RULES.dark_after_sunset_minutes), s.number


def test_sunset_scene_ends_at_sunset_and_the_crew_is_called_later_instead_of_waiting():
    day = ShootDay(1, date(2026, 11, 2), DAY_SHIFT,
                   [strip(1, "الفيلا", eighths=2), strip(2, "الدرعية", time="غروب", eighths=1, int_ext="خارجي")])
    ct = call_times(day, RULES)
    sunset = ct.sunset
    assert sunset.strftime("%H:%M") == "17:07"                           # the Riyadh table for November
    assert ct.scene_start[2] + timedelta(minutes=minutes(RULES, 1)) == sunset
    assert ct.crew_call.hour > 7 and ct.wrap == sunset and ct.light == {2: "الغروب"}


def test_dawn_scene_ends_at_the_next_sunrise_and_night_starts_after_dark():
    day = ShootDay(1, date(2026, 11, 3), NIGHT_SHIFT, [strip(1, "الفيلا", time="ليل", eighths=1),
                                                       strip(2, "الفيلا", time="فجر", eighths=1)])
    ct = call_times(day, RULES)
    assert ct.sunrise.date() == date(2026, 11, 4) and ct.wrap == ct.sunrise
    assert ct.scene_start[2] + timedelta(minutes=minutes(RULES, 1)) == ct.sunrise
    night_only = call_times(ShootDay(1, date(2026, 11, 3), NIGHT_SHIFT, [strip(1, "الفيلا", time="ليل")]), RULES)
    assert night_only.scene_start[1] >= night_only.sunset + timedelta(minutes=RULES.dark_after_sunset_minutes)


def test_a_crew_call_moved_later_for_the_sunset_still_gets_a_meal(schedule):
    # Example day 2: two day scenes, then the sunset scene at Diriyah. Without the meal the crew would be
    # called at 10:50 and work to 17:07 (6h17) with no break. The meal is added and the call moves earlier.
    ct = call_times(schedule.day(2), RULES)
    assert ct.meal is not None
    assert ct.meal - ct.crew_call <= timedelta(hours=RULES.meal_after_hours)
    assert ct.scene_start[17].strftime("%H:%M") == "16:07" and ct.wrap.strftime("%H:%M") == "17:07"
    for d in schedule.days:   # and no example day runs past the meal rule without a meal
        times = call_times(d, RULES)
        if times.wrap - times.crew_call > timedelta(hours=RULES.meal_after_hours):
            assert times.meal is not None, d.number


def test_sunrise_and_sunset_can_be_set_by_hand():
    day = ShootDay(1, date(2026, 11, 2), DAY_SHIFT, [strip(1, "الدرعية", time="غروب", eighths=1)])
    ct = call_times(day, TimeRules(sunset="17:30"))
    assert ct.scene_start[1].strftime("%H:%M") == "16:30"


def test_too_much_work_before_sunset_is_a_problem_not_a_wrong_time():
    strips = [strip(n, "الفيلا", eighths=8, int_ext="خارجي") for n in (1, 2, 3)]
    strips.append(strip(4, "الفيلا", time="غروب", eighths=1, int_ext="خارجي"))
    day = ShootDay(1, date(2026, 11, 2), DAY_SHIFT, strips)
    warnings = call_times(day, RULES).warnings
    assert any("لا يكفي الوقت قبل الغروب" in w for w in warnings)
    assert any("ينتهي بعد الغروب" in w for w in warnings)
    assert open_problems(day, RULES) == warnings     # no review flags, so the problems are the time warnings


# ---------- budget summary ----------

def test_budget_summary_on_the_example(schedule):
    b = budget_summary(schedule)
    assert (b.shoot_days, b.night_shifts) == (len(schedule.days), 2)
    assert (b.night_scenes, b.dawn_scenes, b.sunset_scenes) == (10, 2, 1)   # ليل, فجر and غروب counted apart
    assert b.company_moves == sum(d.moves for d in schedule.days)
    assert b.actors[0].name == "فهد"                       # the lead is cast number 1
    assert "خيل عربي" in [x for _, items in b.animal_days for x in items]


def test_hold_days_and_idle_dates_are_counted_on_the_calendar(schedule):
    # The example shoots 31 Oct, 2, 3, 5 and 7 Nov: 1 and 4 Nov are working dates with no shooting.
    b = budget_summary(schedule)
    assert [d.date for d in schedule.days] == [date(2026, 10, 31), date(2026, 11, 2), date(2026, 11, 3),
                                               date(2026, 11, 5), date(2026, 11, 7)]
    assert (b.first_date, b.last_date) == (date(2026, 10, 31), date(2026, 11, 7))
    assert b.idle_dates == [date(2026, 11, 1), date(2026, 11, 4)]
    adel = next(a for a in b.actors if a.name == "الأستاذ عادل")
    # Shoot days 1, 4, 5 = 31 Oct, 5 Nov, 7 Nov. He waits through 1, 2, 3 and 4 Nov (6 Nov is Friday, off).
    assert adel.days == [1, 4, 5] and adel.hold_days == 4


def test_hold_days_count_the_gaps():
    days = [ShootDay(i, date(2026, 11, i), DAY_SHIFT, [Strip(scene(i, "البيت", cast), DAY_SHIFT, "الفيلا", "بيت", [])])
            for i, cast in ((1, ["أ"]), (2, ["ب"]), (3, ["ب"]), (4, ["أ"]))]
    b = budget_summary(Schedule(days, [], SETTINGS, {}, {}))
    assert {a.name: a.hold_days for a in b.actors} == {"أ": 2, "ب": 0}


def test_a_turnaround_is_counted_only_on_consecutive_dates():
    def day(n, d, shift):
        return ShootDay(n, d, shift, [strip(n, "x", time="ليل" if shift == NIGHT_SHIFT else "نهار")])
    thursday_night_then_saturday = [day(1, date(2026, 11, 5), NIGHT_SHIFT), day(2, date(2026, 11, 7), DAY_SHIFT)]
    monday_night_then_tuesday = [day(1, date(2026, 11, 2), NIGHT_SHIFT), day(2, date(2026, 11, 3), DAY_SHIFT)]
    assert budget_summary(Schedule(thursday_night_then_saturday, [], SETTINGS, {}, {})).night_to_day_turnarounds == 0
    assert budget_summary(Schedule(monday_night_then_tuesday, [], SETTINGS, {}, {})).night_to_day_turnarounds == 1


# ---------- the files ----------

def test_pages_are_written_in_eighths():
    assert (pages(8), pages(11), pages(3)) == ("1", "1 3/8", "3/8")


def test_call_sheet_is_a_draft_until_someone_approves_it(schedule):
    draft = call_sheet_html(schedule, 2, "تجربة")
    assert 'dir="rtl"' in draft and "مسودة" in draft and "watermark" in draft
    assert "ممثل طفل" in draft and "تصريح تصوير" in draft and "ضوء الغروب" in draft and "17:07" in draft
    approved = call_sheet_html(schedule, 2, "تجربة", Approval("مساعد المخرج"))
    assert '<div class="watermark">' not in approved and "معتمدة من: مساعد المخرج" in approved
    with pytest.raises(ValueError):
        call_sheet_html(schedule, 99, "تجربة")


def flagged_schedule():
    flagged = scene(1, "البيت", ["سلمان"], review_flags=["الاسم «سلمان» يطابق أكثر من شخصية"])
    return build_schedule([flagged], [LocationEntry("البيت", Site("الفيلا"))], {}, Settings(start=date(2026, 11, 1)))


def test_review_flags_reach_the_schedule_and_the_call_sheet():
    s = flagged_schedule()
    assert "يطابق أكثر من شخصية" in schedule_html(s, "تجربة")
    assert "يطابق أكثر من شخصية" in call_sheet_html(s, 1, "تجربة")
    assert budget_summary(s).flagged_scenes == [1]


def test_a_call_sheet_with_an_open_flag_cannot_be_approved_without_an_override():
    s = flagged_schedule()
    with pytest.raises(ValueError):
        call_sheet_html(s, 1, "تجربة", Approval("مساعد المخرج"))
    approved = call_sheet_html(s, 1, "تجربة", Approval("مساعد المخرج", override=True))
    assert "اعتُمدت مع تجاوز 2 مشكلة" in approved and "يطابق أكثر من شخصية" in approved


def test_schedule_csv_has_bom_and_one_row_per_scene(schedule, tmp_path):
    path = tmp_path / "schedule.csv"
    write_schedule_csv(schedule, path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert len(raw.decode("utf-8-sig").strip().splitlines()) == 1 + 26


# ---------- the command ----------

def test_plan_command_writes_all_files(tmp_path):
    assert plan.main([str(ROOT / "examples" / "breakdown.jsonl"), "--out", str(tmp_path), "--call-sheet-day", "2,3"]) == 0
    for name in ("schedule.html", "schedule.csv", "budget_summary.md", "cast_days.csv", "call_sheet_day_2.html",
                 "call_sheet_day_3.html"):
        assert (tmp_path / name).exists(), name
    assert not (tmp_path / "approvals.csv").exists()


def test_a_wrong_call_sheet_day_stops_before_any_file_is_written(tmp_path):
    out = tmp_path / "plan"
    assert plan.main([str(ROOT / "examples" / "breakdown.jsonl"), "--out", str(out), "--call-sheet-day", "99"]) == 2
    assert not out.exists()


def test_a_real_script_must_bring_its_own_locations_and_availability(tmp_path):
    own = tmp_path / "breakdown.jsonl"
    own.write_bytes((ROOT / "examples" / "breakdown.jsonl").read_bytes())
    assert plan.main([str(own), "--out", str(tmp_path / "plan")]) == 2
    assert plan.main([str(own), "--out", str(tmp_path / "plan"), "--locations", str(ROOT / "data" / "kamera_jaddi.locations.csv"),
                      "--availability", str(ROOT / "data" / "kamera_jaddi.availability.csv")]) == 0


def test_a_typo_in_the_availability_file_stops_the_plan(tmp_path, capsys):
    av = (ROOT / "data" / "kamera_jaddi.availability.csv").read_text(encoding="utf-8-sig")
    (tmp_path / "av.csv").write_text(av.replace("الجد عبدالله", "الجد عبداللة"), encoding="utf-8")   # ة: still him
    (tmp_path / "typo.csv").write_text(av.replace("الجد عبدالله", "الجد عبدالرحمن"), encoding="utf-8")
    common = [str(ROOT / "examples" / "breakdown.jsonl"), "--locations", str(ROOT / "data" / "kamera_jaddi.locations.csv")]
    assert plan.main([*common, "--availability", str(tmp_path / "av.csv"), "--out", str(tmp_path / "ok")]) == 0
    assert plan.main([*common, "--availability", str(tmp_path / "typo.csv"), "--out", str(tmp_path / "no")]) == 2
    assert "الجد عبدالرحمن" in capsys.readouterr().out and not (tmp_path / "no").exists()


def test_approval_is_refused_on_open_problems_and_logged_when_overridden(tmp_path):
    bd = tmp_path / "breakdown.jsonl"
    flagged = scene(1, "البيت", ["سلمان"], review_flags=["الاسم «سلمان» يطابق أكثر من شخصية"])
    bd.write_text(json.dumps(flagged.model_dump(), ensure_ascii=False) + "\n", encoding="utf-8")
    (tmp_path / "loc.csv").write_text("المكان,الموقع,العنوان,ملاحظات\nالبيت,الفيلا,,\n", encoding="utf-8")
    (tmp_path / "av.csv").write_text("الشخصية,غير متاح في,متاح فقط في,نهار فقط,ملاحظات\n", encoding="utf-8")
    common = [str(bd), "--locations", str(tmp_path / "loc.csv"), "--availability", str(tmp_path / "av.csv"),
              "--approved-by", "مساعد المخرج"]
    assert plan.main([*common, "--out", str(tmp_path / "refused")]) == 3
    assert not (tmp_path / "refused").exists()
    assert plan.main([*common, "--out", str(tmp_path / "ok"), "--override-problems"]) == 0
    log = (tmp_path / "ok" / "approvals.csv").read_text(encoding="utf-8-sig")
    assert "مساعد المخرج" in log and "سلمان" in log
