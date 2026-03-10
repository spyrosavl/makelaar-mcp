# makelaar-mcp

Your AI makelaar (real estate agent) for the Dutch housing market. Search [funda.nl](https://www.funda.nl), compare listings, calculate Dutch mortgages, and estimate buying costs — all from Claude.

[![PyPI](https://img.shields.io/pypi/v/makelaar-mcp)](https://pypi.org/project/makelaar-mcp/)
[![CI](https://github.com/spyrosavl/makelaar-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/spyrosavl/makelaar-mcp/actions/workflows/ci.yml)

## Quick start

**Prerequisites:** Install [uv](https://docs.astral.sh/uv/) (Python package runner) if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Claude Code

```bash
claude mcp add makelaar -- uvx makelaar-mcp
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "makelaar": {
      "command": "FULL_PATH_TO_UVX",
      "args": ["makelaar-mcp"]
    }
  }
}
```

Replace `FULL_PATH_TO_UVX` with the output of `which uvx` (e.g. `/Users/you/.local/bin/uvx`). Claude Desktop doesn't inherit your shell PATH, so the full path is required.

Then restart Claude Desktop.

---

## What you can ask

> Search for apartments in Amsterdam under €400k with energy label A or better

> I earn €80,000/year, my partner earns €50,000. Can we afford this €500,000 house? We're first-time buyers, both 29. Include NHG.

> Compare these two listings: https://www.funda.nl/detail/koop/amsterdam/appartement-rapenburgerstraat-103-f/43363178/ and https://www.funda.nl/detail/koop/amsterdam/huis-arendonksingel-54/43363912/

> What are the total buying costs for a €350,000 apartment? I'm a starter, age 27.

> Show me the price history for this listing: https://www.funda.nl/detail/koop/amsterdam/huis-arendonksingel-54/43363912/

---

## Tools

### `search_listings`

Search funda.nl with filters for location, price, area, property type, energy label, and more. Supports multi-city search and pagination (15 results/page).

### `get_listing`

Full property details by listing ID or funda.nl URL.

### `get_price_history`

Historical asking prices, sale prices, and WOZ values for a listing.

### `compare_listings`

Side-by-side comparison of 2–10 properties: price, area, price/m², bedrooms, year built, energy label, garden.

### `calculate_dutch_mortgage`

Dutch-specific mortgage calculator covering:
- **Annuity & linear** mortgage types
- **NHG** (Nationale Hypotheek Garantie) — eligibility, premium, interest discount
- **Hypotheekrenteaftrek** — mortgage interest deduction (36.97%) minus eigenwoningforfait
- **Startersvrijstelling** — 0% transfer tax for first-time buyers age 18–34
- **NIBUD max mortgage** — income-based borrowing limit with partner income and student debt

### `calculate_total_cost`

Itemized breakdown of bijkomende kosten (additional buying costs):

| Cost | Typical amount |
|------|---------------|
| Overdrachtsbelasting (transfer tax) | 0% / 2% / 10.4% |
| Notariskosten (notary) | €1,500 – €2,500 |
| Taxatiekosten (appraisal) | ~€600 |
| Hypotheekadviseur (mortgage advisor) | ~€2,500 |
| Bankgarantie (bank guarantee) | ~€500 |
| Kadaster (land registry) | ~€150 |
| NHG premium (optional) | 0.6% of mortgage |
| Aankoopmakelaar (optional) | ~1.5% of price |

These costs must come from savings — you can't borrow them.

---

## Disclaimer

This project is **not affiliated with, endorsed by, or connected to funda.nl** or Funda B.V. Property data is sourced from third-party services and may be incomplete or outdated.

Mortgage calculations and cost estimates are **approximations for informational purposes only — not financial advice**. Dutch mortgage rules, tax rates, and NHG limits change annually. Always consult a licensed mortgage advisor (*hypotheekadviseur*) before making financial decisions.

See [LICENSE](LICENSE) for the full MIT license.

---

## Acknowledgements

Built on [pyfunda](https://github.com/0xMH/pyfunda) by [0xMH](https://github.com/0xMH) — the Python library that makes funda.nl data accessible.

---

## Development

```bash
git clone https://github.com/spyrosavl/makelaar-mcp.git
cd makelaar-mcp
uv sync
uv run pytest                              # run tests
uv run ruff check src/ tests/              # lint
uv run mcp dev src/makelaar_mcp/server.py  # MCP Inspector
```
