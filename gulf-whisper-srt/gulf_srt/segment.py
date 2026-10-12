"""Turn timed words into subtitle cues that follow broadcast-style rules.

Whisper gives us words with start/end times. A subtitle editor wants short,
readable blocks: at most two lines of 42 characters, on screen for 1 to 6
seconds, not faster than about 17 characters per second, broken at natural
places (end of a sentence, a comma, a pause), and never overlapping.
"""

from dataclasses import dataclass

# A word ending in one of these closes the sentence, so the cue ends there.
SENTENCE_END = (".", "!", "?", "؟", "…")
# A comma-like mark is a softer break: we only cut there if the cue is already long.
SOFT_BREAK = ("،", ",", "؛", ";", ":")


@dataclass
class Word:
    start: float  # seconds
    end: float  # seconds
    text: str


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]

    @property
    def text(self) -> str:
        return " ".join(self.lines)


@dataclass(frozen=True)
class Rules:
    max_line_chars: int = 42  # Netflix-style limit for Arabic
    min_duration: float = 1.0  # seconds a cue must stay on screen
    max_duration: float = 6.0
    max_cps: float = 17.0  # reading speed: characters per second
    pause_split: float = 0.6  # a silence this long (seconds) starts a new cue
    tiny_cue_chars: int = 8  # cues shorter than this get merged into a neighbour
    merge_max_gap: float = 1.0  # only merge cues that are this close in time


def wrap_lines(text: str, max_chars: int = 42) -> list[str] | None:
    """Split text into one or two lines of at most max_chars.

    For two lines we prefer to break right after punctuation, and otherwise
    where the two lines are closest in length, because balanced lines are
    easier to read. Returns None if the text cannot fit in two lines.
    """
    if len(text) <= max_chars:
        return [text]
    words = text.split()
    best = None
    for i in range(1, len(words)):
        first, second = " ".join(words[:i]), " ".join(words[i:])
        if len(first) <= max_chars and len(second) <= max_chars:
            no_punctuation = not first.endswith(SENTENCE_END + SOFT_BREAK)
            rank = (no_punctuation, abs(len(first) - len(second)))  # False sorts first
            if best is None or rank < best[0]:
                best = (rank, [first, second])
    return best[1] if best else None


def build_cues(words: list[Word], rules: Rules = Rules()) -> list[Cue]:
    """The whole segmentation step: group words, merge tiny cues, fix timing."""
    groups = _group_words(words, rules)
    cues = [_make_cue(group, rules) for group in groups]
    cues = _merge_tiny(cues, rules)
    _fix_timing(cues, rules)
    return cues


def _join(words: list[Word]) -> str:
    return " ".join(w.text for w in words)


def _make_cue(words: list[Word], rules: Rules) -> Cue:
    text = _join(words)
    lines = wrap_lines(text, rules.max_line_chars)
    if lines is None:  # only possible for one huge "word"; keep it rather than lose it
        lines = [text]
    return Cue(words[0].start, words[-1].end, lines)


def _break_reason(current: list[Word], next_word: Word, rules: Rules) -> str | None:
    """Should next_word start a new cue? Returns "limit", "natural" or None.

    "limit" means a hard rule forces a cut (too long to fit or to stay on screen).
    "natural" means there is a good place to cut (a pause or the end of a sentence).
    """
    previous = current[-1]
    if wrap_lines(_join(current + [next_word]), rules.max_line_chars) is None:
        return "limit"  # it would not fit in two lines
    if next_word.end - current[0].start > rules.max_duration:
        return "limit"  # the cue would stay on screen too long
    if next_word.start - previous.end >= rules.pause_split:
        return "natural"  # the speaker paused
    if previous.text.endswith(SENTENCE_END):
        return "natural"  # the sentence ended
    if previous.text.endswith(SOFT_BREAK) and len(_join(current)) >= rules.max_line_chars:
        return "natural"  # a comma, and we already have a full line
    return None


def _best_cut(current: list[Word]) -> int:
    """When a limit forces a cut, look back over the second half of the cue for a
    better spot (after punctuation, or at the longest short pause), so we don't
    cut in the middle of a phrase. Returns how many words stay in this cue."""
    best_index, best_score = len(current), 0.0
    for i in range(max(len(current) // 2, 1), len(current)):
        score = current[i].start - current[i - 1].end  # the pause before word i
        if current[i - 1].text.endswith(SENTENCE_END + SOFT_BREAK):
            score += 1.0  # punctuation is a better place than any pause
        if score > best_score:
            best_index, best_score = i, score
    return best_index if best_score >= 0.2 else len(current)


def _group_words(words: list[Word], rules: Rules) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for word in words:
        reason = _break_reason(current, word, rules) if current else None
        if reason == "natural":
            groups.append(current)
            current = []
        elif reason == "limit":
            cut = _best_cut(current)
            groups.append(current[:cut])
            current = current[cut:]  # the words after the cut move to the next cue
            if current and _break_reason(current, word, rules) == "limit":
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def _is_tiny(cue: Cue, rules: Rules) -> bool:
    return len(cue.text) < rules.tiny_cue_chars or cue.end - cue.start < rules.min_duration


def _try_merge(first: Cue, second: Cue, rules: Rules) -> Cue | None:
    """Join two neighbouring cues if the result still follows the rules."""
    if second.start - first.end > rules.merge_max_gap:
        return None
    if second.end - first.start > rules.max_duration:
        return None
    lines = wrap_lines(first.text + " " + second.text, rules.max_line_chars)
    if lines is None:
        return None
    return Cue(first.start, second.end, lines)


def _merge_tiny(cues: list[Cue], rules: Rules) -> list[Cue]:
    """A one-word flash on screen is hard to read, so glue it to a neighbour."""
    result: list[Cue] = []
    for cue in cues:
        if result and (_is_tiny(result[-1], rules) or _is_tiny(cue, rules)):
            merged = _try_merge(result[-1], cue, rules)
            if merged:
                result[-1] = merged
                continue
        result.append(cue)
    return result


def _fix_timing(cues: list[Cue], rules: Rules) -> None:
    """Stretch short or fast cues into the silence after them, and stop overlaps."""
    for i, cue in enumerate(cues):
        next_start = cues[i + 1].start if i + 1 < len(cues) else float("inf")
        cue.end = min(cue.end, cue.start + rules.max_duration)
        # Long enough to be read: at least min_duration, and at most max_cps.
        needed = max(rules.min_duration, len(cue.text) / rules.max_cps)
        wanted_end = cue.start + min(needed, rules.max_duration)
        if cue.end < wanted_end:
            cue.end = wanted_end
        # Never run into the next cue.
        cue.end = min(cue.end, next_start)
