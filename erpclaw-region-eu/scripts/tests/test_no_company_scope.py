"""No-company scope tests for the ERPClaw Region EU module.

Product rule: with no company given, one company is used; zero or
several refuse. An unknown explicit id refuses. `--company` resolves an
exact case-insensitive name (or an existing id).
"""
import io
import json
import os
import re
import sys
import uuid
from unittest.mock import patch

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from eu_helpers import call_action, ns, is_ok, load_db_query, init_all_tables, get_conn
from erpclaw_lib.query import Q, Table

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SEED_ACTION = "eu-seed-eu-defaults"
SUMMARY_ACTION = "eu-tax-summary"
COUNTRY = "DE"
CURRENCY = "EUR"
FROM_DATE = "2026-01-01"
TO_DATE = "2026-12-31"

ZERO_ERROR = "No company found. Create one first."
ZERO_SUGGESTION = "Run 'tutorial' to create a demo company, or 'setup company' to create your own."
MULTI_ERROR = "Multiple companies found. Please specify the company by name."
MULTI_SUGGESTION = "Pass the company name (e.g. --company \"Acme\"), or use --company-id with one of the IDs above."
NAME_SUGGESTION = "Use one of the available company names exactly, or run 'list-companies' to see them."


def _seed_company(conn, name, abbr):
    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO company (id, name, abbr, default_currency, country,"
        " fiscal_year_start_month) VALUES (?, ?, ?, ?, ?, 1)",
        (cid, name, abbr, CURRENCY, COUNTRY))
    conn.commit()
    return cid


def _seed_fiscal_year(conn, company_id):
    fid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO fiscal_year (id, name, start_date, end_date, company_id)"
        " VALUES (?, ?, ?, ?, ?)",
        (fid, "FY-%s" % fid[:6], FROM_DATE, TO_DATE, company_id))
    conn.commit()
    return fid


def _two_companies(conn):
    acme = _seed_company(conn, "Acme Widgets", "ACME")
    _seed_fiscal_year(conn, acme)
    wayne = _seed_company(conn, "Wayne Enterprises", "WAYNE")
    _seed_fiscal_year(conn, wayne)
    return acme, wayne


def _multi_error(acme, wayne):
    return {
        "status": "error",
        "error": MULTI_ERROR,
        "message": MULTI_ERROR,
        "companies": [
            {"id": acme, "name": "Acme Widgets"},
            {"id": wayne, "name": "Wayne Enterprises"},
        ],
        "suggestion": MULTI_SUGGESTION,
    }


def _state(conn):
    out = {}
    for name in ("company", "account", "regional_settings", "tax_template", "audit_log"):
        table = Table(name)
        rows = conn.execute(Q.from_(table).select(table.star).get_sql()).fetchall()
        out[name] = sorted(repr(sorted(dict(row).items())) for row in rows)
    return out


_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?")


def _norm(state):
    normed = {}
    for table, rows in state.items():
        normed[table] = sorted(_TS_RE.sub("TS", _UUID_RE.sub("UUID", row)) for row in rows)
    return normed


def _call_flag(conn, args):
    buf = io.StringIO()

    def _fake_exit(code=0):
        raise SystemExit(code)

    try:
        with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
            _mod._resolve_company_flag(conn, args)
    except SystemExit:
        pass
    output = buf.getvalue().strip()
    if not output:
        return None
    return json.loads(output)


class TestNoCompanyScope:
    def test_report_two_companies_no_company_refuses(self, conn):
        acme, wayne = _two_companies(conn)
        before = _state(conn)
        r = call_action(ACTIONS[SUMMARY_ACTION], conn,
                        ns(from_date=FROM_DATE, to_date=TO_DATE))
        assert r == _multi_error(acme, wayne)
        assert _state(conn) == before

    def test_write_two_companies_no_company_refuses(self, conn):
        acme, wayne = _two_companies(conn)
        before = _state(conn)
        r = call_action(ACTIONS[SEED_ACTION], conn, ns())
        assert r == _multi_error(acme, wayne)
        assert _state(conn) == before

    def test_zero_companies_refuses(self, conn):
        r = call_action(ACTIONS[SUMMARY_ACTION], conn,
                        ns(from_date=FROM_DATE, to_date=TO_DATE))
        assert r == {"status": "error", "error": ZERO_ERROR,
                     "message": ZERO_ERROR, "suggestion": ZERO_SUGGESTION}

    def test_unknown_company_refuses(self, conn):
        _two_companies(conn)
        r = call_action(ACTIONS[SUMMARY_ACTION], conn,
                        ns(company_id="no-such-company",
                           from_date=FROM_DATE, to_date=TO_DATE))
        assert r == {"status": "error",
                     "error": "Company not found: no-such-company",
                     "message": "Company not found: no-such-company"}

    def test_one_company_write_unchanged(self, conn, tmp_path):
        acme = _seed_company(conn, "Acme Widgets", "ACME")
        _seed_fiscal_year(conn, acme)
        r1 = call_action(ACTIONS[SEED_ACTION], conn, ns())
        assert is_ok(r1)
        state_implicit = _state(conn)
        db2 = str(tmp_path / "second.sqlite")
        init_all_tables(db2)
        conn2 = get_conn(db2)
        try:
            acme2 = _seed_company(conn2, "Acme Widgets", "ACME")
            _seed_fiscal_year(conn2, acme2)
            r2 = call_action(ACTIONS[SEED_ACTION], conn2, ns(company_id=acme2))
            assert is_ok(r2)
            state_explicit = _state(conn2)
        finally:
            conn2.close()
        assert _norm(state_implicit) == _norm(state_explicit)

    def test_company_flag_resolves_name(self, conn):
        acme, wayne = _two_companies(conn)
        args = ns(company_name="acme widgets")
        assert _call_flag(conn, args) is None
        assert args.company_id == acme
        args = ns(company_name=acme)
        assert _call_flag(conn, args) is None
        assert args.company_id == acme
        args = ns(company_name="Acme")
        r = _call_flag(conn, args)
        assert r == {"status": "error",
                     "error": "Company 'Acme' not found.",
                     "message": "Company 'Acme' not found.",
                     "available_companies": ["Acme Widgets", "Wayne Enterprises"],
                     "suggestion": NAME_SUGGESTION}
