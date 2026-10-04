"""Behavioural depth tests for the 12 India actions named in m463.

Each test pins what the action does to (or reads from) the database rather
than the shape of its response envelope:

- india-seed-india-defaults is the only writer of the twelve: its test reads
  back every stored row (accounts, categories, templates, lines, audit).
- The other eleven are read-only or purely computational: each test seeds the
  stored rows the action reads, asserts the response carries those exact
  values, and asserts the database is byte-identical afterwards.
- None of the twelve reaches the general ledger (this module posts no journal
  or GL entries), so no test asserts ledger legs; each class comment says so.

Money is text: monetary assertions compare exact Decimal values parsed from
the response strings. No float, no round, no approximation.

Read-backs are built with PyPika through erpclaw_lib.query on the same
connection the action ran on. No sqlite_master, no PRAGMA, no
information_schema anywhere in this file.

Findings documented here without fixing (see CHANGES.md):
- F1 india-generate-einvoice-payload emits empty PrdDesc/HsnCd and Qty 0
  because the core schema has no such columns to read.
- F2/F3 form16 and form24q are fixed: they read the submitted and paid
  salary slips per component and report read zeros when no slips exist.
- F5 tds-return still returns static zero amounts despite its note claiming
  withholding sourcing.
- F6 payroll-summary is fixed: it reads the month's salary slips per
  component and refuses when the payroll components were never seeded.
- F4 india-generate-hsn-summary raises sqlite3.OperationalError
  (no such column: sii.item_name) on the current schema.
- F7 the seed links every template line to the *Input* GST accounts, even on
  the Sales templates.
- F8 india-generate-form24q is fixed: it range-checks --quarter 1-4 like
  india-generate-tds-return does instead of echoing any quarter verbatim.
"""
import json
import os
import sqlite3
import sys
import uuid
from decimal import Decimal

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from in_helpers import call_action, ns, is_ok, is_error, load_db_query, seed_company
from erpclaw_lib.query import Q, Table, P, insert_row

_mod = load_db_query()
ACTIONS = _mod.ACTIONS


# ── read-back helpers (PyPika-built, same connection) ────────────────────────

_SNAP_TABLES = (
    "company", "fiscal_year", "account", "tax_category", "tax_template",
    "tax_template_line", "regional_settings", "customer", "supplier", "item",
    "sales_invoice", "sales_invoice_item", "purchase_invoice",
    "purchase_invoice_item", "employee", "audit_log", "gl_entry",
    "journal_entry", "journal_entry_line",
)


def _snapshot(conn):
    """Every table this module can read or write, as sorted row tuples."""
    snap = {}
    for name in _SNAP_TABLES:
        tbl = Table(name)
        rows = conn.execute(Q.from_(tbl).select(tbl.star).get_sql()).fetchall()
        snap[name] = sorted((tuple(r) for r in rows), key=repr)
    return snap


def _insert(conn, table, **cols):
    sql, _ = insert_row(table, {key: P() for key in cols})
    conn.execute(sql, tuple(cols[key] for key in cols))
    conn.commit()
    return cols.get("id")


def _company_name(conn, company_id):
    co = Table("company")
    row = conn.execute(
        Q.from_(co).select(co.name).where(co.id == P()).get_sql(),
        (company_id,)).fetchone()
    return row["name"]


def _seed_supplier(conn, company_id, name="Depth Supplier"):
    sid = str(uuid.uuid4())
    _insert(conn, "supplier", id=sid, name=name, company_id=company_id)
    return sid


def _seed_purchase_invoice(conn, company_id, supplier_id, posting_date,
                           tax_amount, status="submitted",
                           total_amount="1000"):
    pid = str(uuid.uuid4())
    _insert(conn, "purchase_invoice", id=pid, supplier_id=supplier_id,
            posting_date=posting_date, total_amount=total_amount,
            tax_amount=tax_amount, grand_total=total_amount,
            status=status, company_id=company_id)
    return pid


def _seed_customer(conn, company_id, name="Depth Buyer",
                   tax_id="29ABCDE1234F1Z5"):
    cid = str(uuid.uuid4())
    _insert(conn, "customer", id=cid, name=name, tax_id=tax_id,
            company_id=company_id)
    return cid


def _seed_sales_invoice(conn, company_id, customer_id, posting_date,
                        total_amount, grand_total, status="submitted"):
    iid = str(uuid.uuid4())
    _insert(conn, "sales_invoice", id=iid, customer_id=customer_id,
            posting_date=posting_date, total_amount=total_amount,
            tax_amount="0", grand_total=grand_total, status=status,
            company_id=company_id)
    return iid


def _seed_employee(conn, company_id, full_name="Asha K"):
    eid = str(uuid.uuid4())
    _insert(conn, "employee", id=eid, first_name=full_name.split()[0],
            last_name="K", full_name=full_name,
            date_of_joining="2024-06-01", company_id=company_id)
    return eid


# ── india-add-hsn-code: writes nothing; the "registration" is session-only ───
# No ledger effect: the action performs no inserts and posts no entries.

class TestAddHsnCodeDepth:
    def test_add_hsn_code_echoes_inputs_and_stores_nothing(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-add-hsn-code"], conn, ns(
            code="3004", description="Depth widgets", gst_rate="12"))
        assert is_ok(r)
        assert r["code"] == "3004"
        assert r["description"] == "Depth widgets"
        assert r["gst_rate"] == "12"
        assert r["message"] == "HSN code 3004 registered with GST rate 12%"
        assert "note" in r
        # Real behaviour: nothing is persisted anywhere.
        assert _snapshot(conn) == before

    def test_add_hsn_code_refuses_without_code(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-add-hsn-code"], conn, ns(
            description="Depth widgets", gst_rate="12"))
        assert is_error(r)
        assert r["message"] == "--code is required"
        assert _snapshot(conn) == before


# ── india-add-reverse-charge-rule: writes nothing ────────────────────────────
# No ledger effect: the action performs no inserts and posts no entries.

class TestAddReverseChargeRuleDepth:
    def test_add_reverse_charge_rule_echoes_inputs_and_stores_nothing(
            self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-add-reverse-charge-rule"], conn, ns(
            category="Legal services", gst_rate="18"))
        assert is_ok(r)
        assert r["category"] == "Legal services"
        assert r["gst_rate"] == "18"
        assert r["message"] == (
            "Reverse charge rule registered for 'Legal services' at 18%")
        assert r["mechanism"] == (
            "Under RCM, buyer pays GST instead of seller")
        assert _snapshot(conn) == before

    def test_add_reverse_charge_rule_refuses_without_rate(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-add-reverse-charge-rule"], conn, ns(
            category="Legal services"))
        assert is_error(r)
        assert r["message"] == "--gst-rate is required"
        assert _snapshot(conn) == before


# ── india-compute-itc: pins the sum over stored purchase_invoice rows ────────
# No ledger effect: pure computation over stored rows; nothing is written.

class TestComputeItcDepth:
    def test_compute_itc_sums_submitted_period_tax(self, conn, env):
        cid = env["company_id"]
        sid = _seed_supplier(conn, cid)
        _seed_purchase_invoice(conn, cid, sid, "2026-01-05", "180.00")
        _seed_purchase_invoice(conn, cid, sid, "2026-01-20", "220.50")
        _seed_purchase_invoice(conn, cid, sid, "2026-01-10", "90.00",
                               status="draft")
        _seed_purchase_invoice(conn, cid, sid, "2026-02-02", "999.99")
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-compute-itc"], conn, ns(
            company_id=cid, month="1", year="2026"))
        assert is_ok(r)
        assert r["report"] == "Input Tax Credit"
        assert r["period"] == "2026-01"
        # Only submitted January rows count: 180.00 + 220.50.
        assert r["total_purchase_tax_paid"] == "400.50"
        assert r["ineligible_section_17_5"] == "0.00"
        assert r["eligible_itc"] == "400.50"
        assert (Decimal(r["eligible_itc"])
                == Decimal(r["total_purchase_tax_paid"])
                - Decimal(r["ineligible_section_17_5"]))
        # Read-only: the stored rows are untouched.
        assert _snapshot(conn) == before

    def test_compute_itc_refuses_without_month(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-compute-itc"], conn, ns(
            company_id=env["company_id"], year="2026"))
        assert is_error(r)
        assert r["message"] == "--month and --year are required"
        assert _snapshot(conn) == before


# ── india-generate-einvoice-payload: payload pinned to stored rows ───────────
# No ledger effect: read-only over sales_invoice/customer/item rows.

class TestEinvoicePayloadDepth:
    def test_einvoice_payload_carries_stored_invoice_values(
            self, conn, env):
        cid = env["company_id"]
        cust = _seed_customer(conn, cid)
        inv = _seed_sales_invoice(conn, cid, cust, "2026-01-15",
                                  total_amount="100000",
                                  grand_total="118000")
        item = str(uuid.uuid4())
        _insert(conn, "item", id=item, item_code="WIDGET",
                item_name="Widget")
        _insert(conn, "sales_invoice_item", id=str(uuid.uuid4()),
                sales_invoice_id=inv, item_id=item, quantity="10",
                uom="NOS", rate="10000", amount="100000")
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-einvoice-payload"], conn,
                        ns(invoice_id=inv))
        assert is_ok(r)
        assert r["format"] == "NIC v1.1 JSON"
        payload = r["e_invoice_payload"]
        assert payload["Version"] == "1.1"
        assert payload["DocDtls"] == {"Typ": "INV", "No": inv[:16],
                                      "Dt": "15/01/2026"}
        assert payload["BuyerDtls"] == {"Gstin": "29ABCDE1234F1Z5",
                                        "LglNm": "Depth Buyer", "Pos": ""}
        assert payload["SellerDtls"] == {
            "Gstin": "", "LglNm": _company_name(conn, cid),
            "Addr1": "", "Loc": "", "Pin": 0, "Stcd": ""}
        assert len(payload["ItemList"]) == 1
        line = payload["ItemList"][0]
        assert line["SlNo"] == "1"
        assert line["Unit"] == "NOS"
        assert Decimal(str(line["UnitPrice"])) == Decimal("10000")
        assert Decimal(str(line["TotAmt"])) == Decimal("100000")
        assert Decimal(str(line["AssAmt"])) == Decimal("100000")
        assert Decimal(str(payload["ValDtls"]["AssVal"])) == Decimal("100000")
        assert (Decimal(str(payload["ValDtls"]["TotInvVal"]))
                == Decimal("118000"))
        # F1 (known, not fixed): the core schema has no item_name, hsn_code,
        # qty or gst_rate columns on these rows, so the payload emits the
        # action's defaults — empty description/HSN and zero quantity.
        assert line["PrdDesc"] == ""
        assert line["HsnCd"] == ""
        assert line["Qty"] == 0.0
        assert _snapshot(conn) == before

    def test_einvoice_payload_refuses_without_invoice(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-einvoice-payload"], conn,
                        ns())
        assert is_error(r)
        assert r["message"] == "--invoice-id is required"
        assert _snapshot(conn) == before


# ── india-generate-eway-bill-payload: threshold branch pinned to grand_total ─
# No ledger effect: read-only over the stored sales_invoice row.

class TestEwayBillPayloadDepth:
    def test_eway_bill_above_threshold_and_below(self, conn, env):
        cid = env["company_id"]
        cust = _seed_customer(conn, cid)
        big = _seed_sales_invoice(conn, cid, cust, "2026-01-15",
                                  total_amount="100000",
                                  grand_total="118000")
        small = _seed_sales_invoice(conn, cid, cust, "2026-01-16",
                                    total_amount="1000",
                                    grand_total="1180")
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-eway-bill-payload"], conn,
                        ns(invoice_id=big, transporter_id="29TRN1234"))
        assert is_ok(r)
        assert r["required"] is True
        payload = r["eway_bill_payload"]
        assert payload["docNo"] == big
        assert payload["docDate"] == "15/01/2026"
        assert payload["toGstin"] == "29ABCDE1234F1Z5"
        assert payload["totalValue"] == "118000.00"
        assert payload["transporterId"] == "29TRN1234"

        r2 = call_action(ACTIONS["india-generate-eway-bill-payload"], conn,
                         ns(invoice_id=small, transporter_id="29TRN1234"))
        assert is_ok(r2)
        assert r2["required"] is False
        assert r2["message"] == (
            "E-way bill not required \u2014 invoice value INR 1180 "
            "is below INR 50,000 threshold")
        assert _snapshot(conn) == before

    def test_eway_bill_refuses_without_transporter(self, conn, env):
        cid = env["company_id"]
        cust = _seed_customer(conn, cid)
        inv = _seed_sales_invoice(conn, cid, cust, "2026-01-15",
                                  total_amount="100000",
                                  grand_total="118000")
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-eway-bill-payload"], conn,
                        ns(invoice_id=inv))
        assert is_error(r)
        assert r["message"] == "--transporter-id is required"
        assert _snapshot(conn) == before


# ── india-generate-form16: employee row echoed; amounts static ───────────────
# No ledger effect: reads one employee row; writes nothing.

class TestForm16Depth:
    def test_form16_echoes_employee_and_reports_static_zeros(
            self, conn, env):
        eid = _seed_employee(conn, env["company_id"])
        r0 = call_action(ACTIONS["india-seed-india-payroll"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r0)
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-form16"], conn, ns(
            employee_id=eid, fiscal_year="2025-26"))
        assert is_ok(r)
        assert r["report"] == "Form 16"
        assert r["fiscal_year"] == "2025-26"
        assert r["employee_name"] == "Asha K"
        assert r["part_a"]["period"] == "April 2025 - March 2026"
        # F2 (fixed): amounts are read from the employee's submitted and
        # paid salary slips; with no slips every amount reads "0.00". The
        # schema has no employee PAN column so employee_pan is always "".
        assert r["employee_pan"] == ""
        assert r["part_a"]["quarterly_tds"] == {
            "Q1": "0.00", "Q2": "0.00", "Q3": "0.00", "Q4": "0.00"}
        assert r["part_a"]["total_tds_deducted"] == "0.00"
        assert r["part_b"]["gross_salary"] == "0.00"
        assert r["part_b"]["standard_deduction"] == "75000"
        assert r["part_b"]["taxable_income"] == "0.00"
        assert r["part_b"]["tds_deducted"] == "0.00"
        assert r["slip_count"] == 0
        assert _snapshot(conn) == before

    def test_form16_refuses_unknown_employee(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-form16"], conn, ns(
            employee_id="does-not-exist", fiscal_year="2025-26"))
        assert is_error(r)
        assert r["message"] == "Employee not found: does-not-exist"
        assert _snapshot(conn) == before


# ── india-generate-form24q: company echoed; deductees static ─────────────────
# No ledger effect: reads the company row; writes nothing.

class TestForm24qDepth:
    def test_form24q_echoes_company_and_reports_static_zeros(
            self, conn, env):
        cid = env["company_id"]
        r0 = call_action(ACTIONS["india-seed-india-payroll"], conn, ns(
            company_id=cid))
        assert is_ok(r0)
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
            company_id=cid, quarter="3", year="2025"))
        assert is_ok(r)
        assert r["report"] == "Form 24Q"
        assert r["quarter"] == "Q3"
        assert r["fiscal_year"] == "2025-26"
        assert r["company"] == _company_name(conn, cid)
        # F3 (fixed): deductees and totals are read from the quarter's
        # submitted and paid salary slips; with no slips they read empty.
        assert r["deductees"] == []
        assert r["total_salary_paid"] == "0.00"
        assert r["total_tds_deducted"] == "0.00"
        assert _snapshot(conn) == before

    def test_form24q_refuses_without_quarter(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
            company_id=env["company_id"], year="2025"))
        assert is_error(r)
        assert r["message"] == "--quarter and --year are required"
        assert _snapshot(conn) == before

    def test_form24q_accepts_out_of_range_quarter(self, conn, env):
        # F8 (fixed): like india-generate-tds-return, this action now
        # range-checks --quarter, so "5" is refused.
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
            company_id=env["company_id"], quarter="5", year="2025"))
        assert is_error(r)
        assert r["message"] == "--quarter must be 1-4"
        assert _snapshot(conn) == before


# ── india-generate-hsn-summary: broken on the current schema ────────────────
# F4 (known, not fixed): the SELECT names sii.item_name / sii.item_code /
# sii.qty / sii.tax_amount and i.hsn_code, none of which exist in the core
# schema, so any call with valid dates raises sqlite3.OperationalError before
# any row could be returned. No ledger effect: the failed SELECT writes
# nothing.

class TestHsnSummaryDepth:
    def test_hsn_summary_raises_missing_column(self, conn, env):
        cid = env["company_id"]
        cust = _seed_customer(conn, cid)
        _seed_sales_invoice(conn, cid, cust, "2026-01-15",
                            total_amount="1000", grand_total="1180")
        before = _snapshot(conn)
        with pytest.raises(sqlite3.OperationalError,
                           match="no such column"):
            call_action(ACTIONS["india-generate-hsn-summary"], conn, ns(
                company_id=cid, from_date="2026-01-01",
                to_date="2026-01-31"))
        assert _snapshot(conn) == before

    def test_hsn_summary_refuses_without_dates(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-hsn-summary"], conn, ns(
            company_id=env["company_id"]))
        assert is_error(r)
        assert r["message"] == "--from-date and --to-date are required"
        assert _snapshot(conn) == before


# ── india-generate-tds-return: company/period echoed; rows static ────────────
# No ledger effect: reads the company row; writes nothing.

class TestTdsReturnDepth:
    def test_tds_return_echoes_period_and_reports_static_zeros(
            self, conn, env):
        cid = env["company_id"]
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-tds-return"], conn, ns(
            company_id=cid, quarter="2", year="2025", form="26Q"))
        assert is_ok(r)
        assert r["report"] == "TDS Return \u2014 Form 26Q"
        assert r["period"] == "Q2 FY 2025-26"
        assert r["form"] == "26Q"
        assert r["start_date"] == "2025-07-01"
        assert r["end_date"] == "2025-09-30"
        assert r["company"] == _company_name(conn, cid)
        # F5 (known, not fixed): deductees and totals are static empties.
        assert r["deductees"] == []
        assert r["total_tds_deducted"] == "0.00"
        assert _snapshot(conn) == before

    def test_tds_return_refuses_bad_quarter(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-tds-return"], conn, ns(
            company_id=env["company_id"], quarter="5", year="2025",
            form="26Q"))
        assert is_error(r)
        assert r["message"] == "--quarter must be 1-4"
        assert _snapshot(conn) == before


# ── india-payroll-summary: company/period echoed; totals static ──────────────
# No ledger effect: reads the company row; writes nothing.

class TestPayrollSummaryDepth:
    def test_payroll_summary_refuses_before_components_are_seeded(
            self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-payroll-summary"], conn, ns(
            company_id=env["company_id"], month="3", year="2026"))
        assert is_error(r)
        assert r["message"] == (
            "India payroll components are not set up: PF Employee, "
            "ESI Employee, Professional Tax, TDS on Salary. "
            "Run india-seed-india-payroll first.")
        assert _snapshot(conn) == before

    def test_payroll_summary_refuses_without_month(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-payroll-summary"], conn, ns(
            company_id=env["company_id"], year="2026"))
        assert is_error(r)
        assert r["message"] == "--month and --year are required"
        assert _snapshot(conn) == before


# ── india-seed-india-defaults: the only writer — every stored row pinned ─────
# No ledger effect: seeds master rows only; gl_entry / journal_entry /
# journal_entry_line stay empty (asserted below).

_EXPECTED_ACCOUNTS = [
    ("CGST Input", "tax", "asset"),
    ("CGST Output", "tax", "liability"),
    ("ESI Payable", "payroll_payable", "liability"),
    ("IGST Input", "tax", "asset"),
    ("IGST Output", "tax", "liability"),
    ("PF Payable", "payroll_payable", "liability"),
    ("Professional Tax Payable", "payroll_payable", "liability"),
    ("SGST Input", "tax", "asset"),
    ("SGST Output", "tax", "liability"),
    ("TCS Payable", "tax", "liability"),
    ("TDS Payable", "tax", "liability"),
]

_EXPECTED_CATEGORIES = [
    "GST 0% (Exempt)",
    "GST 0.25% (Precious Stones)",
    "GST 18% (Standard)",
    "GST 3% (Precious Metals)",
    "GST 40% (Luxury)",
    "GST 5% (Essential)",
    "Reverse Charge",
]

_EXPECTED_TEMPLATES = [
    ("India GST 18% Purchase", "purchase", "9.00"),
    ("India GST 18% Sales", "sales", "9.00"),
    ("India GST 40% Purchase", "purchase", "20.00"),
    ("India GST 40% Sales", "sales", "20.00"),
    ("India GST 5% Purchase", "purchase", "2.50"),
    ("India GST 5% Sales", "sales", "2.50"),
]


class TestSeedIndiaDefaultsDepth:
    def test_seed_writes_exact_master_rows_and_is_idempotent(
            self, conn, env):
        cid = env["company_id"]
        r = call_action(ACTIONS["india-seed-india-defaults"], conn, ns(
            company_id=cid))
        assert is_ok(r)
        assert r["company_id"] == cid
        assert r["created"] == {"accounts": 11, "templates": 6,
                                "categories": 7}

        acct = Table("account")
        rows = conn.execute(
            Q.from_(acct).select(acct.name, acct.account_type,
                                 acct.root_type, acct.company_id,
                                 acct.is_group)
            .where(acct.company_id == P()).get_sql(), (cid,)).fetchall()
        assert sorted((row["name"], row["account_type"],
                       row["root_type"]) for row in rows) == \
            _EXPECTED_ACCOUNTS
        assert {row["company_id"] for row in rows} == {cid}
        assert {row["is_group"] for row in rows} == {0}

        tc = Table("tax_category")
        cats = conn.execute(
            Q.from_(tc).select(tc.name).get_sql()).fetchall()
        assert sorted(row["name"] for row in cats) == _EXPECTED_CATEGORIES

        tt = Table("tax_template")
        tt_rows = conn.execute(
            Q.from_(tt).select(tt.id, tt.name, tt.tax_type,
                               tt.is_default, tt.company_id)
            .where(tt.company_id == P()).get_sql(), (cid,)).fetchall()
        assert sorted((row["name"], row["tax_type"])
                      for row in tt_rows) == [
            (name, tax_type)
            for name, tax_type, _ in _EXPECTED_TEMPLATES]
        assert {row["is_default"] for row in tt_rows} == {0}
        tpl_ids = {row["name"]: row["id"] for row in tt_rows}

        ttl = Table("tax_template_line")
        acc = Table("account").as_("a")
        for name, _tax_type, half_rate in _EXPECTED_TEMPLATES:
            lines = conn.execute(
                Q.from_(ttl).join(acc).on(
                    acc.id == ttl.tax_account_id)
                .select(acc.name, ttl.rate, ttl.charge_type,
                        ttl.row_order, ttl.add_deduct)
                .where(ttl.tax_template_id == P()).get_sql(),
                (tpl_ids[name],)).fetchall()
            # F7 (known, not fixed): both lines point at the *Input*
            # accounts, even on the Sales templates.
            assert sorted(tuple(row) for row in
                           ([row["name"], row["rate"],
                             row["charge_type"], row["row_order"],
                             row["add_deduct"]] for row in lines)) == [
                ("CGST Input", half_rate, "on_net_total", 0, "add"),
                ("SGST Input", half_rate, "on_net_total", 1, "add"),
            ]

        audit = Table("audit_log")
        audit_rows = conn.execute(
            Q.from_(audit).select(audit.skill, audit.action,
                                  audit.entity_type, audit.entity_id,
                                  audit.new_values).get_sql()).fetchall()
        seed_audits = [row for row in audit_rows
                       if row["action"] == "india-seed-india-defaults"]
        assert len(seed_audits) == 1
        assert seed_audits[0]["skill"] == "erpclaw-region-in"
        assert seed_audits[0]["entity_type"] == "company"
        assert seed_audits[0]["entity_id"] == cid
        assert json.loads(seed_audits[0]["new_values"]) == {
            "accounts": 11, "templates": 6, "categories": 7}

        # No ledger effect: no GL or journal rows were posted.
        for table in ("gl_entry", "journal_entry", "journal_entry_line"):
            tbl = Table(table)
            count = conn.execute(
                Q.from_(tbl).select(tbl.star).get_sql()).fetchall()
            assert count == []

        # Idempotent: a second run creates no master rows. It does write
        # one more audit row (auditing is unconditional), pinned exactly.
        mid = _snapshot(conn)
        r2 = call_action(ACTIONS["india-seed-india-defaults"], conn, ns(
            company_id=cid))
        assert is_ok(r2)
        assert r2["created"] == {"accounts": 0, "templates": 0,
                                 "categories": 0}
        after = _snapshot(conn)
        for table in _SNAP_TABLES:
            if table == "audit_log":
                continue
            assert after[table] == mid[table], table
        assert len(after["audit_log"]) == len(mid["audit_log"]) + 1
        audit2 = Table("audit_log")
        vals = [json.loads(row["new_values"]) for row in conn.execute(
            Q.from_(audit2).select(audit2.new_values)
            .where((audit2.action == P()) & (audit2.entity_id == P()))
            .get_sql(),
            ("india-seed-india-defaults", cid)).fetchall()]
        assert vals.count({"accounts": 0, "templates": 0,
                           "categories": 0}) == 1

    def test_seed_refuses_non_india_company_without_writing(
            self, conn, env):
        us_id = seed_company(conn, name="US Co", abbr="UC", country="US")
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-seed-india-defaults"], conn, ns(
            company_id=us_id))
        assert is_error(r)
        assert r["message"] == (
            f"Company '{_company_name(conn, us_id)}' country is 'US', "
            "not India (IN).")
        assert r["suggestion"] == (
            "Set company country to 'IN' via erpclaw before using "
            "India actions.")
        assert _snapshot(conn) == before
