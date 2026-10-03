"""M471 depth: behavioural evidence for 12 erpclaw-region-ca actions.

Each action below already had a test that proved the wrong thing (response
shape or routability). Each test here proves the database effect instead:
what row exists afterwards with which exact values, what changed from what
to what, and what did not change. Money is TEXT: exact string comparisons
plus Decimal equality, never float, never approximate, never round().

Reads are PyPika-built queries through ``erpclaw_lib.query`` on a connection
from ``erpclaw_lib.db.get_connection``; catalog questions go through
``erpclaw_lib.seam``.

Per-action depth signal (stored row vs ledger effect):

- ca-compute-cpp2 ............ COMPUTED VALUE (read-only; exact CPP2 math
                                pinned, snapshot proves no write)
- ca-generate-gst-hst-return . READ (sales_invoice + purchase_invoice rows
                                ground every reported total)
- ca-generate-pd7a ............ READ (fixed m343b: prices every slip at the
                                company province from regional_settings and
                                selects the month through the shared helper;
                                snapshot proves no write)
- ca-generate-qst-return ..... READ (invoice rows ground the QST split)
- ca-generate-roe ............ READ (employee + salary_slip rows ground it)
- ca-generate-t4 ............. READ (salary_slip sum grounds every box)
- ca-generate-t4a ............ COMPUTED VALUE (read-only; withholding math
                                pinned, snapshot proves no write)
- ca-payroll-summary ......... READ (salary_slip row grounds every figure)
- ca-seed-ca-coa ............. STORED ROWS (fixed m343d: empty template
                                numbers and numbers the company already uses
                                are stored as NULL — conflicts listed under
                                number_conflicts — so the UNIQUE rule holds;
                                second run is a no-op)
- ca-seed-ca-defaults ........ STORED ROWS (account, tax_category,
                                tax_template, tax_template_line, audit_log)
- ca-seed-ca-payroll ......... STORED ROWS (salary_component, audit_log)
- ca-setup-gst-hst ........... STORED ROWS (regional_settings, audit_log)

Ledger note: none of these twelve actions reaches the ledger on its success
path (the four writers touch tax/payroll/settings tables plus audit_log;
the reporters and calculators write nothing at all), so no success test
below asserts a new ledger leg. Every test pins gl_entry and
stock_ledger_entry byte-identical so a later reader does not add a leg
assertion that cannot hold.
"""
import importlib.util
import os
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_DIR = os.path.dirname(_TESTS_DIR)
_PARENT_DIR = os.path.dirname(_MODULE_DIR)
_SRC_DIR = os.path.dirname(_PARENT_DIR)
_SETUP_DIR = os.path.join(_SRC_DIR, "erpclaw", "scripts", "erpclaw-setup")

_IN_TREE_LIB = os.path.join(_SETUP_DIR, "lib")
ERPCLAW_LIB = (_IN_TREE_LIB if os.path.isdir(os.path.join(_IN_TREE_LIB, "erpclaw_lib"))
               else os.path.join(os.path.expanduser(
                   os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
if ERPCLAW_LIB not in sys.path:
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, ERPCLAW_LIB)

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


SNAPSHOT_TABLES = (
    "company", "account", "tax_category", "tax_template",
    "tax_template_line", "regional_settings", "salary_component",
    "employee", "payroll_run", "salary_slip", "customer", "supplier",
    "sales_invoice", "purchase_invoice", "gl_entry",
    "stock_ledger_entry", "audit_log",
)

LEDGER_TABLES = ("gl_entry", "stock_ledger_entry")


def _all(conn, table):
    t = Table(table)
    q = Q.from_(t).select(t.star).orderby(t.id)
    return [dict(r) for r in conn.execute(q.get_sql()).fetchall()]


def _count(conn, table):
    t = Table(table)
    q = Q.from_(t).select(fn.Count("*").as_("n"))
    return conn.execute(q.get_sql()).fetchone()["n"]


def _snapshot(conn):
    return {name: _all(conn, name) for name in SNAPSHOT_TABLES}


def _ledgers_pinned(conn, db_path, before):
    assert seam.table_exists("gl_entry", db_path)
    assert seam.table_exists("stock_ledger_entry", db_path)
    for table in LEDGER_TABLES:
        assert _count(conn, table) == before[table], table


def _insert(conn, table, row):
    sql, _cols = insert_row(table, {key: P() for key in row})
    conn.execute(sql, tuple(row.values()))


def _money(actual, expected):
    assert actual == expected, "%r != %r" % (actual, expected)
    assert Decimal(actual) == Decimal(expected)


def _u():
    return str(uuid.uuid4())


def _ca_company(conn):
    return seed_company(conn, country="CA")


def _set_province(conn, company_id, province):
    _insert(conn, "regional_settings", {
        "id": _u(), "company_id": company_id,
        "key": "province", "value": province})
    conn.commit()


def _us_company(conn):
    cid = _u()
    _insert(conn, "company", {
        "id": cid, "name": "US Co %s" % cid[:6], "abbr": "US%s" % cid[:4],
        "default_currency": "USD", "country": "US",
        "fiscal_year_start_month": 1})
    conn.commit()
    return cid


def _customer(conn, company_id):
    cid = _u()
    _insert(conn, "customer", {"id": cid, "name": "Cust %s" % cid[:6],
                              "company_id": company_id})
    return cid


def _supplier(conn, company_id):
    sid = _u()
    _insert(conn, "supplier", {"id": sid, "name": "Supp %s" % sid[:6],
                              "company_id": company_id})
    return sid


def _sales_invoice(conn, company_id, customer_id, posting_date,
                   total, tax, status="submitted"):
    iid = _u()
    _insert(conn, "sales_invoice", {
        "id": iid, "customer_id": customer_id, "posting_date": posting_date,
        "total_amount": total, "tax_amount": tax,
        "grand_total": str(Decimal(total) + Decimal(tax)),
        "status": status, "company_id": company_id})
    return iid


def _purchase_invoice(conn, company_id, supplier_id, posting_date,
                      total, tax, status="submitted"):
    iid = _u()
    _insert(conn, "purchase_invoice", {
        "id": iid, "supplier_id": supplier_id, "posting_date": posting_date,
        "total_amount": total, "tax_amount": tax,
        "grand_total": str(Decimal(total) + Decimal(tax)),
        "status": status, "company_id": company_id})
    return iid


def _employee_with_slip(conn, company_id, gross="5000.00",
                        period="2026-01", slip_status="submitted"):
    emp = _u()
    _insert(conn, "employee", {
        "id": emp, "first_name": "Alice", "last_name": "A",
        "full_name": "Alice A", "date_of_joining": "2025-01-01",
        "employment_type": "full_time", "status": "active",
        "company_id": company_id})
    run = _u()
    _insert(conn, "payroll_run", {
        "id": run, "period_start": "%s-01" % period,
        "period_end": "%s-28" % period, "company_id": company_id,
        "status": "submitted"})
    slip = _u()
    _insert(conn, "salary_slip", {
        "id": slip, "payroll_run_id": run, "employee_id": emp,
        "period_start": period, "period_end": "%s-28" % period,
        "gross_pay": gross, "total_deductions": "1000.00",
        "net_pay": str(Decimal(gross) - Decimal("1000.00")),
        "status": slip_status, "company_id": company_id})
    conn.commit()
    return emp


def _settings(conn, company_id):
    t = Table("regional_settings")
    q = (Q.from_(t).select(t.key, t.value)
         .where(t.company_id == P()).orderby(t.key))
    return {r["key"]: r["value"] for r in
            conn.execute(q.get_sql(), (company_id,)).fetchall()}


def _template_rate(conn, company_id, template_name):
    tt = Table("tax_template")
    tl = Table("tax_template_line")
    q = (Q.from_(tt).join(tl).on(tl.tax_template_id == tt.id)
         .select(tl.rate).where(tt.name == P())
         .where(tt.company_id == P()))
    return [x["rate"] for x in conn.execute(q.get_sql(), (template_name, company_id)).fetchall()]


# ── ca-compute-cpp2: COMPUTED VALUE ─────────────────────────────────────────

class TestComputeCpp2Depth:
    def test_cpp2_exact_math_and_writes_nothing(self, conn, db_path):
        # This action does NOT reach the ledger and stores no row: it prices
        # CPP2 on earnings between the two ceilings. Behaviour = the exact
        # response values, cross-checked against independent Decimal math,
        # plus both ledgers byte-identical.
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-compute-cpp2"], conn,
                        ns(annual_earnings="80000"))
        assert is_ok(r), r
        assert r["cpp2_applicable"] is True
        assert r["first_ceiling"] == "74600"
        assert r["second_ceiling"] == "85000"
        assert r["cpp2_rate"] == "4.00"
        _money(r["annual_earnings"], "80000.00")
        _money(r["cpp2_earnings"], "5400.00")
        _money(r["employee_cpp2"], "216.00")
        _money(r["employer_cpp2"], "216.00")
        _money(r["annual_max_employee"], "416.00")

        # Independent check, not an echo of the action's own helpers:
        # 80000 - 74600 = 5400 of CPP2 room, 4% of that is 216.00,
        # below the 416.00 annual maximum.
        assert Decimal("80000") - Decimal("74600") == Decimal("5400")
        assert (Decimal("5400") * Decimal("0.04")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("216.00")
        assert Decimal(r["employee_cpp2"]) <= Decimal("416.00")

        assert _snapshot(conn) == before, "a computation must write nothing"
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

    def test_cpp2_missing_earnings_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-compute-cpp2"], conn, ns())
        assert is_error(r)
        assert r["message"] == "--annual-earnings (or --gross-salary) is required"

        assert _snapshot(conn) == before


# ── ca-generate-gst-hst-return: READ ────────────────────────────────────────

class TestGenerateGstHstReturnDepth:
    def test_return_totals_match_invoice_rows_and_writes_nothing(
            self, conn, db_path):
        # This action does NOT reach the ledger and stores no row: it adds up
        # submitted sales and purchase invoices for one month. Behaviour = the
        # reported totals equal the stored invoice rows to the cent.
        cid = _ca_company(conn)
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        _sales_invoice(conn, cid, cust, "2026-01-15", "1000.00", "130.00")
        _sales_invoice(conn, cid, cust, "2026-01-20", "2000.00", "260.00")
        _sales_invoice(conn, cid, cust, "2026-02-05", "9999.00", "999.00")
        _sales_invoice(conn, cid, cust, "2026-01-12", "500.00", "65.00",
                       status="draft")
        _purchase_invoice(conn, cid, sup, "2026-01-10", "500.00", "65.00")
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-gst-hst-return"], conn,
                        ns(company_id=cid, period="1", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "GST/HST Return"
        assert r["period"] == "2026-01"
        assert r["business_number"] == "Not configured"
        _money(r["revenue"], "3000.00")
        _money(r["tax_collected"], "390.00")
        _money(r["itc_claimed"], "65.00")
        _money(r["net_tax"], "325.00")
        assert r["sales_invoice_count"] == 2
        assert r["purchase_invoice_count"] == 1
        assert r["action_required"] == "Remit"
        _money(r["amount_due_or_refund"], "325.00")

        # Grounding: the stored rows the return claims to summarise.
        si = Table("sales_invoice")
        q = (Q.from_(si).select(si.posting_date, si.total_amount,
                               si.tax_amount, si.status)
             .where(si.company_id == P()).orderby(si.posting_date))
        rows = [dict(x) for x in conn.execute(q.get_sql(), (cid,)).fetchall()]
        jan_submitted = [x for x in rows
                         if x["posting_date"].startswith("2026-01")
                         and x["status"] == "submitted"]
        assert len(jan_submitted) == 2
        assert (sum(Decimal(x["total_amount"]) for x in jan_submitted)
                == Decimal("3000.00"))
        assert (sum(Decimal(x["tax_amount"]) for x in jan_submitted)
                == Decimal("390.00"))
        # The February invoice and the January draft are excluded.
        assert len(rows) == 4

        assert _snapshot(conn) == before, "a report must write nothing"
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

    def test_return_missing_period_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-gst-hst-return"], conn,
                        ns(company_id=cid))
        assert is_error(r)
        assert r["message"] == "--period (or --month) and --year are required"

        assert _snapshot(conn) == before


# ── ca-generate-pd7a: READ (fixed m343b) ───────────────────────────────────

class TestGeneratePd7aDepth:
    def test_pd7a_reports_month_and_writes_nothing(self, conn, db_path):
        # Fixed m343b: the success path no longer reads a province column
        # off employee (no such column exists); every slip is priced at the
        # company province, and the month's slips come through the shared
        # helper. Behaviour = the exact remittance lines for the stored
        # slip, and the database byte-identical afterwards.
        cid = _ca_company(conn)
        _set_province(conn, cid, "ON")
        _employee_with_slip(conn, cid)
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid, month="1", year="2026"))
        assert is_ok(r), r
        assert r["period"] == "2026-01"
        assert r["employee_count"] == 1
        # The one 5000.00 slip, annual 60000: CPP (60000-3500) x 5.95% =
        # 3361.75 / 12 = 280.15; EI 60000 x 1.63% = 978.00 / 12 = 81.50,
        # employer 81.50 x 1.4 = 114.10; federal 8496.01 - 2303.28 (BPA at
        # the 14% lowest rate) = 6192.73 / 12 = 516.06 and Ontario
        # provincial 2624.53 / 12 = 218.71. Line 5 is federal plus
        # provincial: 516.06 + 218.71 = 734.77; total 1271.96 + 218.71 =
        # 1490.67.
        _money(r["line_1_cpp_employee"], "280.15")
        _money(r["line_2_cpp_employer"], "280.15")
        _money(r["line_3_ei_employee"], "81.50")
        _money(r["line_4_ei_employer"], "114.10")
        _money(r["line_5_income_tax"], "734.77")
        _money(r["total_remittance"], "1490.67")
        _money(r["revenu_quebec_qpp_employee"], "0.00")
        _money(r["revenu_quebec_qpp_employer"], "0.00")
        _money(r["revenu_quebec_provincial_tax"], "0.00")
        _money(r["revenu_quebec_total_remittance"], "0.00")
        assert Decimal("516.06") + Decimal("218.71") == Decimal("734.77")
        assert (Decimal("280.15") + Decimal("280.15") + Decimal("81.50")
                + Decimal("114.10") + Decimal("734.77")
                == Decimal("1490.67"))

        assert _snapshot(conn) == before

    def test_pd7a_missing_month_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        # The refusal check runs before the broken query, so input
        # validation still refuses cleanly with a truthful message.
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-pd7a"], conn,
                        ns(company_id=cid))
        assert is_error(r)
        assert r["message"] == "--month and --year are required"

        assert _snapshot(conn) == before


# ── ca-generate-qst-return: READ ────────────────────────────────────────────

class TestGenerateQstReturnDepth:
    def test_qst_split_matches_invoice_rows_and_writes_nothing(
            self, conn, db_path):
        # This action does NOT reach the ledger and stores no row: it splits
        # the month's GST+QST totals into the QST portion. Behaviour = the
        # split matches the stored invoice rows through the documented
        # 9.975 / 14.975 fraction.
        cid = _ca_company(conn)
        r = call_action(ACTIONS["ca-setup-gst-hst"], conn,
                        ns(company_id=cid,
                           business_number="123456789RT0001", province="QC"))
        assert is_ok(r), r
        cust = _customer(conn, cid)
        sup = _supplier(conn, cid)
        _sales_invoice(conn, cid, cust, "2026-01-15", "1000.00", "149.75")
        _purchase_invoice(conn, cid, sup, "2026-01-10", "500.00", "74.88")
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-qst-return"], conn,
                        ns(company_id=cid, period="1", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "QST Return"
        assert r["period"] == "2026-01"
        _money(r["taxable_sales"], "1000.00")
        _money(r["qst_collected"], "99.75")
        _money(r["qst_input_tax_refunds"], "49.88")
        _money(r["net_qst"], "49.87")
        assert r["sales_invoice_count"] == 1
        assert r["purchase_invoice_count"] == 1
        assert r["action_required"] == "Remit"
        _money(r["amount_due_or_refund"], "49.87")

        # Independent check of the documented fraction.
        fraction = Decimal("9.975") / Decimal("14.975")
        assert (Decimal("149.75") * fraction).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("99.75")
        assert (Decimal("74.88") * fraction).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("49.88")
        assert Decimal("99.75") - Decimal("49.88") == Decimal("49.87")

        assert _snapshot(conn) == before, "a report must write nothing"
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

    def test_qst_on_ontario_company_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        cid = _ca_company(conn)
        r = call_action(ACTIONS["ca-setup-gst-hst"], conn,
                        ns(company_id=cid, business_number="987654321",
                           province="ON"))
        assert is_ok(r), r
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-qst-return"], conn,
                        ns(company_id=cid, period="1", year="2026"))
        assert is_error(r)
        assert r["message"] == "QST return is only for Quebec companies."
        assert "generate-gst-hst-return" in r.get("suggestion", "")

        assert _snapshot(conn) == before


# ── ca-generate-roe: READ ───────────────────────────────────────────────────

class TestGenerateRoeDepth:
    def test_roe_totals_match_slip_rows_and_writes_nothing(
            self, conn, db_path):
        # This action does NOT reach the ledger and stores no row: it totals
        # the employee's submitted salary slips. Behaviour = the blocks equal
        # the stored slip rows.
        cid = _ca_company(conn)
        emp = _employee_with_slip(conn, cid)
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-roe"], conn,
                        ns(employee_id=emp, reason_code="E"))
        assert is_ok(r), r
        assert r["form"] == "ROE"
        assert r["employee_name"] == "Alice A"
        _money(r["block_15b_total_insurable_earnings"], "5000.00")
        _money(r["block_15a_total_insurable_hours"], "173.33")
        assert r["block_16_reason_for_separation"] == "E - Quit"
        assert r["periods_reported"] == 1
        assert r["block_15c_insurable_earnings_by_period"] == [
            {"period": "2026-01", "earnings": "5000.00"}]

        # Grounding: the stored employee and slip rows.
        em = Table("employee")
        q = Q.from_(em).select(em.full_name).where(em.id == P())
        assert (conn.execute(q.get_sql(), (emp,)).fetchone()["full_name"]
                == "Alice A")
        ss = Table("salary_slip")
        q = (Q.from_(ss).select(ss.gross_pay, ss.period_start)
             .where(ss.employee_id == P()))
        slips = [dict(x) for x in conn.execute(q.get_sql(), (emp,)).fetchall()]
        assert len(slips) == 1
        assert slips[0]["gross_pay"] == "5000.00"
        assert slips[0]["period_start"] == "2026-01"

        assert _snapshot(conn) == before, "a report must write nothing"
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

    def test_roe_unknown_employee_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-roe"], conn,
                        ns(employee_id="ghost-ca-roe"))
        assert is_error(r)
        assert r["message"] == "Employee not found: ghost-ca-roe"

        assert _snapshot(conn) == before


# ── ca-generate-t4: READ ─────────────────────────────────────────────────────

class TestGenerateT4Depth:
    def test_t4_boxes_match_slip_sum_and_writes_nothing(
            self, conn, db_path):
        # This action does NOT reach the ledger and stores no row: it sums
        # the year's submitted slips into T4 boxes. Behaviour = every box
        # equals the stored slip total run through the documented estimates.
        cid = _ca_company(conn)
        _set_province(conn, cid, "ON")
        emp = _employee_with_slip(conn, cid)
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-t4"], conn,
                        ns(employee_id=emp, tax_year="2026"))
        assert is_ok(r), r
        assert r["form"] == "T4"
        assert r["tax_year"] == 2026
        assert r["employee_name"] == "Alice A"
        assert r["province_of_employment"] == "ON"
        assert r["sin_masked"] == ""
        _money(r["box_14_employment_income"], "5000.00")
        _money(r["box_16_cpp_contributions"], "89.25")
        _money(r["box_18_ei_premiums"], "81.50")
        # Real behaviour, pinned exactly: with no tax owing the action emits
        # "0" rather than "0.00". Not fixed; the string is asserted as-is.
        assert r["box_22_income_tax_deducted"] == "0"
        assert Decimal(r["box_22_income_tax_deducted"]) == Decimal("0")
        _money(r["box_24_ei_insurable_earnings"], "5000.00")
        _money(r["box_26_cpp_pensionable_earnings"], "5000.00")
        assert r["salary_slips_count"] == 1

        # Grounding: the slip total the boxes are estimated from.
        ss = Table("salary_slip")
        q = (Q.from_(ss).select(ss.gross_pay)
             .where(ss.employee_id == P()).where(ss.status == P()))
        slips = [dict(x) for x in
                 conn.execute(q.get_sql(), (emp, "submitted")).fetchall()]
        assert sum(Decimal(x["gross_pay"]) for x in slips) == Decimal("5000.00")
        # Independent spot-checks of the documented estimates:
        # CPP on (5000 - 3500) at 5.95%; EI on 5000 at 1.63%.
        assert ((Decimal("5000") - Decimal("3500"))
                * Decimal("0.0595")).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP) == Decimal("89.25")
        assert (Decimal("5000") * Decimal("0.0163")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("81.50")

        assert _snapshot(conn) == before, "a report must write nothing"
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

    def test_t4_missing_employee_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-t4"], conn, ns(tax_year="2026"))
        assert is_error(r)
        assert r["message"] == "--employee-id is required"

        assert _snapshot(conn) == before


# ── ca-generate-t4a: COMPUTED VALUE ─────────────────────────────────────────

class TestGenerateT4aDepth:
    def test_t4a_withholding_math_and_writes_nothing(self, conn, db_path):
        # This action does NOT reach the ledger and stores no row: it prices
        # withholding on a stated amount. Behaviour = the exact box values,
        # cross-checked against independent Decimal math.
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-t4a"], conn,
                        ns(recipient_name="Bob", amount="10000",
                           year="2026", income_type="pension"))
        assert is_ok(r), r
        assert r["tax_year"] == 2026
        assert r["recipient_name"] == "Bob"
        assert r["box_description"] == "Pension or superannuation"
        _money(r["box_016_pension"], "10000.00")
        _money(r["box_022_income_tax_deducted"], "2500.00")
        assert r["withholding_rate"] == "25%"

        # Independent check: 10000 exceeds 5000, so the 25% lump-sum rate
        # applies: 10000 * 25% = 2500.00.
        assert (Decimal("10000") * Decimal("25")
                / Decimal("100")) == Decimal("2500")

        assert _snapshot(conn) == before, "a computation must write nothing"
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

    def test_t4a_missing_amount_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-generate-t4a"], conn,
                        ns(recipient_name="Bob", year="2026"))
        assert is_error(r)
        assert r["message"] == "--amount is required"

        assert _snapshot(conn) == before


# ── ca-payroll-summary: READ ────────────────────────────────────────────────

class TestPayrollSummaryDepth:
    def test_summary_matches_slip_row_and_writes_nothing(
            self, conn, db_path):
        # This action does NOT reach the ledger and stores no row: it prices
        # deductions off each submitted slip for the month. Behaviour = the
        # per-employee figures and the totals equal the stored slip's gross
        # run through the documented annualisation.
        cid = _ca_company(conn)
        _set_province(conn, cid, "ON")
        emp = _employee_with_slip(conn, cid)
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid, month="1", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "Canada Payroll Summary"
        assert r["period"] == "2026-01"
        assert r["employee_count"] == 1
        line = r["employees"][0]
        assert line["employee_id"] == emp
        assert line["employee_name"] == "Alice A"
        assert line["province"] == "ON"
        _money(line["gross"], "5000.00")
        _money(line["deductions"]["cpp"], "280.15")
        _money(line["deductions"]["ei"], "81.50")
        _money(line["deductions"]["federal_tax"], "516.06")
        _money(line["deductions"]["provincial_tax"], "218.71")
        _money(line["total_deductions"], "1096.42")
        _money(line["net_pay"], "3903.58")
        totals = r["totals"]
        _money(totals["total_gross"], "5000.00")
        _money(totals["total_cpp"], "280.15")
        _money(totals["total_ei"], "81.50")
        _money(totals["total_federal_tax"], "516.06")
        _money(totals["total_provincial_tax"], "218.71")
        _money(totals["total_deductions"], "1096.42")
        _money(totals["total_net_pay"], "3903.58")
        _money(totals["total_employer_cpp"], "280.15")
        _money(totals["total_employer_ei"], "114.10")

        # Grounding: the stored slip's gross behind every figure.
        ss = Table("salary_slip")
        q = (Q.from_(ss).select(ss.gross_pay, ss.period_start)
             .where(ss.employee_id == P()).where(ss.status == P()))
        slips = [dict(x) for x in
                 conn.execute(q.get_sql(), (emp, "submitted")).fetchall()]
        assert len(slips) == 1
        assert slips[0]["gross_pay"] == "5000.00"
        assert slips[0]["period_start"] == "2026-01"
        # Independent spot-checks on the monthly annualisation (x12):
        # CPP (60000 - 3500) at 5.95% / 12; EI 60000 at 1.63% / 12;
        # federal 8496.01 - 2303.28 (BPA 16452 at the 14% lowest rate) =
        # 6192.73 / 12.
        assert ((Decimal("60000") - Decimal("3500")) * Decimal("0.0595")
                / Decimal("12")).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP) == Decimal("280.15")
        assert (Decimal("60000") * Decimal("0.0163")
                / Decimal("12")).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP) == Decimal("81.50")
        # Internal consistency: parts sum to the total, gross minus total
        # is the net, and the one line is the company total.
        assert (Decimal(line["deductions"]["cpp"])
                + Decimal(line["deductions"]["ei"])
                + Decimal(line["deductions"]["federal_tax"])
                + Decimal(line["deductions"]["provincial_tax"])
                == Decimal("1096.42"))
        assert (Decimal("5000.00") - Decimal("1096.42")
                == Decimal("3903.58"))

        assert _snapshot(conn) == before, "a report must write nothing"
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

    def test_summary_missing_month_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-payroll-summary"], conn,
                        ns(company_id=cid))
        assert is_error(r)
        assert r["message"] == "--month and --year are required"

        assert _snapshot(conn) == before


# ── ca-seed-ca-coa: STORED ROWS (fixed m343b) ───────────────────────────────

class TestSeedCaCoaDepth:
    def test_coa_seed_stores_template_and_second_run_is_noop(self, conn, db_path):
        # Fixed m343d (was m343b for the empty-number part): the 17
        # header/group template rows with no account number are stored as
        # NULL instead of an empty string, and a template number the
        # company already uses on another account is stored as NULL and
        # listed under number_conflicts, so the
        # UNIQUE(account_number, company_id) rule holds and the seed
        # commits. Behaviour = every template row stored, header rows
        # carrying no number, one audit row, and a second run creating
        # nothing further.
        import json as _json
        with open(os.path.join(_PARENT_DIR, "assets",
                               "ca_coa_aspe.json")) as _f:
            _template_rows = _json.load(_f)
        _expected = (_template_rows if isinstance(_template_rows, list)
                     else _template_rows.get("accounts", []))
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-seed-ca-coa"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["accounts_created"] == len(_expected)
        assert r["total_in_template"] == len(_expected)
        assert r["number_conflicts"] == []

        ac = Table("account")
        q = (Q.from_(ac).select(ac.name, ac.account_number)
             .where(ac.company_id == P()))
        stored = {x["name"]: x["account_number"] for x in
                  conn.execute(q.get_sql(), (cid,)).fetchall()}
        assert len(stored) == len(_expected)
        assert stored["Cash"] == "1010"
        assert stored["GST/HST Payable"] == "2200"
        assert stored["Assets"] is None
        q = (Q.from_(ac).select(fn.Count("*").as_("n"))
             .where(ac.company_id == P()))
        assert (conn.execute(q.get_sql(), (cid,)).fetchone()["n"]
                == len(_expected))
        al = Table("audit_log")
        q = (Q.from_(al).select(fn.Count("*").as_("n"))
             .where(al.entity_id == P()))
        assert conn.execute(q.get_sql(), (cid,)).fetchone()["n"] == 1

        after = _snapshot(conn)
        for table in SNAPSHOT_TABLES:
            if table in ("account", "audit_log"):
                continue
            assert after[table] == before[table], table
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

        r2 = call_action(ACTIONS["ca-seed-ca-coa"], conn,
                         ns(company_id=cid))
        assert is_ok(r2), r2
        assert r2["accounts_created"] == 0
        q = (Q.from_(ac).select(fn.Count("*").as_("n"))
             .where(ac.company_id == P()))
        assert (conn.execute(q.get_sql(), (cid,)).fetchone()["n"]
                == len(_expected))

    def test_coa_seed_on_us_company_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        usid = _us_company(conn)
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-seed-ca-coa"], conn, ns(company_id=usid))
        assert is_error(r)
        assert r["message"] == ("This action is for Canadian companies only. "
                                "Company country must be CA.")

        assert _snapshot(conn) == before


# ── ca-seed-ca-defaults: STORED ROWS ────────────────────────────────────────

class TestSeedCaDefaultsDepth:
    def test_defaults_store_exact_rows_and_nothing_else(self, conn, db_path):
        # This action does NOT reach the ledger: it stores tax accounts,
        # categories and templates (plus one audit row). Behaviour = the
        # exact stored rows, the response counts matching them, and a second
        # run creating nothing further.
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-seed-ca-defaults"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["company_id"] == cid
        assert r["accounts_created"] == 4
        assert r["templates_created"] == 11
        assert r["categories_created"] == 9

        ac = Table("account")
        q = (Q.from_(ac).select(ac.name, ac.account_type, ac.root_type)
             .where(ac.company_id == P()).orderby(ac.name))
        accounts = [dict(x) for x in conn.execute(q.get_sql(), (cid,)).fetchall()]
        assert [(x["name"], x["account_type"], x["root_type"])
                for x in accounts] == [
            ("GST Collected", "tax", "liability"),
            ("GST Paid on Purchases", "tax", "asset"),
            ("HST Collected", "tax", "liability"),
            ("HST Paid on Purchases", "tax", "asset"),
        ]

        tc = Table("tax_category")
        q = Q.from_(tc).select(tc.name).orderby(tc.name)
        assert sorted(x["name"] for x in
                      conn.execute(q.get_sql()).fetchall()) == [
            "Exempt", "GST 5%", "HST-Atlantic 15%", "HST-ON 13%",
            "PST-BC 7%", "PST-SK 6%", "QST-QC 9.975%", "RST-MB 7%",
            "Zero-rated",
        ]

        tt = Table("tax_template")
        q = (Q.from_(tt).select(tt.name, tt.tax_type)
             .where(tt.company_id == P()))
        templates = {x["name"]: x["tax_type"] for x in
                     conn.execute(q.get_sql(), (cid,)).fetchall()}
        assert len(templates) == 11
        assert templates["Canada GST 5% Sales"] == "sales"
        assert templates["Canada QST-QC 9.975% Purchase"] == "purchase"
        assert _template_rate(conn, cid, "Canada GST 5% Sales") == ["5"]
        assert _template_rate(conn, cid,
                              "Canada QST-QC 9.975% Purchase") == ["9.975"]

        al = Table("audit_log")
        q = (Q.from_(al).select(al.skill, al.action)
             .where(al.entity_id == P()))
        audits = [dict(x) for x in conn.execute(q.get_sql(), (cid,)).fetchall()]
        assert audits == [{"skill": "erpclaw-region-ca",
                           "action": "ca-seed-ca-defaults"}]

        after = _snapshot(conn)
        for table in SNAPSHOT_TABLES:
            if table in ("account", "tax_category", "tax_template",
                         "tax_template_line", "audit_log"):
                continue
            assert after[table] == before[table], table
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

        # A second run is a no-op for domain rows (counts must agree with
        # the first response, not grow past it).
        r2 = call_action(ACTIONS["ca-seed-ca-defaults"], conn,
                         ns(company_id=cid))
        assert is_ok(r2), r2
        assert (r2["accounts_created"], r2["templates_created"],
                r2["categories_created"]) == (0, 0, 0)
        assert _count(conn, "account") == 4
        assert _count(conn, "tax_template") == 11

    def test_defaults_on_us_company_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        usid = _us_company(conn)
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-seed-ca-defaults"], conn,
                        ns(company_id=usid))
        assert is_error(r)
        assert r["message"] == ("This action is for Canadian companies only. "
                                "Company country must be CA.")

        assert _snapshot(conn) == before


# ── ca-seed-ca-payroll: STORED ROWS ─────────────────────────────────────────

class TestSeedCaPayrollDepth:
    def test_payroll_components_stored_exactly_and_nothing_else(
            self, conn, db_path):
        # This action does NOT reach the ledger: it stores the eight
        # statutory salary components (plus one audit row). Behaviour = the
        # exact stored rows, the response count matching them, and a second
        # run creating nothing further.
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-seed-ca-payroll"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["company_id"] == cid
        assert r["components_created"] == 8
        assert r["components"] == [
            "CPP Employee", "CPP Employer", "CPP2 Employee",
            "CPP2 Employer", "EI Employee", "EI Employer",
            "Federal Income Tax", "Provincial Income Tax",
        ]

        sc = Table("salary_component")
        q = (Q.from_(sc).select(sc.name, sc.component_type,
                               sc.is_statutory).orderby(sc.name))
        stored = [(x["name"], x["component_type"], x["is_statutory"])
                  for x in conn.execute(q.get_sql()).fetchall()]
        assert stored == [
            ("CPP Employee", "deduction", 1),
            ("CPP Employer", "employer_contribution", 1),
            ("CPP2 Employee", "deduction", 1),
            ("CPP2 Employer", "employer_contribution", 1),
            ("EI Employee", "deduction", 1),
            ("EI Employer", "employer_contribution", 1),
            ("Federal Income Tax", "deduction", 1),
            ("Provincial Income Tax", "deduction", 1),
        ]

        al = Table("audit_log")
        q = (Q.from_(al).select(al.skill, al.action)
             .where(al.entity_id == P()))
        audits = [dict(x) for x in conn.execute(q.get_sql(), (cid,)).fetchall()]
        assert audits == [{"skill": "erpclaw-region-ca",
                           "action": "ca-seed-ca-payroll"}]

        after = _snapshot(conn)
        for table in SNAPSHOT_TABLES:
            if table in ("salary_component", "audit_log"):
                continue
            assert after[table] == before[table], table
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

        r2 = call_action(ACTIONS["ca-seed-ca-payroll"], conn,
                         ns(company_id=cid))
        assert is_ok(r2), r2
        assert r2["components_created"] == 0
        assert _count(conn, "salary_component") == 8

    def test_payroll_seed_on_us_company_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        usid = _us_company(conn)
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-seed-ca-payroll"], conn,
                        ns(company_id=usid))
        assert is_error(r)
        assert r["message"] == ("This action is for Canadian companies only. "
                                "Company country must be CA.")

        assert _snapshot(conn) == before


# ── ca-setup-gst-hst: STORED ROWS ───────────────────────────────────────────

class TestSetupGstHstDepth:
    def test_setup_stores_settings_updates_them_and_nothing_else(
            self, conn, db_path):
        # This action does NOT reach the ledger: it stores five
        # regional_settings rows (plus one audit row per call). Behaviour =
        # the exact stored key/value pairs, the response echoing them, and a
        # second call updating the same five rows rather than adding more.
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-setup-gst-hst"], conn,
                        ns(company_id=cid,
                           business_number="123456789RT0001", province="ON"))
        assert is_ok(r), r
        assert r["bn"] == "123456789RT0001"
        assert r["province"] == "ON"
        assert r["province_name"] == "Ontario"
        assert r["tax_type"] == "HST"
        assert _settings(conn, cid) == {
            "bn": "123456789RT0001",
            "gst_hst_configured": "1",
            "province": "ON",
            "province_name": "Ontario",
            "tax_type": "HST",
        }

        al = Table("audit_log")
        q = (Q.from_(al).select(fn.Count("*").as_("n"))
             .where(al.entity_id == P()))
        assert conn.execute(q.get_sql(), (cid,)).fetchone()["n"] == 1

        after = _snapshot(conn)
        for table in SNAPSHOT_TABLES:
            if table in ("regional_settings", "audit_log"):
                continue
            assert after[table] == before[table], table
        _ledgers_pinned(conn, db_path, {t: 0 for t in LEDGER_TABLES})

        # Update path: the same five keys move from ON to BC.
        r2 = call_action(ACTIONS["ca-setup-gst-hst"], conn,
                         ns(company_id=cid, business_number="987654321",
                            province="BC"))
        assert is_ok(r2), r2
        assert r2["bn"] == "987654321"
        assert r2["province"] == "BC"
        assert _settings(conn, cid) == {
            "bn": "987654321",
            "gst_hst_configured": "1",
            "province": "BC",
            "province_name": "British Columbia",
            "tax_type": "GST+PST",
        }
        rs = Table("regional_settings")
        q = (Q.from_(rs).select(fn.Count("*").as_("n"))
             .where(rs.company_id == P()))
        assert conn.execute(q.get_sql(), (cid,)).fetchone()["n"] == 5

    def test_setup_bad_bn_refused_truthfully_and_writes_nothing(
            self, conn, db_path):
        cid = _ca_company(conn)
        conn.commit()
        before = _snapshot(conn)

        r = call_action(ACTIONS["ca-setup-gst-hst"], conn,
                        ns(company_id=cid, business_number="123",
                           province="ON"))
        assert is_error(r)
        assert r["message"] == ("BN must be 9 digits (base) or "
                                "15 characters (full)")

        assert _snapshot(conn) == before
