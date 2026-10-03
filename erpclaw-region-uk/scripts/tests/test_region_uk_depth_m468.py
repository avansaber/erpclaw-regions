"""Behavioural depth for three erpclaw-region-uk actions (task m468).

Each action below previously had only a shape test (asserts on the response
envelope) or no test at all, and none of them observed the database: an
action could return a perfect envelope while writing nothing — or the wrong
thing — and stay green. Every test here drives the REAL action against a
fresh core DB, reads the stored rows back with PyPika-built queries through
``erpclaw_lib.query`` on a connection from ``erpclaw_lib.db.get_connection``,
and compares exact values; money is compared as exact ``Decimal`` strings,
never float, never rounded. Catalog questions go through
``erpclaw_lib.seam``.

Per-action depth (stored row vs ledger effect):

- uk-setup-vat: stored rows (``regional_settings`` vat_number + mtd_enabled
  plus the audit row). It posts no ledger rows, so no ledger assertion can
  hold; the write-nothing-else proof is a full snapshot taken before and
  after the call.
- uk-tax-summary: stored rows (the report pins VAT collected/reclaimed/net
  and payroll totals against the underlying sales_invoice, purchase_invoice
  and salary_slip rows, with draft/cancelled/out-of-window/other-company
  rows proved excluded). The report itself is read-only and posts no
  ledger rows, so no ledger assertion can hold for it; the snapshot is the
  no-write proof.
- uk-validate-vat-number: neither stored row nor ledger effect. It is a
  pure validator: it stores no rows and reaches no ledger, so no ledger or
  stored-row assertion can hold; the tests pin the exact classification of
  three inputs and prove the database is byte-identical afterwards.

No test in this file inspects catalog tables or sets connection options;
reads are PyPika-built and run on a connection from
``erpclaw_lib.db.get_connection``.
"""
import json
import os
import sys
import uuid
from decimal import Decimal

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from uk_helpers import (  # noqa: E402
    call_action, is_error, is_ok, load_db_query, ns, seed_company,
)
from erpclaw_lib import seam  # noqa: E402
from erpclaw_lib.db import get_connection  # noqa: E402
from erpclaw_lib.query import Field, P, Q, Table, insert_row  # noqa: E402

UK = load_db_query()

VALID_VAT = "GB289136634"
VALID_VAT_BARE = "289136634"
CHECKSUM_BAD_VAT = "GB123456789"


@pytest.fixture
def conn(db_path):
    connection = get_connection(db_path)
    yield connection
    connection.close()


def _msg(result):
    return result.get("message", "")


def _row(conn, table, row_id):
    t = Table(table)
    q = Q.from_(t).select(t.star).where(t.id == P())
    found = conn.execute(q.get_sql(), (row_id,)).fetchone()
    assert found is not None, "%s %s not found" % (table, row_id)
    return dict(found)


def _where(conn, table, **filters):
    t = Table(table)
    q = Q.from_(t).select(t.star)
    params = []
    for column, value in filters.items():
        q = q.where(Field(column) == P())
        params.append(value)
    return [dict(r) for r in conn.execute(q.get_sql(), params).fetchall()]


def _all(conn, table):
    t = Table(table)
    q = Q.from_(t).select(t.star).orderby(t.id)
    return [dict(r) for r in conn.execute(q.get_sql()).fetchall()]


def _snapshot(conn, tables):
    return {name: _all(conn, name) for name in tables}


_SNAPSHOT_TABLES = (
    "company", "fiscal_year", "regional_settings", "customer", "supplier",
    "employee", "payroll_run", "sales_invoice", "purchase_invoice",
    "salary_slip", "audit_log",
)
_LEDGERS = ("gl_entry", "payment_ledger_entry", "stock_ledger_entry")


def _regional(conn, company_id):
    rows = _where(conn, "regional_settings", company_id=company_id)
    return {r["key"]: r["value"] for r in rows}


def _audits(conn, action, entity_id):
    rows = _where(conn, "audit_log", action=action, entity_id=entity_id)
    return [r for r in rows if r["skill"] == "erpclaw-region-uk"]


def _insert(conn, table, **values):
    row_id = values.pop("id", str(uuid.uuid4()))
    columns = ["id"] + list(values.keys())
    placeholders = {column: P() for column in columns}
    sql, _ = insert_row(table, placeholders)
    conn.execute(sql, [row_id] + [values[column] for column in values])
    conn.commit()
    return row_id


# ---------------------------------------------------------------------------
# uk-setup-vat — stored rows (no ledger: regional_settings master data posts
# no GL, payment-ledger or stock rows).
# ---------------------------------------------------------------------------

class TestUkSetupVatDepth:
    def test_setup_stores_vat_number_and_mtd_flag(self, conn, env):
        assert seam.table_exists("regional_settings")
        cid = env["company_id"]
        assert _regional(conn, cid) == {}
        ledgers_before = _snapshot(conn, _LEDGERS)

        r = call_action(UK.ACTIONS["uk-setup-vat"], conn, ns(
            company_id=cid, vat_number=VALID_VAT_BARE))
        assert is_ok(r), r
        assert r["vat_number_stored"] is True
        assert r["vat_number"] == VALID_VAT
        assert r["mtd_enabled"] is True

        stored = _regional(conn, cid)
        assert stored == {"vat_number": VALID_VAT, "mtd_enabled": "true"}

        audits = _audits(conn, "uk-setup-vat", cid)
        assert len(audits) == 1
        assert audits[0]["entity_type"] == "company"
        assert json.loads(audits[0]["new_values"]) == {"vat_number": VALID_VAT}

        assert _snapshot(conn, _LEDGERS) == ledgers_before

    def test_setup_updates_in_place_without_duplicates(self, conn, env):
        cid = env["company_id"]
        first = call_action(UK.ACTIONS["uk-setup-vat"], conn, ns(
            company_id=cid, vat_number="GB111111111"))
        assert is_ok(first), first
        assert _regional(conn, cid)["vat_number"] == "GB111111111"

        second = call_action(UK.ACTIONS["uk-setup-vat"], conn, ns(
            company_id=cid, vat_number="gb 289 136 634"))
        assert is_ok(second), second
        assert second["vat_number"] == VALID_VAT

        stored = _regional(conn, cid)
        assert stored == {"vat_number": VALID_VAT, "mtd_enabled": "true"}
        assert len(_where(conn, "regional_settings", company_id=cid)) == 2
        assert len(_audits(conn, "uk-setup-vat", cid)) == 2

    def test_setup_refusals_leave_the_database_identical(self, conn, env):
        cid = env["company_id"]
        other_gb = seed_company(conn, country="GB")
        us = seed_company(conn, country="US")
        snapshot = _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS)

        r = call_action(UK.ACTIONS["uk-setup-vat"], conn, ns(
            company_id=cid, vat_number=None))
        assert is_error(r)
        assert _msg(r) == "--vat-number is required."

        r = call_action(UK.ACTIONS["uk-setup-vat"], conn, ns(
            company_id=cid, vat_number="GB123"))
        assert is_error(r)
        assert _msg(r) == (
            "Invalid UK VAT number: GB123. Must be GB + 9 digits.")

        r = call_action(UK.ACTIONS["uk-setup-vat"], conn, ns(
            company_id=us, vat_number=VALID_VAT))
        assert is_error(r)
        assert _msg(r) == ("This action is for UK companies only. "
                           "Company country must be GB.")

        assert _regional(conn, cid) == {}
        assert _regional(conn, other_gb) == {}
        assert _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS) == snapshot


# ---------------------------------------------------------------------------
# uk-tax-summary — stored rows (the dashboard pins its totals against the
# underlying invoice/slip rows; it is read-only so no ledger assertion can
# hold for the report itself — the snapshot is the no-write proof).
# ---------------------------------------------------------------------------

def _tax_book(conn, cid, other_cid):
    cust = _insert(conn, "customer", name="Acme Ltd", company_id=cid)
    sup = _insert(conn, "supplier", name="Supply Co", company_id=cid)
    emp = _insert(conn, "employee", first_name="Amy", last_name="Chen",
                  full_name="Amy Chen", date_of_joining="2025-01-01",
                  company_id=cid)
    run = _insert(conn, "payroll_run", period_start="2026-03-01",
                  period_end="2026-03-31", company_id=cid, status="submitted")
    other_cust = _insert(conn, "customer", name="Other Ltd",
                         company_id=other_cid)

    def sales(tax, date, status, company=cid, customer=cust):
        return _insert(conn, "sales_invoice", customer_id=customer,
                       posting_date=date, tax_amount=tax, status=status,
                       company_id=company)

    def purchase(tax, date, status):
        return _insert(conn, "purchase_invoice", supplier_id=sup,
                       posting_date=date, tax_amount=tax, status=status,
                       company_id=cid)

    def slip(gross, ded, net, start, status):
        return _insert(conn, "salary_slip", payroll_run_id=run,
                       employee_id=emp, period_start=start,
                       period_end="2026-03-31", gross_pay=gross,
                       total_deductions=ded, net_pay=net, status=status,
                       company_id=cid)

    sales("200.00", "2026-03-15", "submitted")
    sales("40.00", "2026-04-10", "submitted")
    sales("999.99", "2026-03-15", "draft")
    sales("50.00", "2025-01-01", "submitted")
    sales("500.00", "2026-03-15", "submitted",
          company=other_cid, customer=other_cust)
    purchase("30.00", "2026-03-20", "submitted")
    purchase("10.00", "2026-03-20", "cancelled")
    slip("3000.00", "800.00", "2200.00", "2026-03-01", "submitted")
    slip("999.00", "99.00", "900.00", "2026-03-01", "draft")
    slip("100.00", "10.00", "90.00", "2026-02-01", "submitted")
    return run


class TestUkTaxSummaryDepth:
    def test_summary_pins_totals_and_excludes_non_qualifying_rows(
            self, conn, env):
        for table in ("sales_invoice", "purchase_invoice", "salary_slip"):
            assert seam.table_exists(table)
        cid = env["company_id"]
        other = seed_company(conn, country="GB")
        _tax_book(conn, cid, other)
        before = _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS)

        march = call_action(UK.ACTIONS["uk-tax-summary"], conn, ns(
            company_id=cid, from_date="2026-03-01", to_date="2026-03-31"))
        assert is_ok(march), march
        assert march["period"] == "2026-03-01 to 2026-03-31"
        assert march["vat_collected"] == "200.00"
        assert march["vat_reclaimed"] == "30.00"
        assert march["net_vat"] == "170.00"
        assert Decimal(march["net_vat"]) == (
            Decimal(march["vat_collected"]) - Decimal(march["vat_reclaimed"]))
        assert march["payroll_slips"] == 1
        assert march["total_gross_pay"] == "3000.00"
        assert march["total_deductions"] == "800.00"
        assert march["total_net_pay"] == "2200.00"
        assert Decimal(march["total_net_pay"]) == (
            Decimal(march["total_gross_pay"])
            - Decimal(march["total_deductions"]))

        wider = call_action(UK.ACTIONS["uk-tax-summary"], conn, ns(
            company_id=cid, from_date="2026-03-01", to_date="2026-04-30"))
        assert is_ok(wider), wider
        assert wider["vat_collected"] == "240.00"
        assert wider["vat_reclaimed"] == "30.00"
        assert wider["net_vat"] == "210.00"
        assert wider["payroll_slips"] == 1

        qualifying = [r["tax_amount"] for r in _where(
            conn, "sales_invoice", company_id=cid, status="submitted")
            if "2026-03-01" <= r["posting_date"] <= "2026-03-31"]
        assert qualifying == ["200.00"]
        reclaimed = [r["tax_amount"] for r in _where(
            conn, "purchase_invoice", company_id=cid, status="submitted")
            if "2026-03-01" <= r["posting_date"] <= "2026-03-31"]
        assert reclaimed == ["30.00"]

        assert _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS) == before

    def test_summary_refusals_leave_the_database_identical(
            self, conn, env):
        cid = env["company_id"]
        other = seed_company(conn, country="GB")
        us = seed_company(conn, country="US")
        _tax_book(conn, cid, other)
        snapshot = _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS)

        r = call_action(UK.ACTIONS["uk-tax-summary"], conn, ns(
            company_id=cid, from_date=None, to_date=None))
        assert is_error(r)
        assert _msg(r) == "--from-date and --to-date are required."

        r = call_action(UK.ACTIONS["uk-tax-summary"], conn, ns(
            company_id=us, from_date="2026-01-01", to_date="2026-12-31"))
        assert is_error(r)
        assert _msg(r) == ("This action is for UK companies only. "
                           "Company country must be GB.")

        r = call_action(UK.ACTIONS["uk-tax-summary"], conn, ns(
            company_id="no-such-company", from_date="2026-01-01",
            to_date="2026-12-31"))
        assert is_error(r)
        assert _msg(r) == "Company not found: no-such-company"

        assert _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS) == snapshot


# ---------------------------------------------------------------------------
# uk-validate-vat-number — neither stored row nor ledger effect: a pure
# validator stores no rows and reaches no ledger, so no ledger or stored-row
# assertion can hold; the no-write proof is the snapshot.
# ---------------------------------------------------------------------------

class TestUkValidateVatNumberDepth:
    def test_classifies_each_shape_and_writes_nothing(self, conn, env):
        before = _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS)

        good = call_action(UK.ACTIONS["uk-validate-vat-number"], conn, ns(
            vat_number="gb 289 136 634"))
        assert is_ok(good), good
        assert good["valid"] is True
        assert good["formatted"] == VALID_VAT
        assert good["digits"] == "289136634"
        assert Decimal(good["digits"]) == Decimal("289136634")

        bad_checksum = call_action(
            UK.ACTIONS["uk-validate-vat-number"], conn, ns(
                vat_number=CHECKSUM_BAD_VAT))
        assert is_ok(bad_checksum), bad_checksum
        assert bad_checksum["valid"] is False
        assert bad_checksum["formatted"] == CHECKSUM_BAD_VAT
        assert bad_checksum["reason"] == (
            "Modulus 97 check digit validation failed")

        bad_format = call_action(
            UK.ACTIONS["uk-validate-vat-number"], conn, ns(
                vat_number="GB123"))
        assert is_ok(bad_format), bad_format
        assert bad_format["valid"] is False
        assert bad_format["reason"] == "Must be GB prefix + exactly 9 digits"

        assert _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS) == before

    def test_missing_number_refuses_without_writing(self, conn, env):
        snapshot = _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS)

        r = call_action(UK.ACTIONS["uk-validate-vat-number"], conn, ns(
            vat_number=None))
        assert is_error(r)
        assert _msg(r) == "--vat-number is required."

        assert _snapshot(conn, _SNAPSHOT_TABLES + _LEDGERS) == snapshot
