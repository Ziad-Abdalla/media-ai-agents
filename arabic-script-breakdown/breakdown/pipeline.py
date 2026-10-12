"""Glue: script text -> list of scene breakdowns."""

import os
from concurrent.futures import ThreadPoolExecutor

import anthropic
from agent_cost_tracker import BudgetExceeded
from anthropic import Anthropic
from dotenv import find_dotenv, load_dotenv

from .cast_aliases import KAMERA_JADDI, CastNames
from .extract import DEFAULT_MODEL, ExtractionError, extract_scene
from .schema import SceneBreakdown
from .split import Scene, cast_list, heading_time, split_script


def make_client() -> Anthropic:
    # Looks for .env in this folder and its parents (the key lives in ../.env).
    load_dotenv(find_dotenv(usecwd=True))
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
    return Anthropic()


def breakdown_script(script: str, client, *, model: str = DEFAULT_MODEL, effort: str | None = None,
                     run_id: str | None = None, workers: int = 4,
                     use_cast_list: bool = True,
                     names: CastNames = KAMERA_JADDI) -> tuple[list[SceneBreakdown], list[str]]:
    """Break down every scene. Returns (breakdowns, errors). A failed scene is reported, not fatal.

    use_cast_list=False sends an empty cast list. It exists only for the "cast list removed"
    experiment in the README. names is the alias map of this script's cast.
    """
    preamble, scenes = split_script(script)
    cast = cast_list(preamble) if use_cast_list else ""
    previous = previous_headings(scenes)

    def extract_one(i: int):
        try:
            return extract_scene(client, scenes[i], previous[i], cast,
                                 model=model, effort=effort, run_id=run_id, names=names)
        # ValueError covers bad JSON from pydantic. APIError covers rate limits and network
        # errors after the SDK's own retries. BudgetExceeded means the cost tracker refused
        # the call (no money spent), so the remaining scenes fail fast the same way.
        except (ExtractionError, ValueError, anthropic.APIError, BudgetExceeded) as e:
            return f"scene {scenes[i].number}: {type(e).__name__}: {e}"

    # A few calls at the same time so a 26-scene script takes seconds, not minutes.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(extract_one, range(len(scenes))))
    done = [r for r in results if isinstance(r, SceneBreakdown)]
    errors = [r for r in results if isinstance(r, str)]
    return done, errors


def previous_headings(scenes: list[Scene]) -> list[str | None]:
    """For each scene, the heading of the scene before it (None for the first scene).

    Two متصل scenes in a row: the second one's previous heading also says متصل and has no
    time in it. So in that case we add the last time that was written out.
    Example: ليل, then متصل, then متصل -> the third scene is told the time is ليل.
    """
    result: list[str | None] = [None]
    last_time = heading_time(scenes[0].heading) if scenes else None
    for prev, current in zip(scenes, scenes[1:]):
        if heading_time(prev.heading) is None and heading_time(current.heading) is None and last_time:
            result.append(f"{prev.heading} (its time, carried from earlier scenes: {last_time})")
        else:
            result.append(prev.heading)
        last_time = heading_time(current.heading) or last_time
    return result
