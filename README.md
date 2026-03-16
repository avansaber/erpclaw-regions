# ERPClaw Regions

4 regional compliance modules for [ERPClaw](https://github.com/avansaber/erpclaw). Tax rules, payroll deductions, chart of accounts templates, government filings, and ID validation for non-US jurisdictions.

## Modules

### Canada (`erpclaw-region-ca`)
GST/HST/PST/QST sales tax, CPP/CPP2/QPP/EI payroll deductions, federal and provincial income tax, T4/T4A/ROE/PD7A filings, Canadian CoA (ASPE), and BN/SIN validation.

### European Union (`erpclaw-region-eu`)
VAT for 27 member states, reverse charge, One-Stop Shop (OSS), Intrastat, EN 16931 e-invoicing, SAF-T, EC Sales List, IBAN validation, EORI, VIES format, withholding tax, and European CoA template.

### India (`erpclaw-region-in`)
GST (post GST 2.0), e-invoicing, GSTR-1/3B returns, TDS, Indian CoA (Ind-AS), PF/ESI/PT payroll deductions, and ID validation.

### United Kingdom (`erpclaw-region-uk`)
VAT (standard/reduced/zero/flat rate), PAYE, National Insurance, student loan deductions, pension (NEST), RTI filings (FPS/EPS/P60/P45), CIS, FRS 102 CoA, and VAT number/UTR/NINO/CRN validation.

## Installation

Requires [ERPClaw](https://github.com/avansaber/erpclaw) core. Install by region:

```
install-module erpclaw-region-ca
install-module erpclaw-region-uk
install-module erpclaw-region-eu
install-module erpclaw-region-in
```

Or ask naturally:

```
"I operate in Canada"
"Set me up for UK compliance"
```

## Links

- **Source**: [github.com/avansaber/erpclaw-regions](https://github.com/avansaber/erpclaw-regions)
- **ERPClaw Core**: [github.com/avansaber/erpclaw](https://github.com/avansaber/erpclaw)
- **Website**: [erpclaw.ai](https://www.erpclaw.ai)

## License

MIT License -- Copyright (c) 2026 AvanSaber / Nikhil Jathar
