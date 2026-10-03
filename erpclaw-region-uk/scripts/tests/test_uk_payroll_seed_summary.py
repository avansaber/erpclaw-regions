"""Behaviour of uk-seed-uk-payroll and uk-payroll-summary.

The seed writes salary_component rows and one audit_log row per run; the
summary reads submitted salary slips for one company and one calendar month.
Every value is read back from the database or compared as an exact string.
"""
import json
import os
import sys
import uuid

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from uk_helpers import (call_action, is_error, is_ok,  # noqa: E402
                        load_db_query, ns, seed_company)

M = load_db_query()
ACTIONS = M.ACTIONS

UK_COMPONENTS = {
    ("PAYE Income Tax", "deduction", "Pay As You Earn income tax", 1),
    ("Employee NI", "deduction", "National Insurance - employee contribution", 1),
    ("Employer NI", "employer_contribution",
     "National Insurance - employer contribution", 1),
    ("Student Loan", "deduction", "Student loan repayment", 0),
    ("Employee Pension", "deduction",
     "Employee pension contribution (NEST/auto-enrollment)", 1),
    ("Employer Pension", "employer_contribution",
     "Employer pension contribution (NEST/auto-enrollment)", 1),
    ("Basic Salary", "earning", "Basic monthly/weekly salary", 0),
    ("Overtime", "earning", "Overtime payments", 0),
}


def _components(conn):
    rows = conn.execute(
        "SELECT name, component_type, description, is_statutory, "
        "is_tax_applicable, is_pre_tax, gl_account_id FROM salary_component"
    ).fetchall()
    return rows


def _audit_rows(conn, action):
    return conn.execute(
        "SELECT skill, entity_type, entity_id, new_values FROM audit_log "
        "WHERE action = ? ORDER BY timestamp, rowid", (action,)
    ).fetchall()


def _employee(conn, company_id, full_name):
    eid = str(uuid.uuid4())
    first, last = full_name.split(" ", 1)
    conn.execute(
        "INSERT INTO employee (id, first_name, last_name, full_name, "
        "date_of_joining, company_id) VALUES (?, ?, ?, ?, ?, ?)",
        (eid, first, last, full_name, "2025-01-06", company_id))
    conn.commit()
    return eid


def _run(conn, company_id, start, end):
    rid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO payroll_run (id, period_start, period_end, status, "
        "company_id) VALUES (?, ?, ?, 'submitted', ?)",
        (rid, start, end, company_id))
    conn.commit()
    return rid


def _slip(conn, company_id, run_id, employee_id, start, end,
          gross, deductions, net, status="submitted"):
    sid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO salary_slip (id, payroll_run_id, employee_id, "
        "period_start, period_end, gross_pay, total_deductions, net_pay, "
        "status, company_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, run_id, employee_id, start, end, gross, deductions, net,
         status, company_id))
    conn.commit()
    return sid


# ── uk-seed-uk-payroll ───────────────────────────────────────────────────────

def test_seed_uk_payroll_creates_the_eight_components(conn, env):
    cid = env["company_id"]
    r = call_action(ACTIONS["uk-seed-uk-payroll"], conn, ns(company_id=cid))
    assert is_ok(r)
    assert r["components_created"] == 8
    assert r["company_id"] == cid

    rows = _components(conn)
    assert len(rows) == 8
    assert {(x["name"], x["component_type"], x["description"],
             x["is_statutory"]) for x in rows} == UK_COMPONENTS
    # No GL account is mapped and the schema defaults stand.
    assert {x["gl_account_id"] for x in rows} == {None}
    assert {x["is_tax_applicable"] for x in rows} == {1}
    assert {x["is_pre_tax"] for x in rows} == {0}

    audits = _audit_rows(conn, "uk-seed-uk-payroll")
    assert len(audits) == 1
    assert (audits[0]["skill"], audits[0]["entity_type"],
            audits[0]["entity_id"]) == ("erpclaw-region-uk", "company", cid)
    assert json.loads(audits[0]["new_values"]) == {"components": 8}


def test_seed_uk_payroll_second_run_creates_nothing(conn, env):
    cid = env["company_id"]
    first = call_action(ACTIONS["uk-seed-uk-payroll"], conn, ns(company_id=cid))
    before = sorted(tuple(x) for x in conn.execute(
        "SELECT id, name, component_type, description, is_statutory "
        "FROM salary_component").fetchall())
    second = call_action(ACTIONS["uk-seed-uk-payroll"], conn, ns(company_id=cid))
    after = sorted(tuple(x) for x in conn.execute(
        "SELECT id, name, component_type, description, is_statutory "
        "FROM salary_component").fetchall())
    assert (first["components_created"], second["components_created"]) == (8, 0)
    assert len(after) == 8
    assert after == before
    audits = _audit_rows(conn, "uk-seed-uk-payroll")
    assert [json.loads(a["new_values"]) for a in audits] == [
        {"components": 8}, {"components": 0}]


def test_seed_uk_payroll_refuses_a_non_uk_company(conn, env):
    us = seed_company(conn, name="US Co", abbr="US", country="US")
    r = call_action(ACTIONS["uk-seed-uk-payroll"], conn, ns(company_id=us))
    assert is_error(r)
    assert r["message"] == ("This action is for UK companies only. "
                            "Company country must be GB.")
    assert conn.execute("SELECT COUNT(*) FROM salary_component").fetchone()[0] == 0
    assert _audit_rows(conn, "uk-seed-uk-payroll") == []

    r = call_action(ACTIONS["uk-seed-uk-payroll"], conn,
                    ns(company_id="no-such-company"))
    assert is_error(r)
    assert r["message"] == "Company not found: no-such-company"
    assert conn.execute("SELECT COUNT(*) FROM salary_component").fetchone()[0] == 0


# ── uk-payroll-summary ───────────────────────────────────────────────────────

def _payroll(conn, env):
    """March 2026 payroll for the env company plus rows that must not count."""
    cid = env["company_id"]
    alice = _employee(conn, cid, "Alice Archer")
    bob = _employee(conn, cid, "Bob Baker")
    carol = _employee(conn, cid, "Carol Clark")
    march = _run(conn, cid, "2026-03-01", "2026-03-31")
    _slip(conn, cid, march, alice, "2026-03-01", "2026-03-31",
          "3000.00", "612.40", "2387.60")
    _slip(conn, cid, march, bob, "2026-03-01", "2026-03-31",
          "2500.50", "480.25", "2020.25")
    # Not submitted: draft and cancelled slips in the same month.
    _slip(conn, cid, march, carol, "2026-03-01", "2026-03-31",
          "9999.00", "1000.00", "8999.00", status="draft")
    _slip(conn, cid, march, carol, "2026-03-01", "2026-03-31",
          "7777.00", "700.00", "7077.00", status="cancelled")
    # Submitted, but in April.
    april = _run(conn, cid, "2026-04-01", "2026-04-30")
    _slip(conn, cid, april, alice, "2026-04-01", "2026-04-30",
          "4000.00", "800.00", "3200.00")
    # Submitted, March, but another UK company.
    other = seed_company(conn, name="Other UK", abbr="OU", country="GB")
    dave = _employee(conn, other, "Dave Dunn")
    other_run = _run(conn, other, "2026-03-01", "2026-03-31")
    _slip(conn, other, other_run, dave, "2026-03-01", "2026-03-31",
          "5000.00", "1000.00", "4000.00")
    return other


def test_uk_payroll_summary_totals_submitted_slips_for_the_month(conn, env):
    _payroll(conn, env)
    audit_before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="3", year="2026"))
    assert is_ok(r)
    assert r["report"] == "UK Payroll Summary"
    assert r["period"] == "2026-03"
    assert r["employee_count"] == 2
    assert sorted((e["employee_name"], e["gross_pay"], e["deductions"],
                   e["net_pay"]) for e in r["employees"]) == [
        ("Alice Archer", "3000.00", "612.40", "2387.60"),
        ("Bob Baker", "2500.50", "480.25", "2020.25"),
    ]
    assert (r["total_gross"], r["total_deductions"], r["total_net"]) == (
        "5500.50", "1092.65", "4407.85")
    # Read-only: nothing written.
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == audit_before


def test_uk_payroll_summary_is_scoped_to_company_and_month(conn, env):
    other = _payroll(conn, env)
    r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
        company_id=other, month="3", year="2026"))
    assert is_ok(r)
    assert [(e["employee_name"], e["gross_pay"]) for e in r["employees"]] == [
        ("Dave Dunn", "5000.00")]
    assert (r["total_gross"], r["total_deductions"], r["total_net"]) == (
        "5000.00", "1000.00", "4000.00")

    r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="4", year="2026"))
    assert is_ok(r)
    assert r["employee_count"] == 1
    assert (r["total_gross"], r["total_deductions"], r["total_net"]) == (
        "4000.00", "800.00", "3200.00")

    r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="5", year="2026"))
    assert is_ok(r)
    assert (r["employee_count"], r["employees"]) == (0, [])
    assert (r["total_gross"], r["total_deductions"], r["total_net"]) == (
        "0.00", "0.00", "0.00")


def test_uk_payroll_summary_refusals(conn, env):
    _payroll(conn, env)
    r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
        company_id=env["company_id"], year="2026"))
    assert is_error(r)
    assert r["message"] == "--month and --year are required."

    r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="3"))
    assert is_error(r)
    assert r["message"] == "--month and --year are required."

    us = seed_company(conn, name="US Co", abbr="US", country="US")
    r = call_action(ACTIONS["uk-payroll-summary"], conn, ns(
        company_id=us, month="3", year="2026"))
    assert is_error(r)
    assert r["message"] == ("This action is for UK companies only. "
                            "Company country must be GB.")
