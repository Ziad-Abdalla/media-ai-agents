"""From the breakdown to a draft shooting schedule, call times and a budget summary. Plain rules, no AI.

The schedule is a DRAFT for the assistant director to edit, not a final plan. It uses a simple
greedy method that anyone can follow by hand:

1. Every scene becomes a "strip" with a shift and a site:
   - shift: نهار and غروب are shot on a day shift; ليل and فجر on a night shift
     (a dawn scene is shot at the end of a night). One shoot day is one shift, never both.
   - site: the real place where the crew goes, taken from the locations file. Many script places are
     one site: the school corridor, the principal's office and the school gate are all "the school".
2. Strips are sorted: day shift first, then by site, then by place, then by scene number.
3. Fill the shoot days one date at a time (days off are skipped):
   a. Start the day with the strip that is hardest to place: the one with the fewest dates on which
      all its actors are free. (Like packing a bag: the awkward things go in first.) Ties go to the
      first strip in the sorted list.
   b. Keep adding strips of the same shift whose actors are free that date, best first: same place as a
      strip already in the day, then same site, then a new site (only while the day has fewer sites than
      the limit, because every new site is a company move).
   c. Stop when the day reaches its scene or page limit, or nothing else fits. Go to the next date.
4. A strip that never fits within the horizon is reported as unscheduled, with the reason.

Same inputs, same schedule, every time: there is no randomness and no model call.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from .normalize import item_key, same_place
from .schema import SceneBreakdown

DAY_SHIFT, NIGHT_SHIFT = "نهاري", "ليلي"
SHIFT_OF_TIME = {"نهار": DAY_SHIFT, "غروب": DAY_SHIFT, "ليل": NIGHT_SHIFT, "فجر": NIGHT_SHIFT}
# Order of scenes inside one day: day shift = day then sunset; night shift = night then dawn.
TIME_ORDER = {"نهار": 0, "غروب": 1, "ليل": 0, "فجر": 1}
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


# ---------- inputs: the locations file and the cast availability file ----------

@dataclass
class Site:
    name: str
    address: str = ""


@dataclass
class LocationEntry:
    script_place: str  # a place as the script writes it, or the start of it ("بيت أبو فهد")
    site: Site
    note: str = ""     # about this place, e.g. "needs a filming permit"


@dataclass
class Availability:
    unavailable: set[date] = field(default_factory=set)
    only_on: set[date] = field(default_factory=set)  # empty = no "only on" rule
    day_only: bool = False
    note: str = ""

    def free_on(self, day: date, shift: str) -> bool:
        if day in self.unavailable or (self.only_on and day not in self.only_on):
            return False
        return not (self.day_only and shift == NIGHT_SHIFT)


def _rows(path: Path) -> list[list[str]]:
    """CSV rows without the header, blank lines and comment lines (lines starting with #)."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    return [r for r in rows[1:] if r and r[0].strip() and not r[0].lstrip().startswith("#")]


def _dates(cell: str) -> set[date]:
    return {date.fromisoformat(d.strip()) for d in cell.split(";") if d.strip()}


def load_locations(path: Path) -> list[LocationEntry]:
    """Columns: script place, site, address, notes."""
    entries = []
    for row in _rows(path):
        row = row + [""] * (4 - len(row))
        entries.append(LocationEntry(row[0].strip(), Site(row[1].strip(), row[2].strip()), row[3].strip()))
    return entries


def load_availability(path: Path) -> dict[str, Availability]:
    """Columns: character, unavailable dates, only-available dates, day only (نعم), notes."""
    result = {}
    for row in _rows(path):
        row = row + [""] * (5 - len(row))
        result[row[0].strip()] = Availability(_dates(row[1]), _dates(row[2]), row[3].strip() == "نعم",
                                              row[4].strip())
    return result


def find_entry(place: str, entries: list[LocationEntry]) -> LocationEntry | None:
    """The locations-file entry for one script place. The entry with the most matching words wins:
    "سطح بيت أبو فهد" matches the entry "بيت أبو فهد"."""
    hits = [e for e in entries if same_place(place, e.script_place)]
    if not hits:
        return None
    return max(hits, key=lambda e: len(item_key(e.script_place).split()))


# ---------- the schedule ----------

@dataclass(eq=False)  # two strips are the same only if they are the same object
class Strip:
    scene: SceneBreakdown
    shift: str
    site: str           # site name; several sites joined with " + " if one scene needs two
    place_key: str      # normalized script place, to group the same set together
    flags: list[str]    # things a person must check (unknown location, review flags from extraction)
    place_notes: list[str] = field(default_factory=list)  # notes from the locations file

    @property
    def number(self) -> int:
        return self.scene.scene_number


@dataclass
class ShootDay:
    number: int
    date: date
    shift: str
    strips: list[Strip]

    @property
    def sites(self) -> list[str]:
        return list(dict.fromkeys(s.site for s in self.strips))

    @property
    def moves(self) -> int:
        """Company moves: how many times the crew changes site during the day, in shooting order."""
        return sum(a.site != b.site for a, b in pairwise(self.strips))

    @property
    def eighths(self) -> int:
        return sum(s.scene.length_eighths for s in self.strips)

    @property
    def cast(self) -> list[str]:
        return list(dict.fromkeys(c for s in self.strips for c in s.scene.characters))


@dataclass
class Settings:
    start: date
    days_off: set[int] = field(default_factory=lambda: {WEEKDAYS["fri"]})
    max_scenes: int = 6
    max_eighths: int = 24          # 3 pages
    max_sites: int = 2             # at most one company move per day
    horizon_days: int = 60         # stop looking for dates after this


@dataclass
class Schedule:
    days: list[ShootDay]
    unscheduled: list[tuple[Strip, str]]
    settings: Settings
    sites: dict[str, Site]
    availability: dict[str, Availability]


def make_strips(scenes: list[SceneBreakdown], entries: list[LocationEntry]) -> tuple[list[Strip], dict[str, Site]]:
    strips, sites = [], {}
    for s in scenes:
        flags, notes, found = list(s.review_flags), [], []
        for part in s.location.split("/"):
            entry = find_entry(part, entries)
            if entry is None:
                site = Site(part.strip())
                flags.append(f"المكان «{part.strip()}» غير موجود في ملف المواقع")
            else:
                site = entry.site
                if entry.note:
                    notes.append(f"{entry.script_place}: {entry.note}")
            sites.setdefault(site.name, site)
            found.append(site.name)
        found = list(dict.fromkeys(found))
        if len(found) > 1:
            flags.append("المشهد في أكثر من موقع: يُصوَّر على جزأين")
        strips.append(Strip(s, SHIFT_OF_TIME[s.time_of_day], " + ".join(found), item_key(s.location), flags, notes))
    order = [DAY_SHIFT, NIGHT_SHIFT]
    strips.sort(key=lambda t: (order.index(t.shift), t.site, t.place_key, t.number))
    return strips, sites


def working_dates(settings: Settings) -> list[date]:
    days = (settings.start + timedelta(days=i) for i in range(settings.horizon_days))
    return [d for d in days if d.weekday() not in settings.days_off]


def cast_free(strip: Strip, day: date, availability: dict[str, Availability]) -> bool:
    return all(availability[c].free_on(day, strip.shift) for c in strip.scene.characters if c in availability)


def build_schedule(scenes: list[SceneBreakdown], entries: list[LocationEntry],
                   availability: dict[str, Availability], settings: Settings) -> Schedule:
    strips, sites = make_strips(scenes, entries)
    dates = working_dates(settings)
    rank = {s: i for i, s in enumerate(strips)}
    # How many dates each strip could go on. Fewest options = place it first.
    options = {s: sum(cast_free(s, d, availability) for d in dates) for s in strips}

    remaining = list(strips)
    days: list[ShootDay] = []
    for day in dates:
        if not remaining:
            break
        free = [s for s in remaining if cast_free(s, day, availability)]
        if not free:
            continue
        anchor = min(free, key=lambda s: (options[s], rank[s]))
        chosen = [anchor]
        while len(chosen) < settings.max_scenes:
            nxt = _best_next(chosen, free, settings)
            if nxt is None:
                break
            chosen.append(nxt)
        # Shooting order: by time of day (dawn after night, sunset after day), then by site so the
        # crew stays put, then by scene number.
        site_order = list(dict.fromkeys(s.site for s in chosen))
        chosen.sort(key=lambda s: (TIME_ORDER[s.scene.time_of_day], site_order.index(s.site), s.place_key, s.number))
        days.append(ShootDay(len(days) + 1, day, anchor.shift, chosen))
        remaining = [s for s in remaining if s not in chosen]

    unscheduled = [(s, _why_not(s, dates, availability)) for s in remaining]
    return Schedule(days, unscheduled, settings, sites, availability)


def _best_next(chosen: list[Strip], free: list[Strip], settings: Settings) -> Strip | None:
    places = {s.place_key for s in chosen}
    sites = {s.site for s in chosen}
    eighths = sum(s.scene.length_eighths for s in chosen)
    candidates = []
    for s in free:
        if s in chosen or s.shift != chosen[0].shift:
            continue
        if eighths + s.scene.length_eighths > settings.max_eighths:
            continue
        if s.site not in sites and len(sites) >= settings.max_sites:
            continue
        preference = 0 if s.place_key in places else 1 if s.site in sites else 2
        candidates.append((preference, free.index(s), s))
    return min(candidates, key=lambda c: c[:2])[2] if candidates else None


def _why_not(strip: Strip, dates: list[date], availability: dict[str, Availability]) -> str:
    if not any(cast_free(strip, d, availability) for d in dates):
        blocked = [c for c in strip.scene.characters
                   if c in availability and not any(availability[c].free_on(d, strip.shift) for d in dates)]
        return "لا يوجد يوم يتوفر فيه: " + "، ".join(blocked or strip.scene.characters)
    return "أيام التوفر امتلأت بمشاهد أخرى: عدّل الحدود أو رتّب يدوياً"


# ---------- call times for one day ----------

@dataclass
class CallTimes:
    crew_call: datetime
    scene_start: dict[int, datetime]   # scene number -> estimated start
    actor_call: dict[str, datetime]    # actor -> call time (before their first scene, for makeup)
    meal: datetime | None              # start of the meal break
    wrap: datetime


@dataclass
class TimeRules:
    """Plain, editable estimates. Change them to match the unit's real pace."""
    day_crew_call: str = "07:00"
    night_crew_call: str = "16:00"
    first_setup_minutes: int = 60    # from crew call to the first shot
    scene_setup_minutes: int = 45    # lighting and blocking for each scene
    minutes_per_eighth: int = 15     # shooting time: about 2 hours per page
    move_minutes: int = 60           # one company move
    meal_after_hours: int = 6        # meal break once this many hours have passed since crew call
    meal_minutes: int = 60
    actor_prep_minutes: int = 90     # makeup and wardrobe before the actor's first scene


def call_times(day: ShootDay, rules: TimeRules | None = None) -> CallTimes:
    rules = rules or TimeRules()
    call = rules.day_crew_call if day.shift == DAY_SHIFT else rules.night_crew_call
    crew_call = datetime.combine(day.date, datetime.strptime(call, "%H:%M").time())
    t = crew_call + timedelta(minutes=rules.first_setup_minutes)
    meal = None
    starts: dict[int, datetime] = {}
    for i, strip in enumerate(day.strips):
        if i and strip.site != day.strips[i - 1].site:
            t += timedelta(minutes=rules.move_minutes)
        if meal is None and t >= crew_call + timedelta(hours=rules.meal_after_hours):
            meal, t = t, t + timedelta(minutes=rules.meal_minutes)
        starts[strip.number] = t
        t += timedelta(minutes=rules.scene_setup_minutes + strip.scene.length_eighths * rules.minutes_per_eighth)
    actors: dict[str, datetime] = {}
    for strip in day.strips:
        for name in strip.scene.characters:
            actors.setdefault(name, starts[strip.number] - timedelta(minutes=rules.actor_prep_minutes))
    return CallTimes(crew_call, starts, dict(sorted(actors.items(), key=lambda kv: kv[1])), meal, t)


# ---------- the budget summary ----------

@dataclass
class ActorDays:
    name: str
    days: list[int]          # shoot-day numbers worked
    hold_days: int           # shoot days between the first and last work day with no scene for this actor


@dataclass
class BudgetSummary:
    shoot_days: int
    day_shifts: int
    night_shifts: int
    night_scenes: int
    company_moves: int
    night_to_day_turnarounds: int    # a day shift right after a night shift: crew rest needs checking
    site_days: dict[str, int]
    actors: list[ActorDays]
    extras_days: list[tuple[int, list[str]]]
    vehicle_days: list[tuple[int, list[str]]]
    animal_days: list[tuple[int, list[str]]]
    unscheduled: int
    flagged_scenes: list[int]


def budget_summary(schedule: Schedule) -> BudgetSummary:
    days = schedule.days
    worked: dict[str, list[int]] = defaultdict(list)
    scene_count: dict[str, int] = defaultdict(int)
    site_days: dict[str, int] = defaultdict(int)
    for d in days:
        for name in d.cast:
            worked[name].append(d.number)
        for strip in d.strips:
            for name in strip.scene.characters:
                scene_count[name] += 1
        for site in d.sites:
            site_days[site] += 1
    actors = [ActorDays(n, ds, (ds[-1] - ds[0] + 1) - len(ds)) for n, ds in worked.items()]
    # Most shoot days first, then most scenes: the lead gets cast number 1.
    actors.sort(key=lambda a: (-len(a.days), -scene_count[a.name], a.name))

    def per_day(attr: str) -> list[tuple[int, list[str]]]:
        out = []
        for d in days:
            items = list(dict.fromkeys(x for s in d.strips for x in getattr(s.scene, attr)))
            if items:
                out.append((d.number, items))
        return out

    return BudgetSummary(
        shoot_days=len(days),
        day_shifts=sum(d.shift == DAY_SHIFT for d in days),
        night_shifts=sum(d.shift == NIGHT_SHIFT for d in days),
        night_scenes=sum(s.shift == NIGHT_SHIFT for d in days for s in d.strips),
        company_moves=sum(d.moves for d in days),
        night_to_day_turnarounds=sum(a.shift == NIGHT_SHIFT and b.shift == DAY_SHIFT for a, b in pairwise(days)),
        site_days=dict(sorted(site_days.items(), key=lambda kv: -kv[1])),
        actors=actors,
        extras_days=per_day("extras"),
        vehicle_days=per_day("vehicles"),
        animal_days=per_day("animals"),
        unscheduled=len(schedule.unscheduled),
        flagged_scenes=sorted(s.number for d in days for s in d.strips if s.flags),
    )
