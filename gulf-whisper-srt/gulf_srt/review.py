"""A one-file HTML review page: play the episode with the draft subtitles under it,
see the QC flags, and click any flag or line to jump to that moment.

It is a plain .html file with no server and nothing loaded from the internet. The media
is linked by a relative path, so keep the page next to the outputs and open it in a browser.
The subtitles are embedded in the page (not loaded from the .vtt), because browsers refuse
to load a subtitle track from a local file.
"""

import html
import json
import os
import re
from pathlib import Path

from gulf_srt.formats import timecode
from gulf_srt.qc import LOOK_FIRST, MISSING, READABILITY, Issue, summary
from gulf_srt.segment import Cue

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".mxf"}
# The page is for Arabic-speaking staff, so its labels are Arabic. The QC details stay in
# English (they are technical and also go into the .qc.md report).
PRIORITY_AR = {LOOK_FIRST: "قد تكون الكلمات خاطئة", READABILITY: "صعبة القراءة", MISSING: "ربما فات حوار"}

_STYLE = """
body { font-family: "Segoe UI", Tahoma, sans-serif; margin: 0; background: #f4f1ea; color: #222; }
header { background: #1d2a38; color: #fff; padding: 14px 24px; }
header h1 { margin: 0; font-size: 20px; }
header p { margin: 4px 0 0; opacity: .8; font-size: 13px; }
main { display: grid; grid-template-columns: 1.3fr 1fr; gap: 18px; padding: 18px 24px; }
section { background: #fff; border-radius: 8px; padding: 14px 16px; box-shadow: 0 1px 3px #0002; }
h2 { font-size: 15px; margin: 0 0 10px; }
video, audio { width: 100%; }
#screen { background: #000; color: #fff; min-height: 96px; display: flex; align-items: center;
  justify-content: center; text-align: center; font-size: 24px; line-height: 1.5; padding: 10px;
  border-radius: 6px; margin-top: 10px; white-space: pre-line; }
.stats { display: flex; gap: 10px; margin-bottom: 12px; }
.stat { flex: 1; background: #f4f1ea; border-radius: 6px; padding: 8px; text-align: center; }
.stat b { display: block; font-size: 22px; }
ol { margin: 0; padding: 0 30px 0 0; max-height: 520px; overflow-y: auto; }
li { margin: 0 0 6px; cursor: pointer; padding: 4px 6px; border-radius: 4px; }
li:hover { background: #eef3f8; }
li.now { background: #fff3c4; }
li.flag { border-right: 4px solid #c0392b; }
.time { font-family: Consolas, monospace; color: #555; direction: ltr; unicode-bidi: isolate; }
.p1 { color: #c0392b; } .p2 { color: #b9770e; } .p3 { color: #2471a3; }
.detail { font-size: 13px; color: #444; }
"""

_SCRIPT = r"""
const media = document.getElementById('media');
const screen = document.getElementById('screen');
const lines = document.querySelectorAll('#dialogue li');
function show(t) {
  const i = CUES.findIndex(c => c.start <= t && t < c.end);
  screen.textContent = i >= 0 ? CUES[i].lines.join('\n') : '';
  lines.forEach((li, k) => li.classList.toggle('now', k === i));
}
function jump(t) { media.currentTime = Math.max(0, t - 0.5); media.play(); }
document.querySelectorAll('[data-t]').forEach(el => el.addEventListener('click', () => jump(+el.dataset.t)));
media.addEventListener('timeupdate', () => show(media.currentTime));
// page.html#t=26 opens at 26 seconds, so a link can point a colleague at one moment
const start = parseFloat((location.hash.match(/t=([\d.]+)/) || [])[1]);
if (!isNaN(start)) { show(start); media.currentTime = start; }
"""


def _isolate_quotes(text: str) -> str:
    """Keep each «Arabic word» in an English sentence in its own direction, so it doesn't
    swap places with the numbers next to it."""
    return re.sub("«([^»]*)»", lambda m: f"«<bdi>{m.group(1)}</bdi>»", text)


def review_page(cues: list[Cue], issues: list[Issue], media: str | Path, output: str | Path, title: str) -> str:
    """Build the page. `media` is linked relative to where the page will be saved."""
    media_link = Path(os.path.relpath(Path(media).resolve(), Path(output).resolve().parent)).as_posix()
    tag = "video" if Path(media).suffix.lower() in VIDEO_EXTENSIONS else "audio"
    s = summary(cues, issues)
    flagged = {i.cue for i in issues if i.cue is not None}
    esc = html.escape

    issue_items = "\n".join(
        f'<li data-t="{i.start:.2f}"><span class="time">{timecode(i.start)}</span> '
        f'<b class="p{i.priority}">{PRIORITY_AR[i.priority]}</b> '
        f'{"السطر " + str(i.cue) if i.cue else "فراغ"}<div class="detail" dir="ltr">{_isolate_quotes(esc(i.detail))}</div></li>'
        for i in issues
    ) or "<li>لا توجد ملاحظات.</li>"
    dialogue_items = "\n".join(
        f'<li data-t="{c.start:.2f}" class="{"flag" if n in flagged else ""}">'
        f'<span class="time">{timecode(c.start)}</span> {esc(c.text)}</li>'
        for n, c in enumerate(cues, start=1)
    )
    cue_data = json.dumps([{"start": c.start, "end": c.end, "lines": c.lines} for c in cues], ensure_ascii=False)
    cue_data = cue_data.replace("</", "<\\/")  # a subtitle containing "</script>" can't end the script early

    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head><meta charset="utf-8"><title>{esc(title)} - subtitle review</title><style>{_STYLE}</style></head>
<body>
<header><h1>{esc(title)}: مراجعة الترجمة المبدئية</h1>
<p>مسودة آلية من gulf-whisper-srt. لا تُسلَّم قبل أن يراجعها محرر.</p></header>
<main>
<section>
<h2>المشاهدة</h2>
<{tag} id="media" controls preload="metadata" src="{esc(media_link)}"></{tag}>
<div id="screen"></div>
<h2 style="margin-top:16px">الحوار كامل (اضغط على أي سطر للانتقال إليه)</h2>
<ol id="dialogue">{dialogue_items}</ol>
</section>
<section>
<h2>ابدأ من هنا: نقاط المراجعة</h2>
<div class="stats">
<div class="stat"><b>{s['cues']}</b>سطر ترجمة</div>
<div class="stat"><b>{s['cues_flagged']}</b>عليها ملاحظة</div>
<div class="stat"><b>{s['share_flagged']:.0%}</b>نسبة المراجعة</div>
</div>
<ol>{issue_items}</ol>
</section>
</main>
<script>const CUES = {cue_data};{_SCRIPT}</script>
</body></html>
"""
