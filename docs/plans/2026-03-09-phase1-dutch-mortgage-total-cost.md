# Phase 1: Dutch Mortgage Calculator + Total Cost of Ownership

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the generic `calculate_affordability` tool with a Dutch-specific mortgage calculator, and add a new `calculate_total_cost` tool for bijkomende kosten.

**Architecture:** Two pure-computation MCP tools in the existing `server.py`. The Dutch mortgage calculator handles annuity/linear payments, NHG, hypotheekrenteaftrek, transfer tax, and NIBUD max mortgage approximation. The total cost tool itemizes all additional costs a buyer must pay from savings. No external APIs — all formulas and constants are hardcoded.

**Tech Stack:** Python 3.11+, FastMCP, pytest, uv

---

## Task 1: Remove old `calculate_affordability` tests

**Files:**
- Modify: `tests/test_server.py:263-315`

**Step 1: Delete old affordability tests**

Remove the three test functions:
- `test_calculate_affordability_basic` (lines 263-283)
- `test_calculate_affordability_with_income` (lines 286-298)
- `test_calculate_affordability_zero_interest` (lines 301-315)

Also remove the section comment `# calculate_affordability` above them (lines 258-261).

**Step 2: Verify remaining tests still pass**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py -v`
Expected: 13 tests pass (the 16 minus 3 removed)

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: remove old calculate_affordability tests"
```

---

## Task 2: Write failing tests for `calculate_dutch_mortgage` — annuity basics

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Write the failing tests**

Add at the end of `tests/test_server.py`:

```python
# ---------------------------------------------------------------------------
# calculate_dutch_mortgage
# ---------------------------------------------------------------------------


def test_dutch_mortgage_annuity_basic_keys():
    """calculate_dutch_mortgage returns all expected keys for a basic annuity mortgage."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
    )

    assert isinstance(result, dict)
    for key in (
        "property_price", "loan_amount", "mortgage_type",
        "gross_monthly_payment", "monthly_tax_benefit", "net_monthly_payment",
        "total_paid", "total_interest",
        "nhg_eligible", "transfer_tax_rate", "transfer_tax_amount",
        "max_mortgage",
    ):
        assert key in result, f"Missing key: {key}"


def test_dutch_mortgage_annuity_payment_math():
    """Annuity payment math is correct: P=400k, r=4.5%, n=30yr."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
        annual_interest_rate_pct=4.5,
        loan_term_years=30,
    )

    # Loan = 100% of price (Dutch max LTV)
    assert result["loan_amount"] == 400_000
    # Standard annuity for P=400000, r=4.5%/12, n=360 → ~2,026.74
    assert result["gross_monthly_payment"] == pytest.approx(2026.74, abs=5)
    assert result["total_paid"] > result["loan_amount"]
    assert result["total_interest"] == pytest.approx(
        result["total_paid"] - result["loan_amount"], rel=1e-6
    )


def test_dutch_mortgage_zero_interest():
    """At 0% interest the monthly payment equals loan / months."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=300_000,
        gross_annual_income=80_000,
        annual_interest_rate_pct=0.0,
        loan_term_years=10,
    )

    expected = 300_000 / (10 * 12)
    assert result["gross_monthly_payment"] == pytest.approx(expected, rel=1e-6)
    assert result["total_interest"] == pytest.approx(0.0, abs=1e-6)
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py::test_dutch_mortgage_annuity_basic_keys tests/test_server.py::test_dutch_mortgage_annuity_payment_math tests/test_server.py::test_dutch_mortgage_zero_interest -v`
Expected: FAIL — `ImportError: cannot import name 'calculate_dutch_mortgage'`

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add failing tests for dutch mortgage annuity basics"
```

---

## Task 3: Implement `calculate_dutch_mortgage` — annuity basics

**Files:**
- Modify: `src/funda_mcp/server.py`

**Step 1: Remove old `calculate_affordability` function**

Delete the entire `calculate_affordability` function (the `@mcp.tool()` decorator, function signature, docstring, and body — lines 338-411 in current server.py).

**Step 2: Add `calculate_dutch_mortgage` in its place**

```python
# 2025 Dutch mortgage constants
_NHG_LIMIT = 435_000
_NHG_LIMIT_ENERGY = 461_100
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

    Covers: annuity & linear mortgages, NHG, hypotheekrenteaftrek (mortgage
    interest deduction), transfer tax (startersvrijstelling), and NIBUD max
    mortgage approximation.

    PRESENTATION GUIDELINES:
    - Lead with net monthly payment (what the buyer actually pays after tax benefit).
    - Show gross vs net payment clearly.
    - Format all monetary values as €X.XXX (Dutch thousands separator).
    - If NHG eligible, highlight the savings (lower rate, premium amount).
    - For linear mortgages, show both year-1 and final-year payments.
    - Show max mortgage and whether the property is within budget.
    - Include transfer tax and starter exemption status.
    - Remind user this is an approximation — advise consulting a hypotheekadviseur.

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
        loan_amount = min(price, max(max_mortgage, price))  # allow full price
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
                (loan_amount - i * principal_monthly) * monthly_rate
                for i in range(n)
            )
            total_paid = loan_amount + total_interest
        else:
            # Annuity
            if monthly_rate == 0:
                gross_monthly_payment = loan_amount / n
            else:
                gross_monthly_payment = loan_amount * (
                    monthly_rate * (1 + monthly_rate) ** n
                ) / ((1 + monthly_rate) ** n - 1)
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

        result: dict = {
            "property_price": price,
            "mortgage_type": mortgage_type,
            "loan_amount": loan_amount,
            "annual_interest_rate_pct": annual_interest_rate_pct,
            "effective_interest_rate_pct": round(effective_rate * 100, 2),
            "loan_term_years": loan_term_years,
            # NHG
            "nhg_eligible": nhg_eligible,
            "nhg_premium": nhg_premium,
            # Payments
            "gross_monthly_payment": gross_monthly_payment,
            "monthly_tax_benefit": monthly_tax_benefit,
            "net_monthly_payment": net_monthly_payment,
            # Totals
            "total_paid": total_paid,
            "total_interest": total_interest,
            # Transfer tax
            "transfer_tax_rate": transfer_tax_rate,
            "transfer_tax_amount": transfer_tax_amount,
            # NIBUD
            "max_mortgage": max_mortgage,
            "max_mortgage_details": {
                "combined_income": combined_income,
                "base_multiplier": _NIBUD_BASE_MULTIPLIER,
                "student_debt_monthly_reduction": student_debt_monthly_reduction,
                "max_borrowable": max_mortgage,
            },
        }

        if mortgage_type == "linear":
            result["final_monthly_payment"] = final_monthly_payment

        return result
    except Exception as exc:
        return {"error": str(exc)}
```

**Step 3: Run tests to verify they pass**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py -v`
Expected: All tests pass (13 old + 3 new = 16)

**Step 4: Commit**

```bash
git add src/funda_mcp/server.py tests/test_server.py
git commit -m "feat: replace calculate_affordability with calculate_dutch_mortgage"
```

---

## Task 4: Write failing tests for `calculate_dutch_mortgage` — NHG

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Write the failing tests**

```python
def test_dutch_mortgage_nhg_eligible():
    """NHG is eligible when loan ≤ €435,000 and applies premium + rate discount."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
    )

    assert result["nhg_eligible"] is True
    assert result["nhg_premium"] == round(400_000 * 0.006)  # €2,400
    # Effective rate should be 0.3% lower than nominal
    assert result["effective_interest_rate_pct"] == pytest.approx(4.5 - 0.3, abs=0.01)


def test_dutch_mortgage_nhg_not_eligible():
    """NHG is not eligible when loan > €435,000."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=500_000,
        gross_annual_income=120_000,
    )

    assert result["nhg_eligible"] is False
    assert result["nhg_premium"] == 0
    assert result["effective_interest_rate_pct"] == pytest.approx(4.5, abs=0.01)
```

**Step 2: Run tests to verify they pass (these should pass immediately since NHG logic is already implemented)**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py::test_dutch_mortgage_nhg_eligible tests/test_server.py::test_dutch_mortgage_nhg_not_eligible -v`
Expected: PASS (NHG logic was implemented in Task 3)

Note: These tests pass immediately because the NHG logic was included in the Task 3 implementation. This is acceptable — they serve as regression tests for the NHG boundary.

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add NHG eligibility tests for dutch mortgage"
```

---

## Task 5: Write failing tests for `calculate_dutch_mortgage` — linear mortgage

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Write the failing test**

```python
def test_dutch_mortgage_linear_payments():
    """Linear mortgage has decreasing payments: first > last."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=300_000,
        gross_annual_income=80_000,
        mortgage_type="linear",
        annual_interest_rate_pct=4.0,
        loan_term_years=30,
    )

    assert result["mortgage_type"] == "linear"
    # Linear first month: principal/n + loan*monthly_rate
    # NHG eligible (300k < 435k), so effective rate = 4.0% - 0.3% = 3.7%
    n = 30 * 12
    principal_monthly = 300_000 / n
    monthly_rate = 0.037 / 12
    expected_first = principal_monthly + 300_000 * monthly_rate
    assert result["gross_monthly_payment"] == pytest.approx(expected_first, abs=1)
    assert "final_monthly_payment" in result
    assert result["final_monthly_payment"] < result["gross_monthly_payment"]
    # Total interest for linear < annuity equivalent
    assert result["total_interest"] > 0
```

**Step 2: Run test to verify it passes**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py::test_dutch_mortgage_linear_payments -v`
Expected: PASS (linear logic was implemented in Task 3)

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add linear mortgage payment test"
```

---

## Task 6: Write failing tests for `calculate_dutch_mortgage` — tax benefit & transfer tax

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Write the failing tests**

```python
def test_dutch_mortgage_tax_benefit():
    """Hypotheekrenteaftrek reduces net payment below gross."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
        annual_interest_rate_pct=4.5,
    )

    assert result["monthly_tax_benefit"] > 0
    assert result["net_monthly_payment"] < result["gross_monthly_payment"]
    # Verify formula: (annual_interest - WOZ*0.0035) * 0.3697 / 12
    # NHG eligible → effective rate = 4.2%
    annual_interest = 400_000 * 0.042
    eigenwoningforfait = 400_000 * 0.0035
    expected_benefit = (annual_interest - eigenwoningforfait) * 0.3697 / 12
    assert result["monthly_tax_benefit"] == pytest.approx(expected_benefit, abs=1)


def test_dutch_mortgage_starter_exemption():
    """First-time buyer age 18-34, price ≤ €510k: 0% transfer tax."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
        is_first_time_buyer=True,
        buyer_age=28,
    )

    assert result["transfer_tax_rate"] == 0.0
    assert result["transfer_tax_amount"] == 0


def test_dutch_mortgage_no_starter_exemption():
    """Non-first-time buyer pays 2% transfer tax."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
        is_first_time_buyer=False,
    )

    assert result["transfer_tax_rate"] == 0.02
    assert result["transfer_tax_amount"] == 8_000
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py::test_dutch_mortgage_tax_benefit tests/test_server.py::test_dutch_mortgage_starter_exemption tests/test_server.py::test_dutch_mortgage_no_starter_exemption -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add tax benefit and transfer tax tests"
```

---

## Task 7: Write failing tests for `calculate_dutch_mortgage` — NIBUD max mortgage & student debt

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Write the failing tests**

```python
def test_dutch_mortgage_max_mortgage_basic():
    """Max mortgage ≈ 4.5x combined income."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
    )

    assert result["max_mortgage"] == round(80_000 * 4.5)  # 360,000
    assert result["max_mortgage_details"]["combined_income"] == 80_000


def test_dutch_mortgage_max_mortgage_with_partner():
    """Partner income is added 100% to combined income."""
    from funda_mcp.server import calculate_dutch_mortgage

    result = calculate_dutch_mortgage(
        price=600_000,
        gross_annual_income=80_000,
        partner_income=60_000,
    )

    assert result["max_mortgage_details"]["combined_income"] == 140_000
    assert result["max_mortgage"] == round(140_000 * 4.5)  # 630,000


def test_dutch_mortgage_student_debt_reduces_max():
    """Student debt reduces max mortgage."""
    from funda_mcp.server import calculate_dutch_mortgage

    result_no_debt = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
        student_debt=0,
    )
    result_with_debt = calculate_dutch_mortgage(
        price=400_000,
        gross_annual_income=80_000,
        student_debt=30_000,
    )

    assert result_with_debt["max_mortgage"] < result_no_debt["max_mortgage"]
    # Reduction: 30000 * 0.0045 = 135/month * 12 * 30 = 48,600
    expected_reduction = 30_000 * 0.0045 * 12 * 30
    assert result_no_debt["max_mortgage"] - result_with_debt["max_mortgage"] == pytest.approx(
        expected_reduction, abs=1
    )
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py -k "max_mortgage" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add NIBUD max mortgage and student debt tests"
```

---

## Task 8: Write failing tests for `calculate_total_cost`

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Write the failing tests**

```python
# ---------------------------------------------------------------------------
# calculate_total_cost
# ---------------------------------------------------------------------------


def test_total_cost_basic_keys():
    """calculate_total_cost returns all expected keys."""
    from funda_mcp.server import calculate_total_cost

    result = calculate_total_cost(purchase_price=400_000)

    assert isinstance(result, dict)
    for key in ("purchase_price", "costs", "total_additional_costs",
                "total_including_purchase", "cash_needed"):
        assert key in result, f"Missing key: {key}"
    assert isinstance(result["costs"], list)
    assert len(result["costs"]) >= 5  # at least the mandatory costs


def test_total_cost_starter_zero_transfer_tax():
    """First-time buyer age 18-34, price ≤ €510k: 0% transfer tax."""
    from funda_mcp.server import calculate_total_cost

    result = calculate_total_cost(
        purchase_price=400_000,
        is_first_time_buyer=True,
        buyer_age=28,
    )

    transfer_tax = next(c for c in result["costs"] if "transfer" in c["item"].lower())
    assert transfer_tax["amount"] == 0


def test_total_cost_investor_transfer_tax():
    """Investor pays 10.4% transfer tax."""
    from funda_mcp.server import calculate_total_cost

    result = calculate_total_cost(
        purchase_price=400_000,
        is_investor=True,
    )

    transfer_tax = next(c for c in result["costs"] if "transfer" in c["item"].lower())
    assert transfer_tax["amount"] == round(400_000 * 0.104)  # €41,600


def test_total_cost_with_nhg():
    """NHG premium is included when use_nhg=True."""
    from funda_mcp.server import calculate_total_cost

    result = calculate_total_cost(
        purchase_price=400_000,
        use_nhg=True,
        mortgage_amount=400_000,
    )

    nhg = next(c for c in result["costs"] if "nhg" in c["item"].lower())
    assert nhg["amount"] == round(400_000 * 0.006)  # €2,400


def test_total_cost_without_nhg():
    """NHG premium is NOT included when use_nhg=False."""
    from funda_mcp.server import calculate_total_cost

    result = calculate_total_cost(purchase_price=400_000, use_nhg=False)

    nhg_items = [c for c in result["costs"] if "nhg" in c["item"].lower()]
    assert len(nhg_items) == 0


def test_total_cost_with_buyer_agent():
    """Buyer's agent cost is included when requested."""
    from funda_mcp.server import calculate_total_cost

    result_without = calculate_total_cost(purchase_price=400_000, include_buyer_agent=False)
    result_with = calculate_total_cost(purchase_price=400_000, include_buyer_agent=True)

    assert result_with["total_additional_costs"] > result_without["total_additional_costs"]
    agent = next(c for c in result_with["costs"] if "makelaar" in c["item"].lower() or "agent" in c["item"].lower())
    assert agent["amount"] == round(400_000 * 0.015)  # 1.5%


def test_total_cost_cash_needed_equals_additional():
    """cash_needed equals total_additional_costs (bijkomende kosten from savings)."""
    from funda_mcp.server import calculate_total_cost

    result = calculate_total_cost(purchase_price=400_000)

    assert result["cash_needed"] == result["total_additional_costs"]
    assert result["total_including_purchase"] == result["purchase_price"] + result["total_additional_costs"]
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py -k "total_cost" -v`
Expected: FAIL — `ImportError: cannot import name 'calculate_total_cost'`

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add failing tests for calculate_total_cost"
```

---

## Task 9: Implement `calculate_total_cost`

**Files:**
- Modify: `src/funda_mcp/server.py`

**Step 1: Add `calculate_total_cost` after `calculate_dutch_mortgage`**

```python
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
    """Calculate the total additional costs (bijkomende kosten) for a Dutch
    property purchase. These costs must come from savings — you cannot borrow
    them.

    PRESENTATION GUIDELINES:
    - Lead with the total cash needed from savings — this is the key number.
    - Show a clear table of all cost items with amounts and notes.
    - Format all monetary values as €X.XXX.
    - Highlight the transfer tax situation (starter exemption, regular, investor).
    - After the table show the total: purchase price + additional costs.
    - Add the rule of thumb: 5-6% without buyer's agent, 7-8% with.
    - Remind user: since 2018 you can borrow 100% of property value, but these
      additional costs must come from your own savings.
    - Offer to run calculate_dutch_mortgage to see monthly payments.

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
        costs.append({
            "item": "Overdrachtsbelasting (transfer tax)",
            "amount": round(purchase_price * tax_rate),
            "note": tax_note,
        })
        costs.append({
            "item": "Notariskosten (notary fees)",
            "amount": min(max(round(1_500 + (purchase_price - 200_000) * 0.002), 1_500), 2_500),
            "note": "Transfer deed + mortgage deed",
        })
        costs.append({
            "item": "Taxatiekosten (appraisal)",
            "amount": 600,
            "note": "NWWI-validated, required by lender",
        })
        costs.append({
            "item": "Hypotheekadviseur (mortgage advisor)",
            "amount": 2_500,
            "note": "Standard in NL",
        })
        costs.append({
            "item": "Bankgarantie (bank guarantee)",
            "amount": 500,
            "note": "Or 10% deposit in escrow",
        })
        costs.append({
            "item": "Kadaster (land registry)",
            "amount": 150,
            "note": "Registration fee",
        })

        # Conditional costs
        if use_nhg:
            costs.append({
                "item": "NHG premium",
                "amount": round(mortgage * _NHG_PREMIUM_RATE),
                "note": f"0.6% of mortgage (€{mortgage:,})",
            })
        if include_buyer_agent:
            costs.append({
                "item": "Aankoopmakelaar (buyer's agent)",
                "amount": round(purchase_price * 0.015),
                "note": "~1.5% of purchase price",
            })

        total_additional = sum(c["amount"] for c in costs)

        return {
            "purchase_price": purchase_price,
            "costs": costs,
            "total_additional_costs": total_additional,
            "total_including_purchase": purchase_price + total_additional,
            "cash_needed": total_additional,
            "note": "You can borrow up to 100% of the property value, but these additional costs must come from your own savings.",
        }
    except Exception as exc:
        return {"error": str(exc)}
```

**Step 2: Run all tests to verify they pass**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py -v`
Expected: All tests pass (13 old + 3 mortgage + 7 total_cost = 23)

**Step 3: Commit**

```bash
git add src/funda_mcp/server.py
git commit -m "feat: add calculate_total_cost tool for bijkomende kosten"
```

---

## Task 10: Error handling test for both new tools

**Files:**
- Modify: `tests/test_server.py`

**Step 1: Write the tests**

```python
def test_dutch_mortgage_error_handling():
    """calculate_dutch_mortgage returns error dict on unexpected input."""
    from funda_mcp.server import calculate_dutch_mortgage

    # Passing string instead of int should be caught
    result = calculate_dutch_mortgage(
        price="not a number",  # type: ignore
        gross_annual_income=80_000,
    )
    assert "error" in result


def test_total_cost_error_handling():
    """calculate_total_cost returns error dict on unexpected input."""
    from funda_mcp.server import calculate_total_cost

    result = calculate_total_cost(purchase_price="not a number")  # type: ignore
    assert "error" in result
```

**Step 2: Run tests**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py -k "error" -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add error handling tests for new tools"
```

---

## Task 11: Final verification

**Step 1: Run full test suite**

Run: `cd /Users/spyros/funda-mcp && uv run pytest tests/test_server.py -v`
Expected: All 25 tests pass

**Step 2: Test in MCP Inspector**

Run: `cd /Users/spyros/funda-mcp && uv run mcp dev src/funda_mcp/server.py --transport streamable-http`

In the Inspector, test:
1. `calculate_dutch_mortgage(price=350000, gross_annual_income=70000, is_first_time_buyer=True, buyer_age=28)` — verify NHG eligible, 0% transfer tax, net payment shown
2. `calculate_dutch_mortgage(price=500000, gross_annual_income=90000, mortgage_type="linear")` — verify NHG ineligible, linear payments, first > final
3. `calculate_total_cost(purchase_price=400000, is_first_time_buyer=True, buyer_age=30, use_nhg=True, include_buyer_agent=True)` — verify 0% tax, NHG included, agent included

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: phase 1 complete — dutch mortgage calculator + total cost of ownership"
```
