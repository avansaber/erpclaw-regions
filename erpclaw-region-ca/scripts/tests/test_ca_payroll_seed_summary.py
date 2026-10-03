"""Behaviour of ca-seed-ca-payroll and ca-payroll-summary.

The seed writes salary_component rows (four more for a Quebec company) and one
audit_log row per run. The summary reads every active employee plus anyone
holding a submitted or paid slip for the month (so a leaver paid in the
month is reported) and derives CPP/QPP, EI, federal and provincial tax
from the module's own rate tables. Slips carry full ISO dates in period_start,
as the payroll module writes them. Every value is compared as an exact string.
"""
import json
import os
import sys
import uuid

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from ca_helpers import (call_action, is_error, is_ok,  # noqa: E402
                        load_db_query, ns, seed_company)

M = load_db_query()
ACTIONS = M.ACTIONS

CA_COMPONENTS = {
    ("CPP Employee", "deduction",
     "Canada Pension Plan — employee contribution", 1),
    ("CPP Employer", "employer_contribution",
     "Canada Pension Plan — employer contribution", 1),
    ("CPP2 Employee", "deduction",
     "CPP2 enhanced — employee contribution on earnings above first ceiling", 1),
    ("CPP2 Employer", "employer_contribution",
     "CPP2 enhanced — employer contribution on earnings above first ceiling", 1),
    ("EI Employee", "deduction", "Employment Insurance — employee premium", 1),
    ("EI Employer", "employer_contribution",
     "Employment Insurance — employer premium (1.4x employee)", 1),
    ("Federal Income Tax", "deduction", "Federal income tax withheld at source", 1),
    ("Provincial Income Tax", "deduction",
     "Provincial income tax withheld at source", 1),
}

QC_EXTRA = {
    ("QPP Employee", "deduction",
     "Quebec Pension Plan — employee contribution (replaces CPP in QC)", 1),
    ("QPP Employer", "employer_contribution",
     "Quebec Pension Plan — employer contribution", 1),
    ("QPIP Employee", "deduction",
     "Quebec Parental Insurance Plan — employee premium", 1),
    ("QPIP Employer", "employer_contribution",
     "Quebec Parental Insurance Plan — employer premium", 1),
}


def _set_province(conn, company_id, province):
    conn.execute(
        "INSERT INTO regional_settings (id, company_id, key, value) "
        "VALUES (?, ?, 'province', ?)",
        (str(uuid.uuid4()), company_id, province))
    conn.commit()


def _components(conn):
    return conn.execute(
        "SELECT name, component_type, description, is_statutory, "
        "is_tax_applicable, is_pre_tax, gl_account_id FROM salary_component"
    ).fetchall()


def _audit_rows(conn):
    return conn.execute(
        "SELECT skill, entity_type, entity_id, new_values FROM audit_log "
        "WHERE action = 'ca-seed-ca-payroll' ORDER BY timestamp, rowid"
    ).fetchall()


def _employee(conn, company_id, full_name, status="active"):
    eid = str(uuid.uuid4())
    first, last = full_name.split(" ", 1)
    conn.execute(
        "INSERT INTO employee (id, first_name, last_name, full_name, "
        "date_of_joining, status, company_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eid, first, last, full_name, "2025-01-06", status, company_id))
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


def _slip(conn, company_id, run_id, employee_id, start, end, gross,
          status="submitted"):
    sid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO salary_slip (id, payroll_run_id, employee_id, "
        "period_start, period_end, gross_pay, total_deductions, net_pay, "
        "status, company_id) VALUES (?, ?, ?, ?, ?, ?, '0', ?, ?, ?)",
        (sid, run_id, employee_id, start, end, gross, gross, status,
         company_id))
    conn.commit()
    return sid


# ── ca-seed-ca-payroll ───────────────────────────────────────────────────────

def test_seed_ca_payroll_creates_the_eight_components(conn, env):
    cid = env["company_id"]
    _set_province(conn, cid, "ON")
    r = call_action(ACTIONS["ca-seed-ca-payroll"], conn, ns(company_id=cid))
    assert is_ok(r)
    assert (r["company_id"], r["province"], r["components_created"]) == (
        cid, "ON", 8)

    rows = _components(conn)
    assert len(rows) == 8
    assert {(x["name"], x["component_type"], x["description"],
             x["is_statutory"]) for x in rows} == CA_COMPONENTS
    assert {x["gl_account_id"] for x in rows} == {None}
    assert {x["is_tax_applicable"] for x in rows} == {1}
    assert {x["is_pre_tax"] for x in rows} == {0}

    audits = _audit_rows(conn)
    assert len(audits) == 1
    assert (audits[0]["skill"], audits[0]["entity_type"],
            audits[0]["entity_id"]) == ("erpclaw-region-ca", "company", cid)
    assert json.loads(audits[0]["new_values"]) == {"components_created": 8}


def test_seed_ca_payroll_quebec_adds_qpp_and_qpip_and_is_idempotent(conn, env):
    cid = env["company_id"]
    _set_province(conn, cid, "QC")
    first = call_action(ACTIONS["ca-seed-ca-payroll"], conn, ns(company_id=cid))
    assert is_ok(first)
    assert (first["province"], first["components_created"]) == ("QC", 12)
    before = sorted(tuple(x) for x in conn.execute(
        "SELECT id, name, component_type, description, is_statutory "
        "FROM salary_component").fetchall())
    assert {(x[1], x[2], x[3], x[4]) for x in before} == CA_COMPONENTS | QC_EXTRA

    second = call_action(ACTIONS["ca-seed-ca-payroll"], conn, ns(company_id=cid))
    assert is_ok(second)
    assert second["components_created"] == 0
    after = sorted(tuple(x) for x in conn.execute(
        "SELECT id, name, component_type, description, is_statutory "
        "FROM salary_component").fetchall())
    assert len(after) == 12
    assert after == before
    assert [json.loads(a["new_values"]) for a in _audit_rows(conn)] == [
        {"components_created": 12}, {"components_created": 0}]


def test_seed_ca_payroll_refuses_a_non_canadian_company(conn, env):
    us = seed_company(conn, name="US Co", abbr="US", country="US")
    r = call_action(ACTIONS["ca-seed-ca-payroll"], conn, ns(company_id=us))
    assert is_error(r)
    assert r["message"] == ("This action is for Canadian companies only. "
                            "Company country must be CA.")
    assert conn.execute("SELECT COUNT(*) FROM salary_component").fetchone()[0] == 0
    assert _audit_rows(conn) == []


# ── ca-payroll-summary ───────────────────────────────────────────────────────

def _payroll(conn, env):
    """March 2026 payroll for an Ontario company and a Quebec company."""
    cid = env["company_id"]
    _set_province(conn, cid, "ON")
    erin = _employee(conn, cid, "Erin Evans")
    frank = _employee(conn, cid, "Frank Fox")
    george = _employee(conn, cid, "George Gray", status="left")
    march = _run(conn, cid, "2026-03-01", "2026-03-31")
    _slip(conn, cid, march, erin, "2026-03-01", "2026-03-31", "5000.00")
    # Frank: a draft March slip and a submitted April slip, nothing for March.
    _slip(conn, cid, march, frank, "2026-03-01", "2026-03-31", "9000.00",
          status="draft")
    april = _run(conn, cid, "2026-04-01", "2026-04-30")
    _slip(conn, cid, april, frank, "2026-04-01", "2026-04-30", "6000.00")
    # George has left but his submitted March slip is still reported.
    _slip(conn, cid, march, george, "2026-03-01", "2026-03-31", "7000.00")

    qc = seed_company(conn, name="Quebec Co", abbr="QC", country="CA")
    _set_province(conn, qc, "QC")
    hana = _employee(conn, qc, "Hana Hall")
    qc_run = _run(conn, qc, "2026-03-01", "2026-03-31")
    _slip(conn, qc, qc_run, hana, "2026-03-01", "2026-03-31", "4000.00")
    return {"erin": erin, "frank": frank, "george": george,
            "qc": qc, "hana": hana}


def test_ca_payroll_summary_ontario_month_totals(conn, env):
    ids = _payroll(conn, env)
    audit_before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    r = call_action(ACTIONS["ca-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="3", year="2026"))
    assert is_ok(r)
    assert (r["report"], r["period"], r["employee_count"]) == (
        "Canada Payroll Summary", "2026-03", 3)
    by_id = {e["employee_id"]: e for e in r["employees"]}
    assert set(by_id) == {ids["erin"], ids["frank"], ids["george"]}

    erin = by_id[ids["erin"]]
    assert (erin["employee_name"], erin["province"], erin["gross"]) == (
        "Erin Evans", "ON", "5000.00")
    # Annual 60000.00: CPP (60000 - 3500) x 5.95% = 3361.75 / 12;
    # EI 60000 x 1.63% = 978.00 / 12; federal slabs 58523 x 14% = 8193.22
    # plus 1477 x 20.5% = 302.79 for a gross of 8496.01, less the credit
    # 16452 x 14% (lowest bracket rate) = 2303.28, net 6192.73 / 12;
    # Ontario tax per the module's bracket table, divided by 12.
    assert erin["deductions"] == {
        "cpp": "280.15", "ei": "81.50",
        "federal_tax": "516.06", "provincial_tax": "218.71"}
    assert (erin["total_deductions"], erin["net_pay"]) == ("1096.42", "3903.58")

    frank = by_id[ids["frank"]]
    assert (frank["gross"], frank["deductions"], frank["net_pay"]) == (
        "0.00", {}, "0.00")
    assert frank["note"] == "No salary slip found for this period"

    # George left but was paid in March: annual 84000.00, CPP capped at
    # 4230.45 / 12 = 352.54; EI capped at 1123.07 / 12 = 93.59; federal
    # slabs 58523 x 14% = 8193.22 plus 25477 x 20.5% = 5222.79, gross
    # 13416.01 less the credit 2303.28 = 11112.73 / 12 = 926.06; Ontario
    # 53891 x 5.05% = 2721.50 plus 30109 x 9.15% = 2754.97, gross 5476.47
    # less 655.94 = 4820.53 (below the 5818 surtax threshold) / 12 = 401.71.
    george = by_id[ids["george"]]
    assert (george["employee_name"], george["province"],
            george["gross"]) == ("George Gray", "ON", "7000.00")
    assert george["deductions"] == {
        "cpp": "352.54", "ei": "93.59",
        "federal_tax": "926.06", "provincial_tax": "401.71"}
    assert (george["total_deductions"], george["net_pay"]) == (
        "1773.90", "5226.10")

    assert r["totals"] == {
        "total_gross": "12000.00",
        "total_cpp": "632.69",
        "total_ei": "175.09",
        "total_federal_tax": "1442.12",
        "total_provincial_tax": "620.42",
        "total_deductions": "2870.32",
        "total_net_pay": "9129.68",
        "total_employer_cpp": "632.69",
        "total_employer_ei": "245.13",
    }
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == audit_before


def test_ca_payroll_summary_quebec_company_is_scoped(conn, env):
    ids = _payroll(conn, env)
    r = call_action(ACTIONS["ca-payroll-summary"], conn, ns(
        company_id=ids["qc"], month="3", year="2026"))
    assert is_ok(r)
    assert r["employee_count"] == 1
    hana = r["employees"][0]
    assert (hana["employee_id"], hana["province"], hana["gross"]) == (
        ids["hana"], "QC", "4000.00")
    # Annual 48000.00: QPP (48000 - 3500) x 6.30% = 2803.50 / 12 = 233.63;
    # Quebec EI 48000 x 1.30% = 624.00 / 12 = 52.00; federal 48000 x 14% =
    # 6720.00 less the credit 16452 x 14% (lowest bracket rate) = 2303.28,
    # net 4416.72, Quebec abatement 4416.72 x 16.5% = 728.76,
    # (4416.72 - 728.76) / 12 = 3687.96 / 12 = 307.33.
    assert hana["deductions"] == {
        "qpp": "233.63", "ei": "52.00",
        "federal_tax": "307.33", "provincial_tax": "338.89"}
    assert (hana["total_deductions"], hana["net_pay"]) == ("931.85", "3068.15")
    assert r["totals"] == {
        "total_gross": "4000.00",
        "total_cpp": "233.63",
        "total_ei": "52.00",
        "total_federal_tax": "307.33",
        "total_provincial_tax": "338.89",
        "total_deductions": "931.85",
        "total_net_pay": "3068.15",
        "total_employer_cpp": "233.63",
        "total_employer_ei": "72.80",
    }

    # April for the Ontario company: only Frank's slip.
    r = call_action(ACTIONS["ca-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="4", year="2026"))
    assert is_ok(r)
    assert r["totals"]["total_gross"] == "6000.00"
    assert {e["employee_id"]: e["gross"] for e in r["employees"]} == {
        ids["erin"]: "0.00", ids["frank"]: "6000.00"}


def test_ca_payroll_summary_refusals(conn, env):
    _payroll(conn, env)
    r = call_action(ACTIONS["ca-payroll-summary"], conn, ns(
        company_id=env["company_id"], year="2026"))
    assert is_error(r)
    assert r["message"] == "--month and --year are required"

    r = call_action(ACTIONS["ca-payroll-summary"], conn, ns(
        company_id=env["company_id"], month="3"))
    assert is_error(r)
    assert r["message"] == "--month and --year are required"

    us = seed_company(conn, name="US Co", abbr="US", country="US")
    r = call_action(ACTIONS["ca-payroll-summary"], conn, ns(
        company_id=us, month="3", year="2026"))
    assert is_error(r)
    assert r["message"] == ("This action is for Canadian companies only. "
                            "Company country must be CA.")
