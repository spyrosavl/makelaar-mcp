# makelaar-mcp — Feature Roadmap

Research compiled from: Reddit (r/Netherlands, r/NetherlandsHousing, r/Amsterdam, r/expats), competitor analysis (Zillow, Redfin, Trulia), Dutch government open data APIs, and Dutch mortgage/tax regulations.

---

## Tier 1: Pure Computation (no external APIs needed)

### 1. Dutch Mortgage Calculator

**Pain point:** Current calculator is generic. Dutch mortgage rules are complex and buyers (especially expats) don't understand what they can actually afford.

**What to build:** Replace `calculate_affordability` with a Dutch-specific tool covering:

- **Mortgage types:** Annuity vs linear (linear has decreasing payments, lower total interest)
- **NHG (Nationale Hypotheek Garantie):**
  - 2025 limit: €435,000 (€461,100 with energy renovation)
  - Premium: 0.6% of mortgage (one-time, tax-deductible)
  - Interest discount: ~0.2-0.3% lower rate
- **Hypotheekrenteaftrek (mortgage interest deduction):**
  - Interest deductible at 36.97% (2025 first bracket rate)
  - Minus eigenwoningforfait: 0.35% of WOZ value added as income
  - Net monthly benefit = `(annual_interest - WOZ × 0.0035) × 0.3697 / 12`
- **Starter exemption (startersvrijstelling):**
  - First-time buyer, age 18-34, property ≤ €510,000: 0% transfer tax
  - Otherwise: 2% (primary residence) or 10.4% (investor)
- **NIBUD max mortgage:**
  - ~4.5x gross annual income at ~4% rate
  - 100% of partner income counts (since 2024)
  - Student debt: original amount × 0.45% reduces max monthly payment
  - Max LTV: 100% of property value
- **Output:** Gross monthly payment, net monthly payment (after tax benefit), NHG eligibility, max borrowable amount

**Formulas:**
```
Annuity:  M = P × r(1+r)^n / ((1+r)^n - 1)
Linear:   M_i = P/n + (P - (i-1) × P/n) × r
Tax benefit (year 1): (annual_interest - WOZ × 0.0035) × 0.3697 / 12
NHG premium: mortgage × 0.006
```

---

### 2. Total Cost of Ownership (Bijkomende Kosten)

**Pain point:** Buyers get blindsided by €20-30k in additional costs on top of the purchase price. VvE fees and erfpacht are often hidden surprises. ([Reddit #10](https://reddit.com/r/NetherlandsHousing/comments/1kuamcf/))

**What to build:** `calculate_total_cost` tool that itemizes everything:

| Cost | Amount | Notes |
|------|--------|-------|
| Overdrachtsbelasting (transfer tax) | 0% / 2% / 10.4% | Depends on starter status, age, price, investor |
| Notariskosten | ~€1,500 – €2,500 | Transfer deed + mortgage deed |
| Taxatiekosten (appraisal) | ~€400 – €800 | NWWI-validated, required by lender |
| Hypotheekadviseur (mortgage advisor) | ~€1,500 – €3,500 | Standard in NL |
| NHG premium | 0.6% of mortgage | If applicable |
| Bankgarantie | ~€250 – €750 | Or 10% deposit in escrow |
| Kadaster registration | ~€150 | Land registry fee |
| Makelaarskosten (buyer's agent) | ~1-2% of price | Optional |

**Rule of thumb:** 5-6% without buyer's agent, 7-8% with.

**Key insight:** Since 2018 you can borrow 100% of property value, but bijkomende kosten must come from savings. This tool tells buyers exactly how much cash they need.

**Parameters:** `purchase_price`, `is_first_time_buyer`, `age`, `use_nhg`, `mortgage_amount`, `include_buyer_agent`

---

### 3. Overbidding Estimator

**Pain point:** The #1 Reddit complaint. Asking prices are meaningless — Amsterdam sees 8-23% overbidding. Buyers can't figure out what to actually bid. ([Reddit #1, #6](https://reddit.com/r/NetherlandsHousing/comments/1pc9cju/))

**What to build:** `estimate_selling_price` tool that:

1. Fetches the listing's price history (existing tool)
2. Fetches WOZ value (Tier 2 tool) for comparison
3. Computes: asking-to-WOZ ratio, days on market, number of price changes
4. Applies heuristics:
   - Price drops → seller may accept below asking
   - Fresh listing + high demand area → expect overbidding
   - WOZ significantly below asking → overpriced
   - Long time on market → room for negotiation
5. Returns: estimated selling range, suggested offer amount, confidence level

**Data sources:** pyfunda price history, WOZ API (Tier 2), listing metadata (days on market from publication_date).

---

## Tier 2: Free Dutch Government APIs (no API key required)

### 4. Neighborhood Profile

**Pain point:** "Funda shows the house but not the environment." Users want noise, commute, safety, schools — not just the property. ([Reddit #4](https://reddit.com/r/NetherlandsHousing/comments/1ovhi0z/))

**What to build:** `get_neighborhood_profile` tool.

**Architecture:**
1. Resolve address → `buurtcode` via PDOK Locatieserver
2. Query CBS for neighborhood stats

**PDOK Locatieserver** (the gateway to all government data):
```
GET https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?q={address}&rows=1&fq=type:adres
```
Returns: `buurtcode`, `wijkcode`, `gemeentecode`, coordinates, `nummeraanduiding_id`

**CBS OData API** (free, no auth):
```
# Neighborhood core stats
GET https://opendata.cbs.nl/ODataApi/odata/86165NED/TypedDataSet?$filter=WijkenEnBuurten eq '{buurtcode}'

# Amenity distances
GET https://opendata.cbs.nl/ODataApi/odata/86134NED/TypedDataSet?$filter=WijkenEnBuurten eq '{buurtcode}'
```

**Data returned:**
- Population density, average income, % owner-occupied
- Distance to: supermarket, GP, hospital, schools, train station, highway
- Count of amenities within 1/3/5 km
- Age distribution, household composition
- Average WOZ value in neighborhood

---

### 5. Flood Risk Check

**Pain point:** The Netherlands is largely below sea level. Flood risk varies dramatically by location and directly impacts insurance and property value.

**What to build:** `check_flood_risk` tool.

**API:**
```
GET https://service.pdok.nl/rws/overstromingsrisico/wms/v1_0?
  service=WMS&version=1.3.0&request=GetFeatureInfo
  &layers=waterdiepte_bij_doorbraak
  &query_layers=waterdiepte_bij_doorbraak
  &info_format=application/json
  &CRS=EPSG:28992&I=50&J=50
  &BBOX={x1},{y1},{x2},{y2}&WIDTH=100&HEIGHT=100
```

**Returns:** Maximum flood depth in meters for various dike breach scenarios.

**Parameters:** Property address or coordinates.

---

### 6. Soil Contamination Check

**Pain point:** Contaminated soil can tank property value, block renovations, and pose health risks. Buyers rarely check this.

**What to build:** `check_soil_quality` tool.

**API:**
```
GET https://service.pdok.nl/rivm/bodemkwaliteit/wfs/v1_0?
  service=WFS&version=2.0.0&request=GetFeature
  &typeName=bodemkwaliteit:Locatie
  &outputFormat=application/json
  &CQL_FILTER=INTERSECTS(geometrie,POINT({lon} {lat}))
```

**Returns:** Soil investigation status, contamination level, remediation status.

---

### 7. WOZ Value Lookup

**Pain point:** WOZ (municipal tax valuation) is essential for negotiation, tax calculation, and eigenwoningforfait — but buyers don't know how to find it.

**What to build:** `get_woz_value` tool.

**API:**
```
# Step 1: Get nummeraanduiding_id from PDOK Locatieserver
# Step 2: Query WOZ
GET https://api.wozwaardeloket.nl/wozwaardeloket-api/v1/wozwaarde/nummeraanduiding/{id}
```

**Returns:** WOZ value per year, reference date.

**Use cases:**
- Compare WOZ vs asking price (is the property overpriced?)
- Calculate eigenwoningforfait for hypotheekrenteaftrek
- Estimate property tax (OZB)

---

### 8. Air Quality

**Pain point:** Part of the "neighborhood quality" wishlist. Noise and air quality were specifically requested on Reddit.

**What to build:** `check_air_quality` tool.

**API** (free, no auth):
```
# Find nearest stations
GET https://api.luchtmeetnet.nl/open_api/stations?page=1&per_page=100

# Get measurements
GET https://api.luchtmeetnet.nl/open_api/measurements?station_number={id}&page=1&per_page=10
```

**Returns:** PM2.5, PM10, NO2, O3 levels from nearest measurement station. Station type (traffic/background/industrial).

---

## Tier 3: Needs Data Processing or API Keys

### 9. School Quality Near Property

**Pain point:** Families need school quality data. Funda shows nothing about nearby schools.

**Data source:** DUO (Dienst Uitvoering Onderwijs) CKAN API (free, no auth):
```
GET https://onderwijsdata.duo.nl/api/3/action/package_show?id=oordelen-v02
```

**Data:** School addresses (CSV with lat/lon), inspection ratings, exam pass rates per school.

**Implementation:** Download school CSVs, geocode, find nearest schools to a given property, return their quality scores. Medium effort — needs CSV preprocessing.

---

### 10. Commute Time Calculator

**Pain point:** One of the most requested features across all sources. Especially valuable for expats choosing between cities.

**What to build:** `calculate_commute` tool.

**Data sources:**
- Car/bike: OSRM (free, open-source routing engine)
- Public transit: NS API (free key from `apiportal.ns.nl`)
- CBS already has distance-to-train-station per neighborhood (quick proxy)

**Parameters:** `from_address`, `to_address`, `modes=["car", "bike", "transit"]`

---

### 11. New Listing Alerts

**Pain point:** Reddit's #2 complaint. Funda's notifications are too slow. In a competitive market, seeing a listing hours late means missing out. Multiple developers built tools specifically for this ([pyfunda](https://github.com/0xMH/pyfunda), [Home Finder](https://werules.github.io/home-finder/)).

**What to build:** `watch_search` and `check_new_listings` tools.

**Implementation:** Uses pyfunda's `poll_new_listings()` and `get_latest_id()`. Store watched searches and last-seen ID in a local JSON file. The `check_new_listings` tool returns any new matches since last check.

**Architecture:**
```python
@mcp.tool()
def watch_search(location, price_max, ...) -> dict:
    """Save search criteria + current latest_id to local state."""

@mcp.tool()
def check_new_listings() -> list[dict]:
    """Check all watched searches for new listings since last check."""
```

---

### 12. Price Trend Analysis

**Pain point:** "Should I buy now or wait?" — buyers want to know if prices are rising or falling in their target area.

**Data sources:**
- CBS housing price indices (free OData API)
- pyfunda historical listing data
- Price history across multiple listings in an area

**What to build:** `get_price_trends` tool that returns YoY/QoQ price changes per city or postcode area.

---

## The Gateway: PDOK Locatieserver

Every Tier 2 tool chains off the same entry point. One call resolves any Dutch address into all the identifiers needed by every other API:

```
GET https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?q={address}
```

**Returns:**

| Field | Used by |
|-------|---------|
| `buurtcode` | CBS neighborhood stats (#4) |
| `nummeraanduiding_id` | WOZ value (#7), BAG building data |
| `gemeentecode` | Crime statistics |
| `centroide_ll` (coordinates) | Flood risk (#5), soil quality (#6), air quality (#8), school proximity (#9) |
| `gekoppeld_perceel` | Kadaster plot data |

**Implementation:** Build `resolve_address` as an internal helper. All Tier 2 tools call it first, then query their specific API with the returned identifier.

---

## Implementation Priority

```
Phase 1 (pure computation, ship immediately):
  ├── Dutch mortgage calculator (replace calculate_affordability)
  ├── Total cost of ownership (bijkomende kosten)
  └── Overbidding estimator (uses existing price history)

Phase 2 (free APIs, no auth):
  ├── resolve_address (PDOK — internal helper for all below)
  ├── Neighborhood profile (CBS)
  ├── WOZ value lookup
  ├── Flood risk check (PDOK)
  └── Soil contamination check (PDOK)

Phase 3 (more integration work):
  ├── Air quality (luchtmeetnet)
  ├── School quality (DUO CSVs)
  ├── Commute time (OSRM + NS)
  ├── New listing alerts (local state)
  └── Price trend analysis (CBS indices)
```

---

## Competitive Landscape

No Netherlands-specific or funda-specific MCP server exists on GitHub. The closest are:
- `tae0y/real-estate-mcp` (319 stars) — Korean apartment data, 14+ tools
- `neco001/openstreetmap-mcp` — neighborhood livability via Overpass API
- `brightdata/real-estate-ai-agent` (121 stars) — generic scraping

**Third-party tools filling funda's gaps:**
- [woningstats.nl](https://woningstats.nl) — value estimates, neighborhood stats (324 upvotes)
- [Huisradars](https://huisradars.nl) — price estimation, noise maps (194 upvotes)
- [Krib.nl extension](https://krib.nl/en/extension) — transaction prices on funda listings
- [WalterLiving](https://walterliving.com) — valuation reports with overbidding data

**Sources:** Research conducted March 2026 across Reddit, GitHub, Dutch government API documentation, and competitor product analysis.
