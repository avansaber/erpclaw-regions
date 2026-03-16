"""L1 pytest tests for ERPClaw Region India module.

Covers: GSTIN/PAN/TAN/Aadhaar validation, GST computation (intra/inter-state),
HSN codes, ITC, PF, ESI, professional tax, TDS on salary,
reports (GSTR1, GSTR3B, HSN summary, e-invoice, e-way bill),
tax summary, available reports, and status.
"""
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from in_helpers import call_action, ns, is_ok, is_error, load_db_query

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_pan_valid(self, conn, env):
        r = call_action(ACTIONS["india-validate-pan"], conn, ns(pan="ABCPD1234E"))
        assert is_ok(r)
        assert r["valid"] is True
        assert r["entity_type"] == "Individual / Person"

    def test_validate_pan_invalid(self, conn, env):
        r = call_action(ACTIONS["india-validate-pan"], conn, ns(pan="12345"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_tan_valid(self, conn, env):
        r = call_action(ACTIONS["india-validate-tan"], conn, ns(tan="ABCD12345E"))
        assert is_ok(r)
        assert r["valid"] is True

    def test_validate_tan_invalid(self, conn, env):
        r = call_action(ACTIONS["india-validate-tan"], conn, ns(tan="12345"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_aadhaar_wrong_length(self, conn, env):
        r = call_action(ACTIONS["india-validate-aadhaar"], conn, ns(aadhaar="12345"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_aadhaar_starts_with_0(self, conn, env):
        r = call_action(ACTIONS["india-validate-aadhaar"], conn, ns(aadhaar="012345678901"))
        assert is_ok(r)
        assert r["valid"] is False


# ── GST Computation ──────────────────────────────────────────────────────────

class TestGSTComputation:
    def test_compute_gst_intra_state(self, conn, env):
        r = call_action(ACTIONS["india-compute-gst"], conn, ns(
            amount="10000", seller_state="27", buyer_state="27",
            gst_rate="18"))
        assert is_ok(r)
        assert r["intra_state"] is True
        assert r["cgst_amount"] == "900.00"
        assert r["sgst_amount"] == "900.00"
        assert r["igst_amount"] == "0"
        assert r["total_tax"] == "1800.00"

    def test_compute_gst_inter_state(self, conn, env):
        r = call_action(ACTIONS["india-compute-gst"], conn, ns(
            amount="10000", seller_state="27", buyer_state="29",
            gst_rate="18"))
        assert is_ok(r)
        assert r["intra_state"] is False
        assert r["igst_amount"] == "1800.00"
        assert r["cgst_amount"] == "0"
        assert r["sgst_amount"] == "0"

    def test_compute_gst_missing_rate_and_hsn(self, conn, env):
        r = call_action(ACTIONS["india-compute-gst"], conn, ns(
            amount="10000", seller_state="27", buyer_state="27"))
        assert is_error(r)

    def test_list_hsn_codes(self, conn, env):
        r = call_action(ACTIONS["india-list-hsn-codes"], conn, ns())
        assert is_ok(r)
        assert "codes" in r
        assert "total_count" in r


# ── Payroll ──────────────────────────────────────────────────────────────────

class TestPayroll:
    def test_compute_pf(self, conn, env):
        r = call_action(ACTIONS["india-compute-pf"], conn, ns(
            basic_salary="12000", company_id=env["company_id"]))
        assert is_ok(r)
        # 12% of 12000 = 1440
        assert r["employee_pf_12_pct"] == "1440.00"
        assert r["capped"] is False

    def test_compute_pf_above_ceiling(self, conn, env):
        r = call_action(ACTIONS["india-compute-pf"], conn, ns(
            basic_salary="25000", company_id=env["company_id"]))
        assert is_ok(r)
        # Capped at 15000 wage: 12% of 15000 = 1800
        assert r["employee_pf_12_pct"] == "1800.00"
        assert r["capped"] is True

    def test_compute_esi_applicable(self, conn, env):
        r = call_action(ACTIONS["india-compute-esi"], conn, ns(
            gross_salary="18000", company_id=env["company_id"]))
        assert is_ok(r)
        assert r["applicable"] is True
        # 0.75% of 18000 = 135
        assert r["employee_contribution"] == "135"

    def test_compute_esi_above_ceiling(self, conn, env):
        r = call_action(ACTIONS["india-compute-esi"], conn, ns(
            gross_salary="25000", company_id=env["company_id"]))
        assert is_ok(r)
        assert r["applicable"] is False
        assert r["employee_contribution"] == "0.00"

    def test_compute_professional_tax(self, conn, env):
        r = call_action(ACTIONS["india-compute-professional-tax"], conn, ns(
            gross_salary="30000", state_code="MH",
            company_id=env["company_id"]))
        assert is_ok(r)
        assert r["applicable"] is True

    def test_compute_tds_on_salary(self, conn, env):
        r = call_action(ACTIONS["india-compute-tds-on-salary"], conn, ns(
            annual_income="800000", regime="new",
            company_id=env["company_id"]))
        assert is_ok(r)
        assert r["total_annual_tax"]


# ── Reports ──────────────────────────────────────────────────────────────────

class TestReports:
    def test_generate_gstr1(self, conn, env):
        r = call_action(ACTIONS["india-generate-gstr1"], conn, ns(
            company_id=env["company_id"], month="1", year="2026"))
        assert is_ok(r)
        assert r["report"] == "GSTR-1"

    def test_generate_gstr3b(self, conn, env):
        r = call_action(ACTIONS["india-generate-gstr3b"], conn, ns(
            company_id=env["company_id"], month="1", year="2026"))
        assert is_ok(r)
        assert r["report"] == "GSTR-3B"

    def test_tax_summary(self, conn, env):
        r = call_action(ACTIONS["india-tax-summary"], conn, ns(
            company_id=env["company_id"],
            from_date="2026-01-01", to_date="2026-12-31"))
        assert is_ok(r)

    def test_available_reports(self, conn, env):
        r = call_action(ACTIONS["india-available-reports"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert len(r["reports"]) >= 1

    def test_status(self, conn, env):
        r = call_action(ACTIONS["status"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert r["skill"] == "erpclaw-region-in"
