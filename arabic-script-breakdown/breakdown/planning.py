"""From the breakdown to a draft shooting schedule, call times and a budget summary. Plain rules, no AI.

The schedule is a DRAFT for the assistant director to edit, not a final plan. It uses a simple
greedy method that anyone can follow by hand:

1. Every scene becomes a "strip" with a shift and a site:
   - shift: نهار and غروب are shot on a day shift; ليل and فجر on a night shift
     (a dawn scene is shot at the end of a night). One shoot day is one shift, never both.
   - site: the real place where the crew goes, taken from the locations file. Many script places are
     one site: the school corridor, the principal's office and the school gate are all "the school".
   A strip is "free" on a date when all its actors are free and all its sites are open on that weekday
   for that shift (in the example the school can be used by day only on Saturday, when there are no students).
2. Strips are sorted: day shift first, then by site, then by place, then by scene number.
3. Fill the shoot days one date at a time (days off are skipped):
   a. Start the day with the strip that is hardest to place: the one with the fewest free dates.
      (Like packing a bag: the awkward things go in first.) Ties go to the first strip in the sorted list.
   b. Keep adding strips of the same shift that are free that date, best first: same place as a
      strip already in the day, then same site, then a new site (only while the day has fewer sites than
      the limit, because every new site is a company move). Among new sites, the one with the most
      scenes waiting that date wins, so the company move is spent on a site that fills the day.
   c. Stop when the day reaches its scene or page limit, or nothing else fits. Go to the next date.
4. Second pass: two light days (under half the page limit) of the same shift are joined into one if the
   limits allow, even at the cost of one extra company move, because a crew day costs far more than a move.
5. A strip that never fits within the horizon is reported as unscheduled, with the reason.

The availability file is matched to the breakdown's character names with the same spelling rules as the
rest of the tool ("ابو  فهد" is أبو فهد). A name in that file that matches no character is kept as
unknown, and the plan command refuses to go on: a typo must never silently drop an actor's blocked date.

Same inputs, same schedule, every time: there is no randomness and no model call.
"""

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import combinations, pairwise
from pathlib import Path

from .normalize import item_key, normalize_arabic, same_place
from .schema import SceneBreakdown

DAY_SHIFT, NIGHT_SHIFT = "نهاري", "ليلي"
SHIFT_OF_TIME = {"نهار": DAY_SHIFT, "غروب": DAY_SHIFT, "ليل": NIGHT_SHIFT, "فجر": NIGHT_SHIFT}
# Order of scenes inside one day: day shift = day then sunset; night shift = night then dawn.
TIME_ORDER = {"نهار": 0, "غروب": 1, "ليل": 0, "فجر": 1}
LIGHT_TIMES = {"غروب": "الغروب", "فجر": "الفجر"}  # scenes that must be shot in the real light
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
WEEKDAY_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

# Sunrise and sunset in Riyadh on the 15th of each month, local time (standard sun-position formula,
# rounded). Within about 10 minutes for the whole month. To shoot elsewhere, or to use the exact
# minute for one date, pass --sunrise and --sunset.
RIYADH_SUN = {1: ("06:39", "17:25"), 2: ("06:28", "17:47"), 3: ("06:04", "18:02"), 4: ("05:32", "18:15"),
              5: ("05:10", "18:29"), 6: ("05:04", "18:43"), 7: ("05:13", "18:45"), 8: ("05:27", "18:29"),
              9: ("05:39", "17:58"), 10: ("05:50", "17:27"), 11: ("06:09", "17:07"), 12: ("06:30", "17:07")}


# ---------- inputs: the locations file and the cast availability file ----------

@dataclass
class Site:
    name: str
    address: str = ""
    day_weekdays: set[int] = field(default_factory=set)    # day shifts only on these weekdays; empty = any day
    night_weekdays: set[int] = field(default_factory=set)  # the same for night shifts

    def open_on(self, day: date, shift: str) -> bool:
        allowed = self.day_weekdays if shift == DAY_SHIFT else self.night_weekdays
        return not allowed or day.weekday() in allowed


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


def _weekdays(cell: str) -> set[int]:
    """'sat' or 'السبت' or 'sat;sun' -> weekday numbers (Monday is 0)."""
    names = WEEKDAYS | {name: i for i, name in enumerate(WEEKDAY_AR)}
    days = set()
    for word in cell.replace(";", " ").split():
        if word.lower() not in names:
            raise ValueError(f"unknown weekday {word!r}: write sat, sun ... or السبت، الأحد ...")
        days.add(names[word.lower()])
    return days


def load_locations(path: Path) -> list[LocationEntry]:
    """Columns: script place, site, address, notes, day-shift weekdays, night-shift weekdays.

    Rows with the same site name share one Site. The weekday columns can be written on any one of the
    site's rows. Empty means the site can be used on any day for that shift.
    """
    entries: list[LocationEntry] = []
    sites: dict[str, Site] = {}
    for row in _rows(path):
        row = [cell.strip() for cell in row] + [""] * (6 - len(row))
        site = sites.setdefault(row[1], Site(row[1]))
        site.address = site.address or row[2]
        site.day_weekdays |= _weekdays(row[4])
        site.night_weekdays |= _weekdays(row[5])
        entries.append(LocationEntry(row[0], site, row[3]))
    return entries


def match_availability(availability: dict[str, Availability],
                       scenes: list[SceneBreakdown]) -> tuple[dict[str, Availability], list[str]]:
    """Key the availability rows by the breakdown's own character names.

    Hamza, extra spaces and tashkeel don't matter. Returns (rows by character name, names that match no one).
    """
    by_key = {normalize_arabic(c): c for s in scenes for c in s.characters}
    matched: dict[str, Availability] = {}
    unknown: list[str] = []
    for name, rule in availability.items():
        character = by_key.get(normalize_arabic(name))
        if character is None:
            unknown.append(name)
        else:
            matched[character] = rule
    return matched, unknown


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
    locations: list[Site] = field(default_factory=list)   # the Site objects behind `site`

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

    @property
    def flagged(self) -> list[Strip]:
        """Strips with something a person must check before this day can be approved."""
        return [s for s in self.strips if s.flags]


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
    unknown_availability: list[str] = field(default_factory=list)  # availability names that match no character

    def day(self, number: int) -> ShootDay:
        found = next((d for d in self.days if d.number == number), None)
        if found is None:
            raise ValueError(f"no shoot day {number}: the schedule has {len(self.days)} days")
        return found


def make_strips(scenes: list[SceneBreakdown], entries: list[LocationEntry]) -> tuple[list[Strip], dict[str, Site]]:
    strips, sites = [], {}
    for s in scenes:
        flags, notes, used = list(s.review_flags), [], []
        for part in s.location.split("/"):
            entry = find_entry(part, entries)
            if entry is None:
                site = Site(part.strip())
                flags.append(f"المكان «{part.strip()}» غير موجود في ملف المواقع")
            else:
                site = entry.site
                if entry.note:
                    notes.append(f"{entry.script_place}: {entry.note}")
            site = sites.setdefault(site.name, site)
            if site not in used:
                used.append(site)
        if len(used) > 1:
            flags.append("المشهد في أكثر من موقع: يُصوَّر على جزأين")
        # A name a person still has to check is not matched to anyone's availability, so say so.
        for c in s.characters:
            if any(f"«{c}»" in f for f in s.review_flags):
                flags.append(f"لم يُفحص توفر «{c}»: صحّح الاسم في التفريغ ثم أعد الجدولة")
        strips.append(Strip(s, SHIFT_OF_TIME[s.time_of_day], " + ".join(x.name for x in used), item_key(s.location),
                            flags, notes, used))
    order = [DAY_SHIFT, NIGHT_SHIFT]
    strips.sort(key=lambda t: (order.index(t.shift), t.site, t.place_key, t.number))
    return strips, sites


def working_dates(settings: Settings) -> list[date]:
    days = (settings.start + timedelta(days=i) for i in range(settings.horizon_days))
    return [d for d in days if d.weekday() not in settings.days_off]


def cast_free(strip: Strip, day: date, availability: dict[str, Availability]) -> bool:
    return all(availability[c].free_on(day, strip.shift) for c in strip.scene.characters if c in availability)


def strip_free(strip: Strip, day: date, availability: dict[str, Availability]) -> bool:
    """All the strip's actors are free that date and all its sites are open that weekday, for its shift."""
    return all(site.open_on(day, strip.shift) for site in strip.locations) and cast_free(strip, day, availability)


def build_schedule(scenes: list[SceneBreakdown], entries: list[LocationEntry],
                   availability: dict[str, Availability], settings: Settings) -> Schedule:
    availability, unknown = match_availability(availability, scenes)
    strips, sites = make_strips(scenes, entries)
    dates = working_dates(settings)
    rank = {s: i for i, s in enumerate(strips)}
    # How many dates each strip could go on. Fewest options = place it first.
    options = {s: sum(strip_free(s, d, availability) for d in dates) for s in strips}

    remaining = list(strips)
    days: list[ShootDay] = []
    for day in dates:
        if not remaining:
            break
        free = [s for s in remaining if strip_free(s, day, availability)]
        if not free:
            continue
        anchor = min(free, key=lambda s: (options[s], rank[s]))
        chosen = [anchor]
        while len(chosen) < settings.max_scenes:
            nxt = _best_next(chosen, free, settings)
            if nxt is None:
                break
            chosen.append(nxt)
        days.append(ShootDay(len(days) + 1, day, anchor.shift, _shooting_order(chosen)))
        remaining = [s for s in remaining if s not in chosen]

    days = _join_light_days(days, settings, availability)
    unscheduled = [(s, _why_not(s, dates, availability)) for s in remaining]
    return Schedule(days, unscheduled, settings, sites, availability, unknown)


def _shooting_order(strips: list[Strip]) -> list[Strip]:
    """By time of day (dawn after night, sunset after day), then by site so the crew stays put, then by number."""
    site_order = list(dict.fromkeys(s.site for s in strips))
    return sorted(strips, key=lambda s: (TIME_ORDER[s.scene.time_of_day], site_order.index(s.site), s.place_key,
                                         s.number))


def is_light(day: ShootDay, settings: Settings) -> bool:
    """A light day shoots less than half the page limit."""
    return day.eighths * 2 < settings.max_eighths


def _join_light_days(days: list[ShootDay], settings: Settings,
                     availability: dict[str, Availability]) -> list[ShootDay]:
    """Second pass: join two light days of the same shift into one day.

    Joining saves a whole crew day, so it may cost one extra company move (max_sites + 1 sites):
    an hour's move is far cheaper than a day. The scene and page limits still hold, and the joined
    day goes on whichever of the two dates all its actors and sites are free.
    """
    joined = True
    while joined:
        joined = False
        for a, b in combinations(days, 2):
            if a.shift != b.shift or not (is_light(a, settings) and is_light(b, settings)):
                continue
            strips = a.strips + b.strips
            if (len(strips) > settings.max_scenes or a.eighths + b.eighths > settings.max_eighths
                    or len({s.site for s in strips}) > settings.max_sites + 1):
                continue
            when = next((d for d in (a.date, b.date) if all(strip_free(s, d, availability) for s in strips)), None)
            if when is None:
                continue
            keep, drop = (a, b) if when == a.date else (b, a)
            keep.strips = _shooting_order(strips)
            days.remove(drop)
            joined = True
            break
    for number, day in enumerate(days, start=1):
        day.number = number
    return days


def _best_next(chosen: list[Strip], free: list[Strip], settings: Settings) -> Strip | None:
    places = {s.place_key for s in chosen}
    sites = {s.site for s in chosen}
    eighths = sum(s.scene.length_eighths for s in chosen)
    same_shift = [s for s in free if s not in chosen and s.shift == chosen[0].shift]
    waiting = Counter(s.site for s in same_shift)  # how many scenes are free today at each site
    candidates = []
    for s in same_shift:
        if eighths + s.scene.length_eighths > settings.max_eighths:
            continue
        if s.site not in sites and len(sites) >= settings.max_sites:
            continue
        preference = 0 if s.place_key in places else 1 if s.site in sites else 2
        # A new site costs a company move, so spend it on the site with the most scenes waiting today.
        fill = -waiting[s.site] if preference == 2 else 0
        candidates.append((preference, fill, free.index(s), s))
    return min(candidates, key=lambda c: c[:3])[3] if candidates else None


def _why_not(strip: Strip, dates: list[date], availability: dict[str, Availability]) -> str:
    if any(strip_free(strip, d, availability) for d in dates):
        return "أيام التوفر امتلأت بمشاهد أخرى: عدّل الحدود أو رتّب يدوياً"
    actors = [c for c in strip.scene.characters
              if c in availability and not any(availability[c].free_on(d, strip.shift) for d in dates)]
    closed = [site.name for site in strip.locations if not any(site.open_on(d, strip.shift) for d in dates)]
    if actors or closed:
        return "لا يوجد يوم يتوفر فيه: " + "، ".join(actors + closed)
    return "لا يوجد يوم يتوفر فيه الممثلون والموقع معاً: رتّب يدوياً"


# ---------- call times for one day ----------

@dataclass
class CallTimes:
    crew_call: datetime
    scene_start: dict[int, datetime]   # scene number -> estimated start
    actor_call: dict[str, datetime]    # actor -> call time (before their first scene, for makeup)
    meal: datetime | None              # start of the meal break
    wrap: datetime
    sunrise: datetime                  # the sunrise that ends this shift's light: same day (day), next day (night)
    sunset: datetime
    light: dict[int, str] = field(default_factory=dict)  # scene number -> "الغروب" / "الفجر" for light-bound scenes
    warnings: list[str] = field(default_factory=list)     # problems the AD must solve before approving


@dataclass
class TimeRules:
    """Plain, editable estimates. Change them to match the unit's real pace."""
    day_crew_call: str = "07:00"
    first_setup_minutes: int = 60    # from crew call to the first shot
    scene_setup_minutes: int = 45    # lighting and blocking for each scene
    minutes_per_eighth: int = 15     # shooting time: about 2 hours per page
    move_minutes: int = 60           # one company move
    meal_after_hours: int = 6        # meal break once this many hours have passed since crew call
    meal_minutes: int = 60
    actor_prep_minutes: int = 90     # makeup and wardrobe before the actor's first scene
    dark_after_sunset_minutes: int = 40  # night scenes start once it is fully dark
    light_window_minutes: int = 60   # sunset or dawn light lasts about this long
    max_shift_hours: int = 12        # a longer shift is flagged (crew rest and overtime)
    sunrise: str | None = None       # fixed "HH:MM" for every date; None = the Riyadh table
    sunset: str | None = None

    def sun(self, day: date) -> tuple[datetime, datetime]:
        """(sunrise, sunset) on that date."""
        rise, down = RIYADH_SUN[day.month]
        return _at(day, self.sunrise or rise), _at(day, self.sunset or down)

    def scene_minutes(self, strip: Strip) -> int:
        return self.scene_setup_minutes + strip.scene.length_eighths * self.minutes_per_eighth


def _at(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())


def _minutes(span: timedelta) -> int:
    return int(span.total_seconds() // 60)


def _round_up_5(t: datetime) -> datetime:
    return t + timedelta(minutes=-t.minute % 5)


def _stack(strips: list[Strip], crew_call: datetime, rules: TimeRules,
           meal_needed: bool = False) -> tuple[dict[int, datetime], datetime | None, datetime]:
    """Scenes one after another from the crew call: (start of each scene, meal start, end of the last scene).

    The meal comes before the first scene that would start after meal_after_hours. With meal_needed
    (the whole day is longer than that), it comes before the first scene that would END after it,
    or at the end of this block if no scene does.
    """
    t = crew_call + timedelta(minutes=rules.first_setup_minutes)
    due = crew_call + timedelta(hours=rules.meal_after_hours)
    meal = None
    starts: dict[int, datetime] = {}
    for i, strip in enumerate(strips):
        if i and strip.site != strips[i - 1].site:
            t += timedelta(minutes=rules.move_minutes)
        ends_late = meal_needed and t + timedelta(minutes=rules.scene_minutes(strip)) > due
        if meal is None and (t >= due or ends_late):
            meal, t = t, t + timedelta(minutes=rules.meal_minutes)
        starts[strip.number] = t
        t += timedelta(minutes=rules.scene_minutes(strip))
    if meal_needed and meal is None:
        meal, t = t, t + timedelta(minutes=rules.meal_minutes)
    return starts, meal, t


def call_times(day: ShootDay, rules: TimeRules | None = None) -> CallTimes:
    """Estimated times for one shoot day, built around the real light.

    - Sunset and dawn scenes are counted BACK from the light: on a day shift the sunset scenes end at
      sunset; on a night shift the dawn scenes end at the next sunrise.
    - The other scenes run forward from the crew call. If they finish early, the crew call moves later,
      so the crew does not sit and wait for the light.
    - A night shift never starts its first shot before it is dark.
    Anything that does not fit becomes a warning on the call sheet, not a hidden wrong time.
    """
    rules = rules or TimeRules()
    sunrise, sunset = rules.sun(day.date)
    move = timedelta(minutes=rules.move_minutes)
    if day.shift == DAY_SHIFT:
        crew_call = _at(day.date, rules.day_crew_call)
        light_end = sunset
    else:
        dark = sunset + timedelta(minutes=rules.dark_after_sunset_minutes)
        crew_call = _round_up_5(dark - timedelta(minutes=rules.first_setup_minutes))
        sunrise = rules.sun(day.date + timedelta(days=1))[0]   # the night ends at the next morning's sunrise
        light_end = sunrise
    tied = [s for s in day.strips if s.scene.time_of_day in LIGHT_TIMES]
    others = [s for s in day.strips if s.scene.time_of_day not in LIGHT_TIMES]
    warnings: list[str] = []

    # 1. Light-bound scenes, counted back from sunset (or sunrise) so the last one ends with the light.
    starts: dict[int, datetime] = {}
    t = light_end
    for i in reversed(range(len(tied))):
        t -= timedelta(minutes=rules.scene_minutes(tied[i]))
        starts[tied[i].number] = t
        if i and tied[i].site != tied[i - 1].site:
            t -= move
    light_start = t
    if tied and light_end - light_start > timedelta(minutes=rules.light_window_minutes):
        label = LIGHT_TIMES[tied[0].scene.time_of_day]
        warnings.append(f"مشاهد {label} تحتاج {_minutes(light_end - light_start)} دقيقة وضوء {label} يدوم "
                        f"حوالي {rules.light_window_minutes}: وزّعها على أكثر من يوم")

    # 2. The other scenes, forward from the crew call.
    forward, meal, end = _stack(others, crew_call, rules)
    if tied:
        if others and others[-1].site != tied[0].site:
            end += move
        gap = light_start - end
        if gap >= timedelta(0):   # time to spare: call the crew later instead of waiting for the light
            shift = timedelta(minutes=_minutes(gap) // 5 * 5)
            crew_call += shift
            forward = {n: s + shift for n, s in forward.items()}
            meal = meal + shift if meal else None
            # The later call can still leave a day (crew call to the end of the light) longer than the meal
            # rule. Then add the meal and call the crew that much earlier, so the light scenes don't move.
            if meal is None and light_end - crew_call > timedelta(hours=rules.meal_after_hours):
                crew_call -= timedelta(minutes=rules.meal_minutes)
                forward, meal, _ = _stack(others, crew_call, rules, meal_needed=True)
        else:
            warnings.append(f"لا يكفي الوقت قبل {LIGHT_TIMES[tied[0].scene.time_of_day]}: مشاهد اليوم تحتاج "
                            f"{_minutes(-gap)} دقيقة أكثر. انقل مشهداً إلى يوم آخر")
    starts.update(forward)
    wrap = light_end if tied else end

    if day.shift == DAY_SHIFT:
        for s in others:
            finish = starts[s.number] + timedelta(minutes=rules.scene_minutes(s))
            if "خارجي" in s.scene.int_ext and finish > sunset:
                warnings.append(f"المشهد {s.number} خارجي نهار وينتهي بعد الغروب: قدّمه أو انقله")
    elif wrap > sunrise:
        warnings.append("المشاهد الليلية تمتد بعد الشروق: انقل مشهداً إلى ليلة أخرى")
    hours = (wrap - crew_call).total_seconds() / 3600
    if meal is None and hours > rules.meal_after_hours:
        warnings.append(f"الوردية {hours:.1f} ساعة بلا استراحة طعام (القاعدة: بعد {rules.meal_after_hours} ساعات): "
                        "أضفها يدوياً")
    if hours > rules.max_shift_hours:
        warnings.append(f"طول الوردية {hours:.1f} ساعة، أكثر من {rules.max_shift_hours}: راجع راحة الطاقم والعمل الإضافي")

    actors: dict[str, datetime] = {}
    for strip in day.strips:   # shooting order, so each actor's first scene comes first
        for name in strip.scene.characters:
            actors.setdefault(name, starts[strip.number] - timedelta(minutes=rules.actor_prep_minutes))
    return CallTimes(crew_call, starts, dict(sorted(actors.items(), key=lambda kv: kv[1])), meal, wrap,
                     sunrise, sunset, {s.number: LIGHT_TIMES[s.scene.time_of_day] for s in tied}, warnings)


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
    night_scenes: int                # ليل only
    dawn_scenes: int                 # فجر (shot at the end of a night shift)
    sunset_scenes: int               # غروب (shot at the end of a day shift)
    company_moves: int
    night_to_day_turnarounds: int    # a night shift, then a day shift on the next calendar date: check crew rest
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

    def scenes_at(time_of_day: str) -> int:
        return sum(s.scene.time_of_day == time_of_day for d in days for s in d.strips)

    return BudgetSummary(
        shoot_days=len(days),
        day_shifts=sum(d.shift == DAY_SHIFT for d in days),
        night_shifts=sum(d.shift == NIGHT_SHIFT for d in days),
        night_scenes=scenes_at("ليل"),
        dawn_scenes=scenes_at("فجر"),
        sunset_scenes=scenes_at("غروب"),
        company_moves=sum(d.moves for d in days),
        night_to_day_turnarounds=sum(a.shift == NIGHT_SHIFT and b.shift == DAY_SHIFT
                                     and b.date - a.date == timedelta(days=1) for a, b in pairwise(days)),
        site_days=dict(sorted(site_days.items(), key=lambda kv: -kv[1])),
        actors=actors,
        extras_days=per_day("extras"),
        vehicle_days=per_day("vehicles"),
        animal_days=per_day("animals"),
        unscheduled=len(schedule.unscheduled),
        flagged_scenes=sorted(s.number for d in days for s in d.strips if s.flags),
    )
