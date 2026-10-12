"""Glue: script text -> list of scene breakdowns."""

import os
from concurrent.futures import ThreadPoolExecutor

from anthropic import Anthropic
from dotenv import find_dotenv, load_dotenv

from .extract import DEFAULT_MODEL, ExtractionError, extract_scene
from .schema import SceneBreakdown
from .split import cast_list, split_script


def make_client() -> Anthropic:
    # Looks for .env in this folder and its parents (the key lives in ../.env).
    load_dotenv(find_dotenv(usecwd=True))
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
    return Anthropic()


def breakdown_script(script: str, client, *, model: str = DEFAULT_MODEL, effort: str | None = None,
                     run_id: str | None = None, workers: int = 4,
                     limit: int | None = None) -> tuple[list[SceneBreakdown], list[str]]:
    """Break down every scene. Returns (breakdowns, errors). A failed scene is reported, not fatal."""
    preamble, scenes = split_script(script)
    scenes = scenes[:limit] if limit else scenes
    cast = cast_list(preamble)
    previous = [None] + [s.heading for s in scenes[:-1]]

    def one(i: int):
        try:
            return extract_scene(client, scenes[i], previous[i], cast,
                                 model=model, effort=effort, run_id=run_id)
        except (ExtractionError, ValueError) as e:  # ValueError covers bad JSON from pydantic
            return f"scene {scenes[i].number}: {e}"

    # A few calls at the same time so a 26-scene script takes seconds, not minutes.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, range(len(scenes))))
    done = [r for r in results if isinstance(r, SceneBreakdown)]
    errors = [r for r in results if isinstance(r, str)]
    return done, errors
