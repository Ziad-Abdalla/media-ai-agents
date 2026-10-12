"""Step 4: find the Odoo records the request is talking about (vendor, production, products,
currency).

Vendor matching, in order:
  1. exact match on name or reference (ignoring upper/lower case)  -> use it
  2. fuzzy match on a cleaned-up name                              -> use it only if clearly the best
  3. close-but-not-sure, or several look the same                  -> ask a human
  4. nothing close                                                 -> propose a NEW vendor (needs approval)
We never pick a vendor we're unsure about, and never create one without approval.

Productions (Odoo analytic accounts) are matched the same way, except step 4: the agent never
creates a production. No match means a person picks one from the list.
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
PRODUCTION_WORDS = {"the", "series", "show", "programme", "program", "season", "مسلسل", "برنامج",
                    "الموسم"}

# Arabic letters that people write in more than one way: أ إ آ -> ا, ة -> ه, ى -> ي
ARABIC_VARIANTS = str.maketrans("أإآةى", "اااهي")


def normalize(name: str, drop: set[str] = COMPANY_WORDS) -> str:
    words = re.sub(r"[^\w\s]", " ", name.lower().translate(ARABIC_VARIANTS)).split()
    return " ".join(w for w in words if w not in drop)


def similarity(a: str, b: str, drop: set[str] = COMPANY_WORDS) -> float:
    return difflib.SequenceMatcher(None, normalize(a, drop), normalize(b, drop)).ratio()


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

    wanted = normalize(production_name, PRODUCTION_WORDS)
    exact = [a for a in accounts
             if any(normalize(alias, PRODUCTION_WORDS) == wanted for alias in production_aliases(a))]
    if len(exact) == 1:
        return {"status": "matched", "analytic_id": exact[0]["id"], "name": exact[0]["name"],
                "code": exact[0].get("code"), "score": 1.0, "candidates": []}

    scored = sorted(
        ({"id": a["id"], "name": a["name"], "code": a.get("code"),
          "score": round(max(similarity(production_name, alias, PRODUCTION_WORDS)
                             for alias in production_aliases(a)), 2)}
         for a in accounts),
        key=lambda c: c["score"], reverse=True)
    close = [c for c in scored if c["score"] >= FUZZY_ASK_HUMAN]
    clear_winner = (close and close[0]["score"] >= FUZZY_ACCEPT
                    and not any(c["score"] >= FUZZY_ACCEPT for c in close[1:]))
    if not exact and clear_winner:
        best = close[0]
        return {"status": "matched", "analytic_id": best["id"], "name": best["name"],
                "code": best["code"], "score": best["score"], "candidates": []}
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
