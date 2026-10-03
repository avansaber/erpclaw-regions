"""m633: India GST aggregates are exact decimals (no binary-float drift).

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

from in_helpers import (call_action, ns, is_ok, load_db_query, seed_company,
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
    _insert(conn, "customer", id=cid, name="IN Buyer %s" % cid[:6],
            company_id=company_id)
    return cid


def _supplier(conn, company_id):
    sid = str(uuid.uuid4())
    _insert(conn, "supplier", id=sid, name="IN Supplier %s" % sid[:6],
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


def _seed_gstr_month(conn, company_id):
    cust = _customer(conn, company_id)
    sup = _supplier(conn, company_id)
    _sales(conn, company_id, cust, "2026-05-05", "1000.10", "0.10")
    _sales(conn, company_id, cust, "2026-05-18", "2000.20", "0.20")
    _purchase(conn, company_id, sup, "2026-05-07", "500.10", "0.10")
    _purchase(conn, company_id, sup, "2026-05-21", "700.20", "0.20")
    # Decoys: draft in-month and submitted out-of-month are excluded.
    _sales(conn, company_id, cust, "2026-05-10", "9999.99", "999.99",
           status="draft")
    _purchase(conn, company_id, sup, "2026-06-02", "8888.88", "888.88")


def _second_company(conn):
    cid2 = seed_company(conn, country="IN")
    seed_fiscal_year(conn, cid2)
    return cid2


class TestGenerateGstr3bExact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        _seed_gstr_month(conn, cid)
        r = call_action(ACTIONS["india-generate-gstr3b"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["section_3_1"]["taxable_value"] == "3000.30"
        assert r["section_3_1"]["tax_amount"] == "0.30"
        assert r["section_4"]["itc_available"] == "0.30"
        assert r["section_4"]["from_purchases"] == "0.30"
        assert r["section_6"]["tax_payable"] == "0.30"
        assert r["section_6"]["itc_claimed"] == "0.30"
        assert r["section_6"]["net_payable"] == "0.00"
        assert r["section_6"]["net_refundable"] == "0.00"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 in every summed column; net payable
        # 180000000000000.33 - 180000000000000.33 = 0.00.
        _sales(conn, cid, cust, "2026-05-05", LARGE_A, LARGE_A)
        _sales(conn, cid, cust, "2026-05-18", LARGE_B, LARGE_B)
        _purchase(conn, cid, sup, "2026-05-07", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-05-21", LARGE_B, LARGE_B)
        r = call_action(ACTIONS["india-generate-gstr3b"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["section_3_1"]["taxable_value"] == LARGE_SUM
        assert r["section_3_1"]["tax_amount"] == LARGE_SUM
        assert r["section_4"]["itc_available"] == LARGE_SUM
        assert r["section_4"]["from_purchases"] == LARGE_SUM
        assert r["section_6"]["tax_payable"] == LARGE_SUM
        assert r["section_6"]["itc_claimed"] == LARGE_SUM
        assert r["section_6"]["net_payable"] == "0.00"
        assert r["section_6"]["net_refundable"] == "0.00"

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_gstr_month(conn, cid)
        _seed_gstr_month(conn, _second_company(conn))
        r = call_action(ACTIONS["india-generate-gstr3b"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["section_3_1"]["taxable_value"] == "3000.30"
        assert r["section_3_1"]["tax_amount"] == "0.30"
        assert r["section_4"]["itc_available"] == "0.30"
        assert r["section_4"]["from_purchases"] == "0.30"
        assert r["section_6"]["tax_payable"] == "0.30"
        assert r["section_6"]["itc_claimed"] == "0.30"
        assert r["section_6"]["net_payable"] == "0.00"
        assert r["section_6"]["net_refundable"] == "0.00"


class TestComputeItcExact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        _seed_gstr_month(conn, cid)
        r = call_action(ACTIONS["india-compute-itc"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["total_purchase_tax_paid"] == "0.30"
        assert r["eligible_itc"] == "0.30"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 of purchase tax.
        _sales(conn, cid, cust, "2026-05-05", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-05-07", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-05-21", LARGE_B, LARGE_B)
        r = call_action(ACTIONS["india-compute-itc"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["total_purchase_tax_paid"] == LARGE_SUM
        assert r["eligible_itc"] == LARGE_SUM

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_gstr_month(conn, cid)
        _seed_gstr_month(conn, _second_company(conn))
        r = call_action(ACTIONS["india-compute-itc"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["total_purchase_tax_paid"] == "0.30"
        assert r["eligible_itc"] == "0.30"


class TestIndiaTaxSummaryExact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        _seed_gstr_month(conn, cid)
        r = call_action(ACTIONS["india-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-05-01", to_date="2026-05-31"))
        assert is_ok(r), r
        assert r["gst_collected_on_sales"] == "0.30"
        assert r["gst_paid_on_purchases"] == "0.30"
        assert r["net_gst_payable"] == "0.00"
        assert r["net_gst_refundable"] == "0.00"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 each side; net 0.00.
        _sales(conn, cid, cust, "2026-05-05", LARGE_A, LARGE_A)
        _sales(conn, cid, cust, "2026-05-18", LARGE_B, LARGE_B)
        _purchase(conn, cid, sup, "2026-05-07", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-05-21", LARGE_B, LARGE_B)
        r = call_action(ACTIONS["india-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-05-01", to_date="2026-05-31"))
        assert is_ok(r), r
        assert r["gst_collected_on_sales"] == LARGE_SUM
        assert r["gst_paid_on_purchases"] == LARGE_SUM
        assert r["net_gst_payable"] == "0.00"
        assert r["net_gst_refundable"] == "0.00"

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_gstr_month(conn, cid)
        _seed_gstr_month(conn, _second_company(conn))
        r = call_action(ACTIONS["india-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-05-01", to_date="2026-05-31"))
        assert is_ok(r), r
        assert r["gst_collected_on_sales"] == "0.30"
        assert r["gst_paid_on_purchases"] == "0.30"
        assert r["net_gst_payable"] == "0.00"
        assert r["net_gst_refundable"] == "0.00"
