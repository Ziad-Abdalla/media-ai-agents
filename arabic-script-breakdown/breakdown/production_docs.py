"""Write the planning files the crew reads: the schedule (HTML + CSV), the budget summary and a call sheet.

All pages are Arabic, right-to-left, and print on A4. They are drafts: every page says so until a
named person approves the call sheet with --approved-by.
"""

import csv
from datetime import datetime
from html import escape
from pathlib import Path

from .planning import (
    DAY_SHIFT,
    WEEKDAY_AR,
    BudgetSummary,
    CallTimes,
    Schedule,
    ShootDay,
    Strip,
    budget_summary,
    call_times,
)

DRAFT_NOTE = "مسودة آلية: يراجعها مساعد المخرج ويعدّلها قبل الاعتماد. لا تُرسل للممثلين قبل الاعتماد."
HOLD_DAYS_NOTE = ('<p class="sub">أيام الانتظار: أيام تصوير بين أول وآخر يوم للممثل لا يصوّر فيها.'
                  " إذا كان عقده أسبوعياً تُدفع، فيُفضّل تقليلها.</p>")
LEGEND = ('<p class="legend"><span style="background:#fff">داخلي نهار</span>'
          '<span style="background:#fff3a8">خارجي نهار</span>'
          '<span style="background:#cfe0ff">داخلي ليل</span>'
          '<span style="background:#cdeccd">خارجي ليل</span></p>')

CSS = """
@page { size: A4; margin: 12mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Tahoma, "Noto Naskh Arabic", sans-serif; direction: rtl; color: #1b1b1b;
       margin: 24px; font-size: 14px; line-height: 1.5; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 22px 0 8px; border-bottom: 2px solid #1b1b1b; padding-bottom: 3px; }
.sub { color: #555; margin: 0 0 12px; }
.draft { background: #fff4d6; border: 1px solid #e0b84c; padding: 8px 12px; border-radius: 6px; margin: 10px 0; }
.approved { background: #e6f4ea; border: 1px solid #5aa36d; padding: 8px 12px; border-radius: 6px; margin: 10px 0; }
.synthetic { color: #8a5a00; font-size: 12px; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; }
th, td { border: 1px solid #bbb; padding: 4px 7px; text-align: right; vertical-align: top; }
th { background: #f0f0f0; font-weight: 600; }
.tiles { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
.tile { border: 1px solid #ccc; border-radius: 8px; padding: 8px 14px; min-width: 130px; }
.tile b { display: block; font-size: 22px; }
.tile span { color: #555; font-size: 12px; }
tr.daybreak td { background: #1b1b1b; color: #fff; font-weight: 600; }
tr.int-day td { background: #ffffff; }
tr.ext-day td { background: #fff3a8; }
tr.int-night td { background: #cfe0ff; }
tr.ext-night td { background: #cdeccd; }
.legend span { display: inline-block; padding: 2px 10px; border: 1px solid #bbb; margin-left: 6px; }
.flag { color: #a40000; font-weight: 600; }
.num { font-variant-numeric: tabular-nums; }
span[dir="ltr"] { white-space: nowrap; }
.watermark { position: fixed; top: 40%; left: 0; right: 0; text-align: center; font-size: 110px;
             color: rgba(200, 0, 0, 0.08); transform: rotate(-20deg); pointer-events: none; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.sign { margin-top: 18px; border-top: 1px dashed #999; padding-top: 8px; }
@media print { body { margin: 0; } .tile { break-inside: avoid; } tr { break-inside: avoid; } }
"""


def pages(eighths: int) -> str:
    """Length the way schedulers write it: 11 eighths -> "1 3/8"."""
    whole, rest = divmod(eighths, 8)
    if not rest:
        return str(whole)
    return f"{rest}/8" if not whole else f"{whole} {rest}/8"


def date_ar(d) -> str:
    # The date is wrapped left-to-right so 2026-11-01 is not shown reversed inside Arabic text.
    return f'{WEEKDAY_AR[d.weekday()]} <span dir="ltr">{d.isoformat()}</span>'


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


def strip_class(strip: Strip) -> str:
    """Stripboard colours: INT day white, EXT day yellow, INT night blue, EXT night green."""
    outside = "ext" if "خارجي" in strip.scene.int_ext else "int"
    return f"{outside}-{'day' if strip.shift == DAY_SHIFT else 'night'}"


def _page(title: str, body: str) -> str:
    return (f'<!doctype html>\n<html lang="ar" dir="rtl"><head><meta charset="utf-8">'
            f"<title>{escape(title)}</title><style>{CSS}</style></head><body>\n{body}\n</body></html>\n")


def _table(headers: list[str], rows: list[list[str] | str], row_classes: list[str] | None = None) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    out = [f"<table><thead><tr>{head}</tr></thead><tbody>"]
    for i, row in enumerate(rows):
        cls = f' class="{row_classes[i]}"' if row_classes and row_classes[i] else ""
        if isinstance(row, str):  # one cell across the whole table (the day breaks on the stripboard)
            out.append(f'<tr{cls}><td colspan="{len(headers)}">{row}</td></tr>')
        else:
            out.append(f"<tr{cls}>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def cast_ids(summary: BudgetSummary) -> dict[str, int]:
    """Cast numbers as on a real stripboard: 1 is the actor with the most shoot days."""
    return {a.name: i for i, a in enumerate(summary.actors, start=1)}


# ---------- schedule ----------

def schedule_html(schedule: Schedule, title: str) -> str:
    summary = budget_summary(schedule)
    s = schedule.settings
    days_off = "، ".join(WEEKDAY_AR[d] for d in sorted(s.days_off)) or "لا يوجد"
    body = [
        f"<h1>جدول التصوير المبدئي: {escape(title)}</h1>",
        (f'<p class="sub">يبدأ {date_ar(s.start)} · العطلة: {days_off} · الحد في اليوم: {s.max_scenes} مشاهد'
         f" و{pages(s.max_eighths)} صفحات و{s.max_sites} موقع</p>"),
        f'<div class="draft">{escape(DRAFT_NOTE)}</div>',
        '<p class="synthetic">نص وبيانات اصطناعية للتجربة: لا تخص أي إنتاج حقيقي.</p>',
        _tiles(summary),
        "<h2>لوحة المشاهد (Stripboard)</h2>",
        LEGEND,
    ]
    rows, classes = [], []
    for day in schedule.days:
        rows.append(f"اليوم {day.number} · {date_ar(day.date)} · وردية {day.shift} · {len(day.strips)} مشاهد"
                    f" · {pages(day.eighths)} صفحة · تنقلات بين المواقع: {day.moves}")
        classes.append("daybreak")
        shown_notes: set[str] = set()  # a place note is shown once per day, not on every strip
        for strip in day.strips:
            sc = strip.scene
            flags = "".join(f'<div class="flag">⚠ {escape(f)}</div>' for f in strip.flags)
            flags += "".join(f'<div class="sub">{escape(n)}</div>' for n in strip.place_notes if n not in shown_notes)
            shown_notes.update(strip.place_notes)
            rows.append([f'<span class="num">{sc.scene_number}</span>', escape(sc.int_ext), escape(sc.time_of_day),
                         escape(sc.location), escape(strip.site), pages(sc.length_eighths),
                         escape("، ".join(sc.characters)), flags])
            classes.append(strip_class(strip))
    body.append(_table(["المشهد", "داخلي/خارجي", "الوقت", "المكان في النص", "موقع التصوير", "الطول",
                        "الشخصيات", "ملاحظات"], rows, classes))
    if schedule.unscheduled:
        body.append("<h2>مشاهد لم تُجدول</h2>")
        body.append(_table(["المشهد", "السبب"], [[str(st.number), escape(why)] for st, why in schedule.unscheduled]))
    body.append(budget_html(summary))
    return _page(f"جدول التصوير - {title}", "\n".join(body))


def _tiles(summary: BudgetSummary) -> str:
    tiles = [(summary.shoot_days, "أيام تصوير"), (summary.night_shifts, "ورديات ليلية"),
             (summary.company_moves, "تنقلات بين المواقع"), (len(summary.actors), "ممثلون"),
             (summary.unscheduled, "مشاهد لم تُجدول"), (len(summary.flagged_scenes), "مشاهد تحتاج مراجعة")]
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><b class="num">{n}</b><span>{escape(label)}</span></div>' for n, label in tiles) + "</div>"


def budget_html(summary: BudgetSummary) -> str:
    ids = cast_ids(summary)
    parts = ["<h2>ملخص يهم الميزانية</h2>",
             (f"<p>{summary.shoot_days} أيام تصوير: {summary.day_shifts} نهارية و{summary.night_shifts} ليلية"
              f" ({summary.night_scenes} مشهد ليلي). تنقلات الطاقم بين المواقع داخل اليوم: {summary.company_moves}."
              f" انتقال من وردية ليلية إلى نهارية في اليوم التالي: {summary.night_to_day_turnarounds}.</p>"),
             "<h2>أيام عمل كل ممثل</h2>",
             _table(["رقم", "الشخصية", "أيام العمل", "الأيام", "أيام انتظار"],
                    [[str(ids[a.name]), escape(a.name), str(len(a.days)), "، ".join(map(str, a.days)),
                      str(a.hold_days)] for a in summary.actors]),
             HOLD_DAYS_NOTE,
             "<h2>أيام كل موقع</h2>",
             _table(["موقع التصوير", "عدد الأيام"], [[escape(k), str(v)] for k, v in summary.site_days.items()])]
    for label, items in (("الكومبارس", summary.extras_days), ("المركبات", summary.vehicle_days),
                         ("الحيوانات", summary.animal_days)):
        if items:
            parts.append(f"<h2>{label} حسب اليوم</h2>")
            parts.append(_table(["اليوم", label], [[str(d), escape("، ".join(x))] for d, x in items]))
    return "\n".join(parts)


def write_schedule_csv(schedule: Schedule, path: Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # BOM so Excel shows Arabic
        w = csv.writer(f)
        w.writerow(["اليوم", "التاريخ", "الوردية", "الترتيب", "رقم المشهد", "داخلي/خارجي", "الوقت", "المكان",
                    "موقع التصوير", "الطول (أثمان صفحة)", "الشخصيات", "ملاحظات"])
        for day in schedule.days:
            for i, strip in enumerate(day.strips, start=1):
                sc = strip.scene
                w.writerow([day.number, day.date.isoformat(), day.shift, i, sc.scene_number, sc.int_ext,
                            sc.time_of_day, sc.location, strip.site, sc.length_eighths, "، ".join(sc.characters),
                            " | ".join(strip.flags)])
        for strip, why in schedule.unscheduled:
            w.writerow(["لم يُجدول", "", strip.shift, "", strip.number, strip.scene.int_ext, strip.scene.time_of_day,
                        strip.scene.location, strip.site, strip.scene.length_eighths,
                        "، ".join(strip.scene.characters), why])


def budget_markdown(summary: BudgetSummary) -> str:
    ids = cast_ids(summary)
    lines = ["# ملخص يهم الميزانية (مسودة)", "",
             "| البند | العدد |", "|---|---|",
             f"| أيام التصوير | {summary.shoot_days} |",
             f"| ورديات نهارية | {summary.day_shifts} |",
             f"| ورديات ليلية | {summary.night_shifts} |",
             f"| مشاهد ليلية | {summary.night_scenes} |",
             f"| تنقلات الطاقم بين المواقع | {summary.company_moves} |",
             f"| انتقال من ليلي إلى نهاري | {summary.night_to_day_turnarounds} |",
             f"| مشاهد لم تُجدول | {summary.unscheduled} |",
             f"| مشاهد تحتاج مراجعة | {len(summary.flagged_scenes)} |",
             "", "## أيام عمل كل ممثل", "",
             "| رقم | الشخصية | أيام العمل | الأيام | أيام انتظار |", "|---|---|---|---|---|"]
    lines += [f"| {ids[a.name]} | {a.name} | {len(a.days)} | {', '.join(map(str, a.days))} | {a.hold_days} |"
              for a in summary.actors]
    lines += ["", "## أيام كل موقع", "", "| موقع التصوير | عدد الأيام |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary.site_days.items()]
    for label, items in (("الكومبارس", summary.extras_days), ("المركبات", summary.vehicle_days),
                         ("الحيوانات", summary.animal_days)):
        if items:
            lines += ["", f"## {label} حسب اليوم", "", f"| اليوم | {label} |", "|---|---|"]
            lines += [f"| {d} | {'، '.join(x)} |" for d, x in items]
    return "\n".join(lines) + "\n"


# ---------- call sheet ----------

def call_sheet_notes(day: ShootDay, schedule: Schedule) -> list[str]:
    """Notes a crew needs for the day, built from the data. Nothing here is invented by a model."""
    notes = []
    for name in day.cast:
        a = schedule.availability.get(name)
        if a and a.note:
            notes.append(f"{name}: {a.note}")
    for strip in day.strips:
        notes += strip.place_notes
    for strip in day.strips:
        sc = strip.scene
        if sc.time_of_day in ("فجر", "غروب"):
            light = "الفجر" if sc.time_of_day == "فجر" else "الغروب"
            notes.append(f"المشهد {sc.scene_number} مرتبط بضوء {light}: الوقت المكتوب تقديري، "
                         f"يُضبط على وقت {light} الفعلي في يوم التصوير")
        if sc.is_flashback:
            notes.append(f"المشهد {sc.scene_number} فلاش باك: أزياء ومكياج الفترة القديمة")
        if sc.animals:
            notes.append(f"المشهد {sc.scene_number}: حيوان في التصوير ({'، '.join(sc.animals)}): يحضر المسؤول عنه")
        notes += [f"⚠ المشهد {sc.scene_number}: {f}" for f in strip.flags]
    return list(dict.fromkeys(notes))


def call_sheet_html(schedule: Schedule, day_number: int, title: str, approved_by: str | None = None) -> str:
    day = next((d for d in schedule.days if d.number == day_number), None)
    if day is None:
        raise ValueError(f"no shoot day {day_number}: the schedule has {len(schedule.days)} days")
    times: CallTimes = call_times(day)
    ids = cast_ids(budget_summary(schedule))
    first_scene = {}
    for strip in day.strips:
        for name in strip.scene.characters:
            first_scene.setdefault(name, strip.number)

    status = (f'<div class="approved">معتمدة من: {escape(approved_by)}</div>' if approved_by
              else f'<div class="watermark">مسودة</div><div class="draft">{escape(DRAFT_NOTE)}</div>')
    meal = f" · الاستراحة {hhmm(times.meal)}" if times.meal else ""
    body = [
        f"<h1>ورقة الاستدعاء: {escape(title)}</h1>",
        (f'<p class="sub">اليوم {day.number} من {len(schedule.days)} · {date_ar(day.date)} · وردية {day.shift}'
         f" · حضور الطاقم <b>{hhmm(times.crew_call)}</b>{meal} · نهاية متوقعة {hhmm(times.wrap)}</p>"),
        status,
        '<p class="synthetic">نص وبيانات اصطناعية للتجربة: لا تخص أي إنتاج حقيقي.</p>',
        "<h2>المواقع</h2>",
        _table(["موقع التصوير", "العنوان", "المشاهد"],
               [[escape(n), escape(schedule.sites[n].address or "يُضاف من مدير المواقع"),
                 "، ".join(str(st.number) for st in day.strips if n in st.site.split(" + "))]
                for n in dict.fromkeys(part for site in day.sites for part in site.split(" + "))]),
        "<h2>المشاهد بالترتيب</h2>",
        _table(["#", "بداية تقديرية", "المشهد", "داخلي/خارجي", "الوقت", "المكان", "الطول", "الشخصيات (بالرقم)",
                "الإكسسوار"],
               [[str(i), hhmm(times.scene_start[st.number]), str(st.number), escape(st.scene.int_ext),
                 escape(st.scene.time_of_day), escape(st.scene.location), pages(st.scene.length_eighths),
                 escape("، ".join(f"{ids.get(c, '?')}. {c}" for c in st.scene.characters)),
                 escape("، ".join(st.scene.props))] for i, st in enumerate(day.strips, start=1)],
               [strip_class(st) for st in day.strips]),
        "<h2>الممثلون</h2>",
        _table(["رقم", "الشخصية", "الممثل", "أول مشهد", "الحضور (مكياج وملابس)", "جاهز في الموقع"],
               [[str(ids.get(name, "?")), escape(name), "—", str(first_scene[name]), f"<b>{hhmm(t)}</b>",
                 hhmm(times.scene_start[first_scene[name]])] for name, t in times.actor_call.items()]),
        '<div class="grid2">',
        _dept("الأزياء والمكياج", day, "costume_makeup"),
        _dept("المركبات", day, "vehicles"),
        _dept("الكومبارس", day, "extras"),
        _dept("المؤثرات والصوت", day, "sfx"),
        "</div>",
        "<h2>ملاحظات</h2>",
        "<ul>" + "".join(f"<li>{escape(n)}</li>" for n in call_sheet_notes(day, schedule)) + "</ul>",
        '<div class="sign">اعتماد مساعد المخرج: ____________ &nbsp;&nbsp; التاريخ: ________</div>',
    ]
    return _page(f"ورقة الاستدعاء - اليوم {day.number}", "\n".join(body))


def _dept(label: str, day: ShootDay, attr: str) -> str:
    rows = [[str(st.number), escape("، ".join(getattr(st.scene, attr)))] for st in day.strips
            if getattr(st.scene, attr)]
    if not rows:
        return f"<div><h2>{label}</h2><p>لا يوجد</p></div>"
    return f"<div><h2>{label}</h2>{_table(['المشهد', label], rows)}</div>"
