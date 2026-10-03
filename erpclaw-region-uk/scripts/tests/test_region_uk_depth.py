"""Behavioural depth tests for the 12 routed-only UK actions.

Each action below already had a test that proved the wrong thing: either the
response had the expected keys (shape) or the action name routed at all
(routability). Neither observed the database, so an action could write nothing
or write the wrong thing and still pass. Every test here reads the rows back
through the connection afterwards and compares exact values:

- seed actions assert the stored rows (exact names, types, rates, links),
  idempotent re-runs, and that unrelated rows are untouched;
- aggregate reports (VAT return, MTD, FPS, EPS, P60, P45, payroll summary)
  seed submitted rows plus draft / wrong-period decoys and assert the response
  carries exactly the seeded figures, then re-read the fixtures unchanged;
- pure responses (flat-rate computation, EC sales list) assert exact figures
  and prove the database is byte-identical before and after;
- every action has a refusal case: the error is truthful and the database is
  byte-identical afterwards (a refusal that half-writes is worse than none).

Money is text throughout: exact string comparisons, never float, never
round(). The MTD payload's VAT figures are exact text like every other
figure; only its whole-pound figures are integers.

No action under test reaches the ledger: each test snapshots gl_entry with
everything else and states the no-ledger-effect fact in a comment so a later
reader does not add a balance assertion that cannot hold.

Findings are marked KNOWN DEFECT and recorded in CHANGES.md; production is
unchanged, so the tests below pin the real behaviour, bugs included.
"""
import os
import sys
import uuid
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from uk_helpers import (  # noqa: E402
    call_action, is_error, is_ok, load_db_query, ns, seed_company,
)
from erpclaw_lib.query import (  # noqa: E402
    Q, P, Table, Order, insert_row,
)

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

# Every table any of the 12 actions could conceivably write, so a
# before/after snapshot proves "writes nothing" byte for byte.
SNAPSHOT_TABLES = (
    "account", "tax_template", "tax_template_line", "salary_component",
    "regional_settings", "sales_invoice", "purchase_invoice", "salary_slip",
    "employee", "customer", "supplier", "audit_log", "gl_entry",
)


def _snapshot(conn):
    snap = {}
    for name in SNAPSHOT_TABLES:
        t = Table(name)
        q = Q.from_(t).select(t.star).orderby(t.id, order=Order.asc)
        snap[name] = [dict(r) for r in conn.execute(q.get_sql()).fetchall()]
    return snap


def _insert(conn, table, values):
    sql, _ = insert_row(table, {col: P() for col in values})
    conn.execute(sql, tuple(values.values()))
    conn.commit()


def _add_customer(conn, company_id, name="Cust"):
    cid = str(uuid.uuid4())
    _insert(conn, "customer",
            {"id": cid, "name": "%s %s" % (name, cid[:6]),
             "company_id": company_id})
    return cid


def _add_supplier(conn, company_id, name="Sup"):
    sid = str(uuid.uuid4())
    _insert(conn, "supplier",
            {"id": sid, "name": "%s %s" % (name, sid[:6]),
             "company_id": company_id})
    return sid


def _add_sales_invoice(conn, company_id, customer_id, posting_date, total,
                       tax, status="submitted"):
    iid = str(uuid.uuid4())
    _insert(conn, "sales_invoice",
            {"id": iid, "customer_id": customer_id,
             "posting_date": posting_date, "total_amount": total,
             "tax_amount": tax, "status": status, "company_id": company_id})
    return iid


def _add_purchase_invoice(conn, company_id, supplier_id, posting_date, total,
                          tax, status="submitted"):
    iid = str(uuid.uuid4())
    _insert(conn, "purchase_invoice",
            {"id": iid, "supplier_id": supplier_id,
             "posting_date": posting_date, "total_amount": total,
             "tax_amount": tax, "status": status, "company_id": company_id})
    return iid


def _add_employee(conn, company_id, first, last, ssn, date_of_exit=None):
    eid = str(uuid.uuid4())
    values = {"id": eid, "first_name": first, "last_name": last,
              "full_name": "%s %s" % (first, last),
              "date_of_joining": "2024-01-01", "company_id": company_id,
              "ssn": ssn}
    if date_of_exit is not None:
        values["date_of_exit"] = date_of_exit
    _insert(conn, "employee", values)
    return eid


def _add_payroll_run(conn, company_id, start, end):
    prid = str(uuid.uuid4())
    _insert(conn, "payroll_run",
            {"id": prid, "period_start": start, "period_end": end,
             "company_id": company_id})
    return prid


def _add_slip(conn, company_id, run_id, employee_id, start, end, gross,
              deductions, net, status="submitted"):
    sid = str(uuid.uuid4())
    _insert(conn, "salary_slip",
            {"id": sid, "payroll_run_id": run_id, "employee_id": employee_id,
             "period_start": start, "period_end": end, "gross_pay": gross,
             "total_deductions": deductions, "net_pay": net,
             "status": status, "company_id": company_id})
    return sid


def _seed_vat_period(conn, company_id):
    """Two submitted January sales, one submitted January purchase, plus a
    draft decoy and a February decoy that must both be ignored."""
    cust = _add_customer(conn, company_id)
    sup = _add_supplier(conn, company_id)
    _add_sales_invoice(conn, company_id, cust, "2026-01-10", "1000.00",
                       "200.00")
    _add_sales_invoice(conn, company_id, cust, "2026-01-20", "500.00",
                       "100.00")
    _add_sales_invoice(conn, company_id, cust, "2026-01-15", "999.00",
                       "199.80", status="draft")
    _add_sales_invoice(conn, company_id, cust, "2026-02-05", "700.00",
                       "140.00")
    _add_purchase_invoice(conn, company_id, sup, "2026-01-12", "400.00",
                          "80.00")


def _seed_payroll_period(conn, company_id):
    """Two submitted January slips, plus a draft decoy and a February decoy
    that must both be ignored."""
    e1 = _add_employee(conn, company_id, "Ada", "Lovelace", "AB123456C")
    e2 = _add_employee(conn, company_id, "Alan", "Turing", "CD654321A")
    run = _add_payroll_run(conn, company_id, "2026-01-01", "2026-01-31")
    _add_slip(conn, company_id, run, e1, "2026-01-01", "2026-01-31",
              "3000.00", "600.00", "2400.00")
    _add_slip(conn, company_id, run, e2, "2026-01-05", "2026-01-31",
              "2000.00", "400.00", "1600.00")
    _add_slip(conn, company_id, run, e1, "2026-01-01", "2026-01-31",
              "9999.00", "999.00", "9000.00", status="draft")
    _add_slip(conn, company_id, run, e1, "2026-02-01", "2026-02-28",
              "3000.00", "600.00", "2400.00")
    return e1, e2


def _non_gb_company(conn):
    return seed_company(conn, name="US Co", abbr="UC", country="US")


# ── uk-seed-uk-defaults: stored rows ─────────────────────────────────────────

class TestSeedUkDefaults:
    def test_seed_uk_defaults_creates_vat_accounts_and_templates(self, conn,
                                                                 env):
        cid = env["company_id"]
        # No ledger effect: this action seeds accounts and templates only.
        assert _snapshot(conn)["gl_entry"] == []
        before = _snapshot(conn)
        assert before["account"] == []
        assert before["tax_template"] == []

        r = call_action(ACTIONS["uk-seed-uk-defaults"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["accounts_created"] == 5
        assert r["templates_created"] == 3

        t = Table("account")
        q = (Q.from_(t).select(t.name, t.account_type, t.root_type)
             .where(t.company_id == P()).orderby(t.name, order=Order.asc))
        accounts = [(row["name"], row["account_type"], row["root_type"])
                    for row in conn.execute(q.get_sql(), (cid,)).fetchall()]
        assert accounts == [
            ("VAT Control (UK)", "tax", "liability"),
            ("VAT Input (UK)", "tax", "asset"),
            ("VAT Output (Reduced 5%)", "tax", "liability"),
            ("VAT Output (Standard 20%)", "tax", "liability"),
            ("VAT Output (Zero 0%)", "tax", "liability"),
        ]

        tpl = Table("tax_template")
        q = (Q.from_(tpl).select(tpl.name, tpl.tax_type)
             .where(tpl.company_id == P()).orderby(tpl.name, order=Order.asc))
        templates = [(row["name"], row["tax_type"])
                     for row in conn.execute(q.get_sql(), (cid,)).fetchall()]
        assert templates == [
            ("UK VAT Reduced (5%)", "both"),
            ("UK VAT Standard (20%)", "both"),
            ("UK VAT Zero (0%)", "both"),
        ]

        line = Table("tax_template_line")
        acct = Table("account")
        q = (Q.from_(line).join(tpl).on(line.tax_template_id == tpl.id)
             .join(acct).on(line.tax_account_id == acct.id)
             .select(tpl.name.as_("tpl"), acct.name.as_("acct"), line.rate)
             .where(tpl.company_id == P())
             .orderby(tpl.name, order=Order.asc))
        links = [(row["tpl"], row["acct"], row["rate"])
                 for row in conn.execute(q.get_sql(), (cid,)).fetchall()]
        # KNOWN DEFECT (F1): the Zero template points at the Standard 20%
        # output account, not the Zero 0% one — the lookup pattern
        # "VAT Output%0%" matches "20%" first. Pinned as observed.
        assert links == [
            ("UK VAT Reduced (5%)", "VAT Output (Reduced 5%)", "5"),
            ("UK VAT Standard (20%)", "VAT Output (Standard 20%)", "20"),
            ("UK VAT Zero (0%)", "VAT Output (Standard 20%)", "0"),
        ]

        r = call_action(ACTIONS["uk-seed-uk-defaults"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["accounts_created"] == 0
        assert r["templates_created"] == 0
        t2 = Table("account")
        q = (Q.from_(t2).select(t2.id).where(t2.company_id == P()))
        assert len(conn.execute(q.get_sql(), (cid,)).fetchall()) == 5
        assert _snapshot(conn)["gl_entry"] == []

    def test_seed_uk_defaults_refuses_non_gb_company(self, conn, env):
        other = _non_gb_company(conn)
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-seed-uk-defaults"], conn,
                        ns(company_id=other))
        assert is_error(r), r
        assert "UK companies only" in r["message"]
        assert "GB" in r["message"]
        assert _snapshot(conn) == before


# ── uk-seed-uk-coa: stored rows ──────────────────────────────────────────────

class TestSeedUkCoa:
    def test_seed_uk_coa_imports_frs102_chart(self, conn, env):
        cid = env["company_id"]
        # No ledger effect: chart import writes account rows only.
        assert _snapshot(conn)["gl_entry"] == []

        r = call_action(ACTIONS["uk-seed-uk-coa"], conn, ns(company_id=cid))
        assert is_ok(r), r
        assert r["accounts_created"] == 150
        assert r["standard"] == "FRS 102"

        t = Table("account")
        q = (Q.from_(t).select(t.account_number, t.name, t.account_type,
                               t.root_type, t.is_group)
             .where(t.company_id == P())
             .where(t.account_number == P()))
        def coa_row(number):
            row = conn.execute(q.get_sql(), (cid, number)).fetchone()
            assert row is not None, number
            return (row["account_number"], row["name"], row["account_type"],
                    row["root_type"], row["is_group"])

        assert coa_row("1000") == ("1000", "Current Assets", None, "asset",
                                   1)
        # KNOWN DEFECT (F3): the asset file carries no root_type, so
        # every imported account lands as root_type "asset" — including
        # sales (income) and liability groups. The account_type column
        # keeps only words the registry knows ("expense" and "equity"
        # survive; "asset", "liability" and "income" become NULL).
        # Pinned as observed.
        assert coa_row("6001") == ("6001", "Sales - Standard Rate", None,
                                   "asset", 0)
        assert coa_row("7001") == ("7001", "Purchases - Raw Materials",
                                   "expense", "asset", 0)
        assert coa_row("4000") == ("4000", "Non-Current Liabilities", None,
                                   "asset", 1)

        q = (Q.from_(t).select(t.account_number)
             .where(t.company_id == P()))
        numbers = [row["account_number"]
                   for row in conn.execute(q.get_sql(), (cid,)).fetchall()]
        assert len(numbers) == 150
        assert len(set(numbers)) == 150

        r = call_action(ACTIONS["uk-seed-uk-coa"], conn, ns(company_id=cid))
        assert is_ok(r), r
        assert r["accounts_created"] == 0
        assert len(conn.execute(q.get_sql(), (cid,)).fetchall()) == 150
        assert _snapshot(conn)["gl_entry"] == []

    def test_seed_uk_coa_refuses_non_gb_company(self, conn, env):
        other = _non_gb_company(conn)
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-seed-uk-coa"], conn, ns(company_id=other))
        assert is_error(r), r
        assert "UK companies only" in r["message"]
        assert "GB" in r["message"]
        assert _snapshot(conn) == before


# ── uk-seed-uk-payroll: stored rows ──────────────────────────────────────────

class TestSeedUkPayroll:
    def test_seed_uk_payroll_registers_statutory_components(self, conn, env):
        # No ledger effect: component registration writes salary_component
        # rows only.
        assert _snapshot(conn)["gl_entry"] == []

        r = call_action(ACTIONS["uk-seed-uk-payroll"], conn,
                        ns(company_id=env["company_id"]))
        assert is_ok(r), r
        assert r["components_created"] == 8

        t = Table("salary_component")
        q = (Q.from_(t).select(t.name, t.component_type, t.description,
                               t.is_statutory)
             .orderby(t.name, order=Order.asc))
        components = [(row["name"], row["component_type"],
                       row["description"], row["is_statutory"])
                      for row in conn.execute(q.get_sql()).fetchall()]
        assert components == [
            ("Basic Salary", "earning", "Basic monthly/weekly salary", 0),
            ("Employee NI", "deduction",
             "National Insurance - employee contribution", 1),
            ("Employee Pension", "deduction",
             "Employee pension contribution (NEST/auto-enrollment)", 1),
            ("Employer NI", "employer_contribution",
             "National Insurance - employer contribution", 1),
            ("Employer Pension", "employer_contribution",
             "Employer pension contribution (NEST/auto-enrollment)", 1),
            ("Overtime", "earning", "Overtime payments", 0),
            ("PAYE Income Tax", "deduction", "Pay As You Earn income tax",
             1),
            ("Student Loan", "deduction", "Student loan repayment", 0),
        ]

        r = call_action(ACTIONS["uk-seed-uk-payroll"], conn,
                        ns(company_id=env["company_id"]))
        assert is_ok(r), r
        assert r["components_created"] == 0
        assert len(conn.execute(q.get_sql()).fetchall()) == 8
        assert _snapshot(conn)["gl_entry"] == []

    def test_seed_uk_payroll_refuses_non_gb_company(self, conn, env):
        other = _non_gb_company(conn)
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-seed-uk-payroll"], conn,
                        ns(company_id=other))
        assert is_error(r), r
        assert "UK companies only" in r["message"]
        assert "GB" in r["message"]
        assert _snapshot(conn) == before


# ── uk-compute-flat-rate-vat: pure response, writes nothing ──────────────────

class TestComputeFlatRateVat:
    def test_compute_flat_rate_vat_applies_scheme_rate(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-compute-flat-rate-vat"], conn,
                        ns(gross_turnover="10000",
                           category="Retailing food, confectionery, tobacco,"
                                    " newspapers"))
        assert is_ok(r), r
        assert r["gross_turnover"] == "10000.00"
        assert r["flat_rate"] == "4"
        assert r["first_year_discount"] is False
        assert r["vat_due"] == "400.00"
        assert (Decimal(r["vat_due"])
                == Decimal("10000.00") * Decimal("4") / Decimal("100"))

        r = call_action(ACTIONS["uk-compute-flat-rate-vat"], conn,
                        ns(gross_turnover="10000",
                           category="Retailing food, confectionery, tobacco,"
                                    " newspapers",
                           first_year="true"))
        assert is_ok(r), r
        assert r["flat_rate"] == "3"
        assert r["first_year_discount"] is True
        assert r["vat_due"] == "300.00"
        assert (Decimal(r["vat_due"])
                == Decimal("10000.00") * Decimal("3") / Decimal("100"))
        # No stored row and no ledger effect: the database is byte-identical.
        assert _snapshot(conn) == before

    def test_compute_flat_rate_vat_refuses_unknown_category(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-compute-flat-rate-vat"], conn,
                        ns(gross_turnover="1000", category="Nope"))
        assert is_error(r), r
        assert r["message"] == "Unknown flat rate category: Nope"
        assert _snapshot(conn) == before


# ── uk-generate-vat-return: aggregate read over stored invoices ──────────────

class TestGenerateVatReturn:
    def test_generate_vat_return_aggregates_submitted_period_invoices(
            self, conn, env):
        cid = env["company_id"]
        _seed_vat_period(conn, cid)
        before = _snapshot(conn)
        # No ledger effect: the return aggregates invoice rows, it posts
        # nothing to gl_entry.

        r = call_action(ACTIONS["uk-generate-vat-return"], conn,
                        ns(company_id=cid, period="1", year="2026"))
        assert is_ok(r), r
        assert r["period"] == "2026-01"
        assert r["box1_vat_due_sales"] == "300.00"
        assert r["box2_vat_due_acquisitions"] == "0"
        assert r["box3_total_vat_due"] == "300.00"
        assert r["box4_vat_reclaimed"] == "80.00"
        assert r["box5_net_vat"] == "220.00"
        assert r["box6_total_sales_ex_vat"] == "1500.00"
        assert r["box7_total_purchases_ex_vat"] == "400.00"
        assert r["box8_total_supplies_eu"] == "0"
        assert r["box9_total_acquisitions_eu"] == "0"
        # The draft January invoice (999.00/199.80) and the submitted
        # February invoice (700.00/140.00) are excluded from every box above.
        assert (Decimal(r["box3_total_vat_due"])
                == Decimal(r["box1_vat_due_sales"])
                + Decimal(r["box2_vat_due_acquisitions"]))
        assert (Decimal(r["box5_net_vat"])
                == Decimal(r["box3_total_vat_due"])
                - Decimal(r["box4_vat_reclaimed"]))
        # Fixtures are unchanged: the action only reads.
        assert _snapshot(conn) == before

    def test_generate_vat_return_refuses_without_period(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-generate-vat-return"], conn,
                        ns(company_id=env["company_id"], year="2026"))
        assert is_error(r), r
        assert r["message"] == "--period and --year are required."
        assert _snapshot(conn) == before


# ── uk-generate-mtd-payload: aggregate read, exact text VAT, whole-pound integers ─

class TestGenerateMtdPayload:
    def test_generate_mtd_payload_reports_period_totals(self, conn, env):
        cid = env["company_id"]
        _seed_vat_period(conn, cid)
        before = _snapshot(conn)
        # No ledger effect: read-only aggregate over the same invoice rows
        # as the VAT return.

        r = call_action(ACTIONS["uk-generate-mtd-payload"], conn,
                        ns(company_id=cid, period="1", year="2026"))
        assert is_ok(r), r
        assert r["periodKey"] == "2026-01"
        assert r["finalised"] is True
        # VAT figures are exact text like every other figure; only the
        # whole-pound figures are integers.
        assert r["vatDueSales"] == "300.00"
        assert r["totalVatDue"] == "300.00"
        assert r["vatReclaimedCurrPeriod"] == "80.00"
        # netVatDue is abs-valued in production (observed on this tree);
        # the positive case here cannot distinguish, and is pinned as is.
        assert r["netVatDue"] == "220.00"
        assert r["totalValueSalesExVAT"] == 1500
        assert r["totalValuePurchasesExVAT"] == 400
        assert r["vatDueAcquisitions"] == "0.00"
        # Fixtures are unchanged: the action only reads.
        assert _snapshot(conn) == before

    def test_generate_mtd_payload_refuses_without_period(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-generate-mtd-payload"], conn,
                        ns(company_id=env["company_id"], year="2026"))
        assert is_error(r), r
        assert r["message"] == "--period and --year are required."
        assert _snapshot(conn) == before


# ── uk-generate-ec-sales-list: static response, writes nothing ───────────────

class TestGenerateEcSalesList:
    def test_generate_ec_sales_list_returns_empty_ni_protocol_list(
            self, conn, env):
        cid = env["company_id"]
        _seed_vat_period(conn, cid)
        before = _snapshot(conn)

        r = call_action(ACTIONS["uk-generate-ec-sales-list"], conn,
                        ns(company_id=cid, period="1", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "EC Sales List"
        assert r["period"] == "2026-01"
        assert r["entries"] == []
        assert r["total_supplies"] == "0.00"
        assert Decimal(r["total_supplies"]) == Decimal("0.00")
        assert "NI Protocol" in r["note"]
        # Static report: reads no invoice rows, stores nothing, and has no
        # ledger effect — the database is byte-identical.
        assert _snapshot(conn) == before

    def test_generate_ec_sales_list_refuses_without_year(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-generate-ec-sales-list"], conn,
                        ns(company_id=env["company_id"], period="1"))
        assert is_error(r), r
        assert r["message"] == "--period and --year are required."
        assert _snapshot(conn) == before


# ── uk-payroll-summary: happy path is deepened in place in
# test_region_uk.py; the refusal case lives here ─────────────────────────────

class TestPayrollSummary:
    def test_payroll_summary_refuses_without_month(self, conn, env):
        cid = env["company_id"]
        _seed_payroll_period(conn, cid)
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-payroll-summary"], conn,
                        ns(company_id=cid, year="2026"))
        assert is_error(r), r
        assert r["message"] == "--month and --year are required."
        assert _snapshot(conn) == before


# ── uk-generate-fps: aggregate read over stored slips ────────────────────────

class TestGenerateFps:
    def test_generate_fps_lists_period_slips_with_masked_ninos(
            self, conn, env):
        cid = env["company_id"]
        _seed_payroll_period(conn, cid)
        before = _snapshot(conn)
        # No ledger effect: the FPS lists slip rows, it posts nothing.

        r = call_action(ACTIONS["uk-generate-fps"], conn,
                        ns(company_id=cid, month="1", year="2026"))
        assert is_ok(r), r
        assert r["form"] == "FPS"
        assert r["period"] == "2026-01"
        assert r["employee_count"] == 2
        by_name = {e["employee_name"]: e for e in r["employees"]}
        # The draft January slip (9999.00) and the submitted February slip
        # are excluded from both entries below.
        assert by_name["Ada Lovelace"]["nino_masked"] == "AB****C"
        assert by_name["Ada Lovelace"]["gross_pay"] == "3000.00"
        assert by_name["Ada Lovelace"]["tax_deducted"] == "600.00"
        assert by_name["Ada Lovelace"]["net_pay"] == "2400.00"
        assert by_name["Alan Turing"]["nino_masked"] == "CD****A"
        assert by_name["Alan Turing"]["gross_pay"] == "2000.00"
        assert by_name["Alan Turing"]["tax_deducted"] == "400.00"
        assert by_name["Alan Turing"]["net_pay"] == "1600.00"
        assert (Decimal(by_name["Ada Lovelace"]["gross_pay"])
                == Decimal("3000.00"))
        # The full NINOs never leave the database masked only in transit.
        assert "AB123456C" not in str(r["employees"])
        # Fixtures are unchanged: the action only reads.
        assert _snapshot(conn) == before

    def test_generate_fps_refuses_without_month(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-generate-fps"], conn,
                        ns(company_id=env["company_id"], month="1"))
        assert is_error(r), r
        assert r["message"] == "--month and --year are required."
        assert _snapshot(conn) == before


# ── uk-generate-eps: aggregate read over stored slips ────────────────────────

class TestGenerateEps:
    def test_generate_eps_aggregates_period_payroll(self, conn, env):
        cid = env["company_id"]
        _seed_payroll_period(conn, cid)
        before = _snapshot(conn)
        # No ledger effect: read-only aggregate over the slip rows.

        r = call_action(ACTIONS["uk-generate-eps"], conn,
                        ns(company_id=cid, month="1", year="2026"))
        assert is_ok(r), r
        assert r["form"] == "EPS"
        assert r["period"] == "2026-01"
        assert r["employee_count"] == 2
        assert r["total_gross"] == "5000.00"
        assert r["total_deductions"] == "1000.00"
        assert r["total_net"] == "4000.00"
        assert r["employment_allowance_claimed"] is False
        # The draft January slip (9999.00 gross) and the submitted
        # February slip are excluded from the totals above.
        assert (Decimal(r["total_gross"])
                == Decimal("3000.00") + Decimal("2000.00"))
        assert (Decimal(r["total_net"])
                == Decimal(r["total_gross"])
                - Decimal(r["total_deductions"]))
        # Fixtures are unchanged: the action only reads.
        assert _snapshot(conn) == before

    def test_generate_eps_refuses_without_month(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-generate-eps"], conn,
                        ns(company_id=env["company_id"], year="2026"))
        assert is_error(r), r
        assert r["message"] == "--month and --year are required."
        assert _snapshot(conn) == before


# ── uk-generate-p60: aggregate read over the tax year ────────────────────────

class TestGenerateP60:
    def test_generate_p60_sums_tax_year_slips_only(self, conn, env):
        cid = env["company_id"]
        eid = _add_employee(conn, cid, "Ada", "Lovelace", "AB123456C")
        run = _add_payroll_run(conn, cid, "2025-04-01", "2026-03-31")
        # Tax year 2025 runs 2025-04-06 to 2026-04-05.
        _add_slip(conn, cid, run, eid, "2025-05-01", "2025-05-31",
                  "3000.00", "600.00", "2400.00")
        _add_slip(conn, cid, run, eid, "2026-01-01", "2026-01-31",
                  "3000.00", "600.00", "2400.00")
        _add_slip(conn, cid, run, eid, "2026-02-01", "2026-02-28",
                  "3000.00", "600.00", "2400.00")
        # Submitted but before the tax year starts: must be excluded.
        _add_slip(conn, cid, run, eid, "2025-04-01", "2025-04-30",
                  "7777.00", "777.00", "7000.00")
        # Inside the tax year but still a draft: must be excluded.
        _add_slip(conn, cid, run, eid, "2026-03-01", "2026-03-31",
                  "8888.00", "888.00", "8000.00", status="draft")
        before = _snapshot(conn)
        # No ledger effect: the P60 sums slip rows, it posts nothing.

        r = call_action(ACTIONS["uk-generate-p60"], conn,
                        ns(employee_id=eid, tax_year="2025"))
        assert is_ok(r), r
        assert r["form"] == "P60"
        assert r["tax_year"] == "2025/2026"
        assert r["employee_name"] == "Ada Lovelace"
        assert r["nino_masked"] == "AB****C"
        assert r["total_pay"] == "9000.00"
        assert r["total_tax_deducted"] == "1800.00"
        assert r["total_net_pay"] == "7200.00"
        assert (Decimal(r["total_net_pay"])
                == Decimal(r["total_pay"])
                - Decimal(r["total_tax_deducted"]))
        # Fixtures are unchanged: the action only reads.
        assert _snapshot(conn) == before

    def test_generate_p60_refuses_unknown_employee(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-generate-p60"], conn,
                        ns(employee_id="no-such-employee", tax_year="2025"))
        assert is_error(r), r
        assert r["message"] == "Employee not found: no-such-employee"
        assert _snapshot(conn) == before


# ── uk-generate-p45: aggregate read over the leaver's slips ──────────────────

class TestGenerateP45:
    def test_generate_p45_reports_leaver_totals(self, conn, env):
        cid = env["company_id"]
        eid = _add_employee(conn, cid, "Ada", "Lovelace", "AB123456C",
                            date_of_exit="2026-01-31")
        run = _add_payroll_run(conn, cid, "2026-01-01", "2026-01-31")
        _add_slip(conn, cid, run, eid, "2026-01-01", "2026-01-31",
                  "3000.00", "600.00", "2400.00")
        _add_slip(conn, cid, run, eid, "2026-01-05", "2026-01-31",
                  "2000.00", "400.00", "1600.00")
        before = _snapshot(conn)
        # No ledger effect: the P45 sums slip rows, it posts nothing.

        r = call_action(ACTIONS["uk-generate-p45"], conn,
                        ns(employee_id=eid))
        assert is_ok(r), r
        assert r["form"] == "P45"
        assert r["employee_name"] == "Ada Lovelace"
        assert r["nino_masked"] == "AB****C"
        # KNOWN DEFECT (F2): leaving_date is always "" — production reads
        # the "date_of_leaving" key, which is not a column (the schema has
        # date_of_exit, set to 2026-01-31 above), so the date never
        # surfaces. Expected "2026-01-31", observed "". Pinned as observed.
        assert r["leaving_date"] == ""
        assert r["total_pay_to_date"] == "5000.00"
        assert r["total_tax_to_date"] == "1000.00"
        assert (Decimal(r["total_pay_to_date"])
                == Decimal("3000.00") + Decimal("2000.00"))
        # Fixtures are unchanged: the action only reads.
        assert _snapshot(conn) == before

    def test_generate_p45_refuses_unknown_employee(self, conn, env):
        before = _snapshot(conn)
        r = call_action(ACTIONS["uk-generate-p45"], conn,
                        ns(employee_id="no-such-employee"))
        assert is_error(r), r
        assert r["message"] == "Employee not found: no-such-employee"
        assert _snapshot(conn) == before
