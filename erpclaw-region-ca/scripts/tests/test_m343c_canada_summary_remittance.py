"""M343c: monthly annualisation, truthful PD7A remittance, abatement, paid, T4, unknown province.

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

from ca_helpers import call_action, ns, is_error, is_ok, load_db_query, seed_company  # noqa: E402

from erpclaw_lib import seam  # noqa: E402
from erpclaw_lib.db import get_connection  # noqa: E402
from erpclaw_lib.query import Field, P, Q, Table, fn, insert_row  # noqa: E402

mod = load_db_query()
ACTIONS = mod.ACTIONS

CENT = Decimal("0.01")


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


SUMMARY_MSG = ("Company province is not configured. Set it with "
               "ca-setup-gst-hst --province <code> before running "
               "ca-payroll-summary.")
PD7A_MSG = ("Company province is not configured. Set it with "
            "ca-setup-gst-hst --province <code> before running "
            "ca-generate-pd7a.")
T4_MSG = ("Company province is not configured. Set it with "
          "ca-setup-gst-hst --province <code> before running "
          "ca-generate-t4.")
PERIODS_MSG = "--pay-periods must be 12 for the monthly payroll summary."


class TestMonthlyAnnualisation:
    def _seed_two_slips(self, conn, cid):
        emp = _employee(conn, cid, "Mona Monthly")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-05", "2500.00")
        _slip(conn, cid, run, emp, "2026-03-20", "2500.00")
        return emp

    def test_pay_periods_24_refused_and_writes_nothing(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        self._seed_two_slips(conn, cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026",
                           pay_periods="24"))
        assert is_error(r)
        assert r["message"] == PERIODS_MSG
        assert _snapshot(conn) == before, "a refusal must write nothing"

    def test_absent_periods_annualises_month_by_12(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = self._seed_two_slips(conn, cid)
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026",
                           pay_periods=None))
        assert is_ok(r), r
        assert r["employee_count"] == 1
        line = r["employees"][0]
        assert line["employee_id"] == emp
        # Month total 2500.00 + 2500.00 = 5000.00, annual 60000:
        # CPP (60000 - 3500) x 5.95% = 3361.75 / 12 = 280.15;
        # EI 60000 x 1.63% = 978.00 / 12 = 81.50;
        # federal slabs 58523 x 14% = 8193.22 and 1477 x 20.5% = 302.79,
        # gross 8496.01 less credit 16452 x 14% = 2303.28, net 6192.73 /
        # 12 = 516.06; Ontario provincial 2721.50 + 558.97 = 3280.47 less
        # 655.94 = 2624.53 / 12 = 218.71.
        assert line["gross"] == "5000.00"
        assert line["deductions"] == {
            "cpp": "280.15", "ei": "81.50",
            "federal_tax": "516.06", "provincial_tax": "218.71"}
        _money(line["deductions"]["cpp"], "280.15")
        _money(line["deductions"]["ei"], "81.50")
        _money(line["deductions"]["federal_tax"], "516.06")
        _money(line["deductions"]["provincial_tax"], "218.71")
        assert _rq((Decimal("60000") - Decimal("3500"))
                   * Decimal("0.0595") / Decimal("12")) == Decimal("280.15")
        assert _rq(Decimal("60000") * Decimal("0.0163")
                   / Decimal("12")) == Decimal("81.50")
        assert _rq(Decimal("58523") * Decimal("0.14")) == Decimal("8193.22")
        assert _rq(Decimal("1477") * Decimal("0.205")) == Decimal("302.79")
        assert Decimal("8193.22") + Decimal("302.79") == Decimal("8496.01")
        assert _rq(Decimal("16452") * Decimal("0.14")) == Decimal("2303.28")
        assert Decimal("8496.01") - Decimal("2303.28") == Decimal("6192.73")
        assert _rq(Decimal("6192.73") / Decimal("12")) == Decimal("516.06")
        assert _rq(Decimal("53891") * Decimal("0.0505")) == Decimal("2721.50")
        assert _rq(Decimal("6109") * Decimal("0.0915")) == Decimal("558.97")
        assert Decimal("2721.50") + Decimal("558.97") == Decimal("3280.47")
        assert _rq(Decimal("12989") * Decimal("0.0505")) == Decimal("655.94")
        assert Decimal("3280.47") - Decimal("655.94") == Decimal("2624.53")
        assert _rq(Decimal("2624.53") / Decimal("12")) == Decimal("218.71")

    def test_pd7a_agrees_with_summary(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        self._seed_two_slips(conn, cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        # Same month: CPP 280.15, EI 81.50 and federal 516.06 as the
        # summary; line 5 adds provincial: 516.06 + 218.71 = 734.77.
        _money(r["line_1_cpp_employee"], "280.15")
        _money(r["line_2_cpp_employer"], "280.15")
        _money(r["line_3_ei_employee"], "81.50")
        _money(r["line_4_ei_employer"], "114.10")
        _money(r["line_5_income_tax"], "734.77")
        _money(r["total_remittance"], "1490.67")
        assert Decimal("516.06") + Decimal("218.71") == Decimal("734.77")
        assert Decimal("1271.96") + Decimal("218.71") == Decimal("1490.67")
        assert _rq(Decimal("81.50") * Decimal("1.4")) == Decimal("114.10")
        assert _snapshot(conn) == before, "a report must write nothing"


class TestQuebecAbatement:
    def test_federal_tax_qc_applies_abatement(self, conn, env):
        # Annual 48000: gross 6720.00 less 2303.28 = 4416.72, abatement
        # 4416.72 x 16.5% = 728.76, net (4416.72 - 728.76) = 3687.96.
        r = call_action(ACTIONS["ca-compute-federal-tax"], conn,
                        ns(annual_income="48000", province="QC"))
        assert is_ok(r), r
        _money(r["net_tax"], "3687.96")
        _money(r["quebec_abatement"], "728.76")
        assert _rq(Decimal("48000") * Decimal("0.14")) == Decimal("6720.00")
        assert _rq(Decimal("16452") * Decimal("0.14")) == Decimal("2303.28")
        assert Decimal("6720.00") - Decimal("2303.28") == Decimal("4416.72")
        assert _rq(Decimal("4416.72") * Decimal("0.165")) == Decimal("728.76")
        assert Decimal("4416.72") - Decimal("728.76") == Decimal("3687.96")

    def test_total_deductions_qc_monthly(self, conn, env):
        # Monthly slice: 3687.96 / 12 = 307.33.
        r = call_action(ACTIONS["ca-compute-total-payroll-deductions"], conn,
                        ns(gross_salary="4000", province="QC"))
        assert is_ok(r), r
        _money(r["federal_tax"], "307.33")
        assert _rq(Decimal("3687.96") / Decimal("12")) == Decimal("307.33")


class TestPaidEverywhere:
    def test_paid_slip_in_t4_and_tax_summary(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Pam Paid")
        run = _run(conn, cid, "2026-01-01", "2026-12-31")
        _slip(conn, cid, run, emp, "2026-06-01", "5000.00",
              status="paid", deductions="1200.50")
        before = _snapshot(conn)
        t4 = call_action(ACTIONS["ca-generate-t4"], conn,
                         ns(employee_id=emp, tax_year="2026"))
        assert is_ok(t4), t4
        _money(t4["box_14_employment_income"], "5000.00")
        assert t4["salary_slips_count"] == 1
        s = call_action(ACTIONS["ca-tax-summary"], conn,
                        ns(company_id=cid, from_date="2026-01-01",
                           to_date="2026-12-31"))
        assert is_ok(s), s
        assert s["total_gross_payroll"] == "5000.00"
        assert s["total_payroll_deductions"] == "1200.50"
        assert s["salary_slip_count"] == 1
        assert _snapshot(conn) == before, "reports must write nothing"


class TestT4Exact:
    def test_box_14_large_amounts_exact(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Big Bucks")
        run = _run(conn, cid, "2026-01-01", "2026-12-31")
        _slip(conn, cid, run, emp, "2026-02-01", "90000000000000.11")
        _slip(conn, cid, run, emp, "2026-07-01", "90000000000000.22")
        r = call_action(ACTIONS["ca-generate-t4"], conn,
                        ns(employee_id=emp, tax_year="2026"))
        assert is_ok(r), r
        # Exact decimal sum, not the float sum.
        _money(r["box_14_employment_income"], "180000000000000.33")
        assert (Decimal("90000000000000.11")
                + Decimal("90000000000000.22")
                == Decimal("180000000000000.33"))
        assert r["salary_slips_count"] == 2

    def test_quebec_t4_reports_qpp(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "QC")
        emp = _employee(conn, cid, "Queenie Qpp")
        run = _run(conn, cid, "2026-01-01", "2026-12-31")
        _slip(conn, cid, run, emp, "2026-03-01", "5000.00")
        r = call_action(ACTIONS["ca-generate-t4"], conn,
                        ns(employee_id=emp, tax_year="2026"))
        assert is_ok(r), r
        assert r["province_of_employment"] == "QC"
        # Annual 5000: QPP (5000 - 3500) x 6.30% = 94.50.
        _money(r["box_16_qpp_contributions"], "94.50")
        assert "box_16_cpp_contributions" not in r
        assert "box_26_cpp_pensionable_earnings" not in r
        _money(r["box_26_qpp_pensionable_earnings"], "5000.00")
        assert _rq((Decimal("5000") - Decimal("3500"))
                   * Decimal("0.063")) == Decimal("94.50")


class TestUnknownProvince:
    def test_summary_refuses_without_province(self, conn, env):
        cid = env["company_id"]
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_error(r)
        assert r["message"] == SUMMARY_MSG
        assert _snapshot(conn) == before

    def test_pd7a_refuses_without_province(self, conn, env):
        cid = env["company_id"]
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_error(r)
        assert r["message"] == PD7A_MSG
        assert _snapshot(conn) == before

    def test_t4_refuses_without_province(self, conn, env):
        cid = env["company_id"]
        emp = _employee(conn, cid, "No Prov")
        run = _run(conn, cid, "2026-01-01", "2026-12-31")
        _slip(conn, cid, run, emp, "2026-03-01", "1000.00")
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-generate-t4"], conn,
                        ns(employee_id=emp, tax_year="2026"))
        assert is_error(r)
        assert r["message"] == T4_MSG
        assert _snapshot(conn) == before


class TestTaxSummaryDiscriminate:
    def test_large_amounts_exact(self, conn, env):
        cid = env["company_id"]
        emp = _employee(conn, cid, "Sam Big")
        run = _run(conn, cid, "2026-01-01", "2026-12-31")
        _slip(conn, cid, run, emp, "2026-03-01", "90000000000000.11",
              deductions="100.11")
        _slip(conn, cid, run, emp, "2026-06-01", "90000000000000.22",
              deductions="200.22")
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-tax-summary"], conn,
                        ns(company_id=cid, from_date="2026-01-01",
                           to_date="2026-12-31"))
        assert is_ok(r), r
        assert r["total_gross_payroll"] == "180000000000000.33"
        assert r["total_payroll_deductions"] == "300.33"
        assert r["salary_slip_count"] == 2
        assert (Decimal("90000000000000.11")
                + Decimal("90000000000000.22")
                == Decimal("180000000000000.33"))
        assert (Decimal("100.11") + Decimal("200.22")
                == Decimal("300.33"))
        assert _snapshot(conn) == before, "a report must write nothing"
