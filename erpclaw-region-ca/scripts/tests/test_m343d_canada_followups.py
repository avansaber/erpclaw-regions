"""M343d: Canada follow-ups — ROE paid, leavers, exact sales-tax sums, QPIP.

Money is TEXT: exact string comparisons plus Decimal equality, never float.
Reads are PyPika queries through ``erpclaw_lib.query`` on connections from
``erpclaw_lib.db.get_connection``; catalog questions go through
``erpclaw_lib.seam``.
"""
import os
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from ca_helpers import call_action, ns, is_error, is_ok, load_db_query  # noqa: E402

from erpclaw_lib.db import get_connection  # noqa: E402
from erpclaw_lib.query import P, Q, Table, insert_row  # noqa: E402

mod = load_db_query()
ACTIONS = mod.ACTIONS

CENT = Decimal("0.01")
BONUS_NOTE = ("Every slip in the month, including a one-off bonus, "
              "is annualised by 12; "
              "this approximates the CRA bonus method.")


def _rq(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _money(actual, expected):
    assert actual == expected, "%r != %r" % (actual, expected)
    assert Decimal(actual) == Decimal(expected)


def _u():
    return str(uuid.uuid4())


def _insert(conn, table, row):
    sql, _cols = insert_row(table, {key: P() for key in row})
    conn.execute(sql, tuple(row.values()))


def _set_province(conn, company_id, province):
    _insert(conn, "regional_settings", {
        "id": _u(), "company_id": company_id,
        "key": "province", "value": province})
    conn.commit()


def _employee(conn, company_id, full_name, status="active"):
    eid = _u()
    first, last = full_name.split(" ", 1)
    _insert(conn, "employee", {
        "id": eid, "first_name": first, "last_name": last,
        "full_name": full_name, "date_of_joining": "2025-01-06",
        "status": status, "company_id": company_id})
    conn.commit()
    return eid


def _run(conn, company_id, start, end):
    rid = _u()
    _insert(conn, "payroll_run", {
        "id": rid, "period_start": start, "period_end": end,
        "status": "submitted", "company_id": company_id})
    conn.commit()
    return rid


def _slip(conn, company_id, run_id, employee_id, start, gross,
          status="submitted", deductions="0"):
    sid = _u()
    _insert(conn, "salary_slip", {
        "id": sid, "payroll_run_id": run_id, "employee_id": employee_id,
        "period_start": start, "period_end": start, "gross_pay": gross,
        "total_deductions": deductions, "net_pay": gross,
        "status": status, "company_id": company_id})
    conn.commit()
    return sid


def _customer(conn, company_id):
    cid = _u()
    _insert(conn, "customer", {
        "id": cid, "name": "Cust %s" % cid[:6],
        "company_id": company_id})
    conn.commit()
    return cid


def _supplier(conn, company_id):
    sid = _u()
    _insert(conn, "supplier", {
        "id": sid, "name": "Supp %s" % sid[:6],
        "company_id": company_id})
    conn.commit()
    return sid


def _sales_invoice(conn, company_id, customer_id, posting_date, total, tax,
                   status="submitted"):
    iid = _u()
    _insert(conn, "sales_invoice", {
        "id": iid, "customer_id": customer_id,
        "posting_date": posting_date, "total_amount": total,
        "tax_amount": tax,
        "grand_total": str(Decimal(total) + Decimal(tax)),
        "status": status, "company_id": company_id})
    conn.commit()
    return iid


def _purchase_invoice(conn, company_id, supplier_id, posting_date, total, tax,
                      status="submitted"):
    iid = _u()
    _insert(conn, "purchase_invoice", {
        "id": iid, "supplier_id": supplier_id,
        "posting_date": posting_date, "total_amount": total,
        "tax_amount": tax,
        "grand_total": str(Decimal(total) + Decimal(tax)),
        "status": status, "company_id": company_id})
    conn.commit()
    return iid


@pytest.fixture
def conn(db_path):
    connection = get_connection(db_path)
    yield connection
    connection.close()


SNAPSHOT_TABLES = (
    "company", "account", "tax_category", "tax_template",
    "tax_template_line", "regional_settings", "salary_component",
    "employee", "payroll_run", "salary_slip", "customer", "supplier",
    "sales_invoice", "purchase_invoice", "gl_entry",
    "stock_ledger_entry", "audit_log",
)


def _all(conn, table):
    t = Table(table)
    q = Q.from_(t).select(t.star).orderby(t.id)
    return [dict(r) for r in conn.execute(q.get_sql()).fetchall()]


def _snapshot(conn):
    return {name: _all(conn, name) for name in SNAPSHOT_TABLES}


class TestRoeIncludesPaid:
    def test_submitted_and_paid_count_draft_does_not(self, conn, env):
        cid = env["company_id"]
        emp = _employee(conn, cid, "Roe Paid")
        run = _run(conn, cid, "2026-01-01", "2026-12-31")
        _slip(conn, cid, run, emp, "2026-02-01", "5000.00",
              status="submitted")
        _slip(conn, cid, run, emp, "2026-03-01", "3000.00",
              status="paid")
        _slip(conn, cid, run, emp, "2026-04-01", "700.00",
              status="draft")
        r = call_action(ACTIONS["ca-generate-roe"], conn,
                        ns(employee_id=emp))
        assert is_ok(r), r
        # 5000.00 + 3000.00 over two slips; hours 2 x 173.33 = 346.66.
        _money(r["block_15b_total_insurable_earnings"], "8000.00")
        assert r["periods_reported"] == 2
        _money(r["block_15a_total_insurable_hours"], "346.66")
        assert Decimal("5000.00") + Decimal("3000.00") == Decimal("8000.00")


class TestLeaverInSummary:
    def test_left_employee_with_month_slip_is_reported(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Left One", status="left")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-10", "5000.00")
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 1
        line = r["employees"][0]
        assert line["employee_id"] == emp
        assert line["gross"] == "5000.00"
        # Annual 60000: CPP 280.15, EI 81.50, federal 516.06, ON 218.71.
        assert line["deductions"] == {
            "cpp": "280.15", "ei": "81.50",
            "federal_tax": "516.06", "provincial_tax": "218.71"}
        _money(line["deductions"]["cpp"], "280.15")
        _money(line["deductions"]["ei"], "81.50")
        _money(line["deductions"]["federal_tax"], "516.06")
        _money(line["deductions"]["provincial_tax"], "218.71")
        _money(line["total_deductions"], "1096.42")
        _money(line["net_pay"], "3903.58")
        assert (Decimal("280.15") + Decimal("81.50") + Decimal("516.06")
                + Decimal("218.71")) == Decimal("1096.42")
        assert Decimal("5000.00") - Decimal("1096.42") == Decimal("3903.58")
        assert _snapshot(conn) == before, "a report must write nothing"

    def test_pd7a_pins_the_same_month(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Left One", status="left")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-10", "5000.00")
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 1
        _money(r["line_5_income_tax"], "734.77")
        _money(r["total_remittance"], "1490.67")
        assert Decimal("516.06") + Decimal("218.71") == Decimal("734.77")
        assert (Decimal("280.15") + Decimal("280.15") + Decimal("81.50")
                + Decimal("114.10") + Decimal("734.77")) == Decimal("1490.67")
        assert _snapshot(conn) == before, "a report must write nothing"


class TestExactSalesTaxSums:
    def test_compute_itc_large_amounts_exact(self, conn, env):
        cid = env["company_id"]
        sup = _supplier(conn, cid)
        _purchase_invoice(conn, cid, sup, "2026-03-10", "100.00",
                          "90000000000000.11")
        _purchase_invoice(conn, cid, sup, "2026-03-11", "100.00",
                          "90000000000000.22")
        r = call_action(ACTIONS["ca-compute-itc"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        _money(r["total_purchase_tax"], "180000000000000.33")
        assert (Decimal("90000000000000.11")
                + Decimal("90000000000000.22")
                == Decimal("180000000000000.33"))

    def test_gst_hst_return_large_amounts_exact(self, conn, env):
        cid = env["company_id"]
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        _sales_invoice(conn, cid, cust, "2026-03-10",
                       "90000000000000.11", "90000000000000.11")
        _sales_invoice(conn, cid, cust, "2026-03-11",
                       "90000000000000.22", "90000000000000.22")
        _purchase_invoice(conn, cid, sup, "2026-03-12", "10.00", "0.10")
        _purchase_invoice(conn, cid, sup, "2026-03-13", "10.00", "0.20")
        r = call_action(ACTIONS["ca-generate-gst-hst-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        _money(r["revenue"], "180000000000000.33")
        _money(r["tax_collected"], "180000000000000.33")
        _money(r["itc_claimed"], "0.30")
        _money(r["net_tax"], "180000000000000.03")
        assert Decimal("180000000000000.33") - Decimal("0.30") == Decimal(
            "180000000000000.03")

    def test_qst_return_large_amounts_exact(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "QC")
        cust = _customer(conn, cid)
        _sales_invoice(conn, cid, cust, "2026-03-10",
                       "90000000000000.11", "90000000000000.11")
        _sales_invoice(conn, cid, cust, "2026-03-11",
                       "90000000000000.22", "90000000000000.22")
        r = call_action(ACTIONS["ca-generate-qst-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        _money(r["taxable_sales"], "180000000000000.33")


class TestQpipNonQuebec:
    def test_ontario_pd7a_reports_zero_qpip(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "On Tarrio")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-10", "3000.00")
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        _money(r["revenu_quebec_qpip_employee"], "0.00")
        _money(r["revenu_quebec_qpip_employer"], "0.00")
        _money(r["revenu_quebec_total_remittance"], "0.00")


class TestPayPeriodSingular:
    def test_weekly_pay_period_refused_with_singular_message(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026",
                           pay_period="weekly"))
        assert is_error(r)
        assert (r["message"] == "--pay-period must be monthly "
                "for the monthly payroll summary.")
        assert _snapshot(conn) == before, "a refusal must write nothing"


class TestMonthSelectionPins:
    def test_cancelled_slip_excluded_from_both_reports(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Can Cel")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-10", "5000.00",
              status="cancelled")
        summary = call_action(ACTIONS["ca-payroll-summary"], conn,
                              ns(company_id=cid, month="3", year="2026"))
        assert is_ok(summary), summary
        assert summary["employees"][0]["gross"] == "0.00"
        pd7a = call_action(ACTIONS["ca-generate-pd7a"], conn,
                           ns(company_id=cid, month="3", year="2026"))
        assert is_ok(pd7a), pd7a
        assert pd7a["employee_count"] == 0
        _money(pd7a["total_remittance"], "0.00")

    def test_datetime_period_start_selected_for_march(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Tim Stamp")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-05T00:00:00", "1000.00")
        summary = call_action(ACTIONS["ca-payroll-summary"], conn,
                              ns(company_id=cid, month="3", year="2026"))
        assert is_ok(summary), summary
        assert summary["employees"][0]["gross"] == "1000.00"
        pd7a = call_action(ACTIONS["ca-generate-pd7a"], conn,
                           ns(company_id=cid, month="3", year="2026"))
        assert is_ok(pd7a), pd7a
        assert pd7a["employee_count"] == 1


class TestCoaNumberConflict:
    def test_template_number_already_used_is_stored_as_null(self, conn, env):
        from ca_helpers import seed_account
        cid = env["company_id"]
        seed_account(conn, cid, name="Trade Cash", root_type="asset",
                     account_number="1010")
        r = call_action(ACTIONS["ca-seed-ca-coa"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["number_conflicts"] == [
            {"account_name": "Cash", "account_number": "1010"}]
        ac = Table("account")
        q = (Q.from_(ac).select(ac.name, ac.account_number)
             .where(ac.company_id == P()))
        stored = {x["name"]: x["account_number"] for x in
                  conn.execute(q.get_sql(), (cid,)).fetchall()}
        assert stored["Cash"] is None
        assert stored["Trade Cash"] == "1010"


class TestBonusNote:
    def test_summary_and_pd7a_carry_the_bonus_disclosure(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Ben Bonus")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-10", "5000.00")
        summary = call_action(ACTIONS["ca-payroll-summary"], conn,
                              ns(company_id=cid, month="3", year="2026"))
        assert is_ok(summary), summary
        assert summary["bonus_note"] == BONUS_NOTE
        pd7a = call_action(ACTIONS["ca-generate-pd7a"], conn,
                           ns(company_id=cid, month="3", year="2026"))
        assert is_ok(pd7a), pd7a
        assert pd7a["bonus_note"] == BONUS_NOTE
