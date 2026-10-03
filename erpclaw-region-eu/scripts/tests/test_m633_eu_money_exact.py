"""m633: EU VAT aggregates are exact decimals (no binary-float drift).

Seeds invoice amounts with cents binary floating point cannot represent
exactly, runs each money-aggregating action, and asserts every affected
money figure as the exact hand-computed string.

Small cases pin ordinary cents. Large cases seed 90000000000000.11 and
90000000000000.22 in each summed money column and assert the hand-computed
180000000000000.33 (or the exact derived figure); the pre-change float sum
returns 180000000000000.30 on SQLite, so those cases fail before and pass
after. Second-company cases seed an identical in-period submitted month in
a second company and assert the first company's figures are unchanged.
"""
import os
import sys
import uuid

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from eu_helpers import (call_action, ns, is_ok, load_db_query, seed_company,
                        seed_fiscal_year)
from erpclaw_lib.query import Q, Table, P, insert_row

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

LARGE_A = "90000000000000.11"
LARGE_B = "90000000000000.22"
LARGE_SUM = "180000000000000.33"


def _insert(conn, table, **cols):
    sql, _ = insert_row(table, {key: P() for key in cols})
    conn.execute(sql, tuple(cols[key] for key in cols))
    conn.commit()
    return cols.get("id")


def _customer(conn, company_id):
    cid = str(uuid.uuid4())
    _insert(conn, "customer", id=cid, name="EU Buyer %s" % cid[:6],
            company_id=company_id)
    return cid


def _supplier(conn, company_id):
    sid = str(uuid.uuid4())
    _insert(conn, "supplier", id=sid, name="EU Supplier %s" % sid[:6],
            company_id=company_id)
    return sid


def _sales(conn, company_id, customer_id, posting_date, total, tax,
           status="submitted"):
    iid = str(uuid.uuid4())
    _insert(conn, "sales_invoice", id=iid, customer_id=customer_id,
            posting_date=posting_date, total_amount=total, tax_amount=tax,
            grand_total=total, status=status, company_id=company_id)
    return iid


def _purchase(conn, company_id, supplier_id, posting_date, total, tax,
              status="submitted"):
    pid = str(uuid.uuid4())
    _insert(conn, "purchase_invoice", id=pid, supplier_id=supplier_id,
            posting_date=posting_date, total_amount=total, tax_amount=tax,
            grand_total=total, status=status, company_id=company_id)
    return pid


def _seed_vat_month(conn, company_id):
    cust = _customer(conn, company_id)
    sup = _supplier(conn, company_id)
    _sales(conn, company_id, cust, "2026-03-05", "1000.10", "0.10")
    _sales(conn, company_id, cust, "2026-03-18", "2000.20", "0.20")
    _purchase(conn, company_id, sup, "2026-03-07", "500.10", "0.10")
    _purchase(conn, company_id, sup, "2026-03-21", "700.20", "0.20")
    # Decoys: draft in-month and submitted out-of-month are excluded.
    _sales(conn, company_id, cust, "2026-03-10", "9999.99", "999.99",
           status="draft")
    _sales(conn, company_id, cust, "2026-04-02", "8888.88", "888.88")
    _purchase(conn, company_id, sup, "2026-02-28", "7777.77", "777.77")


def _second_company(conn, country="DE"):
    cid2 = seed_company(conn, country=country)
    seed_fiscal_year(conn, cid2)
    return cid2


class TestEuGenerateVatReturnExact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        r = call_action(ACTIONS["eu-generate-vat-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["output_vat"] == "0.30"
        assert r["input_vat"] == "0.30"
        assert r["net_vat"] == "0.00"
        assert r["total_sales_ex_vat"] == "3000.30"
        assert r["total_purchases_ex_vat"] == "1200.30"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 in every summed column.
        _sales(conn, cid, cust, "2026-03-05", LARGE_A, LARGE_A)
        _sales(conn, cid, cust, "2026-03-18", LARGE_B, LARGE_B)
        _purchase(conn, cid, sup, "2026-03-07", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-03-21", LARGE_B, LARGE_B)
        r = call_action(ACTIONS["eu-generate-vat-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["output_vat"] == LARGE_SUM
        assert r["input_vat"] == LARGE_SUM
        assert r["net_vat"] == "0.00"
        assert r["total_sales_ex_vat"] == LARGE_SUM
        assert r["total_purchases_ex_vat"] == LARGE_SUM

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        _seed_vat_month(conn, _second_company(conn))
        r = call_action(ACTIONS["eu-generate-vat-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["output_vat"] == "0.30"
        assert r["input_vat"] == "0.30"
        assert r["net_vat"] == "0.00"
        assert r["total_sales_ex_vat"] == "3000.30"
        assert r["total_purchases_ex_vat"] == "1200.30"

    def test_empty_period_is_zero(self, conn, env):
        cid = env["company_id"]
        r = call_action(ACTIONS["eu-generate-vat-return"], conn,
                        ns(company_id=cid, period="6", year="2026"))
        assert is_ok(r), r
        assert r["output_vat"] == "0.00"
        assert r["input_vat"] == "0.00"
        assert r["net_vat"] == "0.00"


class TestEuTaxSummaryExact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        r = call_action(ACTIONS["eu-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-03-01", to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["domestic_vat_collected"] == "0.30"
        assert r["domestic_vat_paid"] == "0.30"
        assert r["net_vat"] == "0.00"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33; net 180000000000000.33 - 180000000000000.33
        # = 0.00.
        _sales(conn, cid, cust, "2026-03-05", LARGE_A, LARGE_A)
        _sales(conn, cid, cust, "2026-03-18", LARGE_B, LARGE_B)
        _purchase(conn, cid, sup, "2026-03-07", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-03-21", LARGE_B, LARGE_B)
        r = call_action(ACTIONS["eu-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-03-01", to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["domestic_vat_collected"] == LARGE_SUM
        assert r["domestic_vat_paid"] == LARGE_SUM
        assert r["net_vat"] == "0.00"

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        _seed_vat_month(conn, _second_company(conn))
        r = call_action(ACTIONS["eu-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-03-01", to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["domestic_vat_collected"] == "0.30"
        assert r["domestic_vat_paid"] == "0.30"
        assert r["net_vat"] == "0.00"
