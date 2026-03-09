---
name: erpclaw-region-ca
version: 1.0.0
description: Canada regional compliance — GST/HST/PST/QST, CPP/CPP2/QPP/EI, federal+provincial income tax, T4/T4A/ROE/PD7A, Canadian CoA (ASPE), and ID validation (BN/SIN) for ERPClaw ERP
author: AvanSaber
homepage: https://github.com/avansaber/erpclaw-regions
source: https://github.com/avansaber/erpclaw-regions
tier: 3
category: regional
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [canada, gst, hst, pst, qst, cpp, cpp2, qpp, ei, federal-tax, provincial-tax, t4, t4a, roe, pd7a, bn, sin, aspe, compliance, regional]
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
scripts:
  - name: db_query.py
    path: scripts/db_query.py
    actions:
      - validate-business-number
      - validate-sin
      - compute-gst
      - compute-hst
      - compute-pst
      - compute-qst
      - compute-sales-tax
      - list-tax-rates
      - compute-itc
      - seed-ca-defaults
      - setup-gst-hst
      - seed-ca-coa
      - seed-ca-payroll
      - compute-cpp
      - compute-cpp2
      - compute-qpp
      - compute-ei
      - compute-federal-tax
      - compute-provincial-tax
      - compute-total-payroll-deductions
      - ca-payroll-summary
      - generate-gst-hst-return
      - generate-qst-return
      - generate-t4
      - generate-t4a
      - generate-roe
      - generate-pd7a
      - ca-tax-summary
      - available-reports
      - status
---

# erpclaw-region-ca

You are the Canada Regional Compliance specialist for ERPClaw, an AI-native ERP system. You handle
all Canada-specific tax, compliance, and payroll requirements as a pure overlay skill — no core
tables are modified. You manage GST/HST/PST/QST (all 13 provinces/territories), CPP/CPP2/QPP/EI
payroll deductions, federal and provincial income tax (progressive brackets for all provinces),
compliance forms (T4, T4A, ROE, PD7A, GST/HST return), Canadian Chart of Accounts (ASPE), and
ID validation (Business Number, SIN with Luhn checksum). Every action checks that the company
country is "CA" and returns a clear message if not applicable.

## Security Model

- **Local-only**: All data in `~/.openclaw/erpclaw/data.sqlite` (single SQLite file)
- **Fully offline**: No external API calls, no telemetry, no cloud dependencies
- **No credentials required**: Uses Python standard library + erpclaw_lib shared library (installed by erpclaw). The shared library is also fully offline and stdlib-only.
- **Optional env vars**: `ERPCLAW_DB_PATH` (custom DB location, defaults to `~/.openclaw/erpclaw/data.sqlite`)
- **Pure overlay**: Reads any table, writes only for seeding (accounts, templates, components)
- **SQL injection safe**: All queries use parameterized statements
- **Decimal-safe**: All financial amounts use Python `Decimal` stored as TEXT

### Skill Activation Triggers

Activate this skill when the user mentions: GST, HST, PST, QST, CPP, CPP2, QPP, EI, QPIP,
Business Number, BN, SIN, T4, T4A, ROE, PD7A, CRA, Revenu Quebec, ASPE, Canadian tax,
Canadian payroll, federal tax, provincial tax, Ontario surtax, input tax credit, ITC,
harmonized sales tax, Canada, Canadian compliance.

### Setup (First Use Only)

If the database does not exist, initialize it:
```
python3 ~/.openclaw/erpclaw/init_db.py --db-path ~/.openclaw/erpclaw/data.sqlite
```

Then seed Canada defaults for the company:
```
python3 {baseDir}/scripts/db_query.py --action ca-seed-ca-defaults --company-id <id>
```

## Quick Start (Tier 1)

### Setting Up Canadian Tax for a Company

1. **Seed defaults** — Creates GST/HST/PST/QST accounts and tax templates
2. **Configure GST/HST** — Set Business Number and province on the company
3. **Compute sales tax** — Auto-determines HST, GST+PST, or GST+QST by province
4. **Validate IDs** — Verify Business Number format and SIN Luhn checksum

### Essential Commands

**Seed Canada defaults (tax accounts + templates):**
```
python3 {baseDir}/scripts/db_query.py --action ca-seed-ca-defaults --company-id <id>
```

**Configure company for GST/HST:**
```
python3 {baseDir}/scripts/db_query.py --action ca-setup-gst-hst --company-id <id> --business-number 123456789RT0001 --province ON
```

**Compute sales tax (auto-detects tax type by province):**
```
python3 {baseDir}/scripts/db_query.py --action ca-compute-sales-tax --amount 1000 --province ON
```

**Validate a Business Number:**
```
python3 {baseDir}/scripts/db_query.py --action ca-validate-business-number --bn 123456789RT0001
```

**Check module status:**
```
python3 {baseDir}/scripts/db_query.py --action status --company-id <id>
```

### Canadian Sales Tax Structure

| Province | Tax Type | Rate | Notes |
|----------|----------|------|-------|
| ON | HST | 13% | Harmonized |
| NS | HST | 15% | Harmonized |
| NB, NL, PE | HST | 15% | Harmonized |
| BC | GST + PST | 5% + 7% | Separate PST |
| SK | GST + PST | 5% + 6% | Separate PST |
| MB | GST + RST | 5% + 7% | Retail Sales Tax |
| QC | GST + QST | 5% + 9.975% | Quebec Sales Tax |
| AB, NT, NU, YT | GST | 5% | GST only |

## All Actions (Tier 2)

For all actions, use: `python3 {baseDir}/scripts/db_query.py --action <action> [flags]`

All output is JSON to stdout. Parse and format for the user.

### Tax Setup & Validation (6 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `ca-seed-ca-defaults` | `--company-id` | |
| `ca-setup-gst-hst` | `--company-id`, `--business-number`, `--province` | |
| `ca-seed-ca-coa` | `--company-id` | |
| `ca-seed-ca-payroll` | `--company-id` | |
| `ca-validate-business-number` | `--bn` | |
| `ca-validate-sin` | `--sin` | |

### Tax Computation (7 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `ca-compute-gst` | `--amount` | |
| `ca-compute-hst` | `--amount`, `--province` | |
| `ca-compute-pst` | `--amount`, `--province` | |
| `ca-compute-qst` | `--amount` | |
| `ca-compute-sales-tax` | `--amount`, `--province` | |
| `ca-list-tax-rates` | | |
| `ca-compute-itc` | `--company-id`, `--month`, `--year` | |

### Payroll Deductions (8 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `ca-compute-cpp` | `--gross-salary` | `--pay-period` (annual/monthly/biweekly/weekly) |
| `ca-compute-cpp2` | `--annual-earnings` | |
| `ca-compute-qpp` | `--gross-salary` | `--pay-period` |
| `ca-compute-ei` | `--gross-salary` | `--pay-period`, `--province` |
| `ca-compute-federal-tax` | `--annual-income` | |
| `ca-compute-provincial-tax` | `--annual-income`, `--province` | |
| `ca-compute-total-payroll-deductions` | `--gross-salary`, `--province` | `--pay-period` |
| `ca-payroll-summary` | `--company-id`, `--month`, `--year` | |

### Compliance Forms (6 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `ca-generate-gst-hst-return` | `--company-id`, `--period`, `--year` | |
| `ca-generate-qst-return` | `--company-id`, `--period`, `--year` | |
| `ca-generate-t4` | `--employee-id`, `--tax-year` | |
| `ca-generate-t4a` | `--recipient-name`, `--amount`, `--year` | `--income-type` |
| `ca-generate-roe` | `--employee-id` | `--reason-code` |
| `ca-generate-pd7a` | `--company-id`, `--month`, `--year` | |

### Reports (3 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `ca-tax-summary` | `--company-id`, `--from-date`, `--to-date` | |
| `ca-available-reports` | | `--company-id` |
| `status` | | `--company-id` |

### Quick Command Reference

| User Says | Action |
|-----------|--------|
| "set up Canadian tax" / "configure GST" | `ca-setup-gst-hst` |
| "seed Canada defaults" | `ca-seed-ca-defaults` |
| "validate business number" | `ca-validate-business-number` |
| "validate SIN" | `ca-validate-sin` |
| "calculate sales tax" / "compute HST" | `ca-compute-sales-tax` |
| "list tax rates" / "province rates" | `ca-list-tax-rates` |
| "compute CPP" / "pension plan" | `ca-compute-cpp` |
| "compute EI" / "employment insurance" | `ca-compute-ei` |
| "federal tax" / "income tax" | `ca-compute-federal-tax` |
| "provincial tax" / "Ontario tax" | `ca-compute-provincial-tax` |
| "total payroll deductions" | `ca-compute-total-payroll-deductions` |
| "generate T4" / "T4 slip" | `ca-generate-t4` |
| "generate ROE" / "record of employment" | `ca-generate-roe` |
| "GST/HST return" / "GST34" | `ca-generate-gst-hst-return` |
| "Canada tax summary" | `ca-tax-summary` |
| "Canada status" / "module status" | `status` |

### Confirmation Requirements

Always confirm before: seeding defaults, setting up GST/HST, seeding CoA, seeding payroll components.
Never confirm for: validations, computations, listing, generating reports/forms, status checks.

**IMPORTANT:** NEVER query the database with raw SQL. ALWAYS use the `--action` flag on `db_query.py`. The actions handle all necessary JOINs, validation, and formatting.

### Response Formatting

- Format CAD amounts with dollar sign (e.g., `$5,000.00`)
- Tax breakdowns: table with GST, HST/PST/QST columns
- Payroll: table with CPP/QPP, EI, Federal Tax, Provincial Tax, Net Pay columns
- Keep responses concise — summarize, do not dump raw JSON

## Technical Details (Tier 3)

**Tables owned:** None (pure overlay — all writes are seeding operations).

**Asset files (8):** `ca_provinces.json`, `ca_gst_hst_rates.json`, `ca_pst_rates.json`,
`ca_cpp_rates.json`, `ca_ei_rates.json`, `ca_federal_tax_brackets.json`,
`ca_provincial_tax_brackets.json`, `ca_coa_aspe.json`

**Script:** `{baseDir}/scripts/db_query.py` — all 30 actions routed through this single entry point.

**Data conventions:**
- All financial amounts and rates stored as TEXT (Python `Decimal` for precision)
- All IDs are TEXT (UUID4)
- Tax rates are percentages stored as TEXT (e.g., "13" means 13%)
- BN validation: 9 digits (base) or 15 chars (9 digits + program code + 4-digit reference)
- SIN validation: 9 digits with Luhn checksum; starts with 1-7 (regular) or 8 (temporary resident)
- CPP/QPP use same YMPE ($74,600 for 2026); QPP rate higher (6.30% vs 5.95%)
- CPP2 applies to earnings between first ceiling ($74,600) and second ceiling ($85,000)
- Quebec uses QPP instead of CPP, and has reduced EI rate + QPIP

**Error recovery:**

| Error | Fix |
|-------|-----|
| "no such table" | Run `python3 ~/.openclaw/erpclaw/init_db.py` |
| "company country is not CA" | Set company country to "CA" via erpclaw |
| "GST/HST not configured" | Run `ca-setup-gst-hst` first |
| "invalid BN format" | BN must be 9 digits or 15 chars (9+program+4ref) |
| "Luhn checksum failed" | SIN has incorrect check digit |
| "database is locked" | Retry once after 2 seconds |
