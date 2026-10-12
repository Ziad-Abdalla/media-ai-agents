"""The staff directory (data/staff.yaml): who works here, what each person is responsible
for, who is away, and who may approve which action."""

import re
from dataclasses import dataclass, field

import yaml

from . import config
from .normalize import normalize_ar


@dataclass
class Person:
    id: str
    name_en: str
    name_ar: str
    email: str
    department: str
    role: str
    role_ar: str = ""
    aliases: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    delegate: str | None = None
    out_of_office: dict | None = None
    can_approve: list[str] = field(default_factory=list)

    def away_on(self, day: str) -> bool:
        """day is 'YYYY-MM-DD'. ISO dates compare correctly as strings."""
        ooo = self.out_of_office
        return bool(ooo and ooo["from"] <= day[:10] <= ooo["to"])


def _contains(haystack_norm: str, needle: str) -> bool:
    """Whole-word match on normalized text (works for Arabic and English)."""
    n = normalize_ar(needle)
    if not n:
        return False
    # Arabic words often carry a prefix like و / ل / ب / ال, so allow those before the word.
    return re.search(rf"(?<![\w])(?:[وفبلك]?(?:ال)?){re.escape(n)}(?![\w])", haystack_norm) is not None


class Directory:
    def __init__(self, path: str = config.STAFF_FILE):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.company = data["company"]
        self.departments: dict = data["departments"]
        self.heads: dict = data["department_heads"]
        self.people = {p["id"]: Person(**p) for p in data["people"]}
        self.by_email = {p.email.lower(): p for p in self.people.values()}

    # ---- addresses ----
    @property
    def company_domains(self) -> list[str]:
        return [d.lower() for d in self.company["domains"]]

    @property
    def allowed_domains(self) -> list[str]:
        """Where the agent may ever send (company + approved partners). Everything else is outside."""
        return self.company_domains + [d.lower() for d in self.company.get("partner_domains", [])]

    def is_internal(self, address: str) -> bool:
        return address.lower().rsplit("@", 1)[-1] in self.company_domains

    def is_allowed_recipient(self, address: str) -> bool:
        return address.lower().rsplit("@", 1)[-1] in self.allowed_domains

    # ---- people ----
    def get(self, person_id: str | None) -> Person | None:
        return self.people.get(person_id or "")

    def head_of(self, department: str) -> Person | None:
        return self.get(self.heads.get(department))

    def available(self, person: Person, day: str) -> tuple[Person, str | None]:
        """The person, or their delegate if they are away that day (with a note why)."""
        if person.away_on(day) and person.delegate and self.get(person.delegate):
            d = self.get(person.delegate)
            return d, (f"{person.name_en} is out of office until {person.out_of_office['to']}; "
                       f"delegate {d.name_en}")
        return person, None

    def mentioned_people(self, text: str) -> list[Person]:
        """Staff named in the text (by English name, Arabic name or alias)."""
        t = normalize_ar(text)
        found = []
        for p in self.people.values():
            names = [p.name_en, p.name_ar, *p.aliases]
            if any(_contains(t, n) for n in names):
                found.append(p)
        return found

    def department_scores(self, text: str) -> dict[str, int]:
        """How many of each department's keywords (and its people's responsibilities) appear."""
        t = normalize_ar(text)
        scores = {}
        for dept, info in self.departments.items():
            words = set(info.get("keywords", []))
            for p in self.people.values():
                if p.department == dept:
                    words.update(p.responsibilities)
            score = sum(1 for w in words if _contains(t, w))
            if score:
                scores[dept] = score
        return scores

    def responsibility_hits(self, person: Person, text: str) -> list[str]:
        t = normalize_ar(text)
        return [w for w in person.responsibilities if _contains(t, w)]

    def can_approve(self, person_id: str, action: str) -> bool:
        p = self.get(person_id)
        return bool(p and action in p.can_approve)

    def approvers(self) -> list[Person]:
        return [p for p in self.people.values() if p.can_approve]

    def prompt_table(self) -> str:
        """Compact directory for the model: id | name | role | department | responsibilities."""
        rows = []
        for p in self.people.values():
            away = (f" | OUT OF OFFICE {p.out_of_office['from']}..{p.out_of_office['to']}, "
                    f"delegate: {p.delegate}") if p.out_of_office else ""
            rows.append(f"{p.id} | {p.name_en} ({p.name_ar}) | {p.role} | {p.department} | "
                        f"{', '.join(p.responsibilities[:8])}{away}")
        return "\n".join(rows)
