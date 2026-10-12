"""Step 2: link a new email to earlier correspondence. Three tries, most reliable first.

  1. headers     In-Reply-To / References point at a message we already have. Certain.
  2. subject     same subject after removing "Re:/Fwd:/رد:" and normalizing Arabic, AND at
                 least one person in common (so two vendors both writing "Invoice" are NOT
                 joined). For a forward, the forwarded message's own subject and sender count.
  3. meaning     a local multilingual embedding model (multilingual-e5) turns each email into
                 a vector; if the closest earlier email is similar enough (threshold) and
                 shares a participant, link it. Catches replies from a phone with no headers
                 and a new subject.
Every link stores the method, a confidence and a reason a person can read.

An embedding is a list of numbers that represents the meaning of a text, so two texts
about the same thing get vectors that point in nearly the same direction.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from . import config
from .models import Email
from .normalize import normalize_subject

GENERIC_SUBJECTS = {"", "invoice", "فاتوره", "meeting", "اجتماع", "hello", "مرحبا", "request", "طلب",
                    "urgent", "عاجل", "follow up", "متابعه", "update", "تحديث", "no subject"}


@dataclass
class Link:
    thread_id: str
    method: str          # headers / subject / embedding / new
    confidence: float
    reason: str
    matched_email_id: str | None = None

    def as_dict(self) -> dict:
        return vars(self)


class E5Embedder:
    """intfloat/multilingual-e5-base, loaded on first use. Runs on the GPU if there is one."""

    def __init__(self, model_name: str = config.EMBEDDING_MODEL):
        self.model_name = model_name
        self._model = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = SentenceTransformer(self.model_name, device=device)
        # e5 models expect a "query: " prefix for symmetric similarity
        return self._model.encode([f"query: {t}" for t in texts], normalize_embeddings=True,
                                  convert_to_numpy=True).astype(np.float32)


def _addr(s: str) -> str:
    m = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", s or "")
    return m.group(0).lower() if m else ""


def participants(email: Email, ignore: set[str]) -> set[str]:
    people = {email.from_addr, *email.to, *email.cc}
    if email.forwarded:
        people.add(_addr(email.forwarded.get("from", "")))
    return {p for p in people if p and p not in ignore}


def embedding_text(email: Email) -> str:
    fwd = email.forwarded or {}
    return f"{email.subject}\n{email.new_text[:1200]}\n{fwd.get('subject', '')}\n{fwd.get('text', '')[:800]}"


def _days_between(a: str, b: str) -> float:
    try:
        return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 86400
    except ValueError:
        return 0.0


class ThreadLinker:
    def __init__(self, store, embedder=None, ignore_addresses: list[str] | None = None,
                 threshold: float = config.THREAD_SIMILARITY_THRESHOLD,
                 window_days: int = config.THREAD_WINDOW_DAYS):
        self.store = store
        self.embedder = embedder
        self.ignore = {a.lower() for a in ignore_addresses or []}
        self.threshold = threshold
        self.window_days = window_days

    def embed(self, email: Email) -> np.ndarray | None:
        if self.embedder is None:
            return None
        return self.embedder.encode([embedding_text(email)])[0]

    def link(self, email: Email, vector: np.ndarray | None = None) -> Link:
        people = participants(email, self.ignore)

        # 1. headers
        for ref in [email.in_reply_to, *reversed(email.references)]:
            if ref:
                parent = self.store.email_by_message_id(ref)
                if parent:
                    return Link(parent["thread_id"], "headers", 1.0,
                                f"In-Reply-To/References points to {parent['id']}", parent["id"])

        # 2. subject + a shared participant
        subjects = {normalize_subject(email.subject)}
        if email.forwarded:
            subjects.add(normalize_subject(email.forwarded.get("subject", "")))
        subjects -= GENERIC_SUBJECTS
        for thread in self.store.threads():
            if thread["subject_norm"] in subjects and _days_between(thread["last_date"], email.date) <= self.window_days:
                common = people & set(thread["participants_json"] or [])
                if common:
                    return Link(thread["id"], "subject", 0.85,
                                f"same subject '{thread['subject']}' and shared participant {sorted(common)[0]}")

        # 3. meaning (embeddings)
        if vector is not None:
            best, best_sim = None, -1.0
            for row in self.store.emails("embedding IS NOT NULL"):
                if _days_between(row["date"], email.date) > self.window_days:
                    continue
                sim = float(np.dot(vector, np.frombuffer(row["embedding"], dtype=np.float32)))
                if sim > best_sim:
                    best, best_sim = row, sim
            if best is not None and best_sim >= self.threshold:
                thread = self.store.get_thread(best["thread_id"])
                common = people & set(thread["participants_json"] or [])
                if common:
                    return Link(best["thread_id"], "embedding", round(best_sim, 3),
                                f"similar meaning to {best['id']} ({best_sim:.2f} >= {self.threshold}) "
                                f"and shared participant {sorted(common)[0]}", best["id"])

        new_id = "T-" + hashlib.sha256(email.message_id.encode()).hexdigest()[:8]
        return Link(new_id, "new", 1.0, "no earlier message matched")

    def record(self, email: Email, link: Link) -> None:
        """Create the thread or add this email's people and date to it."""
        people = participants(email, self.ignore)
        thread = self.store.get_thread(link.thread_id)
        if thread is None:
            subj = email.forwarded.get("subject") if email.forwarded and email.forwarded.get("subject") else email.subject
            self.store.add_thread(id=link.thread_id, subject_norm=normalize_subject(subj),
                                  subject=re.sub(r"^\s*((re|fwd?|رد)\s*:\s*)+", "", subj, flags=re.I),
                                  participants_json=sorted(people), first_date=email.date,
                                  last_date=email.date)
        else:
            self.store.update_thread(link.thread_id,
                                     participants_json=sorted(set(thread["participants_json"] or []) | people),
                                     last_date=max(thread["last_date"] or "", email.date))

