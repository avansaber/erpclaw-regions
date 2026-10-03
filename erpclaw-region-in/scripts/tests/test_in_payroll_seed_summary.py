"""India payroll seed writes components; payroll summary reads real slips.

The seed creates the six statutory components and is idempotent. The
summary reads the month's submitted/paid salary_slip rows and their
salary_slip_detail deduction lines, refusing when the components were
never set up. Money is text: exact string comparisons, never float.
"""
import json
import os
import sys
import uuid

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from in_helpers import (
    call_action, ns, is_ok, is_error, load_db_query,
    seed_company, seed_fiscal_year,
)
from erpclaw_lib.query import Q, Table, P, insert_row
from erpclaw_lib.response import row_to_dict

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

EXPECTED_COMPONENTS = [
    ("PF Employee", "deduction",
     "Provident Fund - employee contribution (12% of PF wage)", 1),
    ("PF Employer", "employer_contribution",
     "Provident Fund - employer contribution (EPF + EPS, 12% of PF wage)", 1),
    ("ESI Employee", "deduction",
     "Employees' State Insurance - employee contribution (0.75%)", 1),
    ("ESI Employer", "employer_contribution",
     "Employees' State Insurance - employer contribution (3.25%)", 1),
    ("Professional Tax", "deduction",
     "Professional tax - state slabs", 1),
    ("TDS on Salary", "deduction",
     "Income tax deducted at source on salary (Section 192)", 1),
]
EXPECTED_NAMES = [c[0] for c in EXPECTED_COMPONENTS]
SUGGESTION = ("Use compute-pf, compute-esi, compute-professional-tax, "
              "compute-tds-on-salary for calculations.")
SETUP_MESSAGE = ("India payroll components are not set up: PF Employee, "
                 "ESI Employee, Professional Tax, TDS on Salary. "
                 "Run india-seed-india-payroll first.")
EMPLOYER_BASIS = ("Employer PF equals the employee PF on each slip; employer "
                  "ESI is 3.25% of slip gross, rounded to the rupee, on slips "
                  "that withheld employee ESI. Salary slips do not store "
                  "employer contributions.")

SNAPSHOT_TABLES = (
    "employee", "payroll_run", "salary_slip", "salary_slip_detail",
    "salary_component", "audit_log",
)


def _dump_table(conn, table):
    t = Table(table)
    rows = conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()
    return sorted(
        json.dumps(row_to_dict(r), sort_keys=True, default=str) for r in rows
    )


def _snapshot(conn):
    return {name: _dump_table(conn, name) for name in SNAPSHOT_TABLES}


def _insert(conn, table, **values):
    cols = list(values)
    sql, _ = insert_row(table, {col: P() for col in cols})
    conn.execute(sql, tuple(values[col] for col in cols))
    conn.commit()
    return values.get("id")


def _components_by_name(conn):
    sc = Table("salary_component")
    rows = conn.execute(Q.from_(sc).select(sc.star).get_sql()).fetchall()
    return {row_to_dict(r)["name"]: row_to_dict(r) for r in rows}


def _audit_new_values(conn, action):
    al = Table("audit_log")
    q = (Q.from_(al).select(al.new_values)
         .where(al.action == P()).orderby(al.timestamp, al.rowid))
    return [json.loads(r["new_values"])
            for r in conn.execute(q.get_sql(), (action,)).fetchall()]


def _employee(conn, company_id, full_name):
    eid = str(uuid.uuid4())
    first, _, last = full_name.partition(" ")
    _insert(conn, "employee", id=eid, first_name=first,
            last_name=last or first, full_name=full_name,
            date_of_joining="2024-04-01", company_id=company_id)
    return eid


def _run(conn, company_id, start, end):
    rid = str(uuid.uuid4())
    _insert(conn, "payroll_run", id=rid, period_start=start,
            period_end=end, status="submitted", company_id=company_id)
    return rid


def _slip(conn, company_id, run_id, employee_id, start, end, gross,
          status="submitted"):
    sid = str(uuid.uuid4())
    _insert(conn, "salary_slip", id=sid, payroll_run_id=run_id,
            employee_id=employee_id, period_start=start, period_end=end,
            gross_pay=gross, total_deductions="0", net_pay=gross,
            status=status, company_id=company_id)
    return sid


def _detail(conn, slip_id, component_id, amount,
            component_type="deduction"):
    _insert(conn, "salary_slip_detail", id=str(uuid.uuid4()),
            salary_slip_id=slip_id, salary_component_id=component_id,
            component_type=component_type, amount=amount, year_to_date="0")


def _seed_march_2026(conn, cid):
    """March 2026 payroll per the task packet. Returns ids dict."""
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=cid))
    assert is_ok(r)
    comps = _components_by_name(conn)
    loan_id = str(uuid.uuid4())
    _insert(conn, "salary_component", id=loan_id, name="Loan Recovery",
            component_type="deduction", description="Test-only deduction",
            is_statutory=0)
    comps = _components_by_name(conn)
    asha = _employee(conn, cid, "Asha Rao")
    vikram = _employee(conn, cid, "Vikram Shah")
    run_mar = _run(conn, cid, "2026-03-01", "2026-03-31")
    run_apr = _run(conn, cid, "2026-04-01", "2026-04-30")
    asha_slip = _slip(conn, cid, run_mar, asha, "2026-03-05", "2026-03-31",
                      "15500.00", status="submitted")
    _detail(conn, asha_slip, comps["PF Employee"]["id"], "1200.00")
    _detail(conn, asha_slip, comps["ESI Employee"]["id"], "116.00")
    _detail(conn, asha_slip, comps["Professional Tax"]["id"], "200.00")
    _detail(conn, asha_slip, comps["TDS on Salary"]["id"], "500.00")
    _detail(conn, asha_slip, comps["Loan Recovery"]["id"], "1000.00")
    vik_slip = _slip(conn, cid, run_mar, vikram, "2026-03-05", "2026-03-31",
                     "40000.00", status="submitted")
    _detail(conn, vik_slip, comps["PF Employee"]["id"], "1800.00")
    _detail(conn, vik_slip, comps["Professional Tax"]["id"], "200.00")
    _detail(conn, vik_slip, comps["TDS on Salary"]["id"], "2500.00")
    vik_bonus = _slip(conn, cid, run_mar, vikram, "2026-03-20", "2026-03-31",
                      "10000.00", status="paid")
    _detail(conn, vik_bonus, comps["TDS on Salary"]["id"], "1000.00")
    draft = _slip(conn, cid, run_mar, vikram, "2026-03-06", "2026-03-31",
                  "9000.00", status="draft")
    _detail(conn, draft, comps["PF Employee"]["id"], "999.00")
    cancelled = _slip(conn, cid, run_mar, asha, "2026-03-07", "2026-03-31",
                      "9000.00", status="cancelled")
    _detail(conn, cancelled, comps["PF Employee"]["id"], "999.00")
    apr = _slip(conn, cid, run_apr, asha, "2026-04-05", "2026-04-30",
                "15500.00", status="submitted")
    _detail(conn, apr, comps["PF Employee"]["id"], "1200.00")
    other_cid = seed_company(conn, country="IN")
    seed_fiscal_year(conn, other_cid)
    other_run = _run(conn, other_cid, "2026-03-01", "2026-03-31")
    other_emp = _employee(conn, other_cid, "Other Person")
    other_slip = _slip(conn, other_cid, other_run, other_emp, "2026-03-05",
                       "2026-03-31", "20000.00", status="submitted")
    _detail(conn, other_slip, comps["PF Employee"]["id"], "1800.00")
    return {"asha": asha, "vikram": vikram, "other_cid": other_cid}


def test_seed_creates_six_components(conn, env):
    cid = env["company_id"]
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=cid))
    assert is_ok(r)
    assert r["message"] == "India payroll components seeded"
    assert r["company_id"] == cid
    assert r["components_created"] == 6
    assert r["components"] == EXPECTED_NAMES
    assert r["suggestion"] == SUGGESTION
    rows = conn.execute(
        "SELECT name, component_type, description, is_statutory, "
        "gl_account_id FROM salary_component").fetchall()
    got = {(row["name"], row["component_type"], row["description"],
            row["is_statutory"]) for row in rows}
    assert got == set(EXPECTED_COMPONENTS)
    for row in rows:
        assert row["gl_account_id"] is None
    audits = conn.execute(
        "SELECT skill, entity_type, entity_id, new_values FROM audit_log "
        "WHERE action = 'india-seed-india-payroll'").fetchall()
    assert len(audits) == 1
    assert audits[0]["skill"] == "erpclaw-region-in"
    assert audits[0]["entity_type"] == "company"
    assert audits[0]["entity_id"] == cid
    assert json.loads(audits[0]["new_values"]) == {"components_created": 6}


def test_seed_is_idempotent(conn, env):
    cid = env["company_id"]
    r1 = call_action(ACTIONS["india-seed-india-payroll"], conn,
                     ns(company_id=cid))
    assert is_ok(r1)
    assert r1["components_created"] == 6
    before = sorted(tuple(x) for x in conn.execute(
        "SELECT id, name, component_type, description, is_statutory "
        "FROM salary_component").fetchall())
    r2 = call_action(ACTIONS["india-seed-india-payroll"], conn,
                     ns(company_id=cid))
    assert is_ok(r2)
    assert r2["components_created"] == 0
    after = sorted(tuple(x) for x in conn.execute(
        "SELECT id, name, component_type, description, is_statutory "
        "FROM salary_component").fetchall())
    assert after == before
    assert _audit_new_values(conn, "india-seed-india-payroll") == [
        {"components_created": 6}, {"components_created": 0}]


def test_seed_leaves_pre_existing_component_untouched(conn, env):
    cid = env["company_id"]
    pre_id = str(uuid.uuid4())
    _insert(conn, "salary_component", id=pre_id, name="Professional Tax",
            component_type="deduction", description="Pre-existing description",
            is_statutory=0)
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=cid))
    assert is_ok(r)
    assert r["components_created"] == 5
    row = conn.execute(
        "SELECT id, description, component_type, is_statutory "
        "FROM salary_component WHERE name = 'Professional Tax'").fetchone()
    assert row["id"] == pre_id
    assert row["description"] == "Pre-existing description"


def test_seed_refuses_us_company(conn):
    us_cid = seed_company(conn, country="US")
    seed_fiscal_year(conn, us_cid)
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=us_cid))
    assert is_error(r)
    assert "not India (IN)" in r["message"]
    assert _snapshot(conn) == before
    assert conn.execute(
        "SELECT COUNT(*) FROM salary_component").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = "
        "'india-seed-india-payroll'").fetchone()[0] == 0


def test_summary_march_2026_reads_real_slips(conn, env):
    cid = env["company_id"]
    ids = _seed_march_2026(conn, cid)
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=cid, month="3", year="2026"))
    assert is_ok(r)
    assert r["report"] == "India Payroll Summary"
    assert r["period"] == "2026-03"
    assert r["employee_count"] == 2
    assert r["slip_count"] == 3
    assert r["employer_basis"] == EMPLOYER_BASIS
    assert "note" not in r
    by_id = {e["employee_id"]: e for e in r["employees"]}
    assert set(by_id) == {ids["asha"], ids["vikram"]}
    asha = by_id[ids["asha"]]
    assert asha["employee_name"] == "Asha Rao"
    assert asha["slip_count"] == 1
    assert asha["gross_pay"] == "15500.00"
    assert asha["pf_employee"] == "1200.00"
    assert asha["pf_employer"] == "1200.00"
    assert asha["esi_employee"] == "116.00"
    assert asha["esi_employer"] == "504.00"
    assert asha["professional_tax"] == "200.00"
    assert asha["tds"] == "500.00"
    vikram = by_id[ids["vikram"]]
    assert vikram["employee_name"] == "Vikram Shah"
    assert vikram["slip_count"] == 2
    assert vikram["gross_pay"] == "50000.00"
    assert vikram["pf_employee"] == "1800.00"
    assert vikram["pf_employer"] == "1800.00"
    assert vikram["esi_employee"] == "0.00"
    assert vikram["esi_employer"] == "0.00"
    assert vikram["professional_tax"] == "200.00"
    assert vikram["tds"] == "3500.00"
    assert r["employees"] == sorted(
        r["employees"], key=lambda e: (e["employee_name"], e["employee_id"]))
    assert r["totals"] == {
        "total_pf_employee": "3000.00",
        "total_pf_employer": "3000.00",
        "total_esi_employee": "116.00",
        "total_esi_employer": "504.00",
        "total_professional_tax": "400.00",
        "total_tds": "4000.00",
    }
    assert _snapshot(conn) == before
    before_apr = _snapshot(conn)
    ra = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=cid, month="4", year="2026"))
    assert is_ok(ra)
    assert ra["period"] == "2026-04"
    assert ra["employee_count"] == 1
    assert ra["slip_count"] == 1
    assert ra["totals"]["total_pf_employee"] == "1200.00"
    assert _snapshot(conn) == before_apr


def test_summary_empty_month_returns_read_zeros(conn, env):
    cid = env["company_id"]
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=cid))
    assert is_ok(r)
    before = _snapshot(conn)
    r2 = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=cid, month="5", year="2026"))
    assert is_ok(r2)
    assert r2["employees"] == []
    assert r2["employee_count"] == 0
    assert r2["slip_count"] == 0
    assert r2["totals"] == {
        "total_pf_employee": "0.00",
        "total_pf_employer": "0.00",
        "total_esi_employee": "0.00",
        "total_esi_employer": "0.00",
        "total_professional_tax": "0.00",
        "total_tds": "0.00",
    }
    assert _snapshot(conn) == before


def test_summary_refuses_before_components_are_seeded(conn, env):
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="3", year="2026"))
    assert is_error(r)
    assert r["message"] == SETUP_MESSAGE
    assert _snapshot(conn) == before


def test_summary_refuses_when_only_professional_tax_present(conn, env):
    _insert(conn, "salary_component", id=str(uuid.uuid4()),
            name="Professional Tax", component_type="deduction",
            description="Professional tax - state slabs", is_statutory=1)
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="3", year="2026"))
    assert is_error(r)
    assert r["message"] == (
        "India payroll components are not set up: PF Employee, ESI Employee, "
        "TDS on Salary. Run india-seed-india-payroll first.")
    assert _snapshot(conn) == before


def test_summary_refuses_invalid_month(conn, env):
    cid = env["company_id"]
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=cid))
    assert is_ok(r)
    before = _snapshot(conn)
    r2 = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=cid, month="13", year="2026"))
    assert is_error(r2)
    assert r2["message"] == "Invalid month: 13. Use an integer 1-12."
    assert _snapshot(conn) == before


def test_summary_refuses_invalid_year(conn, env):
    cid = env["company_id"]
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=cid))
    assert is_ok(r)
    before = _snapshot(conn)
    r2 = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=cid, month="3", year="20%6"))
    assert is_error(r2)
    assert r2["message"] == "Invalid year: 20%6. Use a four-digit integer year."
    assert _snapshot(conn) == before


def test_summary_refuses_us_company(conn):
    us_cid = seed_company(conn, country="US")
    seed_fiscal_year(conn, us_cid)
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-payroll-summary"], conn, ns(
        company_id=us_cid, month="3", year="2026"))
    assert is_error(r)
    assert "not India (IN)" in r["message"]
    assert _snapshot(conn) == before
