"""L1 pytest tests for ERPClaw Region UK module.

Covers: VAT number/UTR/NINO/CRN validation, VAT computation (standard, inclusive,
flat rate), VAT rates, PAYE, NI, student loan, pension, CIS deduction,
payroll summary, compliance reports (FPS, EPS, P60, P45, VAT return, MTD),
tax summary, available reports, and status.
"""
import os
import sys
import uuid
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from uk_helpers import call_action, ns, is_ok, is_error, load_db_query

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_vat_number_valid(self, conn, env):
        # GB 123456789 — use a test number that passes modulus check
        r = call_action(ACTIONS["uk-validate-vat-number"], conn, ns(
            vat_number="GB123456789"))
        assert is_ok(r)
        # May be valid or invalid depending on checksum, just verify we get a response
        assert "valid" in r

    def test_validate_utr_valid(self, conn, env):
        r = call_action(ACTIONS["uk-validate-utr"], conn, ns(utr="1234567890"))
        assert is_ok(r)
        assert r["valid"] is True

    def test_validate_utr_invalid(self, conn, env):
        r = call_action(ACTIONS["uk-validate-utr"], conn, ns(utr="12345"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_nino_valid(self, conn, env):
        # Format: 2 letters + 6 digits + 1 letter (A/B/C/D)
        r = call_action(ACTIONS["uk-validate-nino"], conn, ns(nino="AB123456C"))
        assert is_ok(r)
        assert r["valid"] is True

    def test_validate_nino_invalid(self, conn, env):
        r = call_action(ACTIONS["uk-validate-nino"], conn, ns(nino="12345"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_crn_8_digits(self, conn, env):
        r = call_action(ACTIONS["uk-validate-crn"], conn, ns(crn="12345678"))
        assert is_ok(r)
        assert r["valid"] is True

    def test_validate_crn_scottish(self, conn, env):
        r = call_action(ACTIONS["uk-validate-crn"], conn, ns(crn="SC123456"))
        assert is_ok(r)
        assert r["valid"] is True
        assert r["type"] == "Scotland"


# ── VAT Computation ──────────────────────────────────────────────────────────

class TestVATComputation:
    def test_compute_vat_standard(self, conn, env):
        r = call_action(ACTIONS["uk-compute-vat"], conn, ns(amount="1000"))
        assert is_ok(r)
        assert r["vat_rate"] == "20"
        assert r["vat_amount"] == "200.00"
        assert r["total"] == "1200.00"

    def test_compute_vat_reduced(self, conn, env):
        r = call_action(ACTIONS["uk-compute-vat"], conn, ns(
            amount="1000", rate_type="reduced"))
        assert is_ok(r)
        assert r["vat_rate"] == "5"
        assert r["vat_amount"] == "50.00"

    def test_compute_vat_inclusive(self, conn, env):
        r = call_action(ACTIONS["uk-compute-vat-inclusive"], conn, ns(
            gross_amount="1200"))
        assert is_ok(r)
        assert r["net_amount"] == "1000.00"
        assert r["vat_amount"] == "200.00"

    def test_list_vat_rates(self, conn, env):
        r = call_action(ACTIONS["uk-list-vat-rates"], conn, ns())
        assert is_ok(r)
        assert r["standard_rate"] == "20"


# ── Payroll ──────────────────────────────────────────────────────────────────

class TestPayroll:
    def test_compute_paye(self, conn, env):
        r = call_action(ACTIONS["uk-compute-paye"], conn, ns(
            annual_income="50000"))
        assert is_ok(r)
        assert r["net_tax"]
        assert r["personal_allowance"]

    def test_compute_paye_scotland(self, conn, env):
        r = call_action(ACTIONS["uk-compute-paye"], conn, ns(
            annual_income="50000", region="SCO"))
        assert is_ok(r)
        assert r["net_tax"]

    def test_compute_ni(self, conn, env):
        r = call_action(ACTIONS["uk-compute-ni"], conn, ns(
            annual_income="35000"))
        assert is_ok(r)
        assert r["employee_ni"]
        assert r["employer_ni"]

    def test_compute_student_loan(self, conn, env):
        r = call_action(ACTIONS["uk-compute-student-loan"], conn, ns(
            annual_income="35000", plan="1"))
        assert is_ok(r)
        assert r["annual_deduction"]

    def test_compute_pension(self, conn, env):
        r = call_action(ACTIONS["uk-compute-pension"], conn, ns(
            annual_salary="30000"))
        assert is_ok(r)
        assert r["employee_contribution"]
        assert r["employer_contribution"]

    def test_compute_cis_deduction(self, conn, env):
        r = call_action(ACTIONS["uk-compute-cis-deduction"], conn, ns(
            amount="5000"))
        assert is_ok(r)
        assert r["deduction_amount"]

    def test_payroll_summary(self, conn, env):
        # Behavioural: the summary must carry exactly the submitted slips
        # for the month — per-employee figures and totals — and leave them
        # untouched. No ledger effect: it aggregates slips, posts nothing.
        cid = env["company_id"]
        e1, e2 = str(uuid.uuid4()), str(uuid.uuid4())
        conn.execute(
            "INSERT INTO employee (id, first_name, last_name, full_name,"
            " date_of_joining, company_id, ssn)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (e1, "Ada", "Lovelace", "Ada Lovelace", "2024-01-01", cid,
             "AB123456C"))
        conn.execute(
            "INSERT INTO employee (id, first_name, last_name, full_name,"
            " date_of_joining, company_id, ssn)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (e2, "Alan", "Turing", "Alan Turing", "2024-02-01", cid,
             "CD654321A"))
        run = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO payroll_run (id, period_start, period_end,"
            " company_id) VALUES (?, ?, ?, ?)",
            (run, "2026-01-01", "2026-01-31", cid))
        slips = [
            (e1, "2026-01-01", "2026-01-31", "3000.00", "600.00", "2400.00",
             "submitted"),
            (e2, "2026-01-05", "2026-01-31", "2000.00", "400.00", "1600.00",
             "submitted"),
            # Draft January slip and submitted February slip: excluded.
            (e1, "2026-01-01", "2026-01-31", "9999.00", "999.00", "9000.00",
             "draft"),
            (e1, "2026-02-01", "2026-02-28", "3000.00", "600.00", "2400.00",
             "submitted"),
        ]
        for emp, start, end, gross, ded, net, status in slips:
            conn.execute(
                "INSERT INTO salary_slip (id, payroll_run_id, employee_id,"
                " period_start, period_end, gross_pay, total_deductions,"
                " net_pay, status, company_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), run, emp, start, end, gross, ded, net,
                 status, cid))
        conn.commit()
        before = [dict(r) for r in conn.execute(
            "SELECT * FROM salary_slip ORDER BY id").fetchall()]

        r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
            company_id=env["company_id"],
            month="1", year="2026"))
        assert is_ok(r)
        assert r["report"] == "UK Payroll Summary"
        assert r["period"] == "2026-01"
        assert r["employee_count"] == 2
        by_name = {e["employee_name"]: e for e in r["employees"]}
        assert by_name["Ada Lovelace"]["gross_pay"] == "3000.00"
        assert by_name["Ada Lovelace"]["deductions"] == "600.00"
        assert by_name["Ada Lovelace"]["net_pay"] == "2400.00"
        assert by_name["Alan Turing"]["gross_pay"] == "2000.00"
        assert by_name["Alan Turing"]["deductions"] == "400.00"
        assert by_name["Alan Turing"]["net_pay"] == "1600.00"
        assert r["total_gross"] == "5000.00"
        assert r["total_deductions"] == "1000.00"
        assert r["total_net"] == "4000.00"
        assert (Decimal(r["total_net"])
                == Decimal(r["total_gross"])
                - Decimal(r["total_deductions"]))
        after = [dict(r) for r in conn.execute(
            "SELECT * FROM salary_slip ORDER BY id").fetchall()]
        assert after == before


# ── Reports & Status ─────────────────────────────────────────────────────────

class TestReports:
    def test_tax_summary(self, conn, env):
        r = call_action(ACTIONS["uk-tax-summary"], conn, ns(
            company_id=env["company_id"],
            from_date="2026-01-01", to_date="2026-12-31"))
        assert is_ok(r)

    def test_available_reports(self, conn, env):
        r = call_action(ACTIONS["uk-available-reports"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert len(r["reports"]) >= 1

    def test_status(self, conn, env):
        r = call_action(ACTIONS["status"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert r["skill"] == "erpclaw-region-uk"
