"""M472 depth: behavioural evidence for `ca-tax-summary`.

Prior state (read before writing anything below): `test_tax_summary` in
`test_region_ca.py` (`TestReports`) only asserts the response envelope is ok
for an empty company. It never seeds an invoice or a salary slip, never reads
a table back, and never exercises a refusal — so the action could sum the
wrong column, include drafts, leak another company's rows, or clamp a
negative net to zero, and the old test would still pass.

Every test below observes the database through PyPika (`erpclaw_lib.query`)
read-backs on connections from `erpclaw_lib.db.get_connection()`: the rows
that must be counted with their exact values, the rows that must be excluded
(draft status, out-of-range dates, another company), and a snapshot proving
the call writes nothing. Catalog questions go through `erpclaw_lib.seam`.
Money compares exact `Decimal` strings.

Ledger scope, stated once so no later reader adds a balance assertion that
cannot hold: `ca-tax-summary` never reaches the general ledger. It is a
read-only dashboard over `sales_invoice`, `purchase_invoice` and
`salary_slip`; the snapshot includes `gl_entry`, `journal_entry`,
`journal_entry_line` and `audit_log` to prove nothing was posted or logged.

Signal depth for `ca-tax-summary`: stored rows (read-only aggregation; the
payload mirrors stored rows and the database is equal afterwards).
"""
import argparse
import importlib.util
import io
import json
import os
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_HERE)
_MODROOT = os.path.dirname(_SCRIPTS_DIR)
_REGIONS = os.path.dirname(_MODROOT)
_SRC = os.path.dirname(_REGIONS)
_LIB = os.path.join(_SRC, "erpclaw", "scripts", "erpclaw-setup", "lib")
if os.path.isdir(os.path.join(_LIB, "erpclaw_lib")) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from erpclaw_lib.db import get_connection
from erpclaw_lib.query import Q, P, Table, insert_row
from erpclaw_lib import seam


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init_schema(db_path):
    mod = _load_module(
        "m472_init_schema",
        os.path.join(_SRC, "erpclaw", "scripts", "erpclaw-setup", "init_schema.py"),
    )
    mod.init_db(db_path)


_DBQ = None


def _actions():
    global _DBQ
    if _DBQ is None:
        _DBQ = _load_module("m472_db_query", os.path.join(_SCRIPTS_DIR, "db_query.py"))
    return _DBQ.ACTIONS


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "m472.sqlite")
    _init_schema(path)
    assert seam.table_exists("sales_invoice", path)
    assert seam.table_exists("purchase_invoice", path)
    assert seam.table_exists("salary_slip", path)
    conn = get_connection(path)
    try:
        yield conn
    finally:
        conn.close()


def call_action(fn, conn, args):
    buf = io.StringIO()

    def _fake_exit(code=0):
        raise SystemExit(code)

    try:
        with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
            fn(conn, args)
    except SystemExit:
        pass
    return json.loads(buf.getvalue().strip())


def ns(**kwargs):
    base = dict(
        company_id=None, from_date=None, to_date=None,
        month=None, year=None, period=None, tax_year=None,
        amount=None, province=None, search=None, business_number=None,
        bn=None, sin=None, gross_salary=None, annual_income=None,
        annual_earnings=None, pay_period=None, pay_periods="12",
        employee_id=None, recipient_name=None, income_type=None,
        reason_code=None,
    )
    base.update(kwargs)
    return argparse.Namespace(**base)


def is_ok(result):
    return result.get("status") == "ok"


def is_error(result):
    return result.get("status") == "error"


_CENT = Decimal("0.01")


def _money(value):
    return str(Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP))


def _insert(conn, table, **values):
    sql, cols = insert_row(table, {key: P() for key in values})
    conn.execute(sql, [values[col] for col in cols])


def _seed_company(conn, country="CA"):
    cid = str(uuid.uuid4())
    _insert(
        conn, "company", id=cid, name="M472 Co " + cid[:6],
        abbr="M472" + cid[:4], default_currency="CAD",
        country=country, fiscal_year_start_month=1,
    )
    _insert(
        conn, "fiscal_year", id=str(uuid.uuid4()), name="FY-" + cid[:6],
        start_date="2026-01-01", end_date="2026-12-31", company_id=cid,
    )
    conn.commit()
    return cid


def _seed_customer(conn, company_id):
    cid = str(uuid.uuid4())
    _insert(conn, "customer", id=cid, name="Cust " + cid[:6], company_id=company_id)
    conn.commit()
    return cid


def _seed_supplier(conn, company_id):
    sid = str(uuid.uuid4())
    _insert(conn, "supplier", id=sid, name="Sup " + sid[:6], company_id=company_id)
    conn.commit()
    return sid


def _seed_payroll(conn, company_id):
    emp = str(uuid.uuid4())
    _insert(
        conn, "employee", id=emp, first_name="Asha",
        full_name="Asha Singh", date_of_joining="2025-01-01",
        company_id=company_id,
    )
    run = str(uuid.uuid4())
    _insert(
        conn, "payroll_run", id=run, period_start="2026-03-01",
        period_end="2026-03-31", company_id=company_id,
    )
    conn.commit()
    return emp, run


def _seed_sale(conn, company_id, customer_id, posting_date, total, tax, status="submitted"):
    _insert(
        conn, "sales_invoice", id=str(uuid.uuid4()), customer_id=customer_id,
        posting_date=posting_date, currency="CAD", total_amount=total,
        tax_amount=tax, grand_total=_money(Decimal(total) + Decimal(tax)),
        status=status, company_id=company_id,
    )
    conn.commit()


def _seed_purchase(conn, company_id, supplier_id, posting_date, total, tax, status="submitted"):
    _insert(
        conn, "purchase_invoice", id=str(uuid.uuid4()), supplier_id=supplier_id,
        posting_date=posting_date, currency="CAD", total_amount=total,
        tax_amount=tax, grand_total=_money(Decimal(total) + Decimal(tax)),
        status=status, company_id=company_id,
    )
    conn.commit()


def _seed_slip(conn, company_id, employee_id, run_id, period_start, gross, deductions, status="submitted"):
    _insert(
        conn, "salary_slip", id=str(uuid.uuid4()), payroll_run_id=run_id,
        employee_id=employee_id, period_start=period_start,
        period_end=period_start, gross_pay=gross, total_deductions=deductions,
        net_pay=_money(Decimal(gross) - Decimal(deductions)),
        status=status, company_id=company_id,
    )
    conn.commit()


SNAPSHOT_TABLES = (
    "company", "fiscal_year", "customer", "supplier", "employee",
    "payroll_run", "sales_invoice", "purchase_invoice", "salary_slip",
    "gl_entry", "journal_entry", "journal_entry_line", "audit_log",
)


def _snapshot(conn):
    snap = {}
    for name in SNAPSHOT_TABLES:
        table = Table(name)
        rows = conn.execute(Q.from_(table).select("*").get_sql()).fetchall()
        snap[name] = sorted(repr(dict(row)) for row in rows)
    return snap


def _read_sales(conn, company_id, from_date, to_date):
    table = Table("sales_invoice")
    query = (
        Q.from_(table)
        .select(table.tax_amount, table.total_amount)
        .where(
            (table.company_id == P()) & (table.status == P())
            & (table.posting_date >= P()) & (table.posting_date <= P())
        )
    )
    rows = conn.execute(
        query.get_sql(), (company_id, "submitted", from_date, to_date)
    ).fetchall()
    tax = sum((Decimal(row["tax_amount"]) for row in rows), Decimal("0"))
    revenue = sum((Decimal(row["total_amount"]) for row in rows), Decimal("0"))
    return tax, revenue, len(rows)


def _read_purchases(conn, company_id, from_date, to_date):
    table = Table("purchase_invoice")
    query = (
        Q.from_(table)
        .select(table.tax_amount)
        .where(
            (table.company_id == P()) & (table.status == P())
            & (table.posting_date >= P()) & (table.posting_date <= P())
        )
    )
    rows = conn.execute(
        query.get_sql(), (company_id, "submitted", from_date, to_date)
    ).fetchall()
    tax = sum((Decimal(row["tax_amount"]) for row in rows), Decimal("0"))
    return tax, len(rows)


def _read_slips(conn, company_id, from_date, to_date):
    table = Table("salary_slip")
    query = (
        Q.from_(table)
        .select(table.gross_pay, table.total_deductions)
        .where(
            (table.company_id == P()) & (table.status == P())
            & (table.period_start >= P()) & (table.period_start <= P())
        )
    )
    rows = conn.execute(
        query.get_sql(), (company_id, "submitted", from_date, to_date)
    ).fetchall()
    gross = sum((Decimal(row["gross_pay"]) for row in rows), Decimal("0"))
    deductions = sum((Decimal(row["total_deductions"]) for row in rows), Decimal("0"))
    return gross, deductions, len(rows)


class TestTaxSummaryDepth:
    def test_aggregates_only_submitted_in_range_rows_and_writes_nothing(self, db):
        company_id = _seed_company(db)
        customer_id = _seed_customer(db, company_id)
        supplier_id = _seed_supplier(db, company_id)
        employee_id, run_id = _seed_payroll(db, company_id)
        other_company = _seed_company(db)
        other_customer = _seed_customer(db, other_company)

        _seed_sale(db, company_id, customer_id, "2026-03-15", "1000.00", "65.00")
        _seed_sale(db, company_id, customer_id, "2026-06-20", "2000.00", "130.00")
        _seed_sale(db, company_id, customer_id, "2026-04-10", "9999.99", "999.99", status="draft")
        _seed_sale(db, company_id, customer_id, "2025-12-31", "777.77", "77.77")
        _seed_sale(db, other_company, other_customer, "2026-05-01", "500.00", "50.00")

        _seed_purchase(db, company_id, supplier_id, "2026-02-10", "500.00", "25.00")
        _seed_purchase(db, company_id, supplier_id, "2026-09-05", "1500.00", "75.00")
        _seed_purchase(db, company_id, supplier_id, "2026-03-01", "1111.11", "111.11", status="draft")
        _seed_purchase(db, company_id, supplier_id, "2027-01-02", "222.22", "22.22")

        _seed_slip(db, company_id, employee_id, run_id, "2026-03-01", "5000.00", "1200.50")
        _seed_slip(db, company_id, employee_id, run_id, "2026-06-01", "3000.00", "800.25")
        _seed_slip(db, company_id, employee_id, run_id, "2026-04-01", "9999.99", "999.99", status="draft")
        _seed_slip(db, company_id, employee_id, run_id, "2025-12-01", "4444.44", "444.44")

        before = _snapshot(db)
        result = call_action(
            _actions()["ca-tax-summary"], db,
            ns(company_id=company_id, from_date="2026-01-01", to_date="2026-12-31"),
        )
        assert is_ok(result)
        assert result["report"] == "Canada Tax Summary"
        assert result["period"] == "2026-01-01 to 2026-12-31"

        assert result["gst_hst_collected"] == "195.00"
        assert result["revenue"] == "3000.00"
        assert result["itc_paid"] == "100.00"
        assert result["net_gst_hst_payable"] == "95.00"
        assert result["sales_invoice_count"] == 2
        assert result["purchase_invoice_count"] == 2
        assert result["total_gross_payroll"] == "8000.00"
        assert result["total_payroll_deductions"] == "2000.75"
        assert result["salary_slip_count"] == 2

        sales_tax, revenue, sales_count = _read_sales(db, company_id, "2026-01-01", "2026-12-31")
        purchase_tax, purchase_count = _read_purchases(db, company_id, "2026-01-01", "2026-12-31")
        gross, deductions, slip_count = _read_slips(db, company_id, "2026-01-01", "2026-12-31")
        assert result["gst_hst_collected"] == _money(sales_tax)
        assert result["revenue"] == _money(revenue)
        assert result["itc_paid"] == _money(purchase_tax)
        assert result["net_gst_hst_payable"] == _money(max(sales_tax - purchase_tax, Decimal("0")))
        assert result["sales_invoice_count"] == sales_count
        assert result["purchase_invoice_count"] == purchase_count
        assert result["total_gross_payroll"] == _money(gross)
        assert result["total_payroll_deductions"] == _money(deductions)
        assert result["salary_slip_count"] == slip_count

        assert _snapshot(db) == before

    def test_empty_period_returns_zeroes_and_writes_nothing(self, db):
        company_id = _seed_company(db)
        before = _snapshot(db)
        result = call_action(
            _actions()["ca-tax-summary"], db,
            ns(company_id=company_id, from_date="2026-01-01", to_date="2026-12-31"),
        )
        assert is_ok(result)
        assert result["gst_hst_collected"] == "0.00"
        assert result["revenue"] == "0.00"
        assert result["itc_paid"] == "0.00"
        assert result["net_gst_hst_payable"] == "0.00"
        assert result["sales_invoice_count"] == 0
        assert result["purchase_invoice_count"] == 0
        assert result["total_gross_payroll"] == "0.00"
        assert result["total_payroll_deductions"] == "0.00"
        assert result["salary_slip_count"] == 0
        assert _snapshot(db) == before

    def test_net_payable_clamped_at_zero_when_itc_exceeds_collected(self, db):
        company_id = _seed_company(db)
        customer_id = _seed_customer(db, company_id)
        supplier_id = _seed_supplier(db, company_id)
        _seed_sale(db, company_id, customer_id, "2026-03-15", "200.00", "10.00")
        _seed_purchase(db, company_id, supplier_id, "2026-04-10", "1000.00", "50.00")
        result = call_action(
            _actions()["ca-tax-summary"], db,
            ns(company_id=company_id, from_date="2026-01-01", to_date="2026-12-31"),
        )
        assert is_ok(result)
        assert result["gst_hst_collected"] == "10.00"
        assert result["itc_paid"] == "50.00"
        assert result["net_gst_hst_payable"] == "0.00"
        sales_tax, _, _ = _read_sales(db, company_id, "2026-01-01", "2026-12-31")
        purchase_tax, _ = _read_purchases(db, company_id, "2026-01-01", "2026-12-31")
        assert sales_tax == Decimal("10.00")
        assert purchase_tax == Decimal("50.00")

    def test_missing_to_date_refused_without_writes(self, db):
        company_id = _seed_company(db)
        customer_id = _seed_customer(db, company_id)
        _seed_sale(db, company_id, customer_id, "2026-03-15", "1000.00", "65.00")
        before = _snapshot(db)
        result = call_action(
            _actions()["ca-tax-summary"], db,
            ns(company_id=company_id, from_date="2026-01-01", to_date=None),
        )
        assert is_error(result)
        assert result["message"] == "--from-date and --to-date are required"
        assert _snapshot(db) == before
