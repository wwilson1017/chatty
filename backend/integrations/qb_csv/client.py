"""
Chatty — QuickBooks CSV Analysis CRUD and query operations.

Import, query, and analyze QBO export data stored in SQLite.
"""

import json
import logging
import re
from .db import _get_db, write_lock
from .parser import parse_csv_file

logger = logging.getLogger(__name__)


# ── Import operations ────────────────────────────────────────────────────────

def import_records(entity_type: str, records: list[dict], filename: str) -> dict:
    """Bulk-insert parsed records into the appropriate table.

    Returns: {import_id, imported, entity_type, filename}
    """
    db = _get_db()
    with write_lock():
        cursor = db.execute(
            "INSERT INTO imports (filename, entity_type, row_count) VALUES (?, ?, ?)",
            (filename, entity_type, len(records)),
        )
        import_id = cursor.lastrowid

        if entity_type == "accounts":
            _insert_accounts(db, import_id, records)
        elif entity_type == "customers":
            _insert_customers(db, import_id, records)
        elif entity_type == "vendors":
            _insert_vendors(db, import_id, records)
        elif entity_type == "products":
            _insert_products(db, import_id, records)
        elif entity_type in ("invoices", "bills", "expenses", "payments"):
            _insert_transactions(db, import_id, records)
        elif entity_type == "journal_entries":
            _insert_journal_entries(db, import_id, records)

        db.commit()

    return {
        "import_id": import_id,
        "imported": len(records),
        "entity_type": entity_type,
        "filename": filename,
    }


def _insert_accounts(db, import_id: int, records: list[dict]):
    db.executemany(
        """INSERT INTO accounts (import_id, name, type, detail_type, description, balance, currency, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [(import_id, r["name"], r["type"], r["detail_type"], r["description"],
          r["balance"], r["currency"], r["raw_data"]) for r in records],
    )


def _insert_customers(db, import_id: int, records: list[dict]):
    db.executemany(
        """INSERT INTO customers (import_id, display_name, email, phone, address, balance, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(import_id, r["display_name"], r["email"], r["phone"], r["address"],
          r["balance"], r["raw_data"]) for r in records],
    )


def _insert_vendors(db, import_id: int, records: list[dict]):
    db.executemany(
        """INSERT INTO vendors (import_id, display_name, email, phone, address, balance, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [(import_id, r["display_name"], r["email"], r["phone"], r["address"],
          r["balance"], r["raw_data"]) for r in records],
    )


def _insert_products(db, import_id: int, records: list[dict]):
    db.executemany(
        """INSERT INTO products (import_id, name, sku, type, description, price, cost, quantity_on_hand, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(import_id, r["name"], r["sku"], r["type"], r["description"],
          r["price"], r["cost"], r["quantity_on_hand"], r["raw_data"]) for r in records],
    )


def _insert_transactions(db, import_id: int, records: list[dict]):
    db.executemany(
        """INSERT INTO transactions
           (import_id, txn_type, txn_number, txn_date, due_date, entity_name, entity_type,
            account, category, description, amount, balance, status, payment_method, raw_data)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(import_id, r["txn_type"], r["txn_number"], r["txn_date"], r["due_date"],
          r["entity_name"], r["entity_type"], r["account"], r["category"],
          r["description"], r["amount"], r["balance"], r["status"],
          r["payment_method"], r["raw_data"]) for r in records],
    )


def _insert_journal_entries(db, import_id: int, records: list[dict]):
    for r in records:
        cursor = db.execute(
            """INSERT INTO transactions
               (import_id, txn_type, txn_number, txn_date, due_date, entity_name, entity_type,
                account, category, description, amount, balance, status, payment_method, raw_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, r["txn_type"], r["txn_number"], r["txn_date"], r["due_date"],
             r["entity_name"], r["entity_type"], r["account"], r["category"],
             r["description"], r["amount"], r["balance"], r["status"],
             r["payment_method"], r["raw_data"]),
        )
        txn_id = cursor.lastrowid
        db.execute(
            """INSERT INTO journal_lines
               (import_id, txn_id, journal_date, account, debit, credit, description, name, raw_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (import_id, txn_id, r.get("_journal_date", ""), r.get("_account", ""),
             r.get("_debit", 0), r.get("_credit", 0), r.get("_description", ""),
             r.get("_name", ""), r["raw_data"]),
        )


def delete_import(import_id: int) -> bool:
    """Delete an import and all its data (CASCADE)."""
    db = _get_db()
    with write_lock():
        cursor = db.execute("DELETE FROM imports WHERE id = ?", (import_id,))
        db.commit()
    return cursor.rowcount > 0


def list_imports() -> list[dict]:
    """List all imports, newest first."""
    rows = _get_db().execute(
        "SELECT * FROM imports ORDER BY imported_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Import from CSV text ─────────────────────────────────────────────────────

def import_csv_text(csv_content: str, filename: str, entity_type: str | None = None) -> dict:
    """Parse CSV text and import into the database.

    Returns: {import_id, imported, entity_type, filename, warnings, detected_by}
    """
    parsed = parse_csv_file(csv_content, filename, entity_type)
    if not parsed["entity_type"]:
        return {
            "error": "Could not detect entity type",
            "warnings": parsed["warnings"],
            "headers": parsed["headers"],
        }
    if not parsed["records"]:
        return {
            "error": "No records found in CSV",
            "entity_type": parsed["entity_type"],
            "warnings": parsed["warnings"],
        }

    result = import_records(parsed["entity_type"], parsed["records"], filename)
    result["warnings"] = parsed["warnings"]
    result["detected_by"] = parsed["detected_by"]
    return result


# ── Query operations ─────────────────────────────────────────────────────────

def query_transactions(
    txn_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    entity_name: str | None = None,
    category: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int = 100,
) -> list[dict]:
    """Search transactions with optional filters."""
    conditions = []
    params: list = []

    if txn_type:
        conditions.append("txn_type = ?")
        params.append(txn_type)
    if date_from:
        conditions.append("txn_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("txn_date <= ?")
        params.append(date_to)
    if entity_name:
        conditions.append("entity_name LIKE ?")
        params.append(f"%{entity_name}%")
    if category:
        conditions.append("(category LIKE ? OR account LIKE ?)")
        params.extend([f"%{category}%", f"%{category}%"])
    if min_amount is not None:
        conditions.append("amount >= ?")
        params.append(min_amount)
    if max_amount is not None:
        conditions.append("amount <= ?")
        params.append(max_amount)

    where = " AND ".join(conditions) if conditions else "1=1"
    params.append(min(limit, 500))

    rows = _get_db().execute(
        f"SELECT * FROM transactions WHERE {where} ORDER BY txn_date DESC LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def query_accounts(type: str | None = None, limit: int = 100) -> list[dict]:
    if type:
        rows = _get_db().execute(
            "SELECT * FROM accounts WHERE type = ? ORDER BY name LIMIT ?",
            (type, min(limit, 500)),
        ).fetchall()
    else:
        rows = _get_db().execute(
            "SELECT * FROM accounts ORDER BY name LIMIT ?", (min(limit, 500),)
        ).fetchall()
    return [dict(r) for r in rows]


def query_customers(search: str | None = None, limit: int = 50) -> list[dict]:
    if search:
        like = f"%{search}%"
        rows = _get_db().execute(
            "SELECT * FROM customers WHERE display_name LIKE ? OR email LIKE ? ORDER BY display_name LIMIT ?",
            (like, like, min(limit, 500)),
        ).fetchall()
    else:
        rows = _get_db().execute(
            "SELECT * FROM customers ORDER BY display_name LIMIT ?", (min(limit, 500),)
        ).fetchall()
    return [dict(r) for r in rows]


def query_vendors(search: str | None = None, limit: int = 50) -> list[dict]:
    if search:
        like = f"%{search}%"
        rows = _get_db().execute(
            "SELECT * FROM vendors WHERE display_name LIKE ? OR email LIKE ? ORDER BY display_name LIMIT ?",
            (like, like, min(limit, 500)),
        ).fetchall()
    else:
        rows = _get_db().execute(
            "SELECT * FROM vendors ORDER BY display_name LIMIT ?", (min(limit, 500),)
        ).fetchall()
    return [dict(r) for r in rows]


def query_products(search: str | None = None, limit: int = 50) -> list[dict]:
    if search:
        like = f"%{search}%"
        rows = _get_db().execute(
            "SELECT * FROM products WHERE name LIKE ? OR sku LIKE ? OR description LIKE ? ORDER BY name LIMIT ?",
            (like, like, like, min(limit, 500)),
        ).fetchall()
    else:
        rows = _get_db().execute(
            "SELECT * FROM products ORDER BY name LIMIT ?", (min(limit, 500),)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Analytics ────────────────────────────────────────────────────────────────

def get_financial_summary() -> dict:
    """Compute a financial overview from imported data."""
    db = _get_db()

    # Revenue: invoices only (payments are collections against invoices, not new income)
    income_row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE txn_type = 'invoice'"
    ).fetchone()
    total_income = income_row["total"] if income_row else 0

    # Payments received (separate from revenue to avoid double-counting)
    payments_row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE txn_type = 'payment'"
    ).fetchone()
    payments_received = payments_row["total"] if payments_row else 0

    # Expenses: bills + expenses
    expense_row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE txn_type IN ('bill', 'expense')"
    ).fetchone()
    total_expenses = expense_row["total"] if expense_row else 0

    # Accounts receivable (open invoice balances)
    ar_row = db.execute(
        "SELECT COALESCE(SUM(balance), 0) as total FROM transactions WHERE txn_type = 'invoice' AND balance > 0"
    ).fetchone()
    accounts_receivable = ar_row["total"] if ar_row else 0

    # Accounts payable (open bill balances)
    ap_row = db.execute(
        "SELECT COALESCE(SUM(balance), 0) as total FROM transactions WHERE txn_type = 'bill' AND balance > 0"
    ).fetchone()
    accounts_payable = ap_row["total"] if ap_row else 0

    # Top expense categories
    top_categories = [dict(r) for r in db.execute(
        """SELECT category, SUM(amount) as total FROM transactions
           WHERE txn_type IN ('bill', 'expense') AND category != ''
           GROUP BY category ORDER BY total DESC LIMIT 10"""
    ).fetchall()]

    # Top customers by revenue
    top_customers = [dict(r) for r in db.execute(
        """SELECT entity_name, SUM(amount) as total FROM transactions
           WHERE txn_type = 'invoice' AND entity_name != ''
           GROUP BY entity_name ORDER BY total DESC LIMIT 10"""
    ).fetchall()]

    # Top vendors by spend
    top_vendors = [dict(r) for r in db.execute(
        """SELECT entity_name, SUM(amount) as total FROM transactions
           WHERE txn_type IN ('bill', 'expense') AND entity_name != ''
           GROUP BY entity_name ORDER BY total DESC LIMIT 10"""
    ).fetchall()]

    # Monthly income vs expenses (invoices only for income, not payments)
    monthly = [dict(r) for r in db.execute(
        """SELECT
             substr(txn_date, 1, 7) as month,
             SUM(CASE WHEN txn_type = 'invoice' THEN amount ELSE 0 END) as income,
             SUM(CASE WHEN txn_type IN ('bill', 'expense') THEN amount ELSE 0 END) as expenses
           FROM transactions
           WHERE txn_date != ''
           GROUP BY month ORDER BY month"""
    ).fetchall()]

    # Transaction counts
    counts = {}
    for row in db.execute(
        "SELECT txn_type, COUNT(*) as cnt FROM transactions GROUP BY txn_type"
    ).fetchall():
        counts[row["txn_type"]] = row["cnt"]

    # Date range
    date_range = db.execute(
        "SELECT MIN(txn_date) as earliest, MAX(txn_date) as latest FROM transactions WHERE txn_date != ''"
    ).fetchone()

    # Entity counts
    customer_count = db.execute("SELECT COUNT(*) as cnt FROM customers").fetchone()["cnt"]
    vendor_count = db.execute("SELECT COUNT(*) as cnt FROM vendors").fetchone()["cnt"]
    account_count = db.execute("SELECT COUNT(*) as cnt FROM accounts").fetchone()["cnt"]
    product_count = db.execute("SELECT COUNT(*) as cnt FROM products").fetchone()["cnt"]

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "net_income": total_income - total_expenses,
        "payments_received": payments_received,
        "accounts_receivable": accounts_receivable,
        "accounts_payable": accounts_payable,
        "top_expense_categories": top_categories,
        "top_customers_by_revenue": top_customers,
        "top_vendors_by_spend": top_vendors,
        "monthly_income_expense": monthly,
        "transaction_counts": counts,
        "data_date_range": {
            "earliest": date_range["earliest"] if date_range else None,
            "latest": date_range["latest"] if date_range else None,
        },
        "entity_counts": {
            "customers": customer_count,
            "vendors": vendor_count,
            "accounts": account_count,
            "products": product_count,
        },
    }


def find_duplicates() -> dict:
    """Scan for potential duplicate transactions (same date, amount, entity)."""
    db = _get_db()
    rows = db.execute(
        """SELECT t1.id as id_a, t2.id as id_b,
                  t1.txn_type, t1.txn_date, t1.entity_name, t1.amount,
                  t1.txn_number as num_a, t2.txn_number as num_b
           FROM transactions t1
           JOIN transactions t2 ON t1.id < t2.id
                AND t1.txn_type = t2.txn_type
                AND t1.txn_date = t2.txn_date
                AND t1.amount = t2.amount
                AND t1.entity_name = t2.entity_name
                AND t1.entity_name != ''
           ORDER BY t1.txn_date DESC
           LIMIT 100"""
    ).fetchall()
    duplicates = [dict(r) for r in rows]
    return {"duplicates": duplicates, "count": len(duplicates)}


def find_uncategorized() -> dict:
    """Find transactions with empty category/account fields."""
    db = _get_db()
    rows = db.execute(
        """SELECT * FROM transactions
           WHERE (category = '' AND account = '')
           ORDER BY txn_date DESC LIMIT 100"""
    ).fetchall()
    uncategorized = [dict(r) for r in rows]
    return {"uncategorized": uncategorized, "count": len(uncategorized)}


# ── Raw SQL ──────────────────────────────────────────────────────────────────

def run_sql(sql: str) -> dict:
    """Execute a read-only SQL query against the QB CSV database.

    Safety: only SELECT allowed, row limit enforced.
    """
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed"}

    # Enforce row limit if not present
    if "LIMIT" not in stripped.upper():
        stripped = stripped.rstrip(";") + " LIMIT 500"

    try:
        db = _get_db()
        cursor = db.execute(stripped)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = [list(r) for r in cursor.fetchall()]
        return {"columns": columns, "rows": rows, "count": len(rows)}
    except Exception as e:
        return {"error": str(e)}
