"""Shared helper functions for ERPClaw Region India unit tests."""
import argparse
import importlib.util
import io
import json
import os
import sqlite3
import sys
import uuid
from decimal import Decimal
from unittest.mock import patch

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TESTS_DIR)
ROOT_DIR = os.path.dirname(MODULE_DIR)
PARENT_DIR = os.path.dirname(ROOT_DIR)
SRC_DIR = os.path.dirname(PARENT_DIR)
SETUP_DIR = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-setup")
INIT_SCHEMA_PATH = os.path.join(SETUP_DIR, "init_schema.py")

ERPCLAW_LIB = os.path.expanduser("~/.openclaw/erpclaw/lib")
if ERPCLAW_LIB not in sys.path:
    sys.path.insert(0, ERPCLAW_LIB)


def load_db_query():
    db_query_path = os.path.join(MODULE_DIR, "db_query.py")
    spec = importlib.util.spec_from_file_location("db_query_in", db_query_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def init_all_tables(db_path: str):
    spec = importlib.util.spec_from_file_location("init_schema", INIT_SCHEMA_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.init_db(db_path)


class _ConnWrapper:
    def __init__(self, real_conn):
        self._conn = real_conn
        self.company_id = None

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self._conn.executescript(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, val):
        self._conn.row_factory = val


class _DecimalSum:
    def __init__(self):
        self.total = Decimal("0")
    def step(self, value):
        if value is not None:
            self.total += Decimal(str(value))
    def finalize(self):
        return str(self.total)


def get_conn(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.create_aggregate("decimal_sum", 1, _DecimalSum)
    return _ConnWrapper(conn)


def call_action(fn, conn, args) -> dict:
    buf = io.StringIO()
    def _fake_exit(code=0):
        raise SystemExit(code)
    try:
        with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
            fn(conn, args)
    except SystemExit:
        pass
    output = buf.getvalue().strip()
    if not output:
        return {"status": "error", "message": "no output captured"}
    return json.loads(output)


def ns(**kwargs) -> argparse.Namespace:
    defaults = {
        "company_id": None, "gstin": None, "state_code": None,
        "amount": None, "hsn_code": None, "seller_state": None,
        "buyer_state": None, "gst_rate": None, "search": None,
        "code": None, "description": None, "category": None,
        "pan": None, "tan": None, "aadhaar": None,
        "month": None, "year": None, "from_date": None, "to_date": None,
        "invoice_id": None, "transporter_id": None,
        "section": None, "quarter": None, "form": None,
        "basic_salary": None, "gross_salary": None, "annual_income": None,
        "regime": "new", "employee_id": None, "fiscal_year": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def is_error(result: dict) -> bool:
    return result.get("status") == "error"

def is_ok(result: dict) -> bool:
    return result.get("status") == "ok"


def _uuid() -> str:
    return str(uuid.uuid4())


def seed_company(conn, name="Test Co", abbr="TC", country="IN") -> str:
    cid = _uuid()
    conn.execute(
        """INSERT INTO company (id, name, abbr, default_currency, country,
           fiscal_year_start_month)
           VALUES (?, ?, ?, 'INR', ?, 4)""",
        (cid, f"{name} {cid[:6]}", f"{abbr}{cid[:4]}", country)
    )
    conn.commit()
    return cid


def seed_fiscal_year(conn, company_id: str,
                     start="2025-04-01", end="2026-03-31") -> str:
    fid = _uuid()
    conn.execute(
        """INSERT INTO fiscal_year (id, name, start_date, end_date, company_id)
           VALUES (?, ?, ?, ?, ?)""",
        (fid, f"FY-{fid[:6]}", start, end, company_id)
    )
    conn.commit()
    return fid


def build_env(conn) -> dict:
    cid = seed_company(conn, country="IN")
    seed_fiscal_year(conn, cid)
    return {"company_id": cid}
