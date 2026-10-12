"""Step 4: find the Odoo records the request is talking about (vendor, production, products,
currency).

Vendor matching, in order:
  1. exact match on name or reference (ignoring upper/lower case)  -> use it
  2. fuzzy match on a cleaned-up name                              -> use it only if clearly the best
  3. close-but-not-sure, or several look the same                  -> ask a human
  4. nothing close                                                 -> propose a NEW vendor (needs approval)
We never pick a vendor we're unsure about, and never create one without approval.

Productions (Odoo analytic accounts) are matched the same way, except step 4: the agent never
creates a production. No match means a person picks one from the list. And one extra rule:
a match is only accepted if the season or year numbers agree. "Rimal Al-Khobar season 2"
looks 94% like "Rimal Al-Khobar" (code RML-S1), but it is a different budget, so a person
picks. A production house often has two seasons of one show open at the same time.
"""

import difflib
import re

from . import config

FUZZY_ACCEPT = 0.90     # at or above this, a single best match is accepted
FUZZY_ASK_HUMAN = 0.70  # from here up to FUZZY_ACCEPT, a person must choose
PRODUCT_MATCH = 0.75  # products are lower risk: the matched product is shown on the approval page

GENERIC_PRODUCT = "Production Service"  # used for lines that match no product
# When an item name matches no product, its category picks a better fallback than the generic one.
CATEGORY_PRODUCTS = {
    "equipment_rental": "Equipment Rental",
    "crew_services": "Crew & Freelancer Services",
    "location": "Location Fee",
    "catering": "Catering Service",
    "transport": "Transport Service",
}
COMPANY_WORDS = {"co", "company", "llc", "ltd", "est", "establishment", "inc", "trading", "the"}
# Words around a production name that don't help tell productions apart. Season numbers are
# not lost by dropping "season": production_numbers() checks them separately.
PRODUCTION_WORDS = {"the", "series", "show", "programme", "program", "season", "for"}
# Arabic glues small words onto the next one: لمسلسل = "for the series", والبرنامج = "and the
# programme". This catches مسلسل / برنامج / موسم with any of those prefixes in front.
ARABIC_PRODUCTION_WORD = re.compile(r"^و?[بلك]?(ال|ل)?(مسلسل|برنامج|موسم)$")
# Season numbers people write as words. Keys are after normalize() (so الأول is written الاول).
NUMBER_WORDS = {"one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3,
                "four": 4, "fourth": 4, "five": 5, "fifth": 5,
                "الاول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5}

# Arabic letters that people write in more than one way: أ إ آ -> ا, ة -> ه, ى -> ي
ARABIC_VARIANTS = str.maketrans("أإآةى", "اااهي")


def normalize(name: str, drop: set[str] = COMPANY_WORDS) -> str:
    words = re.sub(r"[^\w\s]", " ", name.lower().translate(ARABIC_VARIANTS)).split()
    return " ".join(w for w in words if w not in drop)


def similarity(a: str, b: str, drop: set[str] = COMPANY_WORDS) -> float:
    return difflib.SequenceMatcher(None, normalize(a, drop), normalize(b, drop)).ratio()


def production_key(name: str) -> str:
    """A production name cleaned up for comparing the name only: "لمسلسل رمال الخبر الموسم ٢"
    -> "رمال الخبر". Loose numbers are dropped here because production_numbers() checks them."""
    return " ".join(w for w in normalize(name, PRODUCTION_WORDS).split()
                    if not (ARABIC_PRODUCTION_WORD.match(w) or w.isdigit() or w in NUMBER_WORDS))


def production_numbers(text: str) -> set[int]:
    """Season or year numbers in a production name or code: "S4" -> {4}, "الموسم ٢" -> {2},
    "season two" -> {2}, "RML-S1" -> {1}. A year counts by its last two digits, so
    "Ramadan 2027" and the code BYT-R27 agree. Arabic-Indic digits like ٢ count too."""
    words = normalize(text, set()).replace("_", " ").split()
    numbers = {int(n) for n in re.findall(r"\d+", " ".join(words))}
    numbers |= {NUMBER_WORDS[w] for w in words if w in NUMBER_WORDS}
    return {n % 100 if n >= 2000 else n for n in numbers}


def resolve_vendor(odoo, vendor_name: str) -> dict:
    """Returns {"status": "matched"|"needs_human"|"new", "partner_id": ..., "candidates": [...]}."""
    vendors = odoo.search_read("res.partner", [("supplier_rank", ">", 0)], ["id", "name", "ref"])

    wanted = vendor_name.strip().lower()
    exact = [v for v in vendors
             if v["name"].strip().lower() == wanted or (v.get("ref") or "").strip().lower() == wanted]
    if len(exact) == 1:
        return {"status": "matched", "partner_id": exact[0]["id"], "name": exact[0]["name"],
                "score": 1.0, "candidates": []}

    scored = sorted(
        ({"id": v["id"], "name": v["name"], "score": round(similarity(vendor_name, v["name"]), 2)}
         for v in vendors),
        key=lambda c: c["score"], reverse=True)
    close = [c for c in scored if c["score"] >= FUZZY_ASK_HUMAN]

    if len(exact) > 1:
        return {"status": "needs_human", "partner_id": None, "candidates": close[:5],
                "reason": "several vendors have exactly this name"}
    if close and close[0]["score"] >= FUZZY_ACCEPT:
        runners_up = [c for c in close[1:] if c["score"] >= FUZZY_ACCEPT]
        if not runners_up:
            best = close[0]
            return {"status": "matched", "partner_id": best["id"], "name": best["name"],
                    "score": best["score"], "candidates": []}
    if close:
        return {"status": "needs_human", "partner_id": None, "candidates": close[:5],
                "reason": "similar vendors found, not sure which one"}
    return {"status": "new", "partner_id": None, "candidates": [],
            "reason": "no similar vendor in Odoo"}


def production_aliases(account: dict) -> list[str]:
    """'Rimal Al-Khobar (رمال الخبر)' with code RML-S1 can be called by any of these:
    the full name, the English part, the Arabic part in brackets, or the code."""
    name = account["name"]
    aliases = [name, re.sub(r"\(.*?\)", "", name).strip(), *re.findall(r"\((.*?)\)", name)]
    if account.get("code"):
        aliases.append(account["code"])
    return [a for a in aliases if a]


def production_accounts(odoo) -> list[dict]:
    """The analytic accounts under the Productions plan."""
    plans = odoo.search_read("account.analytic.plan", [("name", "=", config.PRODUCTION_PLAN)], ["id"])
    if not plans:
        return []
    return odoo.search_read("account.analytic.account", [("plan_id", "=", plans[0]["id"])],
                            ["id", "name", "code"])


def match_production(production_name: str | None, accounts: list[dict]) -> dict:
    """Returns {"status": "matched"|"needs_human", "analytic_id": ..., "candidates": [...]}.
    Never "new": the agent does not create productions."""
    everyone = [{"id": a["id"], "name": a["name"], "code": a.get("code"), "score": None}
                for a in accounts]
    if not production_name:
        return {"status": "needs_human", "analytic_id": None, "candidates": everyone,
                "reason": "the email does not say which production"}

    wanted = production_key(production_name)
    asked = production_numbers(production_name)
    scored = sorted(
        ({"id": a["id"], "name": a["name"], "code": a.get("code"),
          "score": round(max(difflib.SequenceMatcher(None, wanted, production_key(alias)).ratio()
                             for alias in production_aliases(a)), 2)}  # 1.0 = exact
         for a in accounts),
        key=lambda c: c["score"], reverse=True)
    # Only productions whose season/year numbers agree with the email can win. "Season 2" never
    # goes to season 1's account, however alike the names are. No number in the email: all agree.
    numbers = {a["id"]: production_numbers(f"{a['name']} {a.get('code') or ''}") for a in accounts}
    agreeing = [c for c in scored if asked <= numbers[c["id"]]]
    sure = [c for c in agreeing if c["score"] >= FUZZY_ACCEPT]
    if len(sure) == 1:
        best = sure[0]
        return {"status": "matched", "analytic_id": best["id"], "name": best["name"],
                "code": best["code"], "score": best["score"], "candidates": []}
    if not sure and scored and scored[0]["score"] >= FUZZY_ACCEPT:
        best = scored[0]  # same show, but a different season or year: a different budget
        return {"status": "needs_human", "analytic_id": None, "candidates": scored,
                "reason": f"'{production_name}' looks like {best['name']} ({best['code']}), "
                          "but the season or year number is different"}
    # The list of productions is short, so the person always sees all of them, best guess first.
    return {"status": "needs_human", "analytic_id": None, "candidates": scored,
            "reason": f"not sure which production '{production_name}' is"}


def resolve_production(odoo, production_name: str | None) -> dict:
    return match_production(production_name, production_accounts(odoo))


def resolve_products(odoo, item_names: list[str], categories: list[str] | None = None) -> list[dict]:
    """For each item: the best matching product. If none matches, the product for the item's
    category (e.g. Location Fee), and if that is missing too, the generic product. In both
    fallback cases the email's wording becomes the line description."""
    products = odoo.search_read("product.product", [("purchase_ok", "=", True)], ["id", "name"])
    by_name = {p["name"]: p for p in products}
    categories = categories or [None] * len(item_names)
    results = []
    for name, category in zip(item_names, categories):
        best = max(products, key=lambda p: similarity(name, p["name"]), default=None)
        if best and similarity(name, best["name"]) >= PRODUCT_MATCH:
            results.append({"product_id": best["id"], "product_name": best["name"], "free_text": False})
            continue
        fallback = by_name.get(CATEGORY_PRODUCTS.get(category, "")) or by_name.get(GENERIC_PRODUCT)
        results.append({"product_id": fallback["id"] if fallback else None,
                        "product_name": fallback["name"] if fallback else GENERIC_PRODUCT,
                        "free_text": True})
    return results


def resolve_currency(odoo, code: str) -> int | None:
    found = odoo.search_read("res.currency", [("name", "=", code.upper())], ["id"])
    return found[0]["id"] if found else None
