"""
Chatty — QuickBooks CSV Analysis SQLite database.

Stores imported QBO export data for persistent querying and analysis.
Schema: imports, accounts, customers, vendors, products, transactions, journal_lines.
"""

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "integrations"
DB_PATH = DATA_DIR / "qb_csv.db"

_connection: sqlite3.Connection | None = None
_write_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("QB CSV DB not initialized — call init_db() first")
    return _connection


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema."""
    migrations: list[str] = []
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    conn.commit()


def init_db() -> None:
    """Initialize the QB CSV Analysis DB."""
    global _connection
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    _connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    _connection.row_factory = sqlite3.Row
    _connection.execute("PRAGMA journal_mode=WAL")
    _connection.execute("PRAGMA foreign_keys=ON")
    _connection.execute("PRAGMA busy_timeout=5000")

    _connection.executescript("""
        -- Import tracking
        CREATE TABLE IF NOT EXISTS imports (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT NOT NULL,
            entity_type  TEXT NOT NULL,
            row_count    INTEGER NOT NULL DEFAULT 0,
            imported_at  TEXT NOT NULL DEFAULT (datetime('now')),
            status       TEXT NOT NULL DEFAULT 'complete'
        );

        -- Chart of Accounts
        CREATE TABLE IF NOT EXISTS accounts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id     INTEGER REFERENCES imports(id) ON DELETE CASCADE,
            name          TEXT NOT NULL,
            type          TEXT NOT NULL DEFAULT '',
            detail_type   TEXT NOT NULL DEFAULT '',
            description   TEXT NOT NULL DEFAULT '',
            balance       REAL NOT NULL DEFAULT 0,
            currency      TEXT NOT NULL DEFAULT 'USD',
            raw_data      TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name);
        CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(type);

        -- Customers
        CREATE TABLE IF NOT EXISTS customers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id     INTEGER REFERENCES imports(id) ON DELETE CASCADE,
            display_name  TEXT NOT NULL,
            email         TEXT NOT NULL DEFAULT '',
            phone         TEXT NOT NULL DEFAULT '',
            address       TEXT NOT NULL DEFAULT '',
            balance       REAL NOT NULL DEFAULT 0,
            raw_data      TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(display_name);

        -- Vendors
        CREATE TABLE IF NOT EXISTS vendors (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id     INTEGER REFERENCES imports(id) ON DELETE CASCADE,
            display_name  TEXT NOT NULL,
            email         TEXT NOT NULL DEFAULT '',
            phone         TEXT NOT NULL DEFAULT '',
            address       TEXT NOT NULL DEFAULT '',
            balance       REAL NOT NULL DEFAULT 0,
            raw_data      TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_vendors_name ON vendors(display_name);

        -- Products & Services
        CREATE TABLE IF NOT EXISTS products (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id         INTEGER REFERENCES imports(id) ON DELETE CASCADE,
            name              TEXT NOT NULL,
            sku               TEXT NOT NULL DEFAULT '',
            type              TEXT NOT NULL DEFAULT '',
            description       TEXT NOT NULL DEFAULT '',
            price             REAL NOT NULL DEFAULT 0,
            cost              REAL NOT NULL DEFAULT 0,
            quantity_on_hand  REAL NOT NULL DEFAULT 0,
            raw_data          TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);

        -- Unified transactions (invoices, bills, expenses, payments)
        CREATE TABLE IF NOT EXISTS transactions (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id         INTEGER REFERENCES imports(id) ON DELETE CASCADE,
            txn_type          TEXT NOT NULL,
            txn_number        TEXT NOT NULL DEFAULT '',
            txn_date          TEXT NOT NULL DEFAULT '',
            due_date          TEXT NOT NULL DEFAULT '',
            entity_name       TEXT NOT NULL DEFAULT '',
            entity_type       TEXT NOT NULL DEFAULT '',
            account           TEXT NOT NULL DEFAULT '',
            category          TEXT NOT NULL DEFAULT '',
            description       TEXT NOT NULL DEFAULT '',
            amount            REAL NOT NULL DEFAULT 0,
            balance           REAL NOT NULL DEFAULT 0,
            status            TEXT NOT NULL DEFAULT '',
            payment_method    TEXT NOT NULL DEFAULT '',
            raw_data          TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(txn_type);
        CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date);
        CREATE INDEX IF NOT EXISTS idx_txn_entity ON transactions(entity_name);
        CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);
        CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account);

        -- Journal entry line items
        CREATE TABLE IF NOT EXISTS journal_lines (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id         INTEGER REFERENCES imports(id) ON DELETE CASCADE,
            txn_id            INTEGER REFERENCES transactions(id) ON DELETE CASCADE,
            journal_date      TEXT NOT NULL DEFAULT '',
            account           TEXT NOT NULL DEFAULT '',
            debit             REAL NOT NULL DEFAULT 0,
            credit            REAL NOT NULL DEFAULT 0,
            description       TEXT NOT NULL DEFAULT '',
            name              TEXT NOT NULL DEFAULT '',
            raw_data          TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_jl_account ON journal_lines(account);
        CREATE INDEX IF NOT EXISTS idx_jl_date ON journal_lines(journal_date);
    """)
    _connection.commit()

    _apply_migrations(_connection)
    logger.info("QB CSV Analysis DB initialized at %s", DB_PATH)


def close_db() -> None:
    """Close the QB CSV DB connection (for backup/restore)."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


def write_lock() -> threading.Lock:
    return _write_lock
