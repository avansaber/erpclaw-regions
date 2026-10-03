"""UK actions never pick an arbitrary company (m788a).

When no company is given: one company -> use it; zero or several -> refuse.
P60/P45 resolve the company the same way and sum only that company's slips.
"""
import json
import os
import sys
import uuid

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from uk_helpers import (  # noqa: E402
    call_action, get_conn, init_all_tables, is_ok, load_db_query, ns,
)
from erpclaw_lib.query import P, Q, Table, insert_row  # noqa: E402

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

ACME_NAME = "Acme Widgets"
ACME_ABBR = "ACME"
WAYNE_NAME = "Wayne Enterprises"
WAYNE_ABBR = "WAYNE"

MULTI_ERROR = "Multiple companies found. Please specify the company by name."
MULTI_SUGGESTION = (
    'Pass the company name (e.g. --company "Acme"), '
    "or use --company-id with one of the IDs above."
)
ZERO_ERROR = "No company found. Create one first."
ZERO_SUGGESTION = (
    "Run 'tutorial' to create a demo company, "
    "or 'setup company' to create your own."
)
NAME_MISS_SUGGESTION = (
    "Use one of the available company names exactly, "
    "or run 'list-companies' to see them."
)

_STATE_TABLES = (
    "company", "account", "regional_settings",
    "tax_template", "salary_slip", "audit_log",
)
_GENERATED_COLUMNS = {
    "id", "company_id", "entity_id",
    "created_at", "updated_at", "timestamp",
}


def _insert(conn, table, **cols):
    sql, _ = insert_row(table, {key: P() for key in cols})
    conn.execute(sql, tuple(cols[key] for key in cols))
    conn.commit()
    return cols.get("id")


def _company(conn, name, abbr):
    cid = str(uuid.uuid4())
    _insert(conn, "company", id=cid, name=name, abbr=abbr,
            default_currency="GBP", country="GB",
            fiscal_year_start_month=4)
    return cid


def _fiscal_year(conn, company_id):
    fid = str(uuid.uuid4())
    _insert(conn, "fiscal_year", id=fid, name="FY-%s" % fid[:6],
            start_date="2025-04-06", end_date="2026-04-05",
            company_id=company_id)
    return fid


def _employee(conn, company_id):
    eid = str(uuid.uuid4())
    _insert(conn, "employee", id=eid, first_name="Bruce", last_name="Wayne",
            full_name="Bruce Wayne", date_of_joining="2024-01-01",
            company_id=company_id, ssn="AB123456C")
    return eid


def _run(conn, company_id, start, end):
    rid = str(uuid.uuid4())
    _insert(conn, "payroll_run", id=rid, period_start=start,
            period_end=end, company_id=company_id)
    return rid


def _slip(conn, company_id, run_id, employee_id, start, end,
          gross, ded, net):
    sid = str(uuid.uuid4())
    _insert(conn, "salary_slip", id=sid, payroll_run_id=run_id,
            employee_id=employee_id, period_start=start, period_end=end,
            gross_pay=gross, total_deductions=ded, net_pay=net,
            status="submitted", company_id=company_id)
    return sid


@pytest.fixture
def two(conn):
    acme = _company(conn, ACME_NAME, ACME_ABBR)
    _fiscal_year(conn, acme)
    wayne = _company(conn, WAYNE_NAME, WAYNE_ABBR)
    _fiscal_year(conn, wayne)
    return {"acme": acme, "wayne": wayne}


def _multiple(acme, wayne):
    return {
        "status": "error",
        "error": MULTI_ERROR,
        "message": MULTI_ERROR,
        "companies": [
            {"id": acme, "name": ACME_NAME},
            {"id": wayne, "name": WAYNE_NAME},
        ],
        "suggestion": MULTI_SUGGESTION,
    }


def _state(conn):
    snap = {}
    for name in _STATE_TABLES:
        table = Table(name)
        rows = conn.execute(Q.from_(table).select(table.star).get_sql())
        snap[name] = sorted(
            json.dumps(dict(row), sort_keys=True, default=str)
            for row in rows.fetchall()
        )
    return snap


def _normalised(state):
    out = {}
    for name, rows in state.items():
        kept = []
        for raw in rows:
            row = {k: v for k, v in json.loads(raw).items()
                   if k not in _GENERATED_COLUMNS}
            kept.append(json.dumps(row, sort_keys=True, default=str))
        out[name] = sorted(kept)
    return out


def _p60_seed(conn, two, june, july):
    emp = _employee(conn, two["acme"])
    run_acme = _run(conn, two["acme"], june[0], july[1])
    run_wayne = _run(conn, two["wayne"], june[0], june[1])
    _slip(conn, two["acme"], run_acme, emp,
          june[0], june[1], "1000.10", "100.10", "900.00")
    _slip(conn, two["acme"], run_acme, emp,
          july[0], july[1], "2000.20", "200.20", "1800.00")
    _slip(conn, two["wayne"], run_wayne, emp,
          june[0], june[1], "1000.10", "100.10", "900.00")
    return emp


def test_report_two_companies_no_company_refuses(conn, two):
    before = _state(conn)
    tax = call_action(ACTIONS["uk-tax-summary"], conn,
                      ns(from_date="2026-03-01", to_date="2026-03-31"))
    assert tax == _multiple(two["acme"], two["wayne"])
    payroll = call_action(ACTIONS["uk-payroll-summary"], conn,
                          ns(month="3", year="2026"))
    assert payroll == _multiple(two["acme"], two["wayne"])
    assert _state(conn) == before


def test_write_two_companies_no_company_refuses(conn, two):
    before = _state(conn)
    seed = call_action(ACTIONS["uk-seed-uk-defaults"], conn, ns())
    assert seed == _multiple(two["acme"], two["wayne"])
    assert _state(conn) == before
    vat = call_action(ACTIONS["uk-setup-vat"], conn,
                      ns(vat_number="289136634"))
    assert vat == _multiple(two["acme"], two["wayne"])
    assert _state(conn) == before


def test_zero_companies_refuses(conn):
    result = call_action(ACTIONS["uk-tax-summary"], conn,
                         ns(from_date="2026-03-01", to_date="2026-03-31"))
    assert result == {
        "status": "error",
        "error": ZERO_ERROR,
        "message": ZERO_ERROR,
        "suggestion": ZERO_SUGGESTION,
    }


def test_unknown_company_refuses(conn, two):
    result = call_action(ACTIONS["uk-tax-summary"], conn,
                         ns(company_id="no-such-company",
                            from_date="2026-03-01", to_date="2026-03-31"))
    assert result["message"] == "Company not found: no-such-company"
    assert result == {
        "status": "error",
        "error": "Company not found: no-such-company",
        "message": "Company not found: no-such-company",
    }


def test_one_company_write_unchanged(tmp_path):
    paths = [str(tmp_path / "one-a.sqlite"), str(tmp_path / "one-b.sqlite")]
    conns = []
    try:
        for path in paths:
            init_all_tables(path)
            conns.append(get_conn(path))
        first, second = conns
        _fiscal_year(first, _company(first, ACME_NAME, ACME_ABBR))
        explicit = _company(second, ACME_NAME, ACME_ABBR)
        _fiscal_year(second, explicit)
        implied = call_action(ACTIONS["uk-seed-uk-defaults"], first, ns())
        assert is_ok(implied), implied
        named = call_action(ACTIONS["uk-seed-uk-defaults"], second,
                            ns(company_id=explicit))
        assert is_ok(named), named
        assert _normalised(_state(first)) == _normalised(_state(second))
    finally:
        for conn in conns:
            conn.close()


def test_p60_scoped_to_company(conn, two):
    emp = _p60_seed(conn, two,
                    ("2025-06-01", "2025-06-30"),
                    ("2025-07-01", "2025-07-31"))
    acme = call_action(ACTIONS["uk-generate-p60"], conn,
                       ns(employee_id=emp, tax_year="2025",
                          company_id=two["acme"]))
    assert is_ok(acme), acme
    assert acme["total_pay"] == "3000.30"
    assert acme["total_tax_deducted"] == "300.30"
    assert acme["total_net_pay"] == "2700.00"
    wayne = call_action(ACTIONS["uk-generate-p60"], conn,
                        ns(employee_id=emp, tax_year="2025",
                           company_id=two["wayne"]))
    assert is_ok(wayne), wayne
    assert wayne["total_pay"] == "1000.10"
    assert wayne["total_tax_deducted"] == "100.10"
    assert wayne["total_net_pay"] == "900.00"
    refused = call_action(ACTIONS["uk-generate-p60"], conn,
                          ns(employee_id=emp, tax_year="2025"))
    assert refused == _multiple(two["acme"], two["wayne"])


def test_p45_scoped_to_company(conn, two):
    emp = _p60_seed(conn, two,
                    ("2026-01-01", "2026-01-31"),
                    ("2026-02-01", "2026-02-28"))
    acme = call_action(ACTIONS["uk-generate-p45"], conn,
                       ns(employee_id=emp, company_id=two["acme"]))
    assert is_ok(acme), acme
    assert acme["total_pay_to_date"] == "3000.30"
    assert acme["total_tax_to_date"] == "300.30"
    wayne = call_action(ACTIONS["uk-generate-p45"], conn,
                        ns(employee_id=emp, company_id=two["wayne"]))
    assert is_ok(wayne), wayne
    assert wayne["total_pay_to_date"] == "1000.10"
    assert wayne["total_tax_to_date"] == "100.10"
    refused = call_action(ACTIONS["uk-generate-p45"], conn,
                          ns(employee_id=emp))
    assert refused == _multiple(two["acme"], two["wayne"])


def test_company_flag_resolves_name(conn, two):
    args = ns(company_name="wayne enterprises")
    _mod._resolve_company_flag(conn, args)
    assert args.company_id == two["wayne"]
    as_id = ns(company_name=two["acme"])
    _mod._resolve_company_flag(conn, as_id)
    assert as_id.company_id == two["acme"]
    miss = call_action(_mod._resolve_company_flag, conn,
                       ns(company_name="Wayne"))
    assert miss == {
        "status": "error",
        "error": "Company 'Wayne' not found.",
        "message": "Company 'Wayne' not found.",
        "available_companies": [ACME_NAME, WAYNE_NAME],
        "suggestion": NAME_MISS_SUGGESTION,
    }
