"""m633: UK VAT/payroll aggregates are exact decimals (no binary-float drift).

Seeds invoice and salary-slip amounts with cents binary floating point
cannot represent exactly, runs each money-aggregating action (plus the MTD
helper's caller), and asserts every affected money figure as the exact
hand-computed string.

Small cases pin ordinary cents. Large cases seed 90000000000000.11 and
90000000000000.22 in each summed money column and assert the hand-computed
180000000000000.33 (or the exact derived figure); the pre-change float sum
returns 180000000000000.30 on SQLite, so those cases fail before and pass
after. The digital VAT payload's VAT figures are exact text like every
other figure; only the whole-pound figures are integers. Its large case
seeds two sales rows totalling 90000000000000.49 and 90000000000000.50 and
asserts totalValueSalesExVAT == 180000000000000 (the exact
180000000000000.99 truncated to whole pounds, while the old float sum comes
back as 180000000000001.0) alongside the exact VAT text
180000000000000.33.
Second-company cases seed an identical in-period submitted row in a second
company and assert the first company's figures are unchanged.
"""
import os
import sys
import uuid

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest

from uk_helpers import (call_action, ns, is_ok, load_db_query, seed_company,
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
    _insert(conn, "customer", id=cid, name="UK Buyer %s" % cid[:6],
            company_id=company_id)
    return cid


def _supplier(conn, company_id):
    sid = str(uuid.uuid4())
    _insert(conn, "supplier", id=sid, name="UK Supplier %s" % sid[:6],
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
    # Decoys: draft in-month and submitted out-of-month are excluded.
    _sales(conn, company_id, cust, "2026-03-10", "9999.99", "999.99",
           status="draft")
    _sales(conn, company_id, cust, "2026-04-02", "8888.88", "888.88")


def _employee(conn, company_id, first="M633", last="Exact", ssn="AB123456C"):
    eid = str(uuid.uuid4())
    _insert(conn, "employee", id=eid, first_name=first, last_name=last,
            full_name="%s %s" % (first, last), date_of_joining="2024-01-01",
            company_id=company_id, ssn=ssn)
    return eid


def _run(conn, company_id, start="2026-03-01", end="2026-03-31"):
    rid = str(uuid.uuid4())
    _insert(conn, "payroll_run", id=rid, period_start=start, period_end=end,
            company_id=company_id)
    return rid


def _slip(conn, company_id, run_id, employee_id, start, end, gross, ded, net,
          status="submitted"):
    sid = str(uuid.uuid4())
    _insert(conn, "salary_slip", id=sid, payroll_run_id=run_id,
            employee_id=employee_id, period_start=start, period_end=end,
            gross_pay=gross, total_deductions=ded, net_pay=net,
            status=status, company_id=company_id)
    return sid


def _second_company(conn):
    cid2 = seed_company(conn, country="GB")
    seed_fiscal_year(conn, cid2)
    return cid2


class TestUkVatReturnExact:
    def test_boxes_sum_cents_exactly(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        r = call_action(ACTIONS["uk-generate-vat-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["box1_vat_due_sales"] == "0.30"
        assert r["box3_total_vat_due"] == "0.30"
        assert r["box4_vat_reclaimed"] == "0.10"
        assert r["box5_net_vat"] == "0.20"
        assert r["box6_total_sales_ex_vat"] == "3000.30"
        assert r["box7_total_purchases_ex_vat"] == "500.10"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 in every summed column; box5
        # 180000000000000.33 - 180000000000000.33 = 0.00.
        # The sales-tax pair here is the same pair the payload case
        # seeds, pinned exactly through this return (see payload note).
        _sales(conn, cid, cust, "2026-03-05", LARGE_A, LARGE_A)
        _sales(conn, cid, cust, "2026-03-18", LARGE_B, LARGE_B)
        _purchase(conn, cid, sup, "2026-03-07", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-03-21", LARGE_B, LARGE_B)
        r = call_action(ACTIONS["uk-generate-vat-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["box1_vat_due_sales"] == LARGE_SUM
        assert r["box3_total_vat_due"] == LARGE_SUM
        assert r["box4_vat_reclaimed"] == LARGE_SUM
        assert r["box5_net_vat"] == "0.00"
        assert r["box6_total_sales_ex_vat"] == LARGE_SUM
        assert r["box7_total_purchases_ex_vat"] == LARGE_SUM

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        _seed_vat_month(conn, _second_company(conn))
        r = call_action(ACTIONS["uk-generate-vat-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["box1_vat_due_sales"] == "0.30"
        assert r["box3_total_vat_due"] == "0.30"
        assert r["box4_vat_reclaimed"] == "0.10"
        assert r["box5_net_vat"] == "0.20"
        assert r["box6_total_sales_ex_vat"] == "3000.30"
        assert r["box7_total_purchases_ex_vat"] == "500.10"


class TestUkMtdPayloadExact:
    def test_helper_totals_are_exact(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        r = call_action(ACTIONS["uk-generate-mtd-payload"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        # VAT figures are exact text like every other figure; only the
        # whole-pound truncations stay integers (3000.30 -> 3000,
        # 500.10 -> 500). Hand-computed tax: 0.10 + 0.20 = 0.30 sales,
        # 0.10 reclaimed, 0.30 - 0.10 = 0.20 net.
        assert r["vatDueSales"] == "0.30"
        assert r["totalVatDue"] == "0.30"
        assert r["vatReclaimedCurrPeriod"] == "0.10"
        assert r["netVatDue"] == "0.20"
        assert r["vatDueAcquisitions"] == "0.00"
        assert r["totalValueSalesExVAT"] == 3000
        assert r["totalValuePurchasesExVAT"] == 500

    def test_large_sales_truncate_to_whole_pounds(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed net: 90000000000000.49 + 90000000000000.50
        # = 180000000000000.99, truncated to 180000000000000 whole pounds.
        # The old float sum comes back as 180000000000001.0. The tax pair
        # is pinned here directly as exact text: 90000000000000.11 +
        # 90000000000000.22 = 180000000000000.33 (the old float payload
        # reads 180000000000000.34); net 0.33 - 0.33 = 0.00.
        _sales(conn, cid, cust, "2026-03-05", "90000000000000.49", LARGE_A)
        _sales(conn, cid, cust, "2026-03-18", "90000000000000.50", LARGE_B)
        _purchase(conn, cid, sup, "2026-03-07", "90000000000000.49", LARGE_A)
        _purchase(conn, cid, sup, "2026-03-21", "90000000000000.50", LARGE_B)
        r = call_action(ACTIONS["uk-generate-mtd-payload"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["vatDueSales"] == "180000000000000.33"
        assert r["totalVatDue"] == "180000000000000.33"
        assert r["vatReclaimedCurrPeriod"] == "180000000000000.33"
        assert r["netVatDue"] == "0.00"
        assert r["totalValueSalesExVAT"] == 180000000000000
        assert r["totalValuePurchasesExVAT"] == 180000000000000

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        _seed_vat_month(conn, _second_company(conn))
        r = call_action(ACTIONS["uk-generate-mtd-payload"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["vatDueSales"] == "0.30"
        assert r["vatReclaimedCurrPeriod"] == "0.10"
        assert r["totalValueSalesExVAT"] == 3000
        assert r["totalValuePurchasesExVAT"] == 500

    def test_refund_period_net_vat_is_absolute_text(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        _sales(conn, cid, cust, "2026-03-05", "100.10", "0.10")
        _purchase(conn, cid, sup, "2026-03-07", "200.35", "0.35")
        r = call_action(ACTIONS["uk-generate-mtd-payload"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        # Refund period: 0.10 - 0.35 = -0.25, reported as abs "0.25".
        assert r["vatDueSales"] == "0.10"
        assert r["totalVatDue"] == "0.10"
        assert r["vatReclaimedCurrPeriod"] == "0.35"
        assert r["netVatDue"] == "0.25"
        assert r["vatDueAcquisitions"] == "0.00"
        assert r["totalValueSalesExVAT"] == 100
        assert r["totalValuePurchasesExVAT"] == 200
        for k in ("vatDueSales", "totalVatDue", "vatReclaimedCurrPeriod",
                  "netVatDue", "vatDueAcquisitions"):
            assert type(r[k]) is str


class TestUkGenerateEpsExact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid)
        e1 = _employee(conn, cid, first="M633a", ssn="AB123456C")
        e2 = _employee(conn, cid, first="M633b", ssn="CD654321A")
        _slip(conn, cid, run, e1, "2026-03-01", "2026-03-31",
              "1000.10", "0.10", "1000.00")
        _slip(conn, cid, run, e2, "2026-03-01", "2026-03-31",
              "2000.20", "0.20", "2000.00")
        _slip(conn, cid, run, e1, "2026-03-01", "2026-03-31",
              "9999.99", "999.99", "9000.00", status="draft")
        r = call_action(ACTIONS["uk-generate-eps"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 2
        assert r["total_gross"] == "3000.30"
        assert r["total_deductions"] == "0.30"
        assert r["total_net"] == "3000.00"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid)
        e1 = _employee(conn, cid, first="M633a", ssn="AB123456C")
        e2 = _employee(conn, cid, first="M633b", ssn="CD654321A")
        # Hand-computed per column: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 for gross, deductions and net pay.
        _slip(conn, cid, run, e1, "2026-03-01", "2026-03-31",
              LARGE_A, LARGE_A, LARGE_A)
        _slip(conn, cid, run, e2, "2026-03-01", "2026-03-31",
              LARGE_B, LARGE_B, LARGE_B)
        r = call_action(ACTIONS["uk-generate-eps"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 2
        assert r["total_gross"] == LARGE_SUM
        assert r["total_deductions"] == LARGE_SUM
        assert r["total_net"] == LARGE_SUM

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid)
        e1 = _employee(conn, cid, first="M633a", ssn="AB123456C")
        e2 = _employee(conn, cid, first="M633b", ssn="CD654321A")
        _slip(conn, cid, run, e1, "2026-03-01", "2026-03-31",
              "1000.10", "0.10", "1000.00")
        _slip(conn, cid, run, e2, "2026-03-01", "2026-03-31",
              "2000.20", "0.20", "2000.00")
        cid2 = _second_company(conn)
        run2 = _run(conn, cid2)
        o1 = _employee(conn, cid2, first="Decoy1", ssn="ZZ111111A")
        o2 = _employee(conn, cid2, first="Decoy2", ssn="ZZ222222B")
        _slip(conn, cid2, run2, o1, "2026-03-01", "2026-03-31",
              "1000.10", "0.10", "1000.00")
        _slip(conn, cid2, run2, o2, "2026-03-01", "2026-03-31",
              "2000.20", "0.20", "2000.00")
        r = call_action(ACTIONS["uk-generate-eps"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 2
        assert r["total_gross"] == "3000.30"
        assert r["total_deductions"] == "0.30"
        assert r["total_net"] == "3000.00"


class TestUkGenerateP60Exact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid, start="2025-06-01", end="2025-06-30")
        emp = _employee(conn, cid)
        other = _employee(conn, cid, first="Other", ssn="EF112233B")
        _slip(conn, cid, run, emp, "2025-06-01", "2025-06-30",
              "1000.10", "100.10", "900.00")
        _slip(conn, cid, run, emp, "2025-07-01", "2025-07-31",
              "2000.20", "200.20", "1800.00")
        _slip(conn, cid, run, other, "2025-06-01", "2025-06-30",
              "7777.77", "777.77", "7000.00")
        _slip(conn, cid, run, emp, "2025-06-01", "2025-06-30",
              "9999.99", "999.99", "9000.00", status="draft")
        r = call_action(ACTIONS["uk-generate-p60"], conn,
                        ns(employee_id=emp, tax_year="2025"))
        assert is_ok(r), r
        assert r["total_pay"] == "3000.30"
        assert r["total_tax_deducted"] == "300.30"
        assert r["total_net_pay"] == "2700.00"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid, start="2025-06-01", end="2025-06-30")
        emp = _employee(conn, cid)
        other = _employee(conn, cid, first="Other", ssn="EF112233B")
        # Hand-computed per column: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 for pay, tax and net.
        _slip(conn, cid, run, emp, "2025-06-01", "2025-06-30",
              LARGE_A, LARGE_A, LARGE_A)
        _slip(conn, cid, run, emp, "2025-07-01", "2025-07-31",
              LARGE_B, LARGE_B, LARGE_B)
        _slip(conn, cid, run, other, "2025-06-01", "2025-06-30",
              "7777.77", "777.77", "7000.00")
        r = call_action(ACTIONS["uk-generate-p60"], conn,
                        ns(employee_id=emp, tax_year="2025"))
        assert is_ok(r), r
        assert r["total_pay"] == LARGE_SUM
        assert r["total_tax_deducted"] == LARGE_SUM
        assert r["total_net_pay"] == LARGE_SUM

    def test_second_company_slip_excluded(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid, start="2025-06-01", end="2025-06-30")
        emp = _employee(conn, cid)
        _slip(conn, cid, run, emp, "2025-06-01", "2025-06-30",
              "1000.10", "100.10", "900.00")
        _slip(conn, cid, run, emp, "2025-07-01", "2025-07-31",
              "2000.20", "200.20", "1800.00")
        cid2 = _second_company(conn)
        run2 = _run(conn, cid2, start="2025-06-01", end="2025-06-30")
        _slip(conn, cid2, run2, emp, "2025-06-01", "2025-06-30",
              "1000.10", "100.10", "900.00")
        r = call_action(ACTIONS["uk-generate-p60"], conn,
                        ns(employee_id=emp, tax_year="2025",
                           company_id=cid))
        assert is_ok(r), r
        assert r["total_pay"] == "3000.30"
        assert r["total_tax_deducted"] == "300.30"
        assert r["total_net_pay"] == "2700.00"


class TestUkGenerateP45Exact:
    def test_sums_cents_exactly(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid)
        emp = _employee(conn, cid)
        other = _employee(conn, cid, first="Other", ssn="EF112233B")
        _slip(conn, cid, run, emp, "2026-01-01", "2026-01-31",
              "1000.10", "100.10", "900.00")
        _slip(conn, cid, run, emp, "2026-02-01", "2026-02-28",
              "2000.20", "200.20", "1800.00")
        _slip(conn, cid, run, other, "2026-01-01", "2026-01-31",
              "7777.77", "777.77", "7000.00")
        _slip(conn, cid, run, emp, "2026-01-01", "2026-01-31",
              "9999.99", "999.99", "9000.00", status="draft")
        r = call_action(ACTIONS["uk-generate-p45"], conn,
                        ns(employee_id=emp))
        assert is_ok(r), r
        assert r["total_pay_to_date"] == "3000.30"
        assert r["total_tax_to_date"] == "300.30"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid)
        emp = _employee(conn, cid)
        other = _employee(conn, cid, first="Other", ssn="EF112233B")
        # Hand-computed per column: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 for pay and tax.
        _slip(conn, cid, run, emp, "2026-01-01", "2026-01-31",
              LARGE_A, LARGE_A, LARGE_A)
        _slip(conn, cid, run, emp, "2026-02-01", "2026-02-28",
              LARGE_B, LARGE_B, LARGE_B)
        _slip(conn, cid, run, other, "2026-01-01", "2026-01-31",
              "7777.77", "777.77", "7000.00")
        r = call_action(ACTIONS["uk-generate-p45"], conn,
                        ns(employee_id=emp))
        assert is_ok(r), r
        assert r["total_pay_to_date"] == LARGE_SUM
        assert r["total_tax_to_date"] == LARGE_SUM

    def test_second_company_slip_excluded(self, conn, env):
        cid = env["company_id"]
        run = _run(conn, cid)
        emp = _employee(conn, cid)
        _slip(conn, cid, run, emp, "2026-01-01", "2026-01-31",
              "1000.10", "100.10", "900.00")
        _slip(conn, cid, run, emp, "2026-02-01", "2026-02-28",
              "2000.20", "200.20", "1800.00")
        cid2 = _second_company(conn)
        run2 = _run(conn, cid2)
        _slip(conn, cid2, run2, emp, "2026-01-01", "2026-01-31",
              "1000.10", "100.10", "900.00")
        r = call_action(ACTIONS["uk-generate-p45"], conn,
                        ns(employee_id=emp, company_id=cid))
        assert is_ok(r), r
        assert r["total_pay_to_date"] == "3000.30"
        assert r["total_tax_to_date"] == "300.30"


class TestUkTaxSummaryExact:
    def test_vat_and_payroll_sum_cents_exactly(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        run = _run(conn, cid)
        emp = _employee(conn, cid)
        _slip(conn, cid, run, emp, "2026-03-01", "2026-03-31",
              "1000.10", "0.10", "1000.00")
        _slip(conn, cid, run, emp, "2026-03-01", "2026-03-31",
              "2000.20", "0.20", "2000.00")
        r = call_action(ACTIONS["uk-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-03-01", to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["vat_collected"] == "0.30"
        assert r["vat_reclaimed"] == "0.10"
        assert r["net_vat"] == "0.20"
        assert r["total_gross_pay"] == "3000.30"
        assert r["total_deductions"] == "0.30"
        assert r["total_net_pay"] == "3000.00"

    def test_large_sums_catch_float_sum(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        # Hand-computed: 90000000000000.11 + 90000000000000.22
        # = 180000000000000.33 in every summed column; net VAT
        # 180000000000000.33 - 180000000000000.33 = 0.00.
        _sales(conn, cid, cust, "2026-03-05", LARGE_A, LARGE_A)
        _sales(conn, cid, cust, "2026-03-18", LARGE_B, LARGE_B)
        _purchase(conn, cid, sup, "2026-03-07", LARGE_A, LARGE_A)
        _purchase(conn, cid, sup, "2026-03-21", LARGE_B, LARGE_B)
        run = _run(conn, cid)
        emp = _employee(conn, cid)
        _slip(conn, cid, run, emp, "2026-03-01", "2026-03-31",
              LARGE_A, LARGE_A, LARGE_A)
        _slip(conn, cid, run, emp, "2026-03-01", "2026-03-31",
              LARGE_B, LARGE_B, LARGE_B)
        r = call_action(ACTIONS["uk-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-03-01", to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["vat_collected"] == LARGE_SUM
        assert r["vat_reclaimed"] == LARGE_SUM
        assert r["net_vat"] == "0.00"
        assert r["total_gross_pay"] == LARGE_SUM
        assert r["total_deductions"] == LARGE_SUM
        assert r["total_net_pay"] == LARGE_SUM

    def test_second_company_rows_excluded(self, conn, env):
        cid = env["company_id"]
        _seed_vat_month(conn, cid)
        run = _run(conn, cid)
        emp = _employee(conn, cid)
        _slip(conn, cid, run, emp, "2026-03-01", "2026-03-31",
              "1000.10", "0.10", "1000.00")
        _slip(conn, cid, run, emp, "2026-03-01", "2026-03-31",
              "2000.20", "0.20", "2000.00")
        cid2 = _second_company(conn)
        _seed_vat_month(conn, cid2)
        run2 = _run(conn, cid2)
        emp2 = _employee(conn, cid2, first="Decoy", ssn="ZZ333333C")
        _slip(conn, cid2, run2, emp2, "2026-03-01", "2026-03-31",
              "1000.10", "0.10", "1000.00")
        _slip(conn, cid2, run2, emp2, "2026-03-01", "2026-03-31",
              "2000.20", "0.20", "2000.00")
        r = call_action(ACTIONS["uk-tax-summary"], conn,
                        ns(company_id=cid,
                           from_date="2026-03-01", to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["vat_collected"] == "0.30"
        assert r["vat_reclaimed"] == "0.10"
        assert r["net_vat"] == "0.20"
        assert r["total_gross_pay"] == "3000.30"
        assert r["total_deductions"] == "0.30"
        assert r["total_net_pay"] == "3000.00"
