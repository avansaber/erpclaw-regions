"""L2-depth tests for six erpclaw-region-in actions.

The pre-existing tests for these actions asserted only the response envelope
(shape keys) or bare routability, never the database. Each test below reads
the rows back through the seam (PyPika via erpclaw_lib.query on the test
connection) and compares exact values, and each action also gets one refusal
case proving the rejection is truthful and the database is byte-identical
afterwards.

Depth signal per action (stored row vs ledger effect):
- india-validate-gstin: pure validator -- asserts derived response fields
  plus a byte-identical database (no stored row, no ledger effect).
- india-setup-gst: stored rows -- 4 regional_settings rows + audit_log row
  with exact values (no ledger effect).
- india-seed-indian-coa: FINDING, broken -- expected 126 stored account
  rows, actually crashes (see test); documents zero committed rows.
- india-tax-summary: read-only report -- asserts exact aggregates over
  seeded invoices plus a byte-identical database (no ledger effect).
- india-tds-withhold: pure computation -- asserts exact computed strings
  plus a byte-identical database (no stored row, no ledger effect).
- india-seed-india-payroll: seeds the six statutory salary components
  plus one audit_log row; the test reads back every stored row and proves
  no other table (and no ledger effect) changed.

Ledger note for the whole file: none of these six actions posts to the
ledger, so no test asserts balanced debit/credit legs -- gl_entry is part of
every snapshot precisely to prove it stays empty.

Money is text: every monetary assertion compares exact Decimal values as
strings. Never float, never approximate, never round().
"""
import json
import os
import sys
import uuid
from decimal import Decimal
from sqlite3 import IntegrityError

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest

from in_helpers import (
    call_action, ns, is_ok, is_error, load_db_query,
    seed_company, seed_fiscal_year,
)
from erpclaw_lib.query import Q, Table, P, insert_row
from erpclaw_lib.response import row_to_dict

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

VALID_GSTIN_27 = "27ABCDE1234F1Z0"
VALID_PAN = "ABCPD1234E"

SNAPSHOT_TABLES = (
    "company", "fiscal_year", "regional_settings", "account",
    "customer", "supplier", "sales_invoice", "purchase_invoice",
    "tax_category", "tax_template", "tax_template_line",
    "salary_component", "gl_entry", "audit_log",
)


def _dump_table(conn, table):
    t = Table(table)
    rows = conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()
    return sorted(
        json.dumps(row_to_dict(r), sort_keys=True, default=str) for r in rows
    )


def _snapshot(conn):
    return {name: _dump_table(conn, name) for name in SNAPSHOT_TABLES}


def _insert(conn, table, **values):
    cols = list(values)
    sql, _ = insert_row(table, {col: P() for col in cols})
    conn.execute(sql, tuple(values[col] for col in cols))



def _settings_map(conn, company_id):
    rs = Table("regional_settings")
    q = (Q.from_(rs).select(rs.key, rs.value)
         .where(rs.company_id == P()))
    return {r["key"]: r["value"]
            for r in conn.execute(q.get_sql(), (company_id,)).fetchall()}


# ── india-validate-gstin: pure validator (no stored row, no ledger) ──────────

class TestValidateGstinDepth:
    def test_valid_gstin_derives_exact_fields_and_writes_nothing(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-validate-gstin"], conn,
                        ns(gstin=VALID_GSTIN_27))
        assert is_ok(r)
        assert r["gstin"] == "27ABCDE1234F1Z0"
        assert r["valid"] is True
        assert r["error"] is None
        assert r["state_code"] == "27"
        assert r["state_name"] == "Maharashtra"
        assert r["pan"] == "ABCDE1234F"
        # Pure validator: no stored row and no ledger effect, so the whole
        # database must read back byte-identical.
        assert _snapshot(conn) == before

    def test_bad_checksum_is_reported_truthfully_and_writes_nothing(
            self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-validate-gstin"], conn,
                        ns(gstin="27ABCDE1234F1Z9"))
        assert is_ok(r)
        assert r["valid"] is False
        assert r["error"] == "Checksum failed (expected '0', got '9')"
        assert r["state_code"] is None
        assert r["state_name"] is None
        assert r["pan"] is None
        assert _snapshot(conn) == before

    def test_missing_gstin_crashes_without_writing_FINDING(self, conn, env):
        # FINDING (deliberately not fixed): `valid, err = ...` later in
        # validate_gstin makes `err` a function-local name, so the
        # `err("--gstin is required")` guard raises UnboundLocalError instead
        # of returning a clean refusal. Same latent crash exists in the
        # pan/tan/aadhaar validators. The database is untouched throughout.
        before = _snapshot(conn)
        with pytest.raises(UnboundLocalError, match="err"):
            call_action(ACTIONS["india-validate-gstin"], conn, ns())
        conn.rollback()
        assert _snapshot(conn) == before


# ── india-setup-gst: stored rows (regional_settings + audit, no ledger) ──────

class TestSetupGstDepth:
    def test_setup_gst_stores_four_settings_rows_and_audit(self, conn, env):
        cid = env["company_id"]
        before_accounts = _dump_table(conn, "account")
        before_gl = _dump_table(conn, "gl_entry")
        r = call_action(ACTIONS["india-setup-gst"], conn, ns(
            company_id=cid, gstin=VALID_GSTIN_27, state_code="27"))
        assert is_ok(r)
        assert r["gstin"] == "27ABCDE1234F1Z0"
        assert r["state_code"] == "27"
        assert r["state_name"] == "Maharashtra"

        settings = _settings_map(conn, cid)
        assert settings == {
            "gstin": "27ABCDE1234F1Z0",
            "gst_state_code": "27",
            "gst_state_name": "Maharashtra",
            "gst_configured": "1",
        }

        al = Table("audit_log")
        q = (Q.from_(al).select(al.skill, al.action, al.entity_type,
                                al.entity_id, al.new_values, al.description)
             .where(al.action == P()).where(al.entity_id == P()))
        audits = conn.execute(
            q.get_sql(), ("india-setup-gst", cid)).fetchall()
        assert len(audits) == 1
        assert audits[0]["skill"] == "erpclaw-region-in"
        assert audits[0]["entity_type"] == "company"
        assert json.loads(audits[0]["new_values"]) == {
            "gstin": "27ABCDE1234F1Z0",
            "gst_state_code": "27",
            "gst_state_name": "Maharashtra",
            "gst_configured": "1",
        }

        # What must NOT have changed: setup-gst creates no GL accounts and
        # posts nothing to the ledger.
        assert _dump_table(conn, "account") == before_accounts
        assert _dump_table(conn, "gl_entry") == before_gl

        # Re-running updates the same four rows instead of duplicating them.
        r2 = call_action(ACTIONS["india-setup-gst"], conn, ns(
            company_id=cid, gstin=VALID_GSTIN_27, state_code="27"))
        assert is_ok(r2)
        assert _settings_map(conn, cid) == settings

    def test_setup_gst_rejects_bad_checksum_without_writing(self, conn, env):
        cid = env["company_id"]
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-setup-gst"], conn, ns(
            company_id=cid, gstin="27ABCDE1234F1Z9", state_code="27"))
        assert is_error(r)
        assert r["message"].startswith("Invalid GSTIN:")
        assert "Checksum failed" in r["message"]
        assert _settings_map(conn, cid) == {}
        assert _snapshot(conn) == before


# ── india-seed-indian-coa: FINDING, broken (no stored rows survive) ──────────

class TestSeedIndianCoaDepth:
    def test_seed_indian_coa_crashes_leaving_zero_rows_FINDING(self, conn, env):
        # FINDING (deliberately not fixed): every template account carries
        # account_number "", so the second insert violates
        # UNIQUE(account_number, company_id) and the action raises
        # sqlite3.IntegrityError instead of creating the expected 126
        # accounts. Nothing is committed: zero account rows, zero audit rows.
        cid = env["company_id"]
        before = _snapshot(conn)
        with pytest.raises(IntegrityError,
                           match="account.account_number"):
            call_action(ACTIONS["india-seed-indian-coa"], conn,
                        ns(company_id=cid))
        conn.rollback()
        acct = Table("account")
        q = (Q.from_(acct).select(acct.id)
             .where(acct.company_id == P()))
        assert conn.execute(q.get_sql(), (cid,)).fetchall() == []
        al = Table("audit_log")
        qa = (Q.from_(al).select(al.id)
              .where(al.action == P()).where(al.entity_id == P()))
        assert conn.execute(
            qa.get_sql(), ("india-seed-indian-coa", cid)).fetchall() == []
        assert _snapshot(conn) == before

    def test_seed_indian_coa_refuses_non_indian_company(self, conn):
        # The country gate runs before any insert, so this refusal is clean:
        # truthful message, no accounts, no audit, identical database.
        us_cid = seed_company(conn, country="US")
        seed_fiscal_year(conn, us_cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-seed-indian-coa"], conn,
                        ns(company_id=us_cid))
        assert is_error(r)
        assert "not India (IN)" in r["message"]
        assert "'US'" in r["message"]
        acct = Table("account")
        q = (Q.from_(acct).select(acct.id)
             .where(acct.company_id == P()))
        assert conn.execute(q.get_sql(), (us_cid,)).fetchall() == []
        assert _snapshot(conn) == before


# ── india-tax-summary: read-only aggregates (no stored row, no ledger) ───────

def _seed_tax_period(conn, cid):
    cust_id = str(uuid.uuid4())
    _insert(conn, "customer", id=cust_id, name="Depth Customer",
            company_id=cid)
    sup_id = str(uuid.uuid4())
    _insert(conn, "supplier", id=sup_id, name="Depth Supplier",
            company_id=cid)
    sales = [
        ("2026-01-15", "submitted", "10000.00", "1800.00"),
        ("2026-02-15", "submitted", "5000.00", "900.00"),
        ("2025-01-15", "submitted", "99999.00", "9999.00"),
        ("2026-03-01", "draft", "777.00", "77.00"),
    ]
    for posting_date, status, total, tax in sales:
        _insert(conn, "sales_invoice", id=str(uuid.uuid4()),
                customer_id=cust_id, posting_date=posting_date,
                status=status, total_amount=total, tax_amount=tax,
                company_id=cid)
    purchases = [
        ("2026-01-20", "submitted", "8000.00", "1440.00"),
        ("2026-04-01", "submitted", "111.00", "11.00"),
        ("2026-02-01", "draft", "222.00", "22.00"),
    ]
    for posting_date, status, total, tax in purchases:
        _insert(conn, "purchase_invoice", id=str(uuid.uuid4()),
                supplier_id=sup_id, posting_date=posting_date,
                status=status, total_amount=total, tax_amount=tax,
                company_id=cid)
    conn.commit()


class TestTaxSummaryDepth:
    def test_tax_summary_reports_exact_aggregates_and_writes_nothing(
            self, conn, env):
        cid = env["company_id"]
        _seed_tax_period(conn, cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-tax-summary"], conn, ns(
            company_id=cid, from_date="2026-01-01", to_date="2026-12-31"))
        assert is_ok(r)
        assert r["report"] == "India Tax Summary"
        assert r["period"] == "2026-01-01 to 2026-12-31"
        co = Table("company")
        qc = Q.from_(co).select(co.name).where(co.id == P())
        assert r["company"] == conn.execute(
            qc.get_sql(), (cid,)).fetchone()["name"]
        # Only in-range submitted invoices count:
        # sales 1800.00 + 900.00 (out-of-range 9999.00 and draft 77.00 out),
        # purchases 1440.00 + 11.00 (draft 22.00 out). Money is text.
        assert r["gst_collected_on_sales"] == "2700.00"
        assert r["gst_paid_on_purchases"] == "1451.00"
        assert r["net_gst_payable"] == "1249.00"
        assert r["net_gst_refundable"] == "0.00"
        assert Decimal(r["gst_collected_on_sales"]) == Decimal("2700.00")
        assert Decimal(r["gst_paid_on_purchases"]) == Decimal("1451.00")
        assert (Decimal(r["gst_collected_on_sales"])
                - Decimal(r["gst_paid_on_purchases"])
                == Decimal(r["net_gst_payable"]))
        # Read-only report: the seeded rows must be untouched and nothing
        # added -- no stored row, and no ledger effect (gl_entry in snapshot).
        assert _snapshot(conn) == before

    def test_tax_summary_refuses_missing_dates(self, conn, env):
        cid = env["company_id"]
        _seed_tax_period(conn, cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-tax-summary"], conn, ns(
            company_id=cid))
        assert is_error(r)
        assert r["message"] == "--from-date and --to-date are required"
        assert _snapshot(conn) == before


# ── india-tds-withhold: pure computation (no stored row, no ledger) ──────────

class TestTdsWithholdDepth:
    def test_tds_withhold_computes_exact_amounts_and_writes_nothing(
            self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-tds-withhold"], conn, ns(
            section="194C", amount="100000", pan=VALID_PAN))
        assert is_ok(r)
        assert r["section"] == "194C"
        assert r["description"] == "Payment to contractors"
        assert r["amount"] == "100000.00"
        assert r["rate"] == "1"
        assert r["tds_applicable"] is True
        # Money is text: 1% of 100000 = 1000.00, net 99000.00, exact strings.
        assert r["tds_amount"] == "1000.00"
        assert r["net_payment"] == "99000.00"
        assert Decimal(r["tds_amount"]) == Decimal("1000.00")
        assert (Decimal(r["amount"]) - Decimal(r["tds_amount"])
                == Decimal(r["net_payment"]))
        assert r["pan"] == VALID_PAN
        assert r["rate_note"] is None

        # Without a PAN the higher 20% rate applies instead of the 1% slab.
        r2 = call_action(ACTIONS["india-tds-withhold"], conn, ns(
            section="194C", amount="100000"))
        assert is_ok(r2)
        assert r2["rate"] == "20"
        assert r2["tds_amount"] == "20000.00"
        assert r2["net_payment"] == "80000.00"
        assert r2["pan"] == "Not provided"
        assert r2["rate_note"] == (
            "Higher rate of 20% applied (PAN not available/invalid)")

        # Pure computation: no stored row and no ledger effect.
        assert _snapshot(conn) == before

    def test_tds_withhold_rejects_unknown_section_without_writing(
            self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-tds-withhold"], conn, ns(
            section="999", amount="100000"))
        assert is_error(r)
        assert r["message"] == "TDS section not found: 999"
        assert "194C" in r["suggestion"]
        assert _snapshot(conn) == before


# ── india-seed-india-payroll: FINDING, no-op (no stored row, no ledger) ───────

class TestSeedIndiaPayrollDepth:
    def test_seed_india_payroll_seeds_six_components(self, conn, env):
        cid = env["company_id"]
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                        ns(company_id=cid))
        assert is_ok(r)
        assert r["message"] == "India payroll components seeded"
        assert r["company_id"] == cid
        assert r["components_created"] == 6
        assert r["components"] == [
            "PF Employee", "PF Employer", "ESI Employee", "ESI Employer",
            "Professional Tax", "TDS on Salary",
        ]
        after = _snapshot(conn)
        for table in SNAPSHOT_TABLES:
            if table in ("salary_component", "audit_log"):
                continue
            assert after[table] == before[table]
        sc = Table("salary_component")
        rows = conn.execute(Q.from_(sc).select(sc.star).get_sql()).fetchall()
        assert len(rows) == 6
        got = {(row_to_dict(rr)["name"], row_to_dict(rr)["component_type"],
                row_to_dict(rr)["description"],
                row_to_dict(rr)["is_statutory"]) for rr in rows}
        assert got == {
            ("PF Employee", "deduction",
             "Provident Fund - employee contribution (12% of PF wage)", 1),
            ("PF Employer", "employer_contribution",
             "Provident Fund - employer contribution (EPF + EPS, 12% of PF wage)", 1),
            ("ESI Employee", "deduction",
             "Employees' State Insurance - employee contribution (0.75%)", 1),
            ("ESI Employer", "employer_contribution",
             "Employees' State Insurance - employer contribution (3.25%)", 1),
            ("Professional Tax", "deduction",
             "Professional tax - state slabs", 1),
            ("TDS on Salary", "deduction",
             "Income tax deducted at source on salary (Section 192)", 1),
        }
        al = Table("audit_log")
        qa = (Q.from_(al).select(al.skill, al.action, al.entity_type,
                                 al.entity_id, al.new_values)
              .where(al.action == P()).where(al.entity_id == P()))
        audits = conn.execute(
            qa.get_sql(), ("india-seed-india-payroll", cid)).fetchall()
        assert len(audits) == 1
        assert audits[0]["skill"] == "erpclaw-region-in"
        assert audits[0]["entity_type"] == "company"
        assert json.loads(audits[0]["new_values"]) == {"components_created": 6}

    def test_seed_india_payroll_refuses_non_indian_company(self, conn):
        us_cid = seed_company(conn, country="US")
        seed_fiscal_year(conn, us_cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                        ns(company_id=us_cid))
        assert is_error(r)
        assert "not India (IN)" in r["message"]
        assert "'US'" in r["message"]
        assert _snapshot(conn) == before
