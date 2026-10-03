"""M343b: Canada payroll remittance, credit rate, aggregation and COA seed.

Covers the six defects fixed in this change: PD7A reporting (company-rate
province, shared month rule), exact-decimal payroll sums in ca-tax-summary,
the COA seed NULL-number fix, the 14% federal credit rate on all five rate
paths, the shared month-slip helper with multi-slip aggregation in both
monthly reports, and integer validation of --year.

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


@pytest.fixture
def conn(db_path):
    connection = get_connection(db_path)
    yield connection
    connection.close()


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


# ── Federal credit rate: one test per rate path ──────────────────────────────

CENT = Decimal("0.01")


def _rq(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


class TestFederalCreditRate:
    """The credit is the BPA at the lowest bracket rate: 16452 x 14%."""

    def test_compute_federal_tax_credit(self, conn, env):
        # 60000: slabs 58523 x 14% = 8193.22 and 1477 x 20.5% = 302.79,
        # gross 8496.01 less the 2303.28 credit = 6192.73 net.
        r = call_action(ACTIONS["ca-compute-federal-tax"], conn,
                        ns(annual_income="60000"))
        assert is_ok(r), r
        assert r["basic_personal_amount"] == "16452"
        _money(r["gross_tax"], "8496.01")
        _money(r["personal_credit"], "2303.28")
        _money(r["net_tax"], "6192.73")
        assert _rq(Decimal("58523") * Decimal("0.14")) == Decimal("8193.22")
        assert _rq(Decimal("1477") * Decimal("0.205")) == Decimal("302.79")
        assert _rq(Decimal("16452") * Decimal("0.14")) == Decimal("2303.28")
        assert Decimal("8496.01") - Decimal("2303.28") == Decimal("6192.73")

    def test_total_deductions_federal_tax(self, conn, env):
        # Monthly slice of the same 60000 annual figure: 6192.73 / 12.
        r = call_action(ACTIONS["ca-compute-total-payroll-deductions"], conn,
                        ns(gross_salary="5000", province="ON"))
        assert is_ok(r), r
        _money(r["federal_tax"], "516.06")
        assert _rq(Decimal("6192.73") / Decimal("12")) == Decimal("516.06")

    def test_payroll_summary_federal_tax(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Amy Adams")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-15", "5000.00")
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        _money(r["employees"][0]["deductions"]["federal_tax"], "516.06")
        assert _rq(Decimal("6192.73") / Decimal("12")) == Decimal("516.06")

    def test_pd7a_income_tax(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Amy Adams")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-15", "5000.00")
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        # Line 5 is federal plus provincial: 516.06 + 218.71 = 734.77.
        _money(r["line_5_income_tax"], "734.77")
        assert _rq(Decimal("6192.73") / Decimal("12")) == Decimal("516.06")
        assert Decimal("516.06") + Decimal("218.71") == Decimal("734.77")

    def test_t4_box_22(self, conn, env):
        # One 60000.00 slip for the year: slab gross 8496.01 less the
        # 2303.28 credit = 6192.73 deducted.
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Amy Adams")
        run = _run(conn, cid, "2026-02-01", "2026-02-28")
        _slip(conn, cid, run, emp, "2026-02-15", "60000.00")
        r = call_action(ACTIONS["ca-generate-t4"], conn,
                        ns(employee_id=emp, tax_year="2026"))
        assert is_ok(r), r
        _money(r["box_14_employment_income"], "60000.00")
        _money(r["box_22_income_tax_deducted"], "6192.73")
        assert Decimal("8496.01") - Decimal("2303.28") == Decimal("6192.73")


# ── PD7A ─────────────────────────────────────────────────────────────────────

class TestGeneratePd7a:
    def test_pd7a_two_employees_reports_exact_lines(self, conn, env):
        # Neither employee nor company carries a province column, so both
        # slips price at the company (ON) rate. Full ISO dates in
        # period_start; the April slip and the March draft must not count.
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        alice = _employee(conn, cid, "Alice Alpha")
        bob = _employee(conn, cid, "Bob Beta")
        march = _run(conn, cid, "2026-03-01", "2026-03-31")
        april = _run(conn, cid, "2026-04-01", "2026-04-30")
        _slip(conn, cid, march, alice, "2026-03-05", "5000.00")
        _slip(conn, cid, march, bob, "2026-03-12", "4000.00")
        _slip(conn, cid, march, bob, "2026-03-12", "9999.99", status="draft")
        _slip(conn, cid, april, alice, "2026-04-02", "5000.00")
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["period"] == "2026-03"
        assert r["employee_count"] == 2
        # Alice, annual 60000: CPP (60000-3500) x 5.95% = 3361.75 / 12;
        # EI 60000 x 1.63% = 978.00 / 12; federal 6192.73 / 12 = 516.06 and
        # Ontario provincial 2624.53 / 12 = 218.71. Bob, annual 48000:
        # CPP 220.65, EI 65.20, federal 368.06 and Ontario provincial
        # 1768.06 / 12 = 147.34. Line 5 is federal plus provincial.
        _money(r["line_1_cpp_employee"], "500.80")
        _money(r["line_2_cpp_employer"], "500.80")
        _money(r["line_3_ei_employee"], "146.70")
        _money(r["line_4_ei_employer"], "205.38")
        _money(r["line_5_income_tax"], "1250.17")
        _money(r["total_remittance"], "2603.85")
        _money(r["revenu_quebec_qpp_employee"], "0.00")
        _money(r["revenu_quebec_qpp_employer"], "0.00")
        _money(r["revenu_quebec_provincial_tax"], "0.00")
        _money(r["revenu_quebec_total_remittance"], "0.00")
        assert _rq((Decimal("60000") - Decimal("3500"))
                   * Decimal("0.0595") / Decimal("12")) == Decimal("280.15")
        assert _rq((Decimal("48000") - Decimal("3500"))
                   * Decimal("0.0595") / Decimal("12")) == Decimal("220.65")
        assert Decimal("280.15") + Decimal("220.65") == Decimal("500.80")
        assert _rq(Decimal("60000") * Decimal("0.0163")
                   / Decimal("12")) == Decimal("81.50")
        assert _rq(Decimal("48000") * Decimal("0.0163")
                   / Decimal("12")) == Decimal("65.20")
        assert _rq(Decimal("81.50") * Decimal("1.4")) == Decimal("114.10")
        assert _rq(Decimal("65.20") * Decimal("1.4")) == Decimal("91.28")
        assert Decimal("516.06") + Decimal("368.06") == Decimal("884.12")
        assert Decimal("218.71") + Decimal("147.34") == Decimal("366.05")
        assert Decimal("884.12") + Decimal("366.05") == Decimal("1250.17")
        assert (Decimal("500.80") + Decimal("500.80") + Decimal("146.70")
                + Decimal("205.38") + Decimal("1250.17")) == Decimal("2603.85")

        assert _snapshot(conn) == before, "a report must write nothing"

    def test_pd7a_quebec_company_uses_qpp_rates(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "QC")
        emp = _employee(conn, cid, "Queenie Quebec")
        run = _run(conn, cid, "2026-03-01", "2026-03-31")
        _slip(conn, cid, run, emp, "2026-03-10", "3000.00")
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 1
        # Annual 36000: QPP (36000-3500) x 6.30% = 2047.50 / 12 = 170.63,
        # moved to Revenu Quebec; Quebec EI 36000 x 1.30% = 468.00 / 12 =
        # 39.00, employer 39.00 x 1.4 = 54.60; federal 36000 x 14% = 5040.00
        # less 2303.28 = 2736.72, abatement 2736.72 x 16.5% = 451.56,
        # (2736.72 - 451.56) / 12 = 2285.16 / 12 = 190.43; Quebec provincial
        # 36000 x 14% = 5040.00 less 18952 x 14% = 2653.28, net 2386.72 /
        # 12 = 198.89, moved to Revenu Quebec. CRA carries federal and EI
        # only: 190.43 + 39.00 + 54.60 = 284.03. QPIP: 36000 x 0.494% =
        # 177.84 / 12 = 14.82 and 36000 x 0.692% = 249.12 / 12 = 20.76;
        # Revenu Quebec total 540.15 + 14.82 + 20.76 = 575.73.
        _money(r["line_1_cpp_employee"], "0.00")
        _money(r["line_2_cpp_employer"], "0.00")
        _money(r["line_3_ei_employee"], "39.00")
        _money(r["line_4_ei_employer"], "54.60")
        _money(r["line_5_income_tax"], "190.43")
        _money(r["total_remittance"], "284.03")
        _money(r["revenu_quebec_qpp_employee"], "170.63")
        _money(r["revenu_quebec_qpp_employer"], "170.63")
        _money(r["revenu_quebec_qpip_employee"], "14.82")
        _money(r["revenu_quebec_qpip_employer"], "20.76")
        _money(r["revenu_quebec_provincial_tax"], "198.89")
        _money(r["revenu_quebec_total_remittance"], "575.73")
        assert _rq((Decimal("36000") - Decimal("3500"))
                   * Decimal("0.063") / Decimal("12")) == Decimal("170.63")
        assert _rq(Decimal("36000") * Decimal("0.013")
                   / Decimal("12")) == Decimal("39.00")
        assert _rq(Decimal("39.00") * Decimal("1.4")) == Decimal("54.60")
        assert _rq(Decimal("2736.72") * Decimal("0.165")) == Decimal("451.56")
        assert Decimal("2736.72") - Decimal("451.56") == Decimal("2285.16")
        assert _rq(Decimal("2285.16") / Decimal("12")) == Decimal("190.43")
        assert _rq(Decimal("36000") * Decimal("0.14")) == Decimal("5040.00")
        assert _rq(Decimal("18952") * Decimal("0.14")) == Decimal("2653.28")
        assert Decimal("5040.00") - Decimal("2653.28") == Decimal("2386.72")
        assert _rq(Decimal("2386.72") / Decimal("12")) == Decimal("198.89")
        assert Decimal("170.63") + Decimal("170.63") == Decimal("341.26")
        assert Decimal("341.26") + Decimal("198.89") == Decimal("540.15")
        assert _rq(Decimal("36000") * Decimal("0.00494")) == Decimal("177.84")
        assert _rq(Decimal("177.84") / Decimal("12")) == Decimal("14.82")
        assert _rq(Decimal("36000") * Decimal("0.00692")) == Decimal("249.12")
        assert _rq(Decimal("249.12") / Decimal("12")) == Decimal("20.76")
        assert (Decimal("540.15") + Decimal("14.82")
                + Decimal("20.76")) == Decimal("575.73")
        assert (Decimal("190.43") + Decimal("39.00")
                + Decimal("54.60")) == Decimal("284.03")

        assert _snapshot(conn) == before, "a report must write nothing"

    def test_pd7a_paid_slip_counts(self, conn, env):
        # Paid means the wages went out and the deductions were withheld,
        # so a paid slip belongs in the remittance; drafts never do.
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Pam Paid")
        run = _run(conn, cid, "2026-05-01", "2026-05-31")
        _slip(conn, cid, run, emp, "2026-05-15", "5000.00", status="paid")
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 1
        _money(r["line_1_cpp_employee"], "280.15")
        _money(r["line_5_income_tax"], "734.77")
        assert Decimal("516.06") + Decimal("218.71") == Decimal("734.77")

    def test_pd7a_wildcard_year_refused(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026%"))
        assert is_error(r)
        assert r["message"] == ("Invalid year: 2026%. "
                                "Use a four-digit integer year.")
        assert _snapshot(conn) == before


# ── Two slips in one month ───────────────────────────────────────────────────

class TestTwoSlipsOneMonth:
    def _seed(self, conn, cid):
        emp = _employee(conn, cid, "Ben Bonus")
        march = _run(conn, cid, "2026-03-01", "2026-03-31")
        april = _run(conn, cid, "2026-04-01", "2026-04-30")
        _slip(conn, cid, march, emp, "2026-03-05", "5000.00")
        _slip(conn, cid, march, emp, "2026-03-20", "1000.00")
        _slip(conn, cid, march, emp, "2026-03-21", "9999.99", status="draft")
        _slip(conn, cid, april, emp, "2026-04-02", "5000.00")
        return emp

    def test_payroll_summary_aggregates_both_slips(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = self._seed(conn, cid)
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 1
        line = r["employees"][0]
        assert line["employee_id"] == emp
        # Monthly gross 6000.00 = 5000.00 + 1000.00, annual 72000:
        # CPP (72000-3500) x 5.95% = 4075.75 / 12; EI 72000 x 1.63% capped
        # at 1123.07 / 12; federal 10956.01 - 2303.28 = 8652.73 / 12;
        # Ontario 4378.47 - 655.94 = 3722.53 / 12.
        assert line["gross"] == "6000.00"
        assert line["deductions"] == {
            "cpp": "339.65", "ei": "93.59",
            "federal_tax": "721.06", "provincial_tax": "310.21"}
        assert (line["total_deductions"], line["net_pay"]) == (
            "1464.51", "4535.49")
        assert r["totals"]["total_gross"] == "6000.00"
        assert r["totals"]["total_federal_tax"] == "721.06"
        assert r["totals"]["total_employer_ei"] == "131.03"
        assert _rq((Decimal("72000") - Decimal("3500"))
                   * Decimal("0.0595") / Decimal("12")) == Decimal("339.65")
        assert _rq(Decimal("1123.07") / Decimal("12")) == Decimal("93.59")
        assert _rq(Decimal("8652.73") / Decimal("12")) == Decimal("721.06")
        assert _rq(Decimal("3722.53") / Decimal("12")) == Decimal("310.21")
        assert _rq(Decimal("93.59") * Decimal("1.4")) == Decimal("131.03")

    def test_pd7a_aggregates_both_slips(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        self._seed(conn, cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["employee_count"] == 1
        _money(r["line_1_cpp_employee"], "339.65")
        _money(r["line_2_cpp_employer"], "339.65")
        _money(r["line_3_ei_employee"], "93.59")
        _money(r["line_4_ei_employer"], "131.03")
        _money(r["line_5_income_tax"], "1031.27")
        _money(r["total_remittance"], "1935.19")
        _money(r["revenu_quebec_qpp_employee"], "0.00")
        _money(r["revenu_quebec_qpp_employer"], "0.00")
        _money(r["revenu_quebec_provincial_tax"], "0.00")
        _money(r["revenu_quebec_total_remittance"], "0.00")
        assert Decimal("721.06") + Decimal("310.21") == Decimal("1031.27")
        assert Decimal("1624.98") + Decimal("310.21") == Decimal("1935.19")
        assert _snapshot(conn) == before, "a report must write nothing"

    def test_payroll_summary_paid_slip_counts(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        emp = _employee(conn, cid, "Pam Paid")
        run = _run(conn, cid, "2026-05-01", "2026-05-31")
        _slip(conn, cid, run, emp, "2026-05-15", "5000.00", status="paid")
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="5", year="2026"))
        assert is_ok(r), r
        assert r["employees"][0]["gross"] == "5000.00"

    def test_payroll_summary_wildcard_year_refused(self, conn, env):
        cid = env["company_id"]
        _set_province(conn, cid, "ON")
        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="3", year="2026_"))
        assert is_error(r)
        assert r["message"] == ("Invalid year: 2026_. "
                                "Use a four-digit integer year.")


# ── Tax summary payroll totals ───────────────────────────────────────────────

class TestTaxSummaryPayroll:
    def test_slips_inside_and_outside_range(self, conn, env):
        cid = env["company_id"]
        emp = _employee(conn, cid, "Sam Slip")
        run = _run(conn, cid, "2026-01-01", "2026-12-31")
        _slip(conn, cid, run, emp, "2026-03-01", "5000.00",
              deductions="1200.50")
        _slip(conn, cid, run, emp, "2026-06-01", "3000.00",
              deductions="800.25")
        _slip(conn, cid, run, emp, "2026-04-01", "9999.99",
              status="draft", deductions="999.99")
        _slip(conn, cid, run, emp, "2025-12-01", "4444.44",
              deductions="444.44")
        before = _snapshot(conn)
        r = call_action(ACTIONS["ca-tax-summary"], conn,
                        ns(company_id=cid, from_date="2026-01-01",
                           to_date="2026-12-31"))
        assert is_ok(r), r
        # Only the two submitted 2026 slips: 5000.00 + 3000.00 and
        # 1200.50 + 800.25, summed as exact decimals.
        assert r["total_gross_payroll"] == "8000.00"
        assert r["total_payroll_deductions"] == "2000.75"
        assert r["salary_slip_count"] == 2
        assert (Decimal("5000.00") + Decimal("3000.00")
                == Decimal("8000.00"))
        assert (Decimal("1200.50") + Decimal("800.25")
                == Decimal("2000.75"))
        assert _snapshot(conn) == before, "a report must write nothing"


# ── COA seed ─────────────────────────────────────────────────────────────────

class TestSeedCaCoa:
    def test_fresh_company_seeds_and_second_run_is_noop(self, conn, db_path,
                                                        env):
        cid = env["company_id"]
        assert seam.table_exists("account", db_path)

        r = call_action(ACTIONS["ca-seed-ca-coa"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["company_id"] == cid
        assert r["accounts_created"] == 154
        assert r["total_in_template"] == 154

        ac = Table("account")
        q = (Q.from_(ac).select(ac.name, ac.account_number)
             .where(ac.company_id == P()))
        stored = {x["name"]: x["account_number"] for x in
                  conn.execute(q.get_sql(), (cid,)).fetchall()}
        assert len(stored) == 154
        assert stored["Cash"] == "1010"
        assert stored["Accounts Receivable"] == "1200"
        assert stored["GST/HST Payable"] == "2200"
        assert stored["Retained Earnings"] == "3200"
        assert stored["Bank Charges and Fees"] == "5900"
        # Header/group rows carry no number (NULL), not an empty string.
        assert stored["Assets"] is None
        assert stored["Current Assets"] is None
        assert stored["Other Expenses"] is None
        q = (Q.from_(ac).select(fn.Count("*").as_("n"))
             .where(ac.company_id == P()))
        assert conn.execute(q.get_sql(), (cid,)).fetchone()["n"] == 154

        r2 = call_action(ACTIONS["ca-seed-ca-coa"], conn,
                         ns(company_id=cid))
        assert is_ok(r2), r2
        assert r2["accounts_created"] == 0
        assert conn.execute(q.get_sql(), (cid,)).fetchone()["n"] == 154
