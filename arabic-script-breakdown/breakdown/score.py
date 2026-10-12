"""Compare the agent's breakdown with the gold (hand-checked) breakdown.

Three kinds of field, three ways to score:
- EXACT_FIELDS:    one right answer from a short list (داخلي / خارجي, نهار / ليل ...). Right or wrong.
- LOCATION_FIELDS: free text, so we normalize the Arabic first and allow small wording differences.
- SET_FIELDS:      lists (characters, props). Characters are compared after the alias map;
                   props match when their main noun (first word) is the same. We count what was
                   found, what was missed,
                   and what was invented, then compute precision / recall / F1.

Precision = of the things the agent listed, how many were really there.
Recall    = of the things really there, how many the agent listed.
F1        = one number that is high only when both are high.
"""

from .normalize import canonical_character, normalize_arabic, same_place, same_prop

# Bump this whenever the scoring rules change, so old and new scores are never mixed up.
# v1: props matched by containment. v2: props matched by main noun + synonym list.
SCORER_VERSION = "v2"

EXACT_FIELDS = ["int_ext", "time_of_day"]
LOCATION_FIELDS = ["location"]
SET_FIELDS = ["characters", "props"]
ALL_FIELDS = EXACT_FIELDS + LOCATION_FIELDS + SET_FIELDS


def match_lists(predicted: list[str], gold: list[str], field: str) -> tuple[list, list, list]:
    """Pair up predicted and gold items. Returns (matched, extra, missing)."""
    if field == "characters":
        # Characters: map nicknames to cast names, then compare exactly.
        pred = list(dict.fromkeys(canonical_character(p) for p in predicted))
        gold_left = list(dict.fromkeys(canonical_character(g) for g in gold))
        same = lambda a, b: normalize_arabic(a) == normalize_arabic(b)  # noqa: E731
    else:
        # Props: same main noun ("الكاميرا القديمة" ~ "كاميرا سينما قديمة", "هاتف" ~ "جوال").
        pred = list(dict.fromkeys(predicted))
        gold_left = list(dict.fromkeys(gold))
        same = same_prop

    matched, extra = [], []
    for p in pred:
        hit = next((g for g in gold_left if same(p, g)), None)
        if hit is None:
            extra.append(p)
        else:
            matched.append(p)
            gold_left.remove(hit)  # each gold item can be matched only once
    return matched, extra, gold_left


def score_scene(pred: dict | None, gold: dict) -> dict:
    """Score one scene. pred=None means the agent gave no answer (everything counts as wrong)."""
    pred = pred or {}
    result: dict = {"scene_number": gold["scene_number"]}
    for field in EXACT_FIELDS:
        result[field] = pred.get(field) == gold[field]
    for field in LOCATION_FIELDS:
        result[field] = bool(pred.get(field)) and same_place(pred[field], gold[field])
    for field in SET_FIELDS:
        matched, extra, missing = match_lists(pred.get(field, []), gold[field], field)
        result[field] = {"tp": len(matched), "extra": extra, "missing": missing}
    return result


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def score_run(preds: dict[int, dict], golds: list[dict]) -> dict:
    """Score a whole script. preds maps scene_number -> predicted breakdown.

    Returns per-field scores (accuracy or F1, all between 0 and 1), an overall
    score (the plain average of the fields), and the per-scene results.
    """
    scenes = [score_scene(preds.get(g["scene_number"]), g) for g in golds]
    n = len(scenes)
    fields: dict[str, float] = {}
    detail: dict[str, dict] = {}
    for field in EXACT_FIELDS + LOCATION_FIELDS:
        fields[field] = sum(s[field] for s in scenes) / n
    for field in SET_FIELDS:
        tp = sum(s[field]["tp"] for s in scenes)
        fp = sum(len(s[field]["extra"]) for s in scenes)
        fn = sum(len(s[field]["missing"]) for s in scenes)
        p, r, f1 = prf(tp, fp, fn)
        fields[field] = f1
        detail[field] = {"precision": p, "recall": r, "f1": f1}
    overall = sum(fields.values()) / len(fields)
    return {"fields": fields, "detail": detail, "overall": overall, "scenes": scenes}


def scene_errors(scored_scene: dict, pred: dict | None, gold: dict) -> list[str]:
    """Human-readable list of what went wrong in one scene."""
    pred = pred or {}
    errors = []
    for field in EXACT_FIELDS + LOCATION_FIELDS:
        if not scored_scene[field]:
            errors.append(f"{field}: got {pred.get(field)!r}, expected {gold[field]!r}")
    for field in SET_FIELDS:
        if scored_scene[field]["missing"]:
            errors.append(f"{field} missing: {', '.join(scored_scene[field]['missing'])}")
        if scored_scene[field]["extra"]:
            errors.append(f"{field} extra: {', '.join(scored_scene[field]['extra'])}")
    return errors


def regression_check(current: dict[str, float], baseline: dict[str, float],
                     threshold: float) -> list[str]:
    """The gate. Returns the fields that dropped more than `threshold` vs the accepted baseline.

    An empty list means the new version is allowed to ship.
    """
    failures = []
    for field, old in baseline.items():
        new = current.get(field, 0.0)
        if old - new > threshold:
            failures.append(f"{field}: {old:.3f} -> {new:.3f} (dropped {old - new:.3f})")
    return failures
