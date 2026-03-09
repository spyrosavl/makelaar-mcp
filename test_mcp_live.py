#!/usr/bin/env python3
"""Live MCP server test harness.

Sends test prompts to Claude CLI with the funda MCP server attached,
captures responses, then uses Claude again to rate each response.
Passed tests are retired from future rounds. Failed tests get a fix
attempt, then are re-tested. Continues until all pass or max rounds hit.

All test+rate pairs within a round run in parallel (ThreadPoolExecutor).

Usage:
    uv run python test_mcp_live.py               # default 20 rounds
    uv run python test_mcp_live.py --rounds 5     # custom round count
    uv run python test_mcp_live.py --workers 8    # custom parallelism
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = str(Path(__file__).resolve().parent)
LOG_FILE = Path(PROJECT_DIR) / "test_mcp_live.log"
MODEL = "claude-haiku-4-5-20251001"  # cheap & fast for testing

MCP_CONFIG = json.dumps({
    "mcpServers": {
        "funda": {
            "command": "uv",
            "args": ["run", "--directory", PROJECT_DIR, "makelaar-mcp"],
        }
    }
})

_log_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Test prompts: each has a prompt and grading criteria
# ---------------------------------------------------------------------------

TEST_CASES: list[dict] = [
    # ------------------------------------------------------------------
    # TIER 1: Data integrity — does the server return correct data?
    # ------------------------------------------------------------------
    {
        "name": "verify_price_per_m2_math",
        "prompt": (
            "Search for apartments in amsterdam for sale. For EACH listing, "
            "verify that the price_per_m2 field equals price ÷ living_area "
            "(integer division). Report any discrepancies. Show the raw numbers."
        ),
        "criteria": (
            "1. At least 10 listings must be shown with their price, area, and price/m² values.\n"
            "2. For EACH listing, the division price ÷ area must be shown or verified.\n"
            "3. If any price_per_m2 does NOT match price ÷ area, it must be flagged.\n"
            "4. If all match, the response must confirm all values are correct.\n"
            "5. Any listings with living_area of 0 or None must be flagged separately."
        ),
    },
    {
        "name": "search_vs_detail_consistency",
        "prompt": (
            "Search for houses in utrecht for sale. Take the first result and "
            "get its full details. Compare EVERY field that appears in both the "
            "search result and the detail view. Are there any differences? List "
            "all fields side by side."
        ),
        "criteria": (
            "1. Search result data must be shown (id, title, price, area, etc).\n"
            "2. Detail result data must be shown for the same listing.\n"
            "3. A side-by-side comparison of overlapping fields must be presented.\n"
            "4. Any differences (e.g. field names, values, missing fields) must be flagged.\n"
            "5. The listing ID used in both calls must match."
        ),
    },
    {
        "name": "empty_location_handling",
        "prompt": (
            "Search for apartments for sale in 'zxqwkjh' (a nonexistent place). "
            "What happens? Then search in '1234ZZ' (invalid postcode). What happens?"
        ),
        "criteria": (
            "1. Results for TWO separate searches must be shown (nonexistent city AND invalid postcode).\n"
            "2. For each, the response must clearly state what was returned (empty results or error).\n"
            "3. The response must NOT fabricate or hallucinate listings.\n"
            "4. The response must acknowledge the locations are invalid or nonexistent.\n"
            "5. Neither search should crash — both must return gracefully."
        ),
    },
    # ------------------------------------------------------------------
    # TIER 2: Server behavior under stress
    # ------------------------------------------------------------------
    {
        "name": "price_history_no_history",
        "prompt": (
            "Search for the newest listing in amsterdam (sort by newest). "
            "Get its price history. Report exactly how many entries the "
            "price history returns and show them all."
        ),
        "criteria": (
            "1. The search must sort by newest to find the most recent listing.\n"
            "2. Price history must be fetched for that specific listing.\n"
            "3. The exact number of price history entries must be reported.\n"
            "4. All entries must be shown (in a table or list).\n"
            "5. The response must NOT invent historical prices that don't exist."
        ),
    },
    {
        "name": "compare_with_bad_id",
        "prompt": (
            "Compare these listings: 99999999 and 88888888. These are fake IDs "
            "that don't exist on funda. What does the tool return?"
        ),
        "criteria": (
            "1. The response must report that the comparison failed or returned errors.\n"
            "2. The error message from the tool must be shown or described.\n"
            "3. The response must NOT fabricate listing details for nonexistent IDs.\n"
            "4. The response should suggest using real IDs (e.g. search first).\n"
            "5. Both IDs must be reported as failed (not just one)."
        ),
    },
    {
        "name": "filter_verification",
        "prompt": (
            "Search for apartments in rotterdam for RENT with price_max=1500 "
            "and area_min=80. Check EVERY result: is any listing priced above "
            "€1,500/month or smaller than 80m²? Report violations."
        ),
        "criteria": (
            "1. Search results with the specified filters must be shown.\n"
            "2. EVERY returned listing must be checked against both filter criteria.\n"
            "3. If any listing violates a filter (price > 1500 or area < 80), it must be flagged.\n"
            "4. If all pass, an explicit 'all results comply' statement must be made.\n"
            "5. The actual price and area of each listing must be shown for verification."
        ),
    },
    # ------------------------------------------------------------------
    # TIER 3: Multi-tool chains
    # ------------------------------------------------------------------
    {
        "name": "detail_then_history_then_mortgage",
        "prompt": (
            "Search for the cheapest house in amsterdam for sale (sort by price_asc). "
            "Get its price history. Then calculate a Dutch mortgage for it with "
            "€48,000 gross annual income. Report which tools you called and in "
            "what order, and show the results of each."
        ),
        "criteria": (
            "1. Data from search, price history, and dutch mortgage must all be shown.\n"
            "2. The cheapest house must be identified (lowest price from search results).\n"
            "3. Price history data must be shown for that specific listing.\n"
            "4. The mortgage calculation must use the actual price of that listing.\n"
            "5. Net monthly payment and max mortgage must be shown."
        ),
    },
    {
        "name": "cross_city_price_comparison",
        "prompt": (
            "Search for apartments for sale in amsterdam, rotterdam, and utrecht "
            "(3 separate searches). For each city, find the median price. "
            "Which city is cheapest? Show ALL prices and the median calculation."
        ),
        "criteria": (
            "1. Results from three separate searches must be shown (one per city).\n"
            "2. All individual listing prices must be shown per city.\n"
            "3. The median must be correctly calculated (middle value when sorted).\n"
            "4. The three medians must be compared and a verdict given.\n"
            "5. The math must be verifiable — sorted prices and median shown."
        ),
    },
    {
        "name": "url_vs_id_listing",
        "prompt": (
            "Search for houses in amsterdam. Take the first result. "
            "Call get_listing with the numeric ID and then with the full URL. "
            "Compare the two responses — are they identical? Show key fields "
            "from both."
        ),
        "criteria": (
            "1. Listing data must be shown from two lookups — one by ID, one by URL.\n"
            "2. Both calls must return data for the same property.\n"
            "3. Key fields from both responses must be shown for comparison.\n"
            "4. Any differences (or confirmation of identical results) must be explicit.\n"
            "5. The URL and ID used must both be shown in the response."
        ),
    },
    {
        "name": "dutch_mortgage_math_verification",
        "prompt": (
            "Calculate a Dutch mortgage for a €500,000 property with exactly:\n"
            "- €100,000 gross annual income\n"
            "- 3.8% annual interest\n"
            "- 25 year term\n"
            "- Not first-time buyer\n\n"
            "Now manually verify the tool's output:\n"
            "1. Loan amount should be €500,000 (100% LTV in NL)\n"
            "2. NHG: 500k > 435k limit, so NOT eligible, effective rate = 3.8%\n"
            "3. Monthly rate = 3.8/100/12\n"
            "4. n = 300 months\n"
            "5. Gross monthly payment via annuity formula\n"
            "6. Tax benefit: (500k × 0.038 - 500k × 0.0035) × 0.3697 / 12\n"
            "7. Net monthly payment = gross - tax benefit\n"
            "8. Max mortgage = 100k × 4.5 = €450,000\n\n"
            "Does the tool's output match your manual calculation? Show both."
        ),
        "criteria": (
            "1. The tool's output values must be shown (loan_amount, gross_monthly_payment, etc).\n"
            "2. A manual calculation must be performed step by step.\n"
            "3. The tool output must be compared against the manual calculation.\n"
            "4. NHG must be reported as NOT eligible (500k > 435k).\n"
            "5. Any discrepancies must be flagged — OR explicit confirmation that values match."
        ),
    },
    # ------------------------------------------------------------------
    # TIER 4: Dutch mortgage calculator
    # ------------------------------------------------------------------
    {
        "name": "dutch_mortgage_nhg_eligibility",
        "prompt": (
            "Calculate a Dutch mortgage for TWO properties:\n"
            "1. €400,000 property, €80,000 gross annual income\n"
            "2. €500,000 property, €100,000 gross annual income\n\n"
            "For each, report: Is NHG eligible? What is the NHG premium? "
            "What is the effective interest rate? The NHG limit is €435,000 — "
            "property 1 should qualify and property 2 should NOT. Verify this."
        ),
        "criteria": (
            "1. Results from two mortgage calculations must be shown.\n"
            "2. Property 1 (€400k) must be reported as NHG eligible with premium shown.\n"
            "3. Property 2 (€500k) must be reported as NHG NOT eligible with €0 premium.\n"
            "4. The effective rate for property 1 must be lower than nominal (NHG discount).\n"
            "5. The effective rate for property 2 must equal the nominal rate (4.5%)."
        ),
    },
    {
        "name": "dutch_mortgage_tax_benefit_math",
        "prompt": (
            "Calculate a Dutch mortgage for a €400,000 property with €80,000 "
            "gross annual income at 4.5% interest, 30 year term.\n\n"
            "Now manually verify the hypotheekrenteaftrek (mortgage interest "
            "deduction) calculation:\n"
            "1. NHG applies (400k < 435k), so effective rate = 4.5% - 0.3% = 4.2%\n"
            "2. Annual interest year 1 = €400,000 × 0.042 = €16,800\n"
            "3. Eigenwoningforfait = WOZ × 0.0035 = €400,000 × 0.0035 = €1,400\n"
            "4. Taxable benefit = €16,800 - €1,400 = €15,400\n"
            "5. Monthly tax benefit = €15,400 × 0.3697 / 12 = ?\n"
            "6. Net monthly payment = gross - tax benefit\n\n"
            "Show the tool output AND your manual calculation. Do they match?"
        ),
        "criteria": (
            "1. The tool's gross_monthly_payment, monthly_tax_benefit, and net_monthly_payment must be shown.\n"
            "2. The manual calculation must follow the 6 steps with actual numbers.\n"
            "3. The tax benefit must approximately match ~€474/month.\n"
            "4. Net payment must equal gross payment minus tax benefit.\n"
            "5. The response must confirm whether tool output matches manual calc."
        ),
    },
    {
        "name": "dutch_mortgage_linear_vs_annuity",
        "prompt": (
            "Calculate a Dutch mortgage for a €350,000 property with €75,000 "
            "income, using BOTH mortgage types:\n"
            "1. Annuity (mortgage_type='annuity')\n"
            "2. Linear (mortgage_type='linear')\n\n"
            "Compare: Which has a lower first-month payment? Which has lower "
            "total interest over the full term? For the linear mortgage, what "
            "is the final monthly payment vs the first? Show all numbers."
        ),
        "criteria": (
            "1. Results from two mortgage calculations must be shown — annuity and linear.\n"
            "2. Both gross monthly payments must be shown.\n"
            "3. The linear first-month payment must be HIGHER than the annuity payment.\n"
            "4. The linear total interest must be LOWER than the annuity total interest.\n"
            "5. The linear final_monthly_payment must be shown and be lower than the first."
        ),
    },
    {
        "name": "dutch_mortgage_starter_exemption",
        "prompt": (
            "Calculate Dutch mortgage for a €450,000 property for THREE buyers:\n"
            "1. First-time buyer, age 28, €70,000 income\n"
            "2. First-time buyer, age 36, €70,000 income\n"
            "3. Non-first-time buyer, age 28, €70,000 income\n\n"
            "Which buyers qualify for the startersvrijstelling (0% transfer tax)? "
            "Show each buyer's transfer tax rate and amount."
        ),
        "criteria": (
            "1. Results from three mortgage calculations must be shown.\n"
            "2. Buyer 1 (first-time, age 28) must have 0% transfer tax / €0 amount.\n"
            "3. Buyer 2 (first-time, age 36) must have 2% transfer tax (age > 34).\n"
            "4. Buyer 3 (not first-time, age 28) must have 2% transfer tax.\n"
            "5. The transfer tax amounts must be numerically correct (0 or €9,000)."
        ),
    },
    {
        "name": "dutch_mortgage_nibud_max_with_student_debt",
        "prompt": (
            "Calculate Dutch mortgage for a €400,000 property for TWO scenarios:\n"
            "1. €80,000 income, no student debt\n"
            "2. €80,000 income, €30,000 student debt\n\n"
            "What is the max mortgage in each case? How much does the student "
            "debt reduce the max mortgage? The penalty formula is: "
            "debt × 0.0045 × 12 × loan_term_years."
        ),
        "criteria": (
            "1. Results from two mortgage calculations must be shown.\n"
            "2. Max mortgage without debt must be shown (~€360,000 = 80k × 4.5).\n"
            "3. Max mortgage with debt must be shown and be LOWER.\n"
            "4. The reduction amount must be shown (30000 × 0.0045 × 12 × 30 = €48,600).\n"
            "5. The difference between the two max mortgages must match ~€48,600."
        ),
    },
    {
        "name": "dutch_mortgage_partner_income",
        "prompt": (
            "Calculate Dutch mortgage for a €600,000 property:\n"
            "1. Single buyer: €80,000 gross income\n"
            "2. With partner: €80,000 + €60,000 partner income\n\n"
            "Since 2024, 100% of partner income counts. Show the max mortgage "
            "for each and the increase from adding the partner."
        ),
        "criteria": (
            "1. Results from two mortgage calculations must be shown.\n"
            "2. Single buyer max mortgage must be ~€360,000 (80k × 4.5).\n"
            "3. With partner max mortgage must be ~€630,000 (140k × 4.5).\n"
            "4. The increase due to partner must be shown (~€270,000).\n"
            "5. Combined income of €140,000 must be reported."
        ),
    },
    # ------------------------------------------------------------------
    # TIER 5: Total cost of ownership
    # ------------------------------------------------------------------
    {
        "name": "total_cost_basic_itemization",
        "prompt": (
            "Calculate the total additional costs (bijkomende kosten) for buying "
            "a €400,000 property in the Netherlands. I am NOT a first-time buyer. "
            "No buyer's agent. No NHG. Show every cost item with its amount."
        ),
        "criteria": (
            "1. The response must show a breakdown of individual cost items.\n"
            "2. Transfer tax must be 2% = €8,000 (not first-time buyer).\n"
            "3. At least 6 cost items must be shown (transfer tax, notary, appraisal, advisor, bank guarantee, kadaster).\n"
            "4. The total additional costs must be the sum of all items.\n"
            "5. The response must state these costs come from savings, not mortgage."
        ),
    },
    {
        "name": "total_cost_starter_vs_investor",
        "prompt": (
            "Calculate total costs for the SAME €400,000 property for THREE buyers:\n"
            "1. First-time buyer, age 28 (startersvrijstelling)\n"
            "2. Regular buyer (not first-time)\n"
            "3. Investor (investment property)\n\n"
            "The transfer tax rates should be 0%, 2%, and 10.4% respectively. "
            "Show each buyer's total costs side by side. How much does the "
            "investor pay MORE than the starter?"
        ),
        "criteria": (
            "1. Results from three total cost calculations must be shown.\n"
            "2. Starter transfer tax must be €0 (0%).\n"
            "3. Regular buyer transfer tax must be €8,000 (2%).\n"
            "4. Investor transfer tax must be €41,600 (10.4%).\n"
            "5. The difference between investor and starter total costs must be shown (~€41,600)."
        ),
    },
    {
        "name": "total_cost_with_all_options",
        "prompt": (
            "Calculate total costs for a €350,000 property with ALL options:\n"
            "- First-time buyer, age 25\n"
            "- NHG (mortgage amount €350,000)\n"
            "- Include buyer's agent\n\n"
            "Show every cost item. NHG premium should be €2,100. "
            "Buyer's agent should be €5,250. Transfer tax should be €0."
        ),
        "criteria": (
            "1. Total cost results with all options enabled must be shown.\n"
            "2. Transfer tax must be €0 (starter exemption).\n"
            "3. NHG premium must be €2,100 (0.6% of €350,000).\n"
            "4. Buyer's agent must be €5,250 (1.5% of €350,000).\n"
            "5. Total cash needed must be the correct sum of all items."
        ),
    },
    # ------------------------------------------------------------------
    # TIER 6: Multi-tool chains with new tools
    # ------------------------------------------------------------------
    {
        "name": "search_then_full_dutch_analysis",
        "prompt": (
            "Search for the cheapest apartment in amsterdam for sale (sort by "
            "price_asc). Then:\n"
            "1. Calculate a Dutch mortgage for it (€70,000 income, first-time "
            "buyer, age 30)\n"
            "2. Calculate the total additional costs (first-time buyer, age 30)\n\n"
            "Report: net monthly payment, cash needed for bijkomende kosten, "
            "whether property is within max mortgage, and NHG eligibility."
        ),
        "criteria": (
            "1. The cheapest apartment must be identified with its specific price shown.\n"
            "2. Mortgage results must be shown using that property's actual price.\n"
            "3. Total cost results must be shown using that property's actual price.\n"
            "4. Net monthly payment (after tax benefit) must be reported as a specific € amount.\n"
            "5. Cash needed for bijkomende kosten must be reported as a specific € amount."
        ),
    },
    {
        "name": "mortgage_vs_total_cost_consistency",
        "prompt": (
            "For a €400,000 property (first-time buyer, age 28, €80,000 income):\n"
            "1. Run calculate_dutch_mortgage with is_first_time_buyer=True, buyer_age=28\n"
            "2. Run calculate_total_cost with is_first_time_buyer=True, buyer_age=28, "
            "use_nhg=True, mortgage_amount=400000\n\n"
            "Verify consistency: the NHG premium should be the same in both "
            "tools (€2,400). The transfer tax should be €0 in both. Are they consistent?"
        ),
        "criteria": (
            "1. Results from BOTH mortgage and total cost calculations must be shown.\n"
            "2. NHG premium from the mortgage result must be €2,400.\n"
            "3. NHG premium from the total cost result must be €2,400.\n"
            "4. Transfer tax must be €0 in both results (starter exemption).\n"
            "5. An explicit statement that the two results are consistent (or any discrepancy)."
        ),
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class TestResult:
    name: str
    prompt: str
    round_num: int = 0
    response: str = ""
    score: int = 0
    feedback: str = ""
    passed: bool = False
    issues: list[str] = field(default_factory=list)


def log(msg: str):
    """Thread-safe append to log file and print."""
    with _log_lock:
        print(msg, flush=True)
        with open(LOG_FILE, "a") as f:
            f.write(msg + "\n")


def run_claude(prompt: str, timeout: int = 120, use_mcp: bool = True,
               model: str | None = None) -> str:
    """Run claude CLI in non-interactive mode."""
    cmd = ["claude", "-p", "--output-format", "text"]
    if model:
        cmd += ["--model", model]
    if use_mcp:
        cmd += ["--mcp-config", MCP_CONFIG]
    cmd += ["--permission-mode", "auto", prompt]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return f"[CLI ERROR] exit code {result.returncode}: {stderr}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return f"[CLI ERROR] Timed out after {timeout}s"
    except FileNotFoundError:
        return "[CLI ERROR] 'claude' not found in PATH"


def rate_response(test: TestResult, criteria: str) -> TestResult:
    """Use claude to rate a response against the test criteria."""
    rating_prompt = f"""You are a strict QA evaluator for an MCP server.
Score ONLY against the numbered criteria below. Nothing else matters.

## Rules for scoring:
- PASS/FAIL each criterion based ONLY on whether the DATA requirement is met.
- FAIL if numbers are wrong or calculations are not shown when asked.
- FAIL if the response says "I would do X" instead of showing actual results.
- FAIL if data appears clearly fabricated (e.g. round numbers, generic text).
- DO NOT penalize for lack of explicit tool call syntax, function_calls blocks,
  or "evidence of MCP invocation". The AI uses tools internally — you cannot
  see the tool calls. Judge the OUTPUT DATA only.
- DO NOT penalize for formatting choices (tables vs lists, etc).
- A score of 6/10 means "decent but clearly flawed". 8/10 means "good with
  minor issues". 10/10 means "all criteria met".

## Test prompt that was given:
{test.prompt}

## AI response to evaluate:
{test.response[:2500]}

## Grading criteria (each worth 2 points, max 10):
{criteria}

## Your task:
1. For each criterion, write PASS or FAIL with a one-line justification.
2. List concrete issues (not vague — say exactly what's wrong or missing).
3. Return ONLY this JSON (no other text):

{{"score": <0-10>, "passed": <true if score >= 8>, "issues": ["concrete issue 1", "concrete issue 2"], "feedback": "1-2 sentence assessment"}}"""

    raw = run_claude(rating_prompt, timeout=120, use_mcp=False, model=MODEL)

    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        data = json.loads(raw[start:end])
        test.score = data.get("score", 0)
        test.passed = data.get("passed", False)
        test.issues = data.get("issues", [])
        test.feedback = data.get("feedback", "")
    except (ValueError, json.JSONDecodeError):
        test.score = 0
        test.passed = False
        test.issues = [f"Could not parse rating response: {raw[:200]}"]
        test.feedback = "Rating failed"

    return test


def print_separator(char: str = "=", width: int = 70):
    log(char * width)


def print_result(result: TestResult):
    status = "PASS" if result.passed else "FAIL"
    log(f"  [{status}] {result.name}: {result.score}/10")
    if result.feedback:
        log(f"         {result.feedback}")
    for issue in result.issues:
        log(f"         - {issue}")


def run_single_test(tc: dict, round_num: int) -> TestResult:
    """Run a single test case: prompt → response → rate. Thread-safe."""
    name = tc["name"]
    log(f"  [START] {name}")

    response = run_claude(tc["prompt"], timeout=180, model=MODEL)
    test = TestResult(
        name=name, prompt=tc["prompt"],
        round_num=round_num, response=response,
    )

    if response.startswith("[CLI ERROR]"):
        test.score = 0
        test.passed = False
        test.issues = [response]
        test.feedback = "CLI error — could not get response"
    else:
        log(f"  [RATING] {name} ({len(response)} chars)...")
        rate_response(test, tc["criteria"])

    print_result(test)
    return test


def attempt_fix(failures: list[TestResult], round_num: int):
    """Ask Claude to fix server.py based on failure feedback."""
    issues_summary = "\n".join(
        f"- {f.name} (round {f.round_num}): score {f.score}/10. "
        f"Issues: {'; '.join(f.issues[:3])}"
        for f in failures
    )

    fix_prompt = f"""You are debugging an MCP server at {PROJECT_DIR}/src/makelaar_mcp/server.py.

The following test failures were found when testing the server through Claude CLI
(round {round_num}):

{issues_summary}

IMPORTANT CONTEXT:
- These tests send prompts to Claude with this MCP server attached.
- The "issues" describe problems with how Claude presented the MCP tool output.
- Most fixes involve improving tool DESCRIPTIONS (docstrings) to better guide
  Claude's presentation, or fixing the data returned by tools.
- The tool descriptions contain PRESENTATION GUIDELINES that instruct Claude
  how to format responses.

Read the server.py file, identify what might cause these issues, and fix them.
Focus on:
1. Tool descriptions/docstrings that may not guide Claude well enough
2. Missing or None data fields in return values
3. Field name mismatches between pyfunda API and our tool output
4. Error handling that swallows useful information

Only edit src/makelaar_mcp/server.py. Do NOT modify test files.
After fixing, verify with: cd {PROJECT_DIR} && uv run pytest tests/test_server.py"""

    fix_cmd = [
        "claude", "-p",
        "--output-format", "text",
        "--allowedTools", "Read,Edit,Bash,Grep,Glob",
        "--permission-mode", "auto",
        fix_prompt,
    ]

    log("    Running Claude to fix issues...")
    try:
        fix_result = subprocess.run(
            fix_cmd, capture_output=True, text=True, timeout=180
        )
        fix_output = fix_result.stdout.strip()
        log(f"    Fix output ({len(fix_output)} chars):")
        for line in fix_output.split("\n")[-5:]:
            log(f"      {line}")
    except subprocess.TimeoutExpired:
        log("    Fix attempt timed out")
        return
    except FileNotFoundError:
        log("    'claude' CLI not found")
        return

    # Verify unit tests still pass
    log("    Verifying unit tests still pass...")
    verify = subprocess.run(
        ["uv", "run", "pytest", "tests/test_server.py", "-q"],
        capture_output=True, text=True, cwd=PROJECT_DIR, timeout=30,
    )
    last_line = verify.stdout.strip().split("\n")[-1] if verify.stdout.strip() else "no output"
    log(f"    {last_line}")
    if verify.returncode != 0:
        log("    Unit tests broke! Reverting fix attempt.")
        subprocess.run(
            ["git", "checkout", "src/makelaar_mcp/server.py"],
            cwd=PROJECT_DIR, capture_output=True,
        )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_test_suite(max_rounds: int = 20, max_workers: int = 5) -> bool:
    """Run test prompts in parallel, rate, fix, repeat. Retire passed tests."""

    # Clear log
    LOG_FILE.write_text(
        f"makelaar-mcp live test — {max_rounds} rounds, {max_workers} workers\n\n"
    )

    # Track which tests have passed (by name)
    passed_tests: set[str] = set()
    # Track pass history: name -> list of scores
    score_history: dict[str, list[int]] = {tc["name"]: [] for tc in TEST_CASES}
    # Track consecutive passes — require 2 in a row to retire
    consecutive_passes: dict[str, int] = {tc["name"]: 0 for tc in TEST_CASES}

    all_results: list[TestResult] = []

    for round_num in range(1, max_rounds + 1):
        # Determine which tests to run this round
        pending = [tc for tc in TEST_CASES if tc["name"] not in passed_tests]

        if not pending:
            log("\nAll tests retired — every scenario passed twice consecutively!")
            break

        print_separator()
        log(f"ROUND {round_num}/{max_rounds}  "
            f"({len(passed_tests)} retired, {len(pending)} remaining)  "
            f"[{max_workers} parallel workers]")
        print_separator()

        # Run all pending tests in parallel
        round_results: list[TestResult] = []
        round_failures: list[TestResult] = []

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(run_single_test, tc, round_num): tc
                for tc in pending
            }
            for future in as_completed(futures):
                test = future.result()
                round_results.append(test)
                all_results.append(test)
                score_history[test.name].append(test.score)

                if test.passed:
                    consecutive_passes[test.name] += 1
                    if consecutive_passes[test.name] >= 2:
                        passed_tests.add(test.name)
                        log(f"    -> {test.name} RETIRED "
                            f"(passed {consecutive_passes[test.name]}x)")
                    else:
                        log(f"    -> {test.name} passed "
                            f"({consecutive_passes[test.name]}/2 to retire)")
                else:
                    consecutive_passes[test.name] = 0
                    round_failures.append(test)

        # Round summary
        log("")
        print_separator("-")
        round_passed = len(pending) - len(round_failures)
        log(f"Round {round_num}: {round_passed}/{len(pending)} passed | "
            f"Total retired: {len(passed_tests)}/{len(TEST_CASES)}")
        print_separator("-")

        # Fix if there are failures and more rounds remain
        if round_failures and round_num < max_rounds:
            log(f"\n  {len(round_failures)} failures — attempting fix...")
            attempt_fix(round_failures, round_num)
        elif not round_failures:
            log("  All pending tests passed this round!")

    # Final report
    log("")
    print_separator("=")
    log("FINAL REPORT")
    print_separator("=")
    log(f"\nRetired (passed): {len(passed_tests)}/{len(TEST_CASES)}")
    for tc in TEST_CASES:
        name = tc["name"]
        scores = score_history[name]
        status = "RETIRED" if name in passed_tests else "FAILING"
        scores_str = " -> ".join(str(s) for s in scores) if scores else "not tested"
        log(f"  [{status}] {name}: {scores_str}")

    remaining = [tc["name"] for tc in TEST_CASES if tc["name"] not in passed_tests]
    if remaining:
        log(f"\nStill failing: {', '.join(remaining)}")

    log(f"\nFull log: {LOG_FILE}")
    return len(passed_tests) == len(TEST_CASES)


if __name__ == "__main__":
    max_rounds = 20
    max_workers = 5
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--rounds" and i < len(sys.argv) - 1:
            max_rounds = int(sys.argv[i + 1])
        elif arg == "--workers" and i < len(sys.argv) - 1:
            max_workers = int(sys.argv[i + 1])
        elif arg == "--model" and i < len(sys.argv) - 1:
            MODEL = sys.argv[i + 1]

    success = run_test_suite(max_rounds=max_rounds, max_workers=max_workers)
    sys.exit(0 if success else 1)
