"""L1 pytest tests for ERPClaw Region EU module.

Covers: VAT number/IBAN/EORI validation, VAT computation, reverse charge,
OSS, distance selling threshold, triangulation, VAT rates listing,
withholding tax, EU country listing, intrastat codes, tax summary,
available reports, and status.
"""
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from eu_helpers import call_action, ns, is_ok, is_error, load_db_query

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_vat_number_valid_de(self, conn, env):
        r = call_action(ACTIONS["eu-validate-eu-vat-number"], conn, ns(
            vat_number="DE123456789"))
        assert is_ok(r)
        assert r["valid"] is True

    def test_validate_vat_number_invalid(self, conn, env):
        r = call_action(ACTIONS["eu-validate-eu-vat-number"], conn, ns(
            vat_number="XX999"))
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_iban_valid(self, conn, env):
        # Known valid German IBAN
        r = call_action(ACTIONS["eu-validate-iban"], conn, ns(
            iban="DE89370400440532013000"))  # fake test fixture for SEC-03
        assert is_ok(r)
        assert r["valid"] is True
        assert r["country"] == "DE"

    def test_validate_iban_invalid(self, conn, env):
        r = call_action(ACTIONS["eu-validate-iban"], conn, ns(
            iban="DE00000000000000000000"))  # fake test fixture for SEC-03
        assert is_ok(r)
        assert r["valid"] is False

    def test_validate_eori_valid(self, conn, env):
        r = call_action(ACTIONS["eu-validate-eori"], conn, ns(
            eori="DE123456789012345"))
        assert is_ok(r)
        assert r["valid"] is True

    def test_check_vies_format(self, conn, env):
        r = call_action(ACTIONS["eu-check-vies-format"], conn, ns(
            vat_number="FR12345678901"))
        assert is_ok(r)


# ── VAT Computation ──────────────────────────────────────────────────────────

class TestVATComputation:
    def test_compute_vat_germany(self, conn, env):
        r = call_action(ACTIONS["eu-compute-vat"], conn, ns(
            amount="1000", country="DE"))
        assert is_ok(r)
        assert r["vat_rate"] == "19"
        assert r["vat_amount"] == "190.00"
        assert r["total"] == "1190.00"

    def test_compute_vat_france(self, conn, env):
        r = call_action(ACTIONS["eu-compute-vat"], conn, ns(
            amount="1000", country="FR"))
        assert is_ok(r)
        assert r["vat_rate"] == "20"
        assert r["vat_amount"] == "200.00"

    def test_compute_reverse_charge(self, conn, env):
        r = call_action(ACTIONS["eu-compute-reverse-charge"], conn, ns(
            amount="5000", seller_country="DE", buyer_country="FR"))
        assert is_ok(r)
        assert r["reverse_charge_applies"] is True
        assert r["seller_vat"] == "0.00"

    def test_compute_reverse_charge_same_country(self, conn, env):
        r = call_action(ACTIONS["eu-compute-reverse-charge"], conn, ns(
            amount="5000", seller_country="DE", buyer_country="DE"))
        assert is_ok(r)
        assert r["reverse_charge_applies"] is False

    def test_list_eu_vat_rates(self, conn, env):
        r = call_action(ACTIONS["eu-list-eu-vat-rates"], conn, ns())
        assert is_ok(r)
        assert r["total"] == 27  # 27 EU member states

    def test_compute_oss_vat(self, conn, env):
        r = call_action(ACTIONS["eu-compute-oss-vat"], conn, ns(
            amount="100", seller_country="DE", buyer_country="FR"))
        assert is_ok(r)
        # OSS uses buyer country rate (France 20%)
        assert r["vat_rate"] == "20"
        assert r["vat_amount"] == "20.00"

    def test_check_distance_selling_threshold_below(self, conn, env):
        r = call_action(ACTIONS["eu-check-distance-selling-threshold"], conn, ns(
            annual_sales="5000"))
        assert is_ok(r)
        assert r["threshold_exceeded"] is False

    def test_check_distance_selling_threshold_above(self, conn, env):
        r = call_action(ACTIONS["eu-check-distance-selling-threshold"], conn, ns(
            annual_sales="15000"))
        assert is_ok(r)
        assert r["threshold_exceeded"] is True

    def test_triangulation_check(self, conn, env):
        r = call_action(ACTIONS["eu-triangulation-check"], conn, ns(
            country_a="DE", country_b="FR", country_c="IT"))
        assert is_ok(r)

    def test_compute_withholding_tax(self, conn, env):
        r = call_action(ACTIONS["eu-compute-withholding-tax"], conn, ns(
            amount="10000", income_type="dividends",
            source_country="DE", recipient_country="FR"))
        assert is_ok(r)
        assert r["gross_amount"] == "10000.00"


# ── Reference Data ───────────────────────────────────────────────────────────

class TestReferenceData:
    def test_list_eu_countries(self, conn, env):
        r = call_action(ACTIONS["eu-list-eu-countries"], conn, ns())
        assert is_ok(r)
        assert r["total"] == 27

    def test_list_intrastat_codes(self, conn, env):
        r = call_action(ACTIONS["eu-list-intrastat-codes"], conn, ns())
        assert is_ok(r)
        assert r["total"] >= 1


# ── Reports & Status ─────────────────────────────────────────────────────────

class TestReports:
    def test_tax_summary(self, conn, env):
        r = call_action(ACTIONS["eu-tax-summary"], conn, ns(
            company_id=env["company_id"],
            from_date="2026-01-01", to_date="2026-12-31"))
        assert is_ok(r)

    def test_available_reports(self, conn, env):
        r = call_action(ACTIONS["eu-available-reports"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert len(r["reports"]) >= 1

    def test_status(self, conn, env):
        r = call_action(ACTIONS["status"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r)
        assert r["skill"] == "erpclaw-region-eu"
