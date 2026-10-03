"""M473 depth: behavioural evidence for the 12 EU overlay actions.

Each action below already had a test that proved the wrong thing (response
shape or routability). Each test here proves the database effect instead:
what row exists afterwards with which exact values, what changed from what
to what, and what did not change. Money is TEXT: exact string comparisons,
Decimal for arithmetic, never float, never round().

Verification reads go through ``erpclaw_lib.db.get_connection()`` with
queries built by ``erpclaw_lib.query`` (PyPika); the one catalog question
asked (table presence) goes through ``erpclaw_lib.seam``, and no other
catalog probing appears below.

Per-action depth signal:
- eu-check-vies-format ......... NEITHER (pure format validation; not even
                                 company-scoped. Asserts exact verdict fields
                                 plus zero writes)
- eu-generate-ec-sales-list .... NEITHER (stub: constant empty payload even
                                 with posted sales in period; asserts the
                                 payload plus zero writes) -- FINDING F2
- eu-generate-einvoice-en16931 . STORED ROW (response mirrors the stored
                                 sales_invoice TEXT amounts exactly)
- eu-generate-intrastat-arrivals  NEITHER (stub; see F2)
- eu-generate-intrastat-dispatches NEITHER (stub; see F2)
- eu-generate-oss-return ....... NEITHER (stub; see F2)
- eu-generate-saft-export ...... STORED ROWS (record counts derived from
                                 stored submitted invoices in range)
- eu-generate-vat-return ....... STORED ROWS (output/input/net/total sums
                                 derived from stored submitted invoices)
- eu-seed-eu-coa ............... STORED ROWS (150 account rows) -- FINDING F1
                                 (every row lands with root_type "asset")
- eu-seed-eu-defaults .......... STORED ROWS (4 account + 3 tax_template rows)
- eu-setup-eu-vat .............. STORED ROWS (2 regional_settings rows)
- eu-tax-summary ............... STORED ROWS (collected/paid/net derived from
                                 stored submitted invoices)

Ledger note: none of these twelve actions posts to the stock or general
ledger on any path (the writers touch account / tax_template /
regional_settings / audit_log only; the readers touch nothing), so no
success test below asserts a new ledger leg. Every writer test pins the
gl_entry and stock_ledger_entry counts unchanged so a later reader does not
add a leg assertion that cannot hold.

Findings deliberately not fixed (see CHANGES.md):
- F1 eu-seed-eu-coa collapses every root_type to "asset" and nulls
  account_type for asset/income/liability template kinds.
- F2 the four report stubs (ec-sales-list, intrastat x2, oss-return) return
  constant empty payloads regardless of posted invoices.
- F3 eu-generate-einvoice-en16931 answers unknown invoice ids with an
  ok-empty structure instead of refusing, and its name-based lookup arm can
  never match (sales_invoice carries naming_series, not name).
- F4 eu-seed-eu-defaults records template names only; the VAT rate is not
  stored on any template row or line (no tax_template_line rows).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from eu_helpers import call_action, ns, is_ok, is_error, load_db_query, seed_company

from erpclaw_lib.db import get_connection
from erpclaw_lib.query import Q, P, Table, fn
from erpclaw_lib import seam

_mod = load_db_query()
ACTIONS = _mod.ACTIONS

SNAPSHOT_TABLES = (
    "account",
    "tax_template",
    "regional_settings",
    "sales_invoice",
    "purchase_invoice",
    "customer",
    "supplier",
    "audit_log",
    "gl_entry",
    "stock_ledger_entry",
)


def _read_all(table_name, order_col="id"):
    """Read every row of a table back through get_connection + PyPika."""
    conn = get_connection()
    try:
        table = Table(table_name)
        query = Q.from_(table).select(table.star).orderby(table.field(order_col))
        return [dict(row) for row in conn.execute(query.get_sql()).fetchall()]
    finally:
        conn.close()


def _snapshot():
    return {name: _read_all(name) for name in SNAPSHOT_TABLES}


def _count(table_name):
    conn = get_connection()
    try:
        table = Table(table_name)
        query = Q.from_(table).select(fn.Count("*").as_("cnt"))
        return conn.execute(query.get_sql()).fetchone()["cnt"]
    finally:
        conn.close()


def _insert(conn, table_name, values):
    table = Table(table_name)
    columns = list(values.keys())
    query = Q.into(table).columns(*columns).insert(
        *[P() for _ in columns]
    )
    conn.execute(query.get_sql(), tuple(values[col] for col in columns))


def _seed_customer(conn, company_id, name="Depth Customer"):
    cid = str(uuid.uuid4())
    _insert(conn, "customer", {"id": cid, "name": name, "company_id": company_id})
    conn.commit()
    return cid


def _seed_supplier(conn, company_id, name="Depth Supplier"):
    sid = str(uuid.uuid4())
    _insert(conn, "supplier", {"id": sid, "name": name, "company_id": company_id})
    conn.commit()
    return sid


def _seed_sales_invoice(conn, company_id, customer_id, posting_date,
                        total, tax, grand, status="submitted"):
    iid = str(uuid.uuid4())
    _insert(conn, "sales_invoice", {
        "id": iid, "customer_id": customer_id, "posting_date": posting_date,
        "company_id": company_id, "total_amount": total, "tax_amount": tax,
        "grand_total": grand, "status": status,
    })
    conn.commit()
    return iid


def _seed_purchase_invoice(conn, company_id, supplier_id, posting_date,
                           total, tax, grand, status="submitted"):
    iid = str(uuid.uuid4())
    _insert(conn, "purchase_invoice", {
        "id": iid, "supplier_id": supplier_id, "posting_date": posting_date,
        "company_id": company_id, "total_amount": total, "tax_amount": tax,
        "grand_total": grand, "status": status,
    })
    conn.commit()
    return iid


def _audit_rows(action, entity_id):
    conn = get_connection()
    try:
        table = Table("audit_log")
        query = (
            Q.from_(table)
            .select(table.star)
            .where((table.action == P()) & (table.entity_id == P()))
        )
        return [
            dict(row)
            for row in conn.execute(query.get_sql(), (action, entity_id)).fetchall()
        ]
    finally:
        conn.close()


def _trade_env(conn, company_id):
    """One customer + one supplier + March submitted pair with exact TEXT money."""
    customer_id = _seed_customer(conn, company_id)
    supplier_id = _seed_supplier(conn, company_id)
    _seed_sales_invoice(conn, company_id, customer_id, "2026-03-05",
                        "1000.00", "190.00", "1190.00")
    _seed_sales_invoice(conn, company_id, customer_id, "2026-03-20",
                        "500.00", "95.00", "595.00")
    _seed_purchase_invoice(conn, company_id, supplier_id, "2026-03-08",
                           "200.00", "38.00", "238.00")
    return {"customer_id": customer_id, "supplier_id": supplier_id}


class TestSeamCatalog:
    def test_snapshot_tables_exist_through_seam(self, db_path):
        for name in SNAPSHOT_TABLES:
            assert seam.table_exists(name) is True, name


# ── eu-seed-eu-defaults: STORED ROWS ─────────────────────────────────────────

class TestSeedEuDefaultsDepth:
    def test_seeds_exact_vat_accounts_templates_and_audit(self, conn, env):
        # This action does NOT reach the ledger: it appends account,
        # tax_template and audit_log rows only. Both ledger counts are
        # pinned unchanged.
        cid = env["company_id"]
        other = seed_company(conn, country="US")
        _insert(conn, "account", {
            "id": str(uuid.uuid4()), "name": "Other Co Account",
            "root_type": "asset", "company_id": other,
        })
        conn.commit()
        ledgers_before = (_count("gl_entry"), _count("stock_ledger_entry"))

        r = call_action(ACTIONS["eu-seed-eu-defaults"], conn,
                        ns(company_id=cid))
        assert is_ok(r), r
        assert r["accounts_created"] == 4
        assert r["templates_created"] == 3
        assert r["country"] == "DE"
        assert r["standard_vat_rate"] == "19"
        assert r["company_id"] == cid

        accounts = {
            row["name"]: row
            for row in _read_all("account")
            if row["company_id"] == cid
        }
        assert sorted(accounts) == [
            "VAT Control (EU)",
            "VAT Input (EU)",
            "VAT Output (DE 19%)",
            "VAT Output (Intra-Community)",
        ]
        assert accounts["VAT Output (DE 19%)"]["account_type"] == "tax"
        assert accounts["VAT Output (DE 19%)"]["root_type"] == "liability"
        assert accounts["VAT Output (Intra-Community)"]["root_type"] == "liability"
        assert accounts["VAT Input (EU)"]["root_type"] == "asset"
        assert accounts["VAT Control (EU)"]["root_type"] == "liability"
        assert all(row["account_type"] == "tax" for row in accounts.values())

        templates = {
            row["name"]: row
            for row in _read_all("tax_template")
            if row["company_id"] == cid
        }
        assert sorted(templates) == [
            "EU VAT Intra-Community (0%)",
            "EU VAT Reverse Charge (0%)",
            "EU VAT Standard (DE 19%)",
        ]
        assert all(row["tax_type"] == "both" for row in templates.values())

        audits = _audit_rows("eu-seed-eu-defaults", cid)
        assert len(audits) == 1
        assert audits[0]["skill"] == "erpclaw-region-eu"
        assert json.loads(audits[0]["new_values"]) == {
            "accounts": 4, "templates": 3,
        }

        # Nothing belonging to the other company moved, and the ledgers
        # stayed empty.
        assert [
            row["name"] for row in _read_all("account")
            if row["company_id"] == other
        ] == ["Other Co Account"]
        assert (_count("gl_entry"), _count("stock_ledger_entry")) == ledgers_before == (0, 0)

        # Idempotent: a second run creates nothing and changes nothing.
        before = _snapshot()
        r2 = call_action(ACTIONS["eu-seed-eu-defaults"], conn,
                         ns(company_id=cid))
        assert is_ok(r2), r2
        assert (r2["accounts_created"], r2["templates_created"]) == (0, 0)
        after = _snapshot()
        deltas = {
            name for name in SNAPSHOT_TABLES if after[name] != before[name]
        }
        assert deltas == {"audit_log"}, deltas
        assert len(after["audit_log"]) == len(before["audit_log"]) + 1, \
            "the rerun must add exactly one audit row and nothing else"

    def test_non_eu_company_refused_truthfully_and_writes_nothing(self, conn, env):
        other = seed_company(conn, country="US")
        before = _snapshot()

        r = call_action(ACTIONS["eu-seed-eu-defaults"], conn,
                        ns(company_id=other))
        assert is_error(r)
        assert "not an EU member state" in r["message"]
        assert "'US'" in r["message"], "the refusal must name the country it saw"

        assert _snapshot() == before, "a refused seed must half-write nothing"


# ── eu-setup-eu-vat: STORED ROWS ─────────────────────────────────────────────

class TestSetupEuVatDepth:
    def test_stores_vat_number_then_updates_from_to(self, conn, env):
        # No ledger legs here either: two regional_settings rows plus audit.
        cid = env["company_id"]
        ledgers_before = (_count("gl_entry"), _count("stock_ledger_entry"))

        r = call_action(ACTIONS["eu-setup-eu-vat"], conn,
                        ns(company_id=cid, vat_number="DE123456789"))
        assert is_ok(r), r
        assert r["vat_number_stored"] is True
        assert r["vat_number"] == "DE123456789"
        assert r["member_state"] == "DE"

        settings = {
            row["key"]: row["value"]
            for row in _read_all("regional_settings")
            if row["company_id"] == cid
        }
        assert settings == {
            "eu_vat_number": "DE123456789",
            "eu_member_state": "DE",
        }

        r2 = call_action(ACTIONS["eu-setup-eu-vat"], conn,
                         ns(company_id=cid, vat_number="DE987654321"))
        assert is_ok(r2), r2
        settings_after = {
            row["key"]: row["value"]
            for row in _read_all("regional_settings")
            if row["company_id"] == cid
        }
        assert settings_after == {
            "eu_vat_number": "DE987654321",
            "eu_member_state": "DE",
        }, "the stored number must move from the old value to the new one"
        assert len([
            row for row in _read_all("regional_settings")
            if row["company_id"] == cid
        ]) == 2, "an update must not duplicate the keys"

        assert (_count("gl_entry"), _count("stock_ledger_entry")) == ledgers_before == (0, 0)

    def test_invalid_vat_number_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-setup-eu-vat"], conn,
                        ns(company_id=env["company_id"], vat_number="XX999"))
        assert is_error(r)
        assert r["message"] == "Invalid EU VAT number: XX999"
        assert "DE123456789" in r.get("suggestion", ""), \
            "the steer must show a valid example"

        assert _snapshot() == before, "a refused setup must half-write nothing"


# ── eu-seed-eu-coa: STORED ROWS (with FINDING F1) ────────────────────────────

class TestSeedEuCoaDepth:
    def test_seeds_template_and_pins_root_type_collapse(self, conn, env):
        # FINDING F1 (documented, not fixed): the template carries "type"
        # but no "root_type", so every one of the 150 rows lands with
        # root_type "asset" -- including equity, liability and income
        # accounts -- and account_type is nulled for the asset / income /
        # liability kinds. The assertions below pin that real behaviour so
        # a fix is visible the moment it lands.
        cid = env["company_id"]

        r = call_action(ACTIONS["eu-seed-eu-coa"], conn, ns(company_id=cid))
        assert is_ok(r), r
        assert r["accounts_created"] == 150
        assert r["standard"] == "EU Generic Template"

        rows = [
            row for row in _read_all("account", order_col="account_number")
            if row["company_id"] == cid
        ]
        assert len(rows) == 150
        by_number = {row["account_number"]: row for row in rows}
        assert by_number["1000"]["name"] == "Current Assets"
        assert by_number["1000"]["is_group"] == 1
        assert by_number["1410"]["name"] == "VAT Input (Deductible)"
        assert by_number["1410"]["is_group"] == 0
        assert by_number["3050"]["name"] == "Retained Earnings"

        assert {row["root_type"] for row in rows} == {"asset"}, \
            "F1: every seeded row carries root_type 'asset'"
        kinds = {}
        for row in rows:
            kinds.setdefault(str(row["account_type"]), 0)
            kinds[str(row["account_type"])] += 1
        assert kinds == {"None": 99, "expense": 40, "equity": 11}, kinds

        audits = _audit_rows("eu-seed-eu-coa", cid)
        assert len(audits) == 1
        assert json.loads(audits[0]["new_values"]) == {"accounts": 150}

        assert (_count("gl_entry"), _count("stock_ledger_entry")) == (0, 0)

        # Idempotent on the numbers: a second run creates nothing new.
        r2 = call_action(ACTIONS["eu-seed-eu-coa"], conn, ns(company_id=cid))
        assert is_ok(r2), r2
        assert r2["accounts_created"] == 0
        assert len([
            row for row in _read_all("account") if row["company_id"] == cid
        ]) == 150

    def test_non_eu_company_refused_truthfully_and_writes_nothing(self, conn, env):
        other = seed_company(conn, country="US")
        before = _snapshot()

        r = call_action(ACTIONS["eu-seed-eu-coa"], conn, ns(company_id=other))
        assert is_error(r)
        assert "not an EU member state" in r["message"]
        assert "'US'" in r["message"]

        assert _snapshot() == before


# ── eu-generate-vat-return: STORED ROWS (sums over submitted invoices) ───────

class TestGenerateVatReturnDepth:
    def test_sums_only_submitted_in_month_and_writes_nothing(self, conn, env):
        # Read-only: no stored row, no ledger legs -- the behaviour is the
        # sums, which must come from the stored submitted rows only.
        cid = env["company_id"]
        trade = _trade_env(conn, cid)
        _seed_sales_invoice(conn, cid, trade["customer_id"], "2026-03-10",
                            "9999.99", "999.99", "10999.98", status="draft")
        _seed_sales_invoice(conn, cid, trade["customer_id"], "2026-02-10",
                            "200.00", "38.00", "238.00")
        _seed_purchase_invoice(conn, cid, trade["supplier_id"], "2026-03-09",
                               "50.00", "9.50", "59.50", status="draft")
        stranger = seed_company(conn, country="DE")
        alien_cust = _seed_customer(conn, stranger)
        _seed_sales_invoice(conn, stranger, alien_cust, "2026-03-11",
                            "777.00", "147.63", "924.63")
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-vat-return"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "VAT Return"
        assert r["country"] == "DE"
        assert r["period"] == "2026-03"
        assert r["company_id"] == cid
        assert r["output_vat"] == "285.00"
        assert r["input_vat"] == "38.00"
        assert r["net_vat"] == "247.00"
        assert r["total_sales_ex_vat"] == "1500.00"
        assert r["total_purchases_ex_vat"] == "200.00"
        assert Decimal(r["net_vat"]) == Decimal(r["output_vat"]) - Decimal(r["input_vat"])
        assert Decimal(r["output_vat"]) == Decimal("190.00") + Decimal("95.00")

        assert _snapshot() == before, "a report must write nothing"

    def test_missing_period_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-vat-return"], conn,
                        ns(company_id=env["company_id"], period=None, year=None))
        assert is_error(r)
        assert r["message"] == "--period and --year are required."

        assert _snapshot() == before


# ── eu-generate-ec-sales-list: NEITHER (stub, FINDING F2) ────────────────────

class TestGenerateEcSalesListDepth:
    def test_constant_empty_payload_despite_posted_sales(self, conn, env):
        # FINDING F2 (documented, not fixed): the action reads nothing past
        # the company row, so submitted intra-period sales still yield an
        # empty list and zero totals. Pinned so a real implementation moves it.
        cid = env["company_id"]
        _trade_env(conn, cid)
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-ec-sales-list"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "EC Sales List"
        assert r["country"] == "DE"
        assert r["period"] == "2026-03"
        assert r["company_id"] == cid
        assert r["entries"] == []
        assert r["total_goods"] == "0.00"
        assert r["total_services"] == "0.00"
        assert r["total_triangulation"] == "0.00"

        assert _snapshot() == before, "a report must write nothing"

    def test_missing_period_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-ec-sales-list"], conn,
                        ns(company_id=env["company_id"], period=None, year=None))
        assert is_error(r)
        assert r["message"] == "--period and --year are required."

        assert _snapshot() == before


# ── eu-generate-saft-export: STORED ROWS (counts over submitted invoices) ────

class TestGenerateSaftExportDepth:
    def test_counts_only_submitted_in_range_and_writes_nothing(self, conn, env):
        # Read-only: the behaviour is the record counts, which must match
        # the stored submitted rows in the closed range.
        cid = env["company_id"]
        trade = _trade_env(conn, cid)
        _seed_sales_invoice(conn, cid, trade["customer_id"], "2026-03-10",
                            "5.00", "0.95", "5.95", status="draft")
        _seed_sales_invoice(conn, cid, trade["customer_id"], "2026-04-01",
                            "7.00", "1.33", "8.33")
        _seed_purchase_invoice(conn, cid, trade["supplier_id"], "2026-03-09",
                               "9.00", "1.71", "10.71", status="draft")
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-saft-export"], conn,
                        ns(company_id=cid, from_date="2026-03-01",
                           to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["standard"] == "OECD SAF-T v2.0"
        assert r["header"]["AuditFileVersion"] == "2.00"
        assert r["header"]["AuditFileCountry"] == "DE"
        assert r["header"]["SelectionCriteria"] == {
            "PeriodStart": "2026-03-01", "PeriodEnd": "2026-03-31",
        }
        assert r["header"]["Company"]["CompanyID"] == cid
        assert r["record_counts"] == {
            "sales_invoices": 2, "purchase_invoices": 1,
        }
        assert r["header"]["AuditFileDateCreated"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")

        assert _snapshot() == before, "a report must write nothing"

    def test_missing_dates_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-saft-export"], conn,
                        ns(company_id=env["company_id"], from_date=None, to_date=None))
        assert is_error(r)
        assert r["message"] == "--from-date and --to-date are required."

        assert _snapshot() == before


# ── eu-generate-intrastat-dispatches / arrivals: NEITHER (stubs, F2) ─────────

class TestGenerateIntrastatDispatchesDepth:
    def test_constant_empty_payload_despite_posted_sales(self, conn, env):
        # FINDING F2: constant empty payload regardless of stored invoices.
        cid = env["company_id"]
        _trade_env(conn, cid)
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-intrastat-dispatches"], conn,
                        ns(company_id=cid, period="3", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "Intrastat Dispatches"
        assert r["country"] == "DE"
        assert r["period"] == "2026-03"
        assert r["company_id"] == cid
        assert r["dispatches"] == []
        assert r["total_value"] == "0.00"
        assert r["total_weight_kg"] == "0"

        assert _snapshot() == before, "a report must write nothing"

    def test_missing_period_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-intrastat-dispatches"], conn,
                        ns(company_id=env["company_id"], period=None, year=None))
        assert is_error(r)
        assert r["message"] == "--period and --year are required."

        assert _snapshot() == before


class TestGenerateIntrastatArrivalsDepth:
    def test_constant_empty_payload_through_month_alias(self, conn, env):
        # FINDING F2; exercised through the --month alias for period.
        cid = env["company_id"]
        _trade_env(conn, cid)
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-intrastat-arrivals"], conn,
                        ns(company_id=cid, month="3", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "Intrastat Arrivals"
        assert r["country"] == "DE"
        assert r["period"] == "2026-03"
        assert r["company_id"] == cid
        assert r["arrivals"] == []
        assert r["total_value"] == "0.00"
        assert r["total_weight_kg"] == "0"

        assert _snapshot() == before, "a report must write nothing"

    def test_missing_period_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-intrastat-arrivals"], conn,
                        ns(company_id=env["company_id"], period=None, year=None))
        assert is_error(r)
        assert r["message"] == "--period and --year are required."

        assert _snapshot() == before


# ── eu-generate-einvoice-en16931: STORED ROW (with FINDING F3) ───────────────

class TestGenerateEinvoiceEn16931Depth:
    def test_mirrors_stored_invoice_amounts_exactly(self, conn, env):
        # Read-only: the payload must echo the stored TEXT money exactly.
        cid = env["company_id"]
        customer_id = _seed_customer(conn, cid)
        iid = _seed_sales_invoice(conn, cid, customer_id, "2026-03-05",
                                  "1000.00", "190.00", "1190.00")
        company = next(
            row for row in _read_all("company") if row["id"] == cid
        )
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-einvoice-en16931"], conn,
                        ns(company_id=cid, invoice_id=iid))
        assert is_ok(r), r
        assert r["standard"] == "EN 16931"
        assert r["invoice_id"] == iid
        assert r["issue_date"] == "2026-03-05"
        assert r["seller"] == {"name": company["name"], "country": "DE"}
        assert r["buyer"] == {"customer_id": customer_id}
        assert r["net_total"] == "1000.00"
        assert r["tax_total"] == "190.00"
        assert r["gross_total"] == "1190.00"
        assert Decimal(r["gross_total"]) == Decimal(r["net_total"]) + Decimal(r["tax_total"])

        assert _snapshot() == before, "a report must write nothing"

    def test_unknown_id_returns_ok_empty_structure_not_an_error(self, conn, env):
        # FINDING F3 (documented, not fixed): an unknown invoice id is
        # answered with an ok-empty structure instead of a refusal, and the
        # name-lookup arm can never match -- sales_invoice carries
        # naming_series, not name, so that OR-arm degrades to a comparison
        # against a string literal and misses every real invoice number.
        cid = env["company_id"]
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-einvoice-en16931"], conn,
                        ns(company_id=cid, invoice_id="m473-no-such-invoice"))
        assert is_ok(r), r
        assert r["standard"] == "EN 16931"
        assert r["invoice_id"] == "m473-no-such-invoice"
        assert r["invoice_lines"] == []
        assert "Invoice not found" in r.get("note", "")

        assert _snapshot() == before

    def test_missing_invoice_id_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-einvoice-en16931"], conn,
                        ns(company_id=env["company_id"], invoice_id=None))
        assert is_error(r)
        assert r["message"] == "--invoice-id is required."

        assert _snapshot() == before


# ── eu-generate-oss-return: NEITHER (stub, FINDING F2) ───────────────────────

class TestGenerateOssReturnDepth:
    def test_constant_empty_quarter_payload_despite_posted_sales(self, conn, env):
        # FINDING F2: constant empty payload regardless of stored invoices.
        cid = env["company_id"]
        _trade_env(conn, cid)
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-oss-return"], conn,
                        ns(company_id=cid, quarter="2", year="2026"))
        assert is_ok(r), r
        assert r["report"] == "OSS Return"
        assert r["country"] == "DE"
        assert r["quarter"] == "Q2 2026"
        assert r["company_id"] == cid
        assert r["supplies_by_country"] == []
        assert r["total_vat_due"] == "0.00"

        assert _snapshot() == before, "a report must write nothing"

    def test_bad_quarter_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-generate-oss-return"], conn,
                        ns(company_id=env["company_id"], quarter="5", year="2026"))
        assert is_error(r)
        assert r["message"] == "Quarter must be 1-4."

        assert _snapshot() == before, "a refused report must half-write nothing"


# ── eu-tax-summary: STORED ROWS (sums over submitted invoices) ───────────────

class TestEuTaxSummaryDepth:
    def test_aggregates_only_submitted_in_range_and_writes_nothing(self, conn, env):
        # Read-only: collected/paid/net must come from the stored submitted
        # rows inside the closed range only.
        cid = env["company_id"]
        trade = _trade_env(conn, cid)
        _seed_sales_invoice(conn, cid, trade["customer_id"], "2026-03-10",
                            "9999.99", "999.99", "10999.98", status="draft")
        _seed_sales_invoice(conn, cid, trade["customer_id"], "2026-04-01",
                            "200.00", "38.00", "238.00")
        _seed_purchase_invoice(conn, cid, trade["supplier_id"], "2026-03-09",
                               "50.00", "9.50", "59.50", status="draft")
        stranger = seed_company(conn, country="DE")
        alien_cust = _seed_customer(conn, stranger)
        _seed_sales_invoice(conn, stranger, alien_cust, "2026-03-11",
                            "777.00", "147.63", "924.63")
        before = _snapshot()

        r = call_action(ACTIONS["eu-tax-summary"], conn,
                        ns(company_id=cid, from_date="2026-03-01",
                           to_date="2026-03-31"))
        assert is_ok(r), r
        assert r["report"] == "EU Tax Summary"
        assert r["country"] == "DE"
        assert r["period"] == "2026-03-01 to 2026-03-31"
        assert r["company_id"] == cid
        assert r["domestic_vat_collected"] == "285.00"
        assert r["domestic_vat_paid"] == "38.00"
        assert r["net_vat"] == "247.00"
        assert r["intra_community_supplies"] == "0.00"
        assert r["intra_community_acquisitions"] == "0.00"
        assert r["oss_vat_due"] == "0.00"
        assert Decimal(r["net_vat"]) == (
            Decimal(r["domestic_vat_collected"]) - Decimal(r["domestic_vat_paid"])
        )

        assert _snapshot() == before, "a report must write nothing"

    def test_missing_dates_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-tax-summary"], conn,
                        ns(company_id=env["company_id"], from_date=None, to_date=None))
        assert is_error(r)
        assert r["message"] == "--from-date and --to-date are required."

        assert _snapshot() == before


# ── eu-check-vies-format: NEITHER (pure validation, no company scope) ────────

class TestCheckViesFormatDepth:
    def test_valid_format_reports_country_and_note_without_db_touch(self, conn, env):
        # No stored row and no ledger effect are possible here: the action
        # performs zero reads and zero writes (it is not even company
        # scoped). The behaviour pinned is the exact verdict plus the proof
        # that the database is byte-identical afterwards.
        before = _snapshot()

        r = call_action(ACTIONS["eu-check-vies-format"], conn,
                        ns(vat_number="FR12345678901"))
        assert is_ok(r), r
        assert r["format_valid"] is True
        assert r["vat_number"] == "FR12345678901"
        assert r["country"] == "FR"
        assert r["prefix"] == "FR"
        assert "VIES" in r["note"]

        assert _snapshot() == before

    def test_unknown_prefix_reports_invalid_without_db_touch(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-check-vies-format"], conn,
                        ns(vat_number="XX999"))
        assert is_ok(r), r
        assert r["format_valid"] is False
        assert r["input"] == "XX999"
        assert r["reason"] == "Does not match any known EU VAT number format"

        assert _snapshot() == before

    def test_missing_vat_number_refused_truthfully_and_writes_nothing(self, conn, env):
        before = _snapshot()

        r = call_action(ACTIONS["eu-check-vies-format"], conn,
                        ns(vat_number=None))
        assert is_error(r)
        assert r["message"] == "--vat-number is required."

        assert _snapshot() == before
