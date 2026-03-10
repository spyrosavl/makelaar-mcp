"""makelaar-mcp: Your AI makelaar — MCP server for Dutch house hunting on funda.nl."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from funda import Funda

mcp = FastMCP("makelaar")
_client = Funda()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _photo_id_to_url(photo_id: int) -> str:
    """Convert a funda photo integer ID to a full CDN URL.

    e.g. 225504764 → https://cloud.funda.nl/valentina_media/225/504/764.jpg
    """
    s = str(photo_id).zfill(9)
    return f"https://cloud.funda.nl/valentina_media/{s[0:3]}/{s[3:6]}/{s[6:9]}.jpg"


def _trim_listing(listing) -> dict:
    """Return a trimmed dict of key fields from a Listing object.

    Handles both search-result field names (global_id, detail_url, publish_date)
    and full-detail field names (tiny_id, url, publication_date).
    """
    price = listing.get("price") or 0
    area = listing.get("living_area") or 0
    price_per_m2 = (price // area) if area else None
    raw_photos = listing.get("photos") or []
    photo_urls = listing.get("photo_urls") or [
        _photo_id_to_url(p) for p in raw_photos if isinstance(p, int)
    ]
    first_photo_url = photo_urls[0] if photo_urls else None
    detail_url = listing.get("url") or listing.get("detail_url") or ""
    if detail_url and not detail_url.startswith("http"):
        detail_url = "https://www.funda.nl" + detail_url
    return {
        "id": listing.get("tiny_id") or listing.get("global_id"),
        "title": listing.get("title"),
        "city": listing.get("city"),
        "price": price,
        "living_area": area,
        "price_per_m2": price_per_m2,
        "bedrooms": listing.get("bedrooms"),
        "energy_label": listing.get("energy_label"),
        "url": detail_url,
        "publication_date": listing.get("publication_date")
        or listing.get("publish_date"),
        "first_photo_url": first_photo_url,
        "photo_urls": photo_urls,
    }


def _compare_row(listing) -> dict:
    """Return a comparison-focused dict from a Listing object."""
    price = listing.get("price") or 0
    area = listing.get("living_area") or 0
    price_per_m2 = (price // area) if area else None
    return {
        "tiny_id": listing.get("tiny_id"),
        "title": listing.get("title"),
        "city": listing.get("city"),
        "price": price,
        "living_area": area,
        "price_per_m2": price_per_m2,
        "bedrooms": listing.get("bedrooms"),
        "bathrooms": listing.get("bathrooms"),
        "year_built": listing.get("year_built"),
        "energy_label": listing.get("energy_label"),
        "garden": listing.get("garden"),
        "url": listing.get("url"),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_listings(
    location: str | list[str],
    offering_type: str = "buy",
    price_min: int | None = None,
    price_max: int | None = None,
    area_min: int | None = None,
    area_max: int | None = None,
    object_type: list[str] | None = None,
    energy_label: list[str] | None = None,
    radius_km: int | None = None,
    sort: str = "newest",
    page: int = 0,
) -> list[dict]:
    """Search funda.nl for properties. Returns up to 15 listings per page.

    ALWAYS call this tool immediately — never say "I would search".

    RESPONSE FORMAT: Show a compact table of ALL results with id, title, price,
    m², €/m², beds, link. Report _search_location and _results_on_this_page
    from returned data. Format prices as €350.000.

    When chaining with other tools (e.g. detail, history, mortgage), keep each
    tool's output BRIEF — just key facts, not full reproduction of all data.

    Search results are summaries; detail data is authoritative. Minor
    differences in price_per_m2, URLs, dates between search and detail are
    NORMAL — do not report them as issues.

    PAGINATION: 15/page. Stop when `_has_more` is false.

    Args:
        location: City/neighbourhood/postcode — always lowercase.
        offering_type: "buy" (default) or "rent".
        price_min: Minimum asking price in €.
        price_max: Maximum asking price in €.
        area_min: Minimum living area in m².
        area_max: Maximum living area in m².
        object_type: Property types, e.g. ["house", "apartment"].
        energy_label: Energy labels, e.g. ["A", "A+", "A++"].
        radius_km: Search radius in km.
        sort: "newest" | "price_asc" | "price_desc" | "area_asc" | "area_desc" | "oldest".
        page: 0-indexed page number.
    """
    try:
        # Validate location input
        if not location or (isinstance(location, str) and not location.strip()):
            return [
                {
                    "error": "Empty location provided. Please specify a city, neighbourhood, or postcode (e.g. 'amsterdam', 'utrecht', '1012AB')."
                }
            ]
        if isinstance(location, list) and all(not loc.strip() for loc in location):
            return [
                {
                    "error": "All location values are empty. Please specify at least one city, neighbourhood, or postcode."
                }
            ]
        if isinstance(location, str):
            location = location.lower()
        else:
            location = [loc.lower() for loc in location]
        results = _client.search_listing(
            location=location,
            offering_type=offering_type,
            price_min=price_min,
            price_max=price_max,
            area_min=area_min,
            area_max=area_max,
            object_type=object_type,
            energy_label=energy_label,
            radius_km=radius_km,
            sort=sort,
            page=page,
        )
        PAGE_SIZE = 15
        listings = [_trim_listing(r) for r in results]
        # Build search metadata so Claude can report exact parameters used
        search_meta = {
            "_search_location": location,
            "_offering_type": offering_type,
            "_sort": sort,
            "_page": page,
            "_page_size": PAGE_SIZE,
            "_results_on_this_page": len(listings),
            "_has_more": len(listings) >= PAGE_SIZE,
        }
        # Include non-default filters in metadata
        if price_min is not None:
            search_meta["_price_min"] = price_min
        if price_max is not None:
            search_meta["_price_max"] = price_max
        if area_min is not None:
            search_meta["_area_min"] = area_min
        if area_max is not None:
            search_meta["_area_max"] = area_max
        if object_type is not None:
            search_meta["_object_type"] = object_type
        if energy_label is not None:
            search_meta["_energy_label"] = energy_label
        if radius_km is not None:
            search_meta["_radius_km"] = radius_km
        # Inject search metadata into each listing dict so Claude
        # can see it without changing the list structure.
        for item in listings:
            item.update(search_meta)
        # Also return a summary line when the list is empty so Claude
        # still gets pagination info and knows to stop.
        if not listings:
            return [
                {
                    **search_meta,
                    "_results_on_this_page": 0,
                    "_has_more": False,
                    "info": "No results on this page. This is the last page.",
                }
            ]
        return listings
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


@mcp.tool()
def get_listing(listing_id: str | int) -> dict:
    """Fetch full details for a single funda.nl property listing.

    ALWAYS call this tool immediately — never say "I would look up".

    RESPONSE FORMAT: Show listing id, title, and a key-facts table: price,
    living_area, price_per_m2, bedrooms, energy_label, year_built, url.

    When chaining with other tools (e.g. after search, before history/mortgage),
    keep output BRIEF — just the key facts table, not every returned field.
    This prevents timeouts on multi-tool workflows.

    Detail data is authoritative. Minor differences vs search results are normal.

    Args:
        listing_id: The listing's tinyId or globalId (integer or string), or
                    the full funda.nl URL (e.g. https://www.funda.nl/detail/...).
    """
    try:
        listing = _client.get_listing(listing_id)
        data = listing.to_dict()
        # Add requested_id for traceability and normalize key fields
        data["_requested_id"] = str(listing_id)
        # Ensure consistent field names with search results
        if "tiny_id" in data and "id" not in data:
            data["id"] = data["tiny_id"]
        elif "global_id" in data and "id" not in data:
            data["id"] = data["global_id"]
        # Ensure price_per_m2 is present
        price = data.get("price") or 0
        area = data.get("living_area") or 0
        if "price_per_m2" not in data:
            data["price_per_m2"] = (price // area) if area else None
        return data
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "_requested_id": str(listing_id)}


@mcp.tool()
def get_price_history(listing_id: str | int) -> list[dict]:
    """Fetch the historical price data for a funda.nl property.

    ALWAYS call this tool immediately — never say "I would check".

    RESPONSE FORMAT: Show entry count and a table of ALL entries (newest first):
    Date | Price | Status. Highlight price changes with ↓/↑ amounts.
    If 0 entries: "No price history available."

    When chaining with other tools, keep output BRIEF to avoid timeouts.

    Args:
        listing_id: The listing's tinyId or globalId (integer or string), or
                    the full funda.nl URL.
    """
    try:
        listing = _client.get_listing(listing_id)
        history = _client.get_price_history(listing)
        if not history:
            return [
                {
                    "info": "No price history available for this listing.",
                    "entry_count": 0,
                }
            ]
        # Add entry_count metadata so Claude can report the exact number
        for entry in history:
            entry["_entry_count"] = len(history)
        return history
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


@mcp.tool()
def compare_listings(listing_ids: list[str | int]) -> list[dict]:
    """Fetch 2–10 funda.nl listings for side-by-side comparison.

    ALWAYS call this tool immediately — never describe what you would do.

    RESPONSE FORMAT: Comparison table with columns per property: tiny_id, title,
    price, living_area, price_per_m2, bedrooms, year_built, energy_label.
    Brief verdict. Report any failed IDs.

    Args:
        listing_ids: 2–10 listing IDs (tinyId/globalId integers or funda.nl URLs).
    """
    rows = []
    for lid in listing_ids:
        try:
            listing = _client.get_listing(lid)
            rows.append(_compare_row(listing))
        except Exception as exc:  # noqa: BLE001
            rows.append({"error": str(exc), "requested_id": lid})
    return rows


# 2025 Dutch mortgage constants
_NHG_LIMIT = 435_000
_NHG_PREMIUM_RATE = 0.006
_NHG_INTEREST_DISCOUNT = 0.003  # ~0.3% lower rate
_EIGENWONINGFORFAIT_RATE = 0.0035
_TAX_DEDUCTION_RATE = 0.3697  # 2025 first bracket
_STARTER_PRICE_LIMIT = 510_000
_STARTER_AGE_MIN = 18
_STARTER_AGE_MAX = 34
_NIBUD_BASE_MULTIPLIER = 4.5
_STUDENT_DEBT_FACTOR = 0.0045  # monthly reduction per € of original debt


@mcp.tool()
def calculate_dutch_mortgage(
    price: int,
    gross_annual_income: int,
    partner_income: int | None = None,
    mortgage_type: str = "annuity",
    annual_interest_rate_pct: float = 4.5,
    loan_term_years: int = 30,
    is_first_time_buyer: bool = False,
    buyer_age: int | None = None,
    student_debt: int = 0,
    woz_value: int | None = None,
) -> dict:
    """Calculate Dutch mortgage details for a property purchase.

    Covers: annuity & linear, NHG, hypotheekrenteaftrek, transfer tax
    (startersvrijstelling), and NIBUD max mortgage approximation.

    ALWAYS call this tool immediately — never say "I would calculate".
    For multiple scenarios, call ONCE PER SCENARIO.

    RESPONSE FORMAT: Show net_monthly_payment, gross_monthly_payment,
    monthly_tax_benefit, nhg_eligible/premium, max_mortgage,
    budget_assessment, transfer_tax. Format as €X.XXX.

    If max_mortgage < price, clearly state the shortfall.

    When chaining with other tools, keep output BRIEF to avoid timeouts.
    Show key numbers in a compact table, not every returned field.

    Args:
        price: Property asking price in €.
        gross_annual_income: Buyer's gross annual income in €.
        partner_income: Partner's gross annual income in € (100% counts since 2024).
        mortgage_type: "annuity" (default) or "linear".
        annual_interest_rate_pct: Annual interest rate % (default 4.5%).
        loan_term_years: Mortgage term in years (default 30).
        is_first_time_buyer: True if eligible for startersvrijstelling.
        buyer_age: Buyer's age (needed for starter exemption: 18-34).
        student_debt: Original student debt amount in € (reduces max mortgage).
        woz_value: WOZ value in € (defaults to price if not given).
    """
    try:
        woz = woz_value if woz_value is not None else price
        combined_income = gross_annual_income + (partner_income or 0)

        # --- Max mortgage (NIBUD approximation) ---
        student_debt_monthly_reduction = student_debt * _STUDENT_DEBT_FACTOR
        max_mortgage = round(
            combined_income * _NIBUD_BASE_MULTIPLIER
            - student_debt_monthly_reduction * 12 * loan_term_years
        )
        if max_mortgage < 0:
            max_mortgage = 0

        # --- Loan amount (100% LTV max in NL) ---
        loan_amount = price  # Dutch LTV = 100% of property value

        # --- NHG ---
        nhg_eligible = loan_amount <= _NHG_LIMIT
        rate = annual_interest_rate_pct / 100
        if nhg_eligible:
            nhg_premium = round(loan_amount * _NHG_PREMIUM_RATE)
            effective_rate = max(rate - _NHG_INTEREST_DISCOUNT, 0)
        else:
            nhg_premium = 0
            effective_rate = rate

        # --- Monthly payments ---
        n = loan_term_years * 12
        monthly_rate = effective_rate / 12

        if mortgage_type == "linear":
            # Year 1 payment (highest)
            principal_monthly = loan_amount / n
            first_month_interest = loan_amount * monthly_rate
            gross_monthly_payment = principal_monthly + first_month_interest
            # Final month payment (lowest)
            last_month_interest = principal_monthly * monthly_rate
            final_monthly_payment = principal_monthly + last_month_interest
            # Total interest for linear
            total_interest = sum(
                (loan_amount - i * principal_monthly) * monthly_rate for i in range(n)
            )
            total_paid = loan_amount + total_interest
        else:
            # Annuity
            if monthly_rate == 0:
                gross_monthly_payment = loan_amount / n
            else:
                gross_monthly_payment = (
                    loan_amount
                    * (monthly_rate * (1 + monthly_rate) ** n)
                    / ((1 + monthly_rate) ** n - 1)
                )
            final_monthly_payment = gross_monthly_payment  # constant for annuity
            total_paid = gross_monthly_payment * n
            total_interest = total_paid - loan_amount

        # --- Hypotheekrenteaftrek (mortgage interest deduction, year 1) ---
        annual_interest_yr1 = loan_amount * effective_rate
        eigenwoningforfait = woz * _EIGENWONINGFORFAIT_RATE
        taxable_benefit = annual_interest_yr1 - eigenwoningforfait
        if taxable_benefit > 0:
            monthly_tax_benefit = taxable_benefit * _TAX_DEDUCTION_RATE / 12
        else:
            monthly_tax_benefit = 0

        net_monthly_payment = gross_monthly_payment - monthly_tax_benefit

        # --- Transfer tax ---
        starter_eligible = (
            is_first_time_buyer
            and buyer_age is not None
            and _STARTER_AGE_MIN <= buyer_age <= _STARTER_AGE_MAX
            and price <= _STARTER_PRICE_LIMIT
        )
        if starter_eligible:
            transfer_tax_rate = 0.0
        else:
            transfer_tax_rate = 0.02
        transfer_tax_amount = round(price * transfer_tax_rate)

        # --- Budget assessment ---
        if max_mortgage >= price:
            budget_assessment = f"Affordable: max mortgage €{max_mortgage:,} covers the €{price:,} property price."
        else:
            shortfall = price - max_mortgage
            budget_assessment = (
                f"NOT affordable with mortgage alone: max mortgage €{max_mortgage:,} "
                f"is €{shortfall:,} short of the €{price:,} property price. "
                f"You would need €{shortfall:,} in additional savings or a cheaper property."
            )

        result: dict = {
            # Echo input parameters for traceability
            "input_parameters": {
                "price": price,
                "gross_annual_income": gross_annual_income,
                "partner_income": partner_income,
                "mortgage_type": mortgage_type,
                "annual_interest_rate_pct": annual_interest_rate_pct,
                "loan_term_years": loan_term_years,
                "is_first_time_buyer": is_first_time_buyer,
                "buyer_age": buyer_age,
                "student_debt": student_debt,
                "woz_value": woz_value,
            },
            "property_price": price,
            "mortgage_type": mortgage_type,
            "loan_amount": loan_amount,
            "annual_interest_rate_pct": annual_interest_rate_pct,
            "effective_interest_rate_pct": round(effective_rate * 100, 2),
            "loan_term_years": loan_term_years,
            # NHG
            "nhg_eligible": nhg_eligible,
            "nhg_premium": nhg_premium,
            # Payments (rounded to 2 decimal places for clean display)
            "gross_monthly_payment": round(gross_monthly_payment, 2),
            "monthly_tax_benefit": round(monthly_tax_benefit, 2),
            "net_monthly_payment": round(net_monthly_payment, 2),
            # Totals
            "total_paid": round(total_paid, 2),
            "total_interest": round(total_interest, 2),
            # Transfer tax
            "transfer_tax_rate": transfer_tax_rate,
            "transfer_tax_amount": transfer_tax_amount,
            # NIBUD
            "max_mortgage": max_mortgage,
            "budget_assessment": budget_assessment,
            "max_mortgage_details": {
                "combined_income": combined_income,
                "base_multiplier": _NIBUD_BASE_MULTIPLIER,
                "student_debt_monthly_reduction": round(
                    student_debt_monthly_reduction, 2
                ),
                "max_borrowable": max_mortgage,
            },
        }

        if mortgage_type == "linear":
            result["final_monthly_payment"] = round(final_monthly_payment, 2)

        return result
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def calculate_total_cost(
    purchase_price: int,
    is_first_time_buyer: bool = False,
    buyer_age: int | None = None,
    mortgage_amount: int | None = None,
    use_nhg: bool = False,
    include_buyer_agent: bool = False,
    is_investor: bool = False,
) -> dict:
    """Calculate total additional costs (bijkomende kosten) for a Dutch property
    purchase. These costs must come from savings — you cannot borrow them.

    ALWAYS call this tool immediately — never say "I would calculate".

    RESPONSE FORMAT: Show costs table (item, amount, note), total_additional_costs,
    and cash_needed. Format as €X.XXX.

    When chaining with other tools, keep output BRIEF to avoid timeouts.

    Args:
        purchase_price: Property purchase price in €.
        is_first_time_buyer: True if eligible for startersvrijstelling.
        buyer_age: Buyer's age (needed for starter exemption: 18-34).
        mortgage_amount: Mortgage amount in € (defaults to 100% of purchase_price).
        use_nhg: Include NHG premium in costs?
        include_buyer_agent: Include buyer's agent (aankoopmakelaar) costs?
        is_investor: Investment property? (10.4% transfer tax).
    """
    try:
        mortgage = mortgage_amount if mortgage_amount is not None else purchase_price

        # --- Transfer tax ---
        starter_eligible = (
            is_first_time_buyer
            and buyer_age is not None
            and _STARTER_AGE_MIN <= buyer_age <= _STARTER_AGE_MAX
            and purchase_price <= _STARTER_PRICE_LIMIT
            and not is_investor
        )
        if starter_eligible:
            tax_rate = 0.0
            tax_note = "Startersvrijstelling: 0% (first-time buyer, age 18-34, price ≤ €510.000)"
        elif is_investor:
            tax_rate = 0.104
            tax_note = "Investor rate: 10.4%"
        else:
            tax_rate = 0.02
            tax_note = "Primary residence: 2%"

        costs = []
        costs.append(
            {
                "item": "Overdrachtsbelasting (transfer tax)",
                "amount": round(purchase_price * tax_rate),
                "note": tax_note,
            }
        )
        costs.append(
            {
                "item": "Notariskosten (notary fees)",
                "amount": min(
                    max(round(1_500 + (purchase_price - 200_000) * 0.002), 1_500), 2_500
                ),
                "note": "Transfer deed + mortgage deed",
            }
        )
        costs.append(
            {
                "item": "Taxatiekosten (appraisal)",
                "amount": 600,
                "note": "NWWI-validated, required by lender",
            }
        )
        costs.append(
            {
                "item": "Hypotheekadviseur (mortgage advisor)",
                "amount": 2_500,
                "note": "Standard in NL",
            }
        )
        costs.append(
            {
                "item": "Bankgarantie (bank guarantee)",
                "amount": 500,
                "note": "Or 10% deposit in escrow",
            }
        )
        costs.append(
            {
                "item": "Kadaster (land registry)",
                "amount": 150,
                "note": "Registration fee",
            }
        )

        # Conditional costs
        if use_nhg:
            costs.append(
                {
                    "item": "NHG premium",
                    "amount": round(mortgage * _NHG_PREMIUM_RATE),
                    "note": f"0.6% of mortgage (€{mortgage:,})",
                }
            )
        if include_buyer_agent:
            costs.append(
                {
                    "item": "Aankoopmakelaar (buyer's agent)",
                    "amount": round(purchase_price * 0.015),
                    "note": "~1.5% of purchase price",
                }
            )

        total_additional = sum(c["amount"] for c in costs)

        return {
            "input_parameters": {
                "purchase_price": purchase_price,
                "is_first_time_buyer": is_first_time_buyer,
                "buyer_age": buyer_age,
                "mortgage_amount": mortgage_amount,
                "use_nhg": use_nhg,
                "include_buyer_agent": include_buyer_agent,
                "is_investor": is_investor,
            },
            "purchase_price": purchase_price,
            "costs": costs,
            "total_additional_costs": total_additional,
            "total_including_purchase": purchase_price + total_additional,
            "cash_needed": total_additional,
            "note": "You can borrow up to 100% of the property value, but these additional costs must come from your own savings.",
        }
    except Exception as exc:
        return {"error": str(exc)}


def main() -> None:
    import sys

    transport = "stdio"
    host = "127.0.0.1"
    port = 3000
    for arg in sys.argv[1:]:
        if arg.startswith("--transport="):
            transport = arg.split("=", 1)[1]
        elif arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
        elif arg.startswith("--host="):
            host = arg.split("=", 1)[1]
    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
