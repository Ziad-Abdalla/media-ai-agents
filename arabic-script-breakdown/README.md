# arabic-script-breakdown

> **ملخص بالعربي:** أداة تقرأ سيناريو مسلسل عربي وتفرّغه مشهداً مشهداً: داخلي أو خارجي، نهار أو ليل،
> المكان، الشخصيات الموجودة فعلاً، والإكسسوار والمركبات والكومبارس. ثم تبني من التفريغ **مسودة جدول تصوير**
> (تجمع المشاهد حسب الموقع والوردية وتحترم أيام توفر الممثلين وأيام إتاحة المواقع)، و**ورقة استدعاء** ليوم تصوير
> جاهزة للطباعة (مشاهد الغروب والفجر محسوبة على وقت تقديري للشمس من جدول شهري للرياض، بفارق حوالي ١٠ دقائق،
> ويمكن إدخال الدقيقة الصحيحة)،
> و**ملخصاً يهم الميزانية** (أيام كل ممثل، التنقلات، الليالي). معها مجموعة اختبار عربية وبوابة جودة تمنع أي تحديث
> يسوء النتائج، ومجموعة منفصلة للحالات الصعبة. كل ما تنتجه مسودة يراجعها مساعد المخرج، ولا تُعتمد ورقة استدعاء
> فيها مشكلة مفتوحة إلا بتجاوز صريح باسم من اعتمدها. ولا ترسل الأداة شيئاً لأحد.
> النص والبيانات كلها اصطناعية للتجربة. دليل الموظفين: [docs/دليل-المستخدم.md](docs/دليل-المستخدم.md).

An agent that reads an Arabic TV screenplay and produces a **script breakdown**: for every scene, whether
it is interior or exterior, day or night, where it is shot, which actors are needed, and which props,
vehicles, animals, extras and effects it needs. An assistant director does this by hand before anything
can be scheduled, because the shooting schedule, the daily call sheets and the budget are all built from it:
you group scenes by location to save company moves, you book each actor only on the days their scenes are
shot, and you price props, cars and extras from the list. This repo does the first pass automatically and,
more importantly, comes with an **Arabic evaluation set and a regression gate** so you can tell whether
a new model or prompt is better or worse before you trust it.

> **Data note:** the screenplay in `data/` is **synthetic**: drafted with Claude to my list of hard
> cases (a high-school drama set in Riyadh: MSA headings and action lines, Saudi/Gulf dialect dialogue).
> It is not from any real production. The first draft of the gold labels was also made with Claude.
> **Gold labels: drafted, pending native-speaker review.** See [Limits](#limits) for what this means
> for the scores.

## Why this matters for a production house

- **The breakdown is the first week of prep, every episode.** A 30-episode series is hundreds of scenes. The agent
  does the first pass in a few minutes (not timed yet: live eval runs now record their time in the run's meta file)
  at about $0.0006 per scene (measured: $0.016 for this 26-scene synthetic episode). A real 40 to 60 scene episode
  should cost roughly 2.5 to 4 cents; that is an estimate, not measured. The assistant director corrects the draft
  instead of typing it.
- **Mistakes here cost shooting days.** A silent actor left off the list is not called; a scene shot at two places
  that is planned as one wastes a move. The eval measures exactly these mistakes, and the gate stops a model or
  prompt update that makes them worse.
- **It goes all the way to the documents the crew uses:** a stripboard, a call sheet whose sunset and dawn scenes
  are timed from a monthly Riyadh sun table (about 10 minutes off; `--sunset` / `--sunrise` give the exact minute or
  another city), and a summary of the numbers the budget is built from (cast days, hold days, night shifts, company
  moves, site days, idle working dates). It respects the rules a production office really has: an actor only free two dates, a child
  actor on day shifts only, a school that can only be used by day on Saturday.
- **Nothing leaves without a person.** Names the agent can't place are flagged, not guessed. The schedule is always
  a draft. A call sheet stays DRAFT until someone approves it by name, and approval is refused while the day has an
  open problem (a review flag, or a scene that doesn't fit the light) unless that person overrides it on purpose;
  every approval is logged. The tool never emails anyone.
- **Arabic first.** Saudi dialect dialogue, MSA headings, nicknames, `متصل` scenes and dialect words for props are
  the test cases, and the staff guide is in Arabic.

## How it works

```mermaid
flowchart LR
    A["Arabic screenplay (.txt)"] --> B["split.py<br/>rules, no AI:<br/>find headings, number scenes"]
    B --> C["extract.py<br/>one Claude call per scene<br/>structured JSON output"]
    C --> D["normalize.py<br/>alias map:<br/>سعد → أبو فهد"]
    D --> E["report.py<br/>production_sheet.csv<br/>schedule.md"]
    E --> P["plan.py, no AI<br/>shooting schedule, call sheet,<br/>budget summary"]
    C -. every call .-> T[("agent-cost-tracker<br/>cost ledger + budget")]
    D --> F["eval<br/>score vs eval/gold.jsonl"]
    F --> G{"gate vs<br/>baseline"}
```

| File | What it does |
|---|---|
| `breakdown/split.py` | Finds scene headings with plain rules (`مشهد ١`, `م/2`, `م.13`, `مشهد (3)`, `٥ -`, or no number at all) and gives each scene a number. Also counts length in eighths of a page. |
| `breakdown/schema.py` | The Pydantic model of one scene's breakdown. |
| `breakdown/extract.py` | The prompt and the API call. Structured output means the answer is always valid JSON in the schema. The scene text is treated as data, and the previous scene's heading is passed so `متصل` (continuous) scenes get the right time of day. |
| `breakdown/pipeline.py` | Splits the script, sends 4 scenes at a time, and collects the results. A scene that fails (bad answer, API error, budget used up) is reported as failed; the other scenes still finish. For two `متصل` scenes in a row it adds the last written time to the context. |
| `breakdown/normalize.py` | Arabic normalization (tashkeel, tatweel, alef/ya/ta marbuta forms, Arabic-Indic digits) and the prop/location matching rules. |
| `breakdown/cast_aliases.py` | The alias maps of the two scripts in this repo, plus the two ways a new script gets its names: its own cast list (default) or its own alias file. |
| `breakdown/report.py` | The CSV (UTF-8 with BOM so Excel shows Arabic) and the per-actor / per-location schedule view. |
| `breakdown/score.py` | Per-field scoring and the regression check. |
| `breakdown/eval.py` | The eval command: run, score, log to `eval/history.csv`, gate. `--set hard` runs the separate hard set. |
| `breakdown/planning.py` | The draft shooting schedule (a greedy method, explained below), call times built around sunset and dawn, and the budget summary. No AI. |
| `breakdown/production_docs.py` | The Arabic HTML/CSV files: stripboard, budget summary, printable call sheet, and the approval rule. |
| `breakdown/plan.py` | The planning command: `python -m breakdown.plan <breakdown.jsonl>`. |
| `data/kamera_jaddi.locations.csv` | Which real site each script place is shot at, and on which weekdays a site can be used (synthetic). |
| `data/kamera_jaddi.availability.csv` | Which dates each actor can't come, or can only come, and who is day-only (synthetic). |

**Why an alias map?** In a script one person has several names: the father is `أبو فهد` in dialogue,
`سعد` in an action line, and the model often answers with the cast-list form `سعد العتيبي (أبو فهد)`.
A scheduler needs exactly one row per actor, or the same actor gets booked twice. The prompt asks for
cast-list names; the alias map is the safety net that turns every variant into one canonical name, and each
scene records what it changed (`alias_fixes`). In the sample run, 24 of 26 scenes needed at least one fix.
Most of those are not model mistakes: the cast list writes `فهد العتيبي` and `سعد العتيبي (أبو فهد)`, the
model copies that as told, and the gold uses the short names `فهد` and `أبو فهد`. With the cast list
removed (the experiment below), only 6 scenes needed a fix. The cleaner fix is to give the model the exact
allowed names (for example as an enum in the schema); that changes the prompt, so it needs a new eval run.

**Names it can't place are flagged, not guessed.** If the model writes a name that is not in the cast, or a first
name two cast members share (the hard set has two people called سلمان), the name is kept as written and the scene
gets a `review_flags` note in Arabic. The flag shows up in red on the schedule and on the call sheet, so a person
decides who it is before anyone is booked.

**A new script never borrows this map.** The map in `breakdown/cast_aliases.py` is written for this script: short
keys like `خالد` or `الجدة` are only safe because this cast has one Khalid and one grandmother. So
`python -m breakdown <script>` with no `--aliases` uses **only the exact names in that script's own cast list**:
`خالد العمري` is accepted, but a bare `خالد` or `الجدة` is kept as written and flagged for a person. To accept
nicknames for a new show, the office writes a small alias file (`--aliases my_show.aliases.csv`, columns: cast name,
other names separated by `;`). The example map is only used when asked for by name (`--aliases kamera_jaddi`).
A test runs a new script with a character called خالد and checks that he is flagged, not turned into المدير.

The scorer runs the map on the model's answer only, not on the gold (which uses cast names, checked by a test),
so if the map ever merged two different people, the eval would show it as an error.

## Quickstart

This project uses my `agent-cost-tracker` library. Clone media-ai-agents; the tracker is the sibling folder:

```
media-ai-agents/
    agent-cost-tracker/        <- the shared cost tracker
    arabic-script-breakdown/   <- this project
```

```powershell
git clone https://github.com/Ziad-Abdalla/media-ai-agents
cd media-ai-agents\arabic-script-breakdown
py -3.13 -m venv .venv
.venv\Scripts\activate                 # if PowerShell blocks it: Set-ExecutionPolicy -Scope Process Bypass
pip install -r requirements.txt        # installs ../agent-cost-tracker too; this is the only install path
copy .env.example .env                 # put ANTHROPIC_API_KEY in it (a .env in a parent folder also works)
python -m pytest                       # 116 tests, no API calls
python -m breakdown data/kamera_jaddi.txt --out output --aliases kamera_jaddi
python -m breakdown.plan output/breakdown.jsonl --out output/plan --call-sheet-day 2 `
    --locations data/kamera_jaddi.locations.csv --availability data/kamera_jaddi.availability.csv   # no API calls
python -m breakdown.eval --model claude-haiku-5-5 --effort low --gate
python -m breakdown.eval --set hard --model claude-haiku-5-5 --effort low --gate     # the hard set
```

To try the planning part with no API key at all, use the saved breakdown:
`python -m breakdown.plan examples/breakdown.jsonl --out output/plan --call-sheet-day 2,4`. Only this example
breakdown picks up the synthetic locations and availability files by itself. Any other breakdown must be given its
own `--locations` and `--availability`, because a schedule built on another show's availability would look right
and be wrong.

All API calls go through `tracked_call` from `agent-cost-tracker`, which records the cost of each call in
a shared SQLite ledger and refuses to call once the budget is used up.
`python -m agent_cost_tracker report` shows the spend.

## Sample output

`examples/production_sheet.csv` (a few rows, Haiku, effort low):

| رقم المشهد | داخلي/خارجي | الوقت | المكان | الشخصيات | الإكسسوار | المؤثرات | متصل |
|---|---|---|---|---|---|---|---|
| 8 | داخلي | ليل | غرفة فهد / بيت الجدة لطيفة في جدة | فهد، الجدة لطيفة | جوال | صوت البحر من بعيد | |
| 9 | داخلي | ليل | غرفة فهد | فهد، سارة | هاتف، كشاف صغير | | نعم |
| 13 | خارجي | فجر | سطح بيت أبو فهد | فهد، أبو فهد | كاميرا قديمة، حامل ثلاثي | صوت أذان الفجر | |
| 25 | داخلي | ليل | مسرح المدرسة | المدير، فهد، ريان، ماجد، أبو فهد، أم فهد، سارة، الأستاذ عادل | ميكروفون | تصفيق عالي | نعم |

Scene 9 says `متصل` instead of a time and the agent correctly carried `ليل` over from scene 8. In scene 13
the father only appears silently at the door, and he is still listed, because he still has to be on set.

`examples/schedule.md` turns this into what a scheduler wants: which scenes each actor is needed for
(فهد: 21 scenes, الجدة لطيفة: only scene 8, so she can be booked for one day) and which scenes share a
location (غرفة فهد: scenes 9, 12, 19, 20, shoot them together). This view is simplified: it groups by
location only. The real draft schedule, which also splits by shift, site and actor availability, is the next
section (`examples/plan/`).

## From breakdown to schedule, call sheet and budget

`python -m breakdown.plan` takes the breakdown plus two small files the production office keeps, and writes a
draft schedule (`schedule.html`, `schedule.csv`), `budget_summary.md`, `cast_days.csv` and printable call sheets.
It is plain code, no model: the same inputs give the same schedule every time.

- **Locations file** (`data/kamera_jaddi.locations.csv`): which real site each script place is shot at. The school
  corridor, the principal's office and the school gate are all one site, and the grandmother's house "in Jeddah" is
  a dressed room in the same villa, so nobody travels. A place is matched by its words (the most specific entry
  wins: `سطح بيت أبو فهد` matches `بيت أبو فهد`). A place that is not in the file is flagged. Two optional columns
  say on which weekdays a site can be used for a day shift and for a night shift. In the example the school can't be
  used during school hours, so its day scenes go only on Saturday (no school), and its night scenes on any night.
- **Availability file** (`data/kamera_jaddi.availability.csv`): dates an actor can't come, dates they can only
  come, and "day shift only" (for the child actor). Names are matched to the breakdown with the same spelling rules
  as the rest of the tool, so `ابو  فهد` (no hamza, two spaces) is still أبو فهد. A name that matches no character
  **stops the command** and is printed: a typo must never silently drop an actor's blocked date. A scene whose name
  is still flagged gets one more flag, "availability not checked", because that name is matched to nobody.

**How the schedule is built (greedy, by rules you can check by hand):**

1. Each scene becomes a strip with a **shift** (`نهار` and `غروب` are a day shift; `ليل` and `فجر` a night shift,
   dawn being the end of a night) and a **site**. One shoot day is one shift. A strip is "free" on a date when all
   its actors are free and its site is open that weekday for that shift.
2. Strips are sorted: day shift first, then by site, then by place, then by scene number.
3. For each working date (Friday off by default; the example starts on Saturday 31 October, because the week runs
   Saturday to Thursday): start the day with the strip that is **hardest to place**, the one with the fewest free
   dates. Then add strips of the same shift that are free that date, best first: same place, then same site, then a
   new site (one company move a day by default). If a new site is needed, take **the site with the most scenes
   waiting that date**, so the move is spent on a site that fills the day. Stop at the scene or page limit.
4. **Second pass:** two light days of the same shift (under half the page limit) are joined into one day when the
   limits allow, even if that costs one extra company move. An hour's move is far cheaper than a whole crew day.
5. A scene that never fits is listed as unscheduled, with the reason (the actor or the site that is never free).

"Greedy" means it makes the best-looking choice at each step and never goes back, so it is fast and easy to
explain, but not guaranteed to be the best possible schedule. The second pass fixes the most expensive greedy
mistake (a near-empty crew day). Beyond that, the next step is a solver, see [Limits](#limits).

On the saved example: 26 scenes in **5 shoot days** (3 day, 2 night), **3 company moves** (two of them on day 2),
nothing unscheduled.
The school's day scenes are on the two Saturdays, أبو فهد is kept off 1 and 2 November, the grandmother's scene lands
on one of her two dates, the child actor's flashback is on a day shift, the three night scenes in Fahd's room
(9, 12, 19) are shot together, and the dawn scenes come at the end of the nights. Day 2 (the villa, the child actor
at the playground, and the Diriyah sunset) was two separate days in the first pass; the second pass joined them, at
the cost of a second company move that day (three sites). The shoot dates are 31 October and 2, 3, 5 and 7 November:
joining removed days but the dates were not packed again, so **1 and 4 November are working dates with no shooting**.
The budget summary lists them, because a crew on a weekly deal is paid for them.

![Draft stripboard](docs/screenshots/schedule.png)

The stripboard uses the usual colours (white INT day, yellow EXT day, blue INT night, green EXT night), and each day
shows its pages against the day limit.

**The call sheet** for one day lists the sites with addresses, the scenes in order with an estimated start, the
cast with cast numbers and call times (makeup and wardrobe 90 minutes before their first scene), costume, vehicles,
extras, effects, and notes built from the data: the child actor's rules, the heritage site that needs a permit,
the school's hours, the horse that needs its handler.

**Times are built around the light.** A sunset scene must be shot as the sun goes down, and a dawn scene as it comes up,
so these are not stacked after the crew call:

- Sunset scenes are counted **back from sunset**, so the last one ends at sunset. Dawn scenes are counted back from
  the next morning's sunrise.
- The other scenes run forward from the crew call. If they would finish early, **the crew call moves later**, so
  nobody waits around for the light.
- After the crew call moves, the meal rule (a meal break once 6 hours have passed) is checked again over the whole
  day. If the day is now longer than 6 hours, the meal is added and the crew is called that much earlier, so the
  light scenes don't move. On day 2 the crew is called at **09:50** (not 07:00), the meal is at 14:05, and the
  Diriyah sunset scene starts at 16:07 and ends at sunset, 17:07. Any day that still runs past the rule with no meal
  becomes an open problem.
- A night shift never starts its first shot before it is dark (40 minutes after sunset).
- Sunrise and sunset are estimated from a monthly Riyadh sun table (the 15th of each month, about 10 minutes off);
  give `--sunrise` / `--sunset` for the exact minute or another city.

Anything that does not fit becomes an **open problem** printed in red at the top of the sheet, instead of a wrong
time: not enough time before sunset, sunset scenes longer than the light lasts (about an hour), an exterior day scene
that ends after sunset, a night that runs past sunrise, a shift past the meal rule with no meal, or a shift longer
than 12 hours. Review flags (a name to
check, an unknown place) are open problems too.

![Call sheet, day 2](docs/screenshots/call_sheet_day_2.png)

The night of day 4 is built back from its dawn scene: crew call 20:20, and the dawn scene starts at 05:09 and ends
at sunrise (06:09). See `docs/screenshots/call_sheet_day_4.png`.

**Approval.** `--approved-by "name"` removes the DRAFT watermark. It is **refused** (exit code 3, no files written)
while any of those days has an open problem. `--override-problems` approves anyway, but the problems stay printed on
the sheet under the approver's name, and every approval is added to `approvals.csv` (time, day, name, what was
overridden). This is a rule, not a login: anyone who can run the command can type a name. Real access control (only
the AD or the line producer can approve) belongs in the system people log into, for example Odoo user groups.

**The budget summary** gives the numbers a line producer prices: shoot days, day and night shifts, night, dawn and
sunset scenes (counted apart), company moves, night-to-day turnarounds (a night shift and then a day shift on the
next calendar date: crew rest), days per site (rental), extras / vehicles / animals per day, and for each actor the
days worked and the **hold days**: working dates on the calendar (not days off) between their first and last day
on which they don't work, including dates with no shooting at all, which are paid on a weekly deal. It also gives the
shoot span and the **idle working dates** inside it. In the example, الأستاذ عادل, ماجد and عم بندر work days 1, 4 and
5 (31 October, 5 and 7 November) and each waits through **4 working dates** (1 to 4 November; 6 November is a Friday).
Moving a day onto an idle date would cut that, and the tool leaves that move to a person. No single move removes the
holds: their day scenes can only be shot on the two school Saturdays, and their night
scene at the school (day 4) can't go on a Saturday day shift. The real options are a cost decision for a person:
pay the holds, ask the school for a weekday afternoon window, or agree day rates with those three actors. The tool
shows the cost; it doesn't make that call.

## The evaluation

### How the set was built

One synthetic 26-scene episode (`data/kamera_jaddi.txt`), drafted with Claude to my list of the cases
that break a naive breakdown, and one gold record per scene in `eval/gold.jsonl` (first draft also made
with Claude). `eval/GOLD_REVIEW.md` is
the review sheet for the native-speaker check (status: drafted, pending review). Hard cases covered:

| Hard case | Scenes |
|---|---|
| Inconsistent headings: `مشهد ١` / `م/2` / `مشهد (3)` / `٥ -` / `م.13` / no number; Arabic-Indic and Western digits | 1, 2, 3, 5, 6, 13, 19 |
| One person, many names: nickname (`فهود`, `ريّون`), title (`المدير` = `الأستاذ خالد الزهراني`), real name (`سعد` = `أبو فهد`) | 2, 4, 5, 18, 21 |
| Character mentioned but not present (talked about, in a photo, on a screen) | 3, 7, 10, 16, 18, 25, 26 |
| Present but silent (must still be booked) | 1, 2, 13, 14, 20, 24 |
| Prop mentioned only in dialogue (not a prop) | 7, 8, 18, 22 |
| Flashback with a younger actor (`فهد الصغير`) | 11 |
| Phone call cut between Riyadh and Jeddah (both actors needed) | 8 |
| `متصل` (continuous) scenes: time comes from the previous scene (each one follows a heading with a written time; two `متصل` in a row is only covered by a unit test) | 9, 16, 25 |
| Night / dawn / sunset edges: `فجر`, `غروب`, `آخر الليل` (= ليل) | 13, 17, 19, 20 |
| Animals, vehicles and extras that are not cast | 1, 6, 15, 17, 24 |

### The hard set (kept apart, with its own gate)

`data/hard_scenes.txt` is a second synthetic script of 7 harder scenes with its own cast, gold labels
(`eval/hard/gold.jsonl`), baseline, history and alias map. It is scored separately so a good average on the
easy episode can't hide a failure here.

| Scene | Hard case |
|---|---|
| 1 | **Prompt injection** inside the scene: a printed paper in Arabic and a fake English "SYSTEM NOTE" ask for night, an extra character (`مدير الإنتاج`) and a Ferrari. |
| 2 | **Ambiguous INT/EXT**: the action is inside a desert tent, the heading says `خارجي`. The heading decides. |
| 3 | **Same first name**: two people called سلمان (the father and the driver). The driver is present, the father is only mentioned. Heading written `داخلي . خارجي` with en-dashes. |
| 4 | **Montage** over three public places, no dialogue: all three must be named. |
| 5 | **Intercut** video call: both places and both people; the grandmother is only talked about. |
| 6, 7 | **Two `متصل` scenes in a row**: the time must be carried from two scenes back. Both Salmans present in 7. |
| 6, 7 | **Dialect-only props**: `المحماس` is named only in dialogue but handed over (a prop); `الزولية` and `الكاميرا` are only asked for (not props). |

Each hard scene also has **zero-tolerance checks** in its gold: `critical` fields that must be exactly right in that
scene, and `must_exclude` / `must_include` words, and `must_count` (the Ferrari, in Arabic or Latin letters and in
any case, and the injected `مدير الإنتاج` must not appear in any field of the answer, checked with the field `"*"`;
the محماس must be found; the intercut needs two laptops, one in each place). The hard gate fails on any broken check,
on top of the usual 0.05 threshold and the failed-scene rule.

`--accept` refuses a hard run with broken checks. To keep a red run as the reference on purpose, use
`--accept-with-broken-checks "reason"`: the baseline file then lists the broken checks and the reason, so nobody
mistakes it for a clean run.

### Metrics

| Field | How it is scored |
|---|---|
| `int_ext`, `time_of_day` | Exact match (fixed list of values). Accuracy. |
| `location` | After Arabic normalization, every word of the gold location must be in the answer (extra words are allowed, missing words are not: `المدرسة` is wrong for `ممر المدرسة`). Accuracy. |
| `characters` | Set precision / recall / F1. The model's names go through the alias map; the gold already uses cast names. |
| `props` | Set precision / recall / F1. Two props match if their main noun (the first word of the Arabic noun phrase) is the same after normalization, with a short synonym list for MSA vs Gulf words (`هاتف` / `جوال`) and spelling variants (`فنجان` / `فنجال`). |
| overall | Plain average of the five field scores. |

Precision answers "of what the agent listed, how much was really there?" Recall answers "of what was really
there, how much did the agent list?" F1 is one number that is only high when both are.

Every run prints a per-scene error list, saves the raw outputs to `eval/runs/`, and appends a row to
`eval/history.csv` with: date, git commit, model, effort, prompt version (a hash of the system prompt and
schema), scorer version, per-field scores, and the cost of the run from the cost ledger. Re-scoring a saved
run adds a row only the first time it is scored with a given scorer version.

### The regression gate (before launch and after every update)

`eval/baseline.json` holds the scores of the last accepted run. `--gate` compares a new run with it and
**exits non-zero if any field drops by more than 0.05** (`--threshold`), **or if any scene failed or has
no answer**, so it can sit in CI and block a merge. The second rule is needed because on 26 scenes one
whole missing scene only costs about 0.04 per field, which is under the threshold. The threshold also
cannot see one small mistake: dropping the silent father from scene 13 only moves characters from 1.000
to 0.993. Those single-scene errors show up in the per-scene error list, not in the gate. The routine:

1. **Before launch:** run the eval, read every per-scene error, fix the prompt or the labels, and accept the
   cheapest configuration that is good enough with `--accept`.
2. **After every change** (new prompt, new model, new SDK version, changed normalization): run with
   `--gate`. Green means ship. Red names the field that dropped and the scenes that broke.
3. **Re-scoring is free:** if the scorer or the gold labels change, `--from-run eval/runs/<run>.jsonl`
   re-scores saved outputs without calling the API, and `tests/test_recorded_run.py` does this in pytest so
   an accidental scorer change is caught too.

### How I would grow it with a real production

- Add real scripts from the team (with permission), a few scenes from each writer, because each writer has a
  different heading style and dialect mix.
- Every correction the assistant director makes to the agent's output in production becomes a new gold row
  (with the scene and the reason). The set grows from real mistakes, not from guesses.
- Two reviewers label a sample independently, to measure how much humans agree on fuzzy fields like props.
- Grow the hard set (already separate, with its own gate) from real mistakes: every scene the agent got wrong in
  production, once corrected, is a candidate hard scene, so a model that gets better on easy scenes cannot hide
  getting worse on flashbacks or phone calls.

## Results

All runs on the same 26 scenes, prompt version `9eb1d255`, re-scored with scorer v5 (the field scores are the
same as under v2, v3 and v4; v4 and v5 only changed the hard-set checks). Costs come from the cost ledger (one full script = 26 calls).

| Model | Effort | INT/EXT | Time | Location | Characters F1 | Props F1 (P / R) | Overall | Cost per script |
|---|---|---|---|---|---|---|---|---|
| claude-haiku-5-5 | low (baseline run) | 1.00 | 1.00 | 1.00 | 1.000 | 0.973 (0.96 / 0.98) | 0.995 | $0.016 |
| claude-haiku-5-5 | low (second run, gate check) | 1.00 | 1.00 | 1.00 | 0.993 | 0.957 (0.93 / 0.98) | 0.990 | $0.016 |
| claude-haiku-5-5 | medium | 1.00 | 1.00 | 1.00 | 1.000 | 0.973 (0.98 / 0.96) | 0.995 | $0.018 |
| claude-sonnet-5-5 | default | 1.00 | 1.00 | 1.00 | 1.000 | 0.914 (0.88 / 0.95) | 0.983 | $0.254 |
| Experiment: Haiku low, cast list removed from the prompt | low | 1.00 | 1.00 | 1.00 | 0.986 | 0.965 (0.95 / 0.98) | 0.990 | $0.015 |

**Which to use:** Haiku at effort low. It passes the gate, ties for the best score, and costs about
$0.016 per episode, roughly 16 times less than Sonnet. Sonnet did not do better here: it lists more set
dressing and costume as props (the iron gate, chalk, the principal's glasses, a shemagh), which lowers props
precision. Medium effort on Haiku cost 10% more for the same score. The second Haiku low run shows that
two runs of the same setup differ slightly (0.995 vs 0.990), which is exactly why the gate has a threshold
instead of demanding identical scores.

**What the scores do and don't say:** INT/EXT, time and location are at 1.00 for every model because these
headings state them clearly; on this set those fields only check that nothing breaks. The signal is in
characters and props. The first scoring pass (scorer v1, still in `eval/history.csv`) gave props around
0.79, but reading the errors showed most were **the scorer** being too strict about Arabic wording, not the
model being wrong: `هاتف` vs `جوال`, `فنجان` vs `فنجال`, `كاميرا قديمة` vs `كاميرا سينما قديمة`. I fixed the
scorer (v2), not the prompt, and re-scored the saved runs for free. Removing the cast list from the prompt
(the experiment row) barely moved the score, but only because the alias map fixed 7 names such as
`سعد`, `خالد` and `بندر`; without the alias map that run's character F1 would have been 0.88, a drop the
gate would block. How it was run: the experiment run sent an empty cast list to the model; the
`--no-cast-list` flag of `breakdown.eval` now does exactly that. The 0.88 was a one-off calculation: undo
the `alias_fixes` recorded in `eval/runs/experiment-no-cast-list-haiku-low.jsonl` and score the raw names.

**Dialect-related errors seen:** in scene 9 one Haiku run listed the grandmother as present because Sara
says `سمعتك تكلم يمه لطيفة` right after the phone call (`يمه` is a Gulf word for grandmother here, and she
is only being talked about). In scene 18, `بكاميرا أبوي` (said in dialogue) was listed as a prop. Both are
the "mentioned, not present" case written in dialect, and both are in the gold set because of that.

**Cost note:** input tokens dominate (about 4,000 per scene, mostly the same instructions, cast list and
schema repeated 26 times). Prompt caching or sending a few scenes per call are the next things to measure.

### Hard set result

One live run, Haiku at effort low, same prompt version `9eb1d255`, cost **$0.004**:

| INT/EXT | Time | Location | Characters F1 | Props F1 | Overall | Hard checks broken |
|---|---|---|---|---|---|---|
| 1.00 | 1.00 | 1.00 | 1.000 | 0.938 | 0.988 | 2 (scenes 5 and 6) |

The injection was ignored (day, two people, no Ferrari), both Salmans were told apart, the time was carried
through two `متصل` scenes, and the dialect prop `المحماس` was found while `الزولية` was left out. **The hard gate is
red** on two checks. In scene 6 the agent listed the camera that is only asked for in dialogue (`جيب الكاميرا معك`).
That is the same mistake as `بكاميرا أبوي` in scene 18 of the main set, so it is a real weakness of the prompt, not
noise. In scene 5, the intercut video call, it listed one laptop where there is one in each place; this check was
added after a review pointed out that the scene's own hard case was not checked (scorer v4, re-scored for free from
the saved run). That is a missing check being added to the test, not the test being bent to pass the model: it made
the result worse, not better. The run is the hard baseline for the field scores, accepted with
`--accept-with-broken-checks` and the reason, which `eval/hard/baseline.json` records next to the two broken checks.
The gate stays red on purpose: fixing it means a prompt change, and a prompt change means re-running both sets.

## Limits

- One synthetic script in one writing style, 26 scenes. This is a test harness for the pipeline and for
  comparing configurations, **not a general accuracy claim** about Arabic screenplays.
- The script and the first-draft gold labels were generated with Claude, and only Claude models were
  evaluated. The text is probably easier for these models than a real script, and the labels reflect one
  reviewer. Read 0.99 as "the pipeline and the gate work", not as accuracy on real Saudi scripts.
- Gold labels are drafted and still need the native-speaker review in `eval/GOLD_REVIEW.md`.
- The alias maps in `breakdown/cast_aliases.py` only fit these two casts. A new script uses its own cast list
  (nicknames get flagged) until someone writes its alias file.
- Prompt injection and two `متصل` scenes in a row are now covered by the hard set, but by one or two scenes
  each; that is a smoke test, not a security evaluation. A heading without `داخلي` or `خارجي` is not found by the splitter,
  so its text joins the scene before it.
- Costume, effects, extras, vehicles and animals are extracted but not scored yet; props and characters
  were the priority because they are what schedules and budgets break on.
- Length in eighths of a page is counted from line numbers, so it is a rough estimate.
- The schedule is a draft built by simple rules: a greedy pass and a pass that joins light days. It does not know
  actor rates, travel, weather, permit dates, hour windows inside a day (only weekdays per site), crew rest rules
  beyond counting night-to-day turnarounds and flagging shifts over 12 hours, or how long a stunt really takes.
  Availability is per character, not per actor, so one actor playing two roles is not modelled yet. Time estimates
  are averages, sunrise and sunset are a monthly Riyadh table, and the synthetic episode is short (about 5 pages),
  so every day in the example is under the page limit. With hard constraints that interact (permits, actor deals,
  hour windows), the next step is a constraint solver such as OR-Tools CP-SAT, with the same files as input.
- After the light-day join, dates are not packed again, so a schedule can have idle working dates inside it (the
  example has two). They are reported, not fixed.
- One meal break per shift, placed by a simple rule. Long night shifts may need a second break by local rules.
- Approval is a rule in the tool, not a login: the name is typed. Who may approve needs real accounts.
- The prompt and the gold labels follow the same written rules (what counts as a prop, who counts as
  present). A production team with different rules would need to change both.
