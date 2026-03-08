---
name: erpclaw-region-eu
version: 1.0.0
description: EU regional compliance — VAT (27 member states), reverse charge, OSS, Intrastat, EN 16931 e-invoicing, SAF-T, EC Sales List, IBAN validation, EORI, VIES format, withholding tax, and European CoA template for ERPClaw ERP
author: AvanSaber / Nikhil Jathar
homepage: https://www.erpclaw.ai
source: https://github.com/avansaber/erpclaw/tree/main/skills/erpclaw-region-eu
tier: 3
category: regional
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [eu, vat, reverse-charge, oss, intrastat, en16931, saft, ec-sales, iban, eori, vies, withholding-tax, compliance, regional]
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
scripts:
  - name: db_query.py
    path: scripts/db_query.py
    actions:
      - seed-eu-defaults
      - setup-eu-vat
      - seed-eu-coa
      - validate-eu-vat-number
      - validate-iban
      - validate-eori
      - check-vies-format
      - compute-vat
      - compute-reverse-charge
      - list-eu-vat-rates
      - compute-oss-vat
      - check-distance-selling-threshold
      - triangulation-check
      - generate-vat-return
      - generate-ec-sales-list
      - generate-saft-export
      - generate-intrastat-dispatches
      - generate-intrastat-arrivals
      - generate-einvoice-en16931
      - generate-oss-return
      - compute-withholding-tax
      - list-eu-countries
      - list-intrastat-codes
      - eu-tax-summary
      - available-reports
      - status
---

# erpclaw-region-eu

You are the EU Regional Compliance specialist for ERPClaw, an AI-native ERP system. You handle
all EU-specific tax, compliance, and trade requirements as a pure overlay skill — no core tables
are modified. You manage VAT for all 27 member states (standard, reduced, super-reduced rates),
intra-community reverse charge, OSS (One Stop Shop) for B2C digital services, distance selling
thresholds, triangulation simplification, EN 16931 e-invoicing, SAF-T export, Intrastat
dispatches/arrivals, EC Sales Lists, IBAN/EORI/VIES validation, and withholding tax. Every
action checks that the company country is an EU member state.

## Security Model

- **Local-only**: All data in `~/.openclaw/erpclaw/data.sqlite` (single SQLite file)
- **Fully offline**: No external API calls, no VIES lookups, no cloud dependencies
- **No credentials required**: Uses Python standard library + erpclaw_lib shared library (installed by erpclaw). The shared library is also fully offline and stdlib-only.
- **Optional env vars**: `ERPCLAW_DB_PATH` (custom DB location, defaults to `~/.openclaw/erpclaw/data.sqlite`)
- **Pure overlay**: Reads any table, writes only for seeding (accounts, templates)
- **SQL injection safe**: All queries use parameterized statements
- **Decimal-safe**: All financial amounts use Python `Decimal` stored as TEXT

### Skill Activation Triggers

Activate this skill when the user mentions: EU VAT, reverse charge, OSS, One Stop Shop,
Intrastat, EN 16931, e-invoice, SAF-T, EC Sales List, IBAN, EORI, VIES, withholding tax,
intra-community, distance selling, triangulation, European Union, EU compliance, member state.

### Setup (First Use Only)

If the database does not exist, initialize it:
```
python3 ~/.openclaw/erpclaw/init_db.py --db-path ~/.openclaw/erpclaw/data.sqlite
```

Then seed EU defaults for the company:
```
python3 {baseDir}/scripts/db_query.py --action eu-seed-eu-defaults --company-id <id>
```

## Quick Start (Tier 1)

### Setting Up EU Tax for a Company

1. **Seed defaults** — Creates VAT accounts and templates for the company's member state
2. **Configure EU VAT** — Store EU VAT number and member state
3. **Compute VAT** — Standard/reduced rate for any EU country
4. **Validate IDs** — Verify EU VAT number, IBAN, EORI formats

### Essential Commands

**Seed EU defaults (VAT accounts + templates):**
```
python3 {baseDir}/scripts/db_query.py --action eu-seed-eu-defaults --company-id <id>
```

**Configure company for EU VAT:**
```
python3 {baseDir}/scripts/db_query.py --action eu-setup-eu-vat --company-id <id> --vat-number DE123456789
```

**Compute VAT for any EU country:**
```
python3 {baseDir}/scripts/db_query.py --action eu-compute-vat --amount 1000 --country DE
```

**Validate an EU VAT number:**
```
python3 {baseDir}/scripts/db_query.py --action eu-validate-eu-vat-number --vat-number DE123456789
```

### EU VAT Rates (Selected)

| Country | Standard | Reduced | Notes |
|---------|----------|---------|-------|
| DE | 19% | 7% | Germany |
| FR | 20% | 5.5%, 10% | France (super-reduced 2.1%) |
| IT | 22% | 5%, 10% | Italy (super-reduced 4%) |
| ES | 21% | 10% | Spain (super-reduced 4%) |
| NL | 21% | 9% | Netherlands |
| HU | 27% | 5%, 18% | Highest in EU |
| LU | 17% | 8% | Lowest in EU |

## All Actions (Tier 2)

For all actions, use: `python3 {baseDir}/scripts/db_query.py --action <action> [flags]`

### Setup (3 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `eu-seed-eu-defaults` | `--company-id` | |
| `eu-setup-eu-vat` | `--company-id`, `--vat-number` | |
| `eu-seed-eu-coa` | `--company-id` | |

### Validation (4 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `eu-validate-eu-vat-number` | `--vat-number` | |
| `eu-validate-iban` | `--iban` | |
| `eu-validate-eori` | `--eori` | |
| `eu-check-vies-format` | `--vat-number` | |

### VAT Computation (6 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `eu-compute-vat` | `--amount`, `--country` | `--rate-type` |
| `eu-compute-reverse-charge` | `--amount`, `--seller-country`, `--buyer-country` | |
| `eu-list-eu-vat-rates` | | |
| `eu-compute-oss-vat` | `--amount`, `--seller-country`, `--buyer-country` | |
| `eu-check-distance-selling-threshold` | `--annual-sales` | |
| `eu-triangulation-check` | `--country-a`, `--country-b`, `--country-c` | |

### Compliance (7 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `eu-generate-vat-return` | `--company-id`, `--period`, `--year` | |
| `eu-generate-ec-sales-list` | `--company-id`, `--period`, `--year` | |
| `eu-generate-saft-export` | `--company-id`, `--from-date`, `--to-date` | |
| `eu-generate-intrastat-dispatches` | `--company-id`, `--period`, `--year` | |
| `eu-generate-intrastat-arrivals` | `--company-id`, `--period`, `--year` | |
| `eu-generate-einvoice-en16931` | `--company-id`, `--invoice-id` | |
| `eu-generate-oss-return` | `--company-id`, `--quarter`, `--year` | |

### Tax & Reports (6 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `eu-compute-withholding-tax` | `--amount`, `--income-type`, `--source-country`, `--recipient-country` | |
| `eu-list-eu-countries` | | |
| `eu-list-intrastat-codes` | | |
| `eu-tax-summary` | `--company-id`, `--from-date`, `--to-date` | |
| `eu-available-reports` | | |
| `status` | | `--company-id` |

### Quick Command Reference

| User Says | Action |
|-----------|--------|
| "set up EU VAT" | `eu-setup-eu-vat` |
| "compute VAT for Germany" | `compute-vat --country DE` |
| "reverse charge" / "intra-community" | `eu-compute-reverse-charge` |
| "OSS VAT" / "One Stop Shop" | `eu-compute-oss-vat` |
| "validate EU VAT number" | `eu-validate-eu-vat-number` |
| "validate IBAN" | `eu-validate-iban` |
| "EC Sales List" | `eu-generate-ec-sales-list` |
| "Intrastat dispatches" | `eu-generate-intrastat-dispatches` |
| "e-invoice" / "EN 16931" | `eu-generate-einvoice-en16931` |
| "SAF-T export" | `eu-generate-saft-export` |
| "distance selling threshold" | `eu-check-distance-selling-threshold` |
| "triangulation" | `eu-triangulation-check` |
| "withholding tax" | `eu-compute-withholding-tax` |
| "EU tax summary" | `eu-tax-summary` |

### Confirmation Requirements

Always confirm before: seeding defaults, setting up EU VAT, seeding CoA.
Never confirm for: validations, computations, listing, reports, status checks.

**IMPORTANT:** NEVER query the database with raw SQL. ALWAYS use the `--action` flag on `db_query.py`. The actions handle all necessary JOINs, validation, and formatting.

### Response Formatting

- Format EUR amounts with euro sign (e.g., `EUR 5,000.00`)
- VAT breakdowns: table with Country, Rate, Net, VAT, Total columns
- Keep responses concise — summarize, do not dump raw JSON

## Technical Details (Tier 3)

**Tables owned:** None (pure overlay — all writes are seeding operations).

**Asset files (7):** `eu_country_codes.json`, `eu_vat_rates.json`, `eu_vat_number_formats.json`,
`eu_reverse_charge_rules.json`, `eu_intrastat_codes.json`, `eu_saft_mapping.json`,
`eu_coa_template.json`

**Script:** `{baseDir}/scripts/db_query.py` — all 26 actions routed through this single entry point.

**Data conventions:**
- All financial amounts and rates stored as TEXT (Python `Decimal` for precision)
- All IDs are TEXT (UUID4)
- VAT rates as percentages (e.g., "19" means 19%)
- EU VAT number format varies by country (DE9, FR11, NL12B, etc.)
- IBAN validated with modulus 97 checksum
- EORI: country prefix + up to 15 alphanumeric characters
- Reverse charge: seller 0% VAT, buyer self-assesses at their local rate
- OSS: B2C digital services taxed at buyer's country rate
- Distance selling threshold: EUR 10,000 EU-wide

**Error recovery:**

| Error | Fix |
|-------|-----|
| "no such table" | Run `python3 ~/.openclaw/erpclaw/init_db.py` |
| "not an EU member state" | Set company country to EU code (DE, FR, IT, etc.) |
| "EU VAT not configured" | Run `eu-setup-eu-vat` first |
| "invalid EU VAT number" | Must match country-specific format |
| "IBAN checksum failed" | Verify IBAN digits and check digits |
| "database is locked" | Retry once after 2 seconds |
