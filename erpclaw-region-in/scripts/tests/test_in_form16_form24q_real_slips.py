"""Form 16 and Form 24Q read the real salary slips.

Form 16 reads the employee's submitted/paid slips across the fiscal year
(April YYYY to March YYYY+1) and reports TDS on Salary per quarter, gross
pay and taxable income. Form 24Q reads the quarter's submitted/paid slips
for the company and reports one deductee row per employee. Both refuse
when the payroll components were never seeded, and both write nothing.

Money is text: exact string comparisons, never float.
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

SETUP_MESSAGE = ("India payroll components are not set up: PF Employee, "
                 "ESI Employee, Professional Tax, TDS on Salary. "
                 "Run india-seed-india-payroll first.")
FORM16_NOTE = ("Amounts are read from the employee's submitted and paid "
               "salary slips for the fiscal year. TDS deposits are not "
               "recorded, so Part A reports TDS deducted.")
FORM24Q_NOTE = ("Form 24Q quarterly TDS on salary return. "
                "Submit via TRACES portal.")

SNAPSHOT_TABLES = (
    "company", "fiscal_year", "employee", "payroll_run", "salary_slip",
    "salary_slip_detail", "salary_component", "audit_log",
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


def _employee(conn, company_id, full_name):
    eid = str(uuid.uuid4())
    first, _, last = full_name.partition(" ")
    _insert(conn, "employee", id=eid, first_name=first,
            last_name=last or first, full_name=full_name,
            date_of_joining="2024-04-01", company_id=company_id)
    return eid


_runs = {}


def _run(conn, company_id, start, end):
    rid = str(uuid.uuid4())
    _insert(conn, "payroll_run", id=rid, period_start=start,
            period_end=end, status="submitted", company_id=company_id)
    return rid


def _run_for(conn, company_id, period_start):
    key = (company_id, period_start[:7])
    if key not in _runs:
        _runs[key] = _run(conn, company_id, period_start[:7] + "-01",
                           period_start[:7] + "-28")
    return _runs[key]


def _slip(conn, company_id, employee_id, start, gross, status="submitted"):
    sid = str(uuid.uuid4())
    _insert(conn, "salary_slip", id=sid,
            payroll_run_id=_run_for(conn, company_id, start),
            employee_id=employee_id, period_start=start,
            period_end=start[:7] + "-28",
            gross_pay=gross, total_deductions="0", net_pay=gross,
            status=status, company_id=company_id)
    return sid


def _detail(conn, slip_id, component_id, amount,
            component_type="deduction"):
    _insert(conn, "salary_slip_detail", id=str(uuid.uuid4()),
            salary_slip_id=slip_id, salary_component_id=component_id,
            component_type=component_type, amount=amount, year_to_date="0")


def _seed_case(conn, cid):
    """Seed components, employees and the task-packet slips. Returns ids."""
    global _runs
    _runs = {}
    r = call_action(ACTIONS["india-seed-india-payroll"], conn,
                    ns(company_id=cid))
    assert is_ok(r)
    comps = _components_by_name(conn)
    loan_id = str(uuid.uuid4())
    _insert(conn, "salary_component", id=loan_id, name="Loan Recovery",
            component_type="deduction", description="Test-only deduction",
            is_statutory=0)
    comps = _components_by_name(conn)
    tds = comps["TDS on Salary"]["id"]
    pf = comps["PF Employee"]["id"]
    asha = _employee(conn, cid, "Asha Rao")
    vikram = _employee(conn, cid, "Vikram Shah")
    s = _slip(conn, cid, asha, "2025-04-05", "30000.00", status="submitted")
    _detail(conn, s, tds, "1000.00")
    _detail(conn, s, pf, "1800.00")
    s = _slip(conn, cid, asha, "2025-10-05", "30000.00", status="paid")
    _detail(conn, s, tds, "1000.00")
    s = _slip(conn, cid, asha, "2026-03-05", "30000.00", status="submitted")
    _detail(conn, s, tds, "1500.00")
    s = _slip(conn, cid, asha, "2025-10-06", "9000.00", status="draft")
    _detail(conn, s, tds, "999.00")
    s = _slip(conn, cid, asha, "2026-01-07", "9000.00", status="cancelled")
    _detail(conn, s, tds, "999.00")
    s = _slip(conn, cid, asha, "2026-04-05", "30000.00", status="submitted")
    _detail(conn, s, tds, "1000.00")
    s = _slip(conn, cid, asha, "2025-03-05", "30000.00", status="submitted")
    _detail(conn, s, tds, "700.00")
    s = _slip(conn, cid, vikram, "2025-10-05", "100000.00",
              status="submitted")
    _detail(conn, s, tds, "8000.00")
    _detail(conn, s, comps["Loan Recovery"]["id"], "500.00")
    s = _slip(conn, cid, vikram, "2025-12-20", "20000.00", status="paid")
    _detail(conn, s, tds, "2000.00")
    other_cid = seed_company(conn, country="IN")
    seed_fiscal_year(conn, other_cid)
    other_emp = _employee(conn, other_cid, "Other Person")
    s = _slip(conn, other_cid, other_emp, "2025-10-05", "50000.00",
              status="submitted")
    _detail(conn, s, tds, "5000.00")
    return {"asha": asha, "vikram": vikram, "other_cid": other_cid}


def test_form16_reads_real_slips(conn, env):
    ids = _seed_case(conn, env["company_id"])
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form16"], conn, ns(
        employee_id=ids["asha"], fiscal_year="2025-26"))
    assert is_ok(r)
    assert r["report"] == "Form 16"
    assert r["fiscal_year"] == "2025-26"
    assert r["employee_name"] == "Asha Rao"
    assert r["part_a"]["quarterly_tds"] == {
        "Q1": "1000.00", "Q2": "0.00", "Q3": "1000.00", "Q4": "1500.00"}
    assert r["part_a"]["total_tds_deducted"] == "3500.00"
    assert "total_tds_deposited" not in r["part_a"]
    assert r["part_b"]["gross_salary"] == "90000.00"
    assert r["part_b"]["standard_deduction"] == "75000"
    assert r["part_b"]["taxable_income"] == "15000.00"
    assert r["part_b"]["tds_deducted"] == "3500.00"
    assert "chapter_vi_a_deductions" not in r["part_b"]
    assert "tax_on_income" not in r["part_b"]
    assert "cess" not in r["part_b"]
    assert "total_tax" not in r["part_b"]
    assert r["slip_count"] == 3
    assert r["note"] == FORM16_NOTE
    assert _snapshot(conn) == before
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form16"], conn, ns(
        employee_id=ids["vikram"], fiscal_year="2025-26"))
    assert is_ok(r)
    assert r["part_a"]["quarterly_tds"] == {
        "Q1": "0.00", "Q2": "0.00", "Q3": "10000.00", "Q4": "0.00"}
    assert r["part_a"]["total_tds_deducted"] == "10000.00"
    assert r["part_b"]["gross_salary"] == "120000.00"
    assert r["part_b"]["taxable_income"] == "45000.00"
    assert r["part_b"]["tds_deducted"] == "10000.00"
    assert r["slip_count"] == 2
    assert _snapshot(conn) == before


def test_form24q_reads_real_slips(conn, env):
    ids = _seed_case(conn, env["company_id"])
    cid = env["company_id"]
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
        company_id=cid, quarter="3", year="2025"))
    assert is_ok(r)
    assert r["report"] == "Form 24Q"
    assert r["quarter"] == "Q3"
    assert r["start_date"] == "2025-10-01"
    assert r["end_date"] == "2025-12-31"
    assert r["deductees"] == [
        {"employee_id": ids["asha"], "employee_name": "Asha Rao",
         "slip_count": 1, "salary_paid": "30000.00",
         "tds_deducted": "1000.00"},
        {"employee_id": ids["vikram"], "employee_name": "Vikram Shah",
         "slip_count": 2, "salary_paid": "120000.00",
         "tds_deducted": "10000.00"},
    ]
    assert r["total_salary_paid"] == "150000.00"
    assert r["total_tds_deducted"] == "11000.00"
    assert r["note"] == FORM24Q_NOTE
    assert _snapshot(conn) == before
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
        company_id=cid, quarter="4", year="2025"))
    assert is_ok(r)
    assert r["start_date"] == "2026-01-01"
    assert r["end_date"] == "2026-03-31"
    assert r["deductees"] == [
        {"employee_id": ids["asha"], "employee_name": "Asha Rao",
         "slip_count": 1, "salary_paid": "30000.00",
         "tds_deducted": "1500.00"},
    ]
    assert r["total_salary_paid"] == "30000.00"
    assert r["total_tds_deducted"] == "1500.00"
    assert _snapshot(conn) == before
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
        company_id=cid, quarter="2", year="2025"))
    assert is_ok(r)
    assert r["start_date"] == "2025-07-01"
    assert r["end_date"] == "2025-09-30"
    assert r["deductees"] == []
    assert r["total_salary_paid"] == "0.00"
    assert r["total_tds_deducted"] == "0.00"
    assert _snapshot(conn) == before


def test_reports_refuse_before_components_are_seeded(conn, env):
    eid = _employee(conn, env["company_id"], "Asha Rao")
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form16"], conn, ns(
        employee_id=eid, fiscal_year="2025-26"))
    assert is_error(r)
    assert r["message"] == SETUP_MESSAGE
    assert _snapshot(conn) == before
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
        company_id=env["company_id"], quarter="3", year="2025"))
    assert is_error(r)
    assert r["message"] == SETUP_MESSAGE
    assert _snapshot(conn) == before


def test_form16_refuses_bad_fiscal_year(conn, env):
    ids = _seed_case(conn, env["company_id"])
    for bad in ("2025-27", "25-26"):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-form16"], conn, ns(
            employee_id=ids["asha"], fiscal_year=bad))
        assert is_error(r)
        assert r["message"] == (
            f"Invalid fiscal year: {bad}. Use YYYY-YY, for example 2025-26.")
        assert _snapshot(conn) == before


def test_form24q_refuses_bad_quarter_and_year(conn, env):
    _seed_case(conn, env["company_id"])
    cid = env["company_id"]
    for bad in ("5", "x"):
        before = _snapshot(conn)
        r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
            company_id=cid, quarter=bad, year="2025"))
        assert is_error(r)
        assert r["message"] == "--quarter must be 1-4"
        assert _snapshot(conn) == before
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
        company_id=cid, quarter="3", year="20x5"))
    assert is_error(r)
    assert r["message"] == "Invalid year: 20x5. Use a four-digit integer year."
    assert _snapshot(conn) == before


def test_form24q_refuses_us_company(conn):
    us_cid = seed_company(conn, country="US")
    seed_fiscal_year(conn, us_cid)
    before = _snapshot(conn)
    r = call_action(ACTIONS["india-generate-form24q"], conn, ns(
        company_id=us_cid, quarter="3", year="2025"))
    assert is_error(r)
    assert "not India (IN)" in r["message"]
    assert _snapshot(conn) == before
