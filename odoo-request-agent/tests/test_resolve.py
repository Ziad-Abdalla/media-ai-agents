from odoo_agent.resolve import resolve_currency, resolve_products, resolve_vendor


def test_exact_name_ignoring_case(odoo):
    result = resolve_vendor(odoo, "riyadh grip co")
    assert result["status"] == "matched" and result["name"] == "Riyadh Grip Co"


def test_small_typo_still_matches(odoo):
    result = resolve_vendor(odoo, "Desert Light Rentals")
    assert result["status"] == "matched" and result["name"] == "Desert Lights Rental"


def test_unsure_match_goes_to_a_human(odoo):
    result = resolve_vendor(odoo, "Riyadh Grip and Light")
    assert result["status"] == "needs_human"
    assert result["candidates"]


def test_unknown_vendor_is_proposed_as_new_never_created(odoo):
    before = len(odoo.records["res.partner"])
    result = resolve_vendor(odoo, "Najd Catering House")
    assert result["status"] == "new"
    assert len(odoo.records["res.partner"]) == before  # nothing written


def test_products_fall_back_to_free_text(odoo):
    crane, catering = resolve_products(odoo, ["Camera crane rental", "Crew catering"])
    assert crane["product_name"] == "Camera Crane Rental" and not crane["free_text"]
    assert catering["product_name"] == "Production Service" and catering["free_text"]


def test_currency(odoo):
    assert resolve_currency(odoo, "sar") is not None
    assert resolve_currency(odoo, "EUR") is None
