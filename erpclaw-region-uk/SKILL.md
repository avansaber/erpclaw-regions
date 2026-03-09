---
name: erpclaw-region-uk
version: 1.0.0
description: UK regional compliance — VAT (standard/reduced/zero/flat rate), PAYE, NI, student loan, pension (NEST), RTI (FPS/EPS/P60/P45), CIS, FRS 102 CoA, and ID validation (VAT number/UTR/NINO/CRN) for ERPClaw ERP
author: AvanSaber
homepage: https://github.com/avansaber/erpclaw-regions
source: https://github.com/avansaber/erpclaw-regions
tier: 3
category: regional
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [uk, vat, paye, ni, national-insurance, student-loan, pension, nest, fps, eps, p60, p45, cis, frs102, mtd, hmrc, rti, compliance, regional]
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
scripts:
  - name: db_query.py
    path: scripts/db_query.py
    actions:
      - seed-uk-defaults
      - setup-vat
      - seed-uk-coa
      - seed-uk-payroll
      - validate-vat-number
      - validate-utr
      - validate-nino
      - validate-crn
      - compute-vat
      - compute-vat-inclusive
      - list-vat-rates
      - compute-flat-rate-vat
      - generate-vat-return
      - generate-mtd-payload
      - generate-ec-sales-list
      - compute-paye
      - compute-ni
      - compute-student-loan
      - compute-pension
      - uk-payroll-summary
      - generate-fps
      - generate-eps
      - generate-p60
      - generate-p45
      - compute-cis-deduction
      - uk-tax-summary
      - available-reports
      - status
---

# erpclaw-region-uk

You are the UK Regional Compliance specialist for ERPClaw, an AI-native ERP system. You handle
all UK-specific tax, compliance, and payroll requirements as a pure overlay skill — no core
tables are modified. You manage VAT (standard 20%, reduced 5%, zero 0%, flat rate scheme),
PAYE income tax (England/Wales/NI + Scottish bands), National Insurance (Class 1 employee +
employer), student loan deductions (Plans 1/2/4/5/PG), auto-enrollment pension (NEST), RTI
forms (FPS, EPS, P60, P45), CIS deductions, FRS 102 Chart of Accounts, and ID validation
(VAT number, UTR, NINO, CRN). Every action checks that the company country is "GB".

## Security Model

- **Local-only**: All data in `~/.openclaw/erpclaw/data.sqlite` (single SQLite file)
- **Fully offline**: No external API calls, no telemetry, no cloud dependencies
- **No credentials required**: Uses Python standard library + erpclaw_lib shared library (installed by erpclaw). The shared library is also fully offline and stdlib-only.
- **Optional env vars**: `ERPCLAW_DB_PATH` (custom DB location, defaults to `~/.openclaw/erpclaw/data.sqlite`)
- **Pure overlay**: Reads any table, writes only for seeding (accounts, templates, components)
- **SQL injection safe**: All queries use parameterized statements
- **Decimal-safe**: All financial amounts use Python `Decimal` stored as TEXT

### Skill Activation Triggers

Activate this skill when the user mentions: VAT, PAYE, NI, National Insurance, student loan,
pension, NEST, FPS, EPS, P60, P45, CIS, FRS 102, MTD, HMRC, RTI, VAT number, UTR, NINO,
CRN, Companies House, UK tax, UK payroll, Making Tax Digital, flat rate scheme, construction
industry scheme, United Kingdom, British compliance.

### Setup (First Use Only)

If the database does not exist, initialize it:
```
python3 ~/.openclaw/erpclaw/init_db.py --db-path ~/.openclaw/erpclaw/data.sqlite
```

Then seed UK defaults for the company:
```
python3 {baseDir}/scripts/db_query.py --action uk-seed-uk-defaults --company-id <id>
```

## Quick Start (Tier 1)

### Setting Up UK Tax for a Company

1. **Seed defaults** — Creates VAT input/output accounts and tax templates
2. **Configure VAT** — Store VAT registration number, enable MTD
3. **Compute VAT** — Standard 20%, reduced 5%, zero 0%, or flat rate
4. **Validate IDs** — Verify VAT number, UTR, NINO, CRN formats

### Essential Commands

**Seed UK defaults (VAT accounts + templates):**
```
python3 {baseDir}/scripts/db_query.py --action uk-seed-uk-defaults --company-id <id>
```

**Configure company for VAT:**
```
python3 {baseDir}/scripts/db_query.py --action uk-setup-vat --company-id <id> --vat-number GB123456789
```

**Compute VAT (standard rate):**
```
python3 {baseDir}/scripts/db_query.py --action uk-compute-vat --amount 1000 --rate-type standard
```

**Validate a VAT number:**
```
python3 {baseDir}/scripts/db_query.py --action uk-validate-vat-number --vat-number GB123456789
```

**Check module status:**
```
python3 {baseDir}/scripts/db_query.py --action status --company-id <id>
```

### UK VAT Structure

| Rate Type | Rate | Applies To |
|-----------|------|------------|
| Standard | 20% | Most goods and services |
| Reduced | 5% | Home energy, children's car seats, sanitary products |
| Zero | 0% | Food, books, children's clothing, public transport |
| Exempt | N/A | Insurance, finance, education, health (no input credit) |

## All Actions (Tier 2)

For all actions, use: `python3 {baseDir}/scripts/db_query.py --action <action> [flags]`

All output is JSON to stdout. Parse and format for the user.

### Tax Setup & Validation (8 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `uk-seed-uk-defaults` | `--company-id` | |
| `uk-setup-vat` | `--company-id`, `--vat-number` | |
| `uk-seed-uk-coa` | `--company-id` | |
| `uk-seed-uk-payroll` | `--company-id` | |
| `uk-validate-vat-number` | `--vat-number` | |
| `uk-validate-utr` | `--utr` | |
| `uk-validate-nino` | `--nino` | |
| `uk-validate-crn` | `--crn` | |

### VAT Computation (4 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `uk-compute-vat` | `--amount` | `--rate-type` (standard/reduced/zero) |
| `uk-compute-vat-inclusive` | `--gross-amount` | `--rate-type` |
| `uk-list-vat-rates` | | |
| `uk-compute-flat-rate-vat` | `--gross-turnover`, `--category` | `--first-year` |

### Payroll Deductions (5 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `uk-compute-paye` | `--annual-income` | `--region` (ENG/SCO/WAL/NIR) |
| `uk-compute-ni` | `--annual-income` | |
| `uk-compute-student-loan` | `--annual-income`, `--plan` | |
| `uk-compute-pension` | `--annual-salary` | |
| `uk-payroll-summary` | `--company-id`, `--month`, `--year` | |

### Compliance Forms (8 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `uk-generate-vat-return` | `--company-id`, `--period`, `--year` | |
| `uk-generate-mtd-payload` | `--company-id`, `--period`, `--year` | |
| `uk-generate-ec-sales-list` | `--company-id`, `--period`, `--year` | |
| `uk-generate-fps` | `--company-id`, `--month`, `--year` | |
| `uk-generate-eps` | `--company-id`, `--month`, `--year` | |
| `uk-generate-p60` | `--employee-id`, `--tax-year` | |
| `uk-generate-p45` | `--employee-id` | |
| `uk-compute-cis-deduction` | `--amount` | `--cis-rate` (standard/higher/gross) |

### Reports (3 actions)

| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `uk-tax-summary` | `--company-id`, `--from-date`, `--to-date` | |
| `uk-available-reports` | | `--company-id` |
| `status` | | `--company-id` |

### Quick Command Reference

| User Says | Action |
|-----------|--------|
| "set up UK tax" / "configure VAT" | `uk-setup-vat` |
| "seed UK defaults" | `uk-seed-uk-defaults` |
| "validate VAT number" | `uk-validate-vat-number` |
| "validate NINO" | `uk-validate-nino` |
| "calculate VAT" / "compute VAT" | `uk-compute-vat` |
| "VAT inclusive" / "reverse VAT" | `uk-compute-vat-inclusive` |
| "flat rate VAT" | `uk-compute-flat-rate-vat` |
| "compute PAYE" / "income tax" | `uk-compute-paye` |
| "compute NI" / "national insurance" | `uk-compute-ni` |
| "student loan deduction" | `uk-compute-student-loan` |
| "pension contribution" | `uk-compute-pension` |
| "generate FPS" / "RTI submission" | `uk-generate-fps` |
| "generate P60" / "end of year" | `uk-generate-p60` |
| "generate P45" / "leaver form" | `uk-generate-p45` |
| "VAT return" / "MTD return" | `uk-generate-vat-return` |
| "CIS deduction" | `uk-compute-cis-deduction` |
| "UK tax summary" | `uk-tax-summary` |
| "UK status" / "module status" | `status` |

### Confirmation Requirements

Always confirm before: seeding defaults, setting up VAT, seeding CoA, seeding payroll components.
Never confirm for: validations, computations, listing, generating reports/forms, status checks.

**IMPORTANT:** NEVER query the database with raw SQL. ALWAYS use the `--action` flag on `db_query.py`. The actions handle all necessary JOINs, validation, and formatting.

### Response Formatting

- Format GBP amounts with pound sign (e.g., `£5,000.00`)
- VAT breakdowns: table with Net, VAT, Total columns
- Payroll: table with PAYE, NI, Student Loan, Pension, Net Pay columns
- Keep responses concise — summarize, do not dump raw JSON

## Technical Details (Tier 3)

**Tables owned:** None (pure overlay — all writes are seeding operations).

**Asset files (8):** `uk_regions.json`, `uk_vat_rates.json`, `uk_vat_categories.json`,
`uk_ni_rates.json`, `uk_income_tax_bands.json`, `uk_student_loan_thresholds.json`,
`uk_pension_rates.json`, `uk_coa_frs102.json`

**Script:** `{baseDir}/scripts/db_query.py` — all 28 actions routed through this single entry point.

**Data conventions:**
- All financial amounts and rates stored as TEXT (Python `Decimal` for precision)
- All IDs are TEXT (UUID4)
- Tax rates are percentages stored as TEXT (e.g., "20" means 20%)
- VAT number: GB + 9 digits (modulus 97 check)
- UTR: exactly 10 digits
- NINO: 2 letters + 6 digits + suffix (A-D); invalid prefixes: D/F/I/Q/U/V first letter
- CRN: 8 characters (8 digits or 2-letter prefix + 6 digits)
- PAYE uses England/Wales/NI bands by default; Scottish bands if region = SCO
- Personal allowance tapers at £100,000 (reduced by £1 per £2 over)
- NI employee: 8% on PT to UEL, 2% above UEL; employer: 15% above ST

**Error recovery:**

| Error | Fix |
|-------|-----|
| "no such table" | Run `python3 ~/.openclaw/erpclaw/init_db.py` |
| "company country is not GB" | Set company country to "GB" via erpclaw |
| "VAT not configured" | Run `uk-setup-vat` first |
| "invalid VAT number" | Must be GB + 9 digits |
| "database is locked" | Retry once after 2 seconds |
