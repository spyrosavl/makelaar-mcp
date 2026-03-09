# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

MCP server wrapping [pyfunda](https://pypi.org/project/pyfunda/) so Claude can be a house-hunting assistant for funda.nl. Built with FastMCP. Single-file server at `src/makelaar_mcp/server.py`.

## Commands

```bash
uv sync                                    # Install deps
uv run pytest                              # Run all 34 unit tests
uv run pytest tests/test_server.py::test_name -v  # Run single test
uv run mcp dev src/makelaar_mcp/server.py     # Launch MCP Inspector (interactive)
uv run python test_mcp_live.py --workers 10  # Live integration tests (sends prompts to claude CLI)
```

## Architecture

**Single server file** (`src/makelaar_mcp/server.py`): All tools live here. No submodules.

- **Helpers** (`_trim_listing`, `_compare_row`, `_photo_id_to_url`): Transform pyfunda Listing objects into trimmed JSON-serializable dicts.
- **6 MCP tools**: `search_listings`, `get_listing`, `get_price_history`, `compare_listings`, `calculate_dutch_mortgage`, `calculate_total_cost`.
- **Dutch mortgage constants** (module-level `_UPPER_CASE`): NHG limits, tax rates, NIBUD multipliers — all 2025 values. Update these when regulations change.

**Error handling pattern**: Every tool wraps its body in try/except and returns `{"error": str(exc)}` — tools never raise.

**Tool docstrings are functional**: They contain presentation instructions that guide Claude's response formatting. Changes to docstrings directly affect how Claude presents results.

## Testing

- **Unit tests** (`tests/test_server.py`): Mock `_client` (pyfunda Funda instance) with `unittest.mock.patch`. Use `make_listing()` helper to create mock Listing objects.
- **Live tests** (`test_mcp_live.py`): Sends prompts to `claude -p` with MCP server attached, then uses Claude to grade responses. Uses Haiku model by default (`--model` to override). Grading criteria must focus on **data correctness**, not tool invocation evidence (Haiku text output doesn't show function_calls blocks).

## Key Domain Rules (Dutch Mortgage)

- **100% LTV**: Dutch buyers can borrow 100% of property value (no down payment on the mortgage itself).
- **Bijkomende kosten**: Additional costs (notary, appraisal, advisor, etc.) must come from savings — cannot be borrowed.
- **NHG**: National mortgage guarantee. Limit €435k, premium 0.6%, interest discount ~0.3%.
- **Hypotheekrenteaftrek**: Mortgage interest deduction at 36.97%, minus eigenwoningforfait (0.35% of WOZ).
- **Startersvrijstelling**: 0% transfer tax for first-time buyers age 18-34 on properties ≤ €510k.

## Feature Roadmap

See `FEATURES.md` for Phase 2-3 plans (government APIs: PDOK, CBS, WOZ, flood risk, etc.). Phase 1 (pure computation tools) is complete.
