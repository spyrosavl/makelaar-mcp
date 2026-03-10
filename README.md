# makelaar-mcp

Your AI makelaar — an [MCP](https://modelcontextprotocol.io) server for Dutch house hunting on [funda.nl](https://www.funda.nl), powered by [pyfunda](https://pypi.org/project/pyfunda/).

---

## Requirements

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/)

---

## Installation

```bash
git clone <repo-url> ~/makelaar-mcp
cd ~/makelaar-mcp
uv sync
```

---

## Usage

### Run tests

```bash
uv run pytest
```

### Launch MCP Inspector (interactive testing)

```bash
uv run mcp dev src/makelaar_mcp/server.py
```

---

## Integration

### Claude Code (CLI)

```bash
claude mcp add makelaar -- uvx makelaar-mcp
```

That's it. The MCP server is now available in all your Claude Code sessions.

### Claude Desktop

Add the following to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "makelaar": {
      "command": "uvx",
      "args": ["makelaar-mcp"]
    }
  }
}
```

Restart Claude Desktop after saving.

---

## Tools

### `search_listings`

Search funda.nl for properties.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `location` | `str \| list[str]` | required | City, area, or postcode(s) |
| `offering_type` | `"buy" \| "rent"` | `"buy"` | Sale or rental |
| `price_min` | `int \| None` | `None` | Minimum price in € |
| `price_max` | `int \| None` | `None` | Maximum price in € |
| `area_min` | `int \| None` | `None` | Minimum living area in m² |
| `area_max` | `int \| None` | `None` | Maximum living area in m² |
| `object_type` | `list[str] \| None` | `None` | e.g. `["house", "apartment"]` |
| `energy_label` | `list[str] \| None` | `None` | e.g. `["A", "A+"]` |
| `radius_km` | `int \| None` | `None` | Radius from postcode/city |
| `sort` | `str` | `"newest"` | `"newest"`, `"price_asc"`, `"price_desc"`, … |
| `page` | `int` | `0` | Page number (15 results per page) |

Returns a list of listings with: `id`, `title`, `city`, `price`, `living_area`, `price_per_m2`, `bedrooms`, `energy_label`, `url`, `publication_date`.

---

### `get_listing`

Fetch full details for a single listing.

| Parameter | Type | Description |
|-----------|------|-------------|
| `listing_id` | `str \| int` | tinyId, globalId, or full funda.nl URL |

Returns the complete listing dict.

---

### `get_price_history`

Fetch historical price data for a listing (via Walter Living).

| Parameter | Type | Description |
|-----------|------|-------------|
| `listing_id` | `str \| int` | tinyId, globalId, or full funda.nl URL |

Returns a list of entries with: `date`, `price`, `human_price`, `status`, `source`.

---

### `compare_listings`

Fetch 2–10 listings and return them side by side.

| Parameter | Type | Description |
|-----------|------|-------------|
| `listing_ids` | `list[str \| int]` | 2–10 tinyIds, globalIds, or URLs |

Returns one row per listing with: `tiny_id`, `title`, `city`, `price`, `living_area`, `price_per_m2`, `bedrooms`, `bathrooms`, `year_built`, `energy_label`, `garden`, `url`.

---

### `calculate_dutch_mortgage`

Dutch-specific mortgage calculator — annuity & linear, NHG, tax deduction, transfer tax, NIBUD max mortgage.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `price` | `int` | required | Property asking price in € |
| `gross_annual_income` | `int` | required | Buyer's gross annual income in € |
| `partner_income` | `int \| None` | `None` | Partner's gross annual income (100% counts since 2024) |
| `mortgage_type` | `str` | `"annuity"` | `"annuity"` or `"linear"` |
| `annual_interest_rate_pct` | `float` | `4.5` | Annual interest rate % |
| `loan_term_years` | `int` | `30` | Mortgage term in years |
| `is_first_time_buyer` | `bool` | `False` | Eligible for startersvrijstelling? |
| `buyer_age` | `int \| None` | `None` | Needed for starter exemption (18-34) |
| `student_debt` | `int` | `0` | Original student debt in € |
| `woz_value` | `int \| None` | `None` | WOZ value in € (defaults to price) |

Returns: `gross_monthly_payment`, `net_monthly_payment`, `monthly_tax_benefit`, `nhg_eligible`, `nhg_premium`, `max_mortgage`, `transfer_tax_rate`, `transfer_tax_amount`, `budget_assessment`, and more.

---

### `calculate_total_cost`

Calculate bijkomende kosten (additional costs that must come from savings).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `purchase_price` | `int` | required | Property purchase price in € |
| `is_first_time_buyer` | `bool` | `False` | Eligible for startersvrijstelling? |
| `buyer_age` | `int \| None` | `None` | Needed for starter exemption (18-34) |
| `mortgage_amount` | `int \| None` | `None` | Defaults to 100% of purchase price |
| `use_nhg` | `bool` | `False` | Include NHG premium? |
| `include_buyer_agent` | `bool` | `False` | Include aankoopmakelaar costs? |
| `is_investor` | `bool` | `False` | Investment property (10.4% tax)? |

Returns: itemized `costs` list, `total_additional_costs`, `cash_needed`.

---

## Example prompts

```
Search for apartments in Amsterdam under €400k with energy label A or better
```
```
Get the full details for listing 12345678
```
```
Calculate a Dutch mortgage for a €450,000 house with €80,000 income, first-time buyer, age 29
```
```
What are the total additional costs for buying a €350,000 property with NHG?
```
```
Compare listings 11111111 and 22222222
```

---

## Project structure

```
makelaar-mcp/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── FEATURES.md
├── src/
│   └── makelaar_mcp/
│       ├── __init__.py
│       └── server.py       # FastMCP server — 6 tools
└── tests/
    └── test_server.py      # 34 unit tests
```
