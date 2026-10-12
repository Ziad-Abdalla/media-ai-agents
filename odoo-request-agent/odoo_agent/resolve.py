"""Step 4: find the Odoo records the request is talking about (vendor, products, currency).

Vendor matching, in order:
  1. exact match on name or reference (ignoring upper/lower case)  -> use it
  2. fuzzy match on a cleaned-up name                              -> use it only if clearly the best
  3. close-but-not-sure, or several look the same                  -> ask a human
  4. nothing close                                                 -> propose a NEW vendor (needs approval)
We never pick a vendor we're unsure about, and never create one without approval.
"""

import difflib
import re

FUZZY_AUTO = 0.90   # at or above this, a single best match is accepted
FUZZY_GREY = 0.70   # between GREY and AUTO, a human must choose
PRODUCT_MATCH = 0.75  # products are lower risk: a wrong guess is visible on the approval page

GENERIC_PRODUCT = "Production Service"  # used for lines that match no product
COMPANY_WORDS = {"co", "company", "llc", "ltd", "est", "establishment", "inc", "trading", "the"}


def normalize(name: str) -> str:
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in COMPANY_WORDS)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


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
    close = [c for c in scored if c["score"] >= FUZZY_GREY]

    if len(exact) > 1:
        return {"status": "needs_human", "partner_id": None, "candidates": close[:5],
                "reason": "several vendors have exactly this name"}
    if close and close[0]["score"] >= FUZZY_AUTO:
        runners_up = [c for c in close[1:] if c["score"] >= FUZZY_AUTO]
        if not runners_up:
            best = close[0]
            return {"status": "matched", "partner_id": best["id"], "name": best["name"],
                    "score": best["score"], "candidates": []}
    if close:
        return {"status": "needs_human", "partner_id": None, "candidates": close[:5],
                "reason": "similar vendors found, not sure which one"}
    return {"status": "new", "partner_id": None, "candidates": [],
            "reason": "no similar vendor in Odoo"}


def resolve_products(odoo, item_names: list[str]) -> list[dict]:
    """For each item, the best product, or the generic product with the text as description."""
    products = odoo.search_read("product.product", [("purchase_ok", "=", True)], ["id", "name"])
    generic = next((p for p in products if p["name"] == GENERIC_PRODUCT), None)
    results = []
    for name in item_names:
        best = max(products, key=lambda p: similarity(name, p["name"]), default=None)
        if best and similarity(name, best["name"]) >= PRODUCT_MATCH:
            results.append({"product_id": best["id"], "product_name": best["name"], "free_text": False})
        else:
            results.append({"product_id": generic["id"] if generic else None,
                            "product_name": GENERIC_PRODUCT, "free_text": True})
    return results


def resolve_currency(odoo, code: str) -> int | None:
    found = odoo.search_read("res.currency", [("name", "=", code.upper())], ["id"])
    return found[0]["id"] if found else None
