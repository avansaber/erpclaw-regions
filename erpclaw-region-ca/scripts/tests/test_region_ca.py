"""L1 pytest tests for ERPClaw Region CA module.

Covers: BN/SIN validation, GST/HST/PST/QST/sales-tax computation,
ITC, tax rates, CPP/CPP2/QPP/EI, federal/provincial tax,
total payroll deductions, payroll summary, compliance reports,
tax summary, available reports, and status.
"""
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from ca_helpers import call_action, ns, is_ok, is_error, load_db_query

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_bn_base_valid(self, conn, env):
        r = call_action(ACTIONS["ca-validate-business-number"], conn, ns(
            bn="123456789"))
        assert is_ok(r)
        assert r["valid"] is True
        assert r["format"] == "base"

    def test_validate_bn_full_valid(self, conn, env):
        r = call_action(ACTIONS["ca-validate-business-number"], conn, ns(
            bn="123456789RT0001"))
        assert is_ok(r)
        assert r["valid"] is True
        assert r["format"] == "full"
        assert r["program_code"] == "RT"

    def test_validate_bn_invalid_length(self, conn, env):
        r = call_action(ACTIONS["ca-validate-business-number"], conn, ns(
            bn="12345"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_sin_valid(self, conn, env):
        # 046 454 286 is a well-known valid Luhn SIN
        r = call_action(ACTIONS["ca-validate-sin"], conn, ns(sin="046454286"))
        assert is_ok(r)
        assert r["valid"] is True

    def test_validate_sin_invalid_luhn(self, conn, env):
        r = call_action(ACTIONS["ca-validate-sin"], conn, ns(sin="123456789"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_sin_wrong_length(self, conn, env):
        r = call_action(ACTIONS["ca-validate-sin"], conn, ns(sin="12345"))
        assert is_ok(r)
        assert r["valid"] is False


# ── Tax Computation ──────────────────────────────────────────────────────────

class TestTaxComputation:
    def test_compute_gst(self, conn, env):
        r = call_action(ACTIONS["ca-compute-gst"], conn, ns(amount="1000"))
        assert is_ok(r)
        assert r["gst_rate"] == "5"
        assert r["gst_amount"] == "50.00"
        assert r["total"] == "1050.00"

    def test_compute_hst_ontario(self, conn, env):
        r = call_action(ACTIONS["ca-compute-hst"], conn, ns(
            amount="1000", province="ON"))
        assert is_ok(r)
        assert r["hst_rate"] == "13"
        assert r["hst_amount"] == "130.00"
        assert r["total"] == "1130.00"

    def test_compute_hst_non_hst_province_error(self, conn, env):
        r = call_action(ACTIONS["ca-compute-hst"], conn, ns(
            amount="1000", province="AB"))
        assert is_error(r)

    def test_compute_pst(self, conn, env):
        r = call_action(ACTIONS["ca-compute-pst"], conn, ns(
            amount="1000", province="BC"))
        assert is_ok(r)
        assert r["pst_amount"] == "70.00"  # BC PST = 7%

    def test_compute_qst(self, conn, env):
        r = call_action(ACTIONS["ca-compute-qst"], conn, ns(
            amount="1000"))
        assert is_ok(r)
        # QST = 9.975%
        assert r["qst_amount"] == "99.75"

    def test_compute_sales_tax(self, conn, env):
        r = call_action(ACTIONS["ca-compute-sales-tax"], conn, ns(
            amount="1000", province="ON"))
        assert is_ok(r)
        assert r["province"] == "ON"
        assert r["total_tax"] == "130.00"

    def test_list_tax_rates(self, conn, env):
        r = call_action(ACTIONS["ca-list-tax-rates"], conn, ns())
        assert is_ok(r)
        assert len(r["provinces"]) >= 13  # 13 provinces/territories

    def test_compute_itc(self, conn, env):
        r = call_action(ACTIONS["ca-compute-itc"], conn, ns(
            company_id=env["company_id"], month="1", year="2026"))
        assert is_ok(r)
        assert r["eligible_itc"]  # May be 0 with no invoices, but key should exist


# ── Payroll ──────────────────────────────────────────────────────────────────

class TestPayroll:
    def test_compute_cpp(self, conn, env):
        r = call_action(ACTIONS["ca-compute-cpp"], conn, ns(
            gross_salary="5000", pay_periods="12"))
        assert is_ok(r)
        assert r["employee_cpp"]
        assert r["employer_cpp"]

    def test_compute_cpp2(self, conn, env):
        r = call_action(ACTIONS["ca-compute-cpp2"], conn, ns(
            annual_earnings="80000"))
        assert is_ok(r)
        # 80000 is above first ceiling, so CPP2 should apply
        assert "employee_cpp2" in r

    def test_compute_qpp(self, conn, env):
        r = call_action(ACTIONS["ca-compute-qpp"], conn, ns(
            gross_salary="5000", pay_periods="12"))
        assert is_ok(r)
        assert r["employee_qpp"]

    def test_compute_ei(self, conn, env):
        r = call_action(ACTIONS["ca-compute-ei"], conn, ns(
            gross_salary="5000", province="ON"))
        assert is_ok(r)
        assert r["employee_ei"]
        assert r["employer_ei"]

    def test_compute_ei_quebec(self, conn, env):
        r = call_action(ACTIONS["ca-compute-ei"], conn, ns(
            gross_salary="5000", province="QC"))
        assert is_ok(r)
        assert "note" in r  # Quebec has different EI rate

    def test_compute_federal_tax(self, conn, env):
        r = call_action(ACTIONS["ca-compute-federal-tax"], conn, ns(
            annual_income="80000"))
        assert is_ok(r)
        assert r["net_tax"]
        assert r["effective_rate"]

    def test_compute_provincial_tax(self, conn, env):
        r = call_action(ACTIONS["ca-compute-provincial-tax"], conn, ns(
            annual_income="80000", province="ON"))
        assert is_ok(r)
        assert r["net_tax"]

    def test_compute_total_payroll_deductions(self, conn, env):
        r = call_action(ACTIONS["ca-compute-total-payroll-deductions"], conn, ns(
            gross_salary="5000", province="ON"))
        assert is_ok(r)
        assert r["total_deductions"]
        assert r["net_pay"]

    def test_payroll_summary(self, conn, env):
        r = call_action(ACTIONS["ca-payroll-summary"], conn, ns(
            company_id=env["company_id"], month="1", year="2026"))
        assert is_ok(r)


# ── Reports & Status ─────────────────────────────────────────────────────────

class TestReports:
    def test_available_reports(self, conn, env):
        r = call_action(ACTIONS["ca-available-reports"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert len(r["reports"]) >= 1

    def test_tax_summary(self, conn, env):
        r = call_action(ACTIONS["ca-tax-summary"], conn, ns(
            company_id=env["company_id"],
            from_date="2026-01-01", to_date="2026-12-31"))
        assert is_ok(r)

    def test_status(self, conn, env):
        r = call_action(ACTIONS["status"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert r["skill"] == "erpclaw-region-ca"
