"""Chatty — QuickBooks CSV Analysis agent tools (8 tools).

Query, analyze, and manage imported QuickBooks CSV data — all accessible
to the AI agent for financial analysis without API connection.
"""

from . import client as qb

# ═══════════════════════════════════════════════════════════════════════════════
# Tool Definitions (schema only — sent to the AI provider)
# ═══════════════════════════════════════════════════════════════════════════════

QB_CSV_TOOL_DEFS = [
    # ── Query & Analysis (6 tools) ─────────────────────────────────────────────
    {
        "name": "qb_csv_query",
        "description": (
            "Query imported QuickBooks CSV data using SQL. "
            "Tables: accounts (name, type, detail_type, balance), "
            "customers (display_name, email, phone, balance), "
            "vendors (display_name, email, phone, balance), "
            "products (name, sku, type, price, cost, quantity_on_hand), "
            "transactions (txn_type, txn_number, txn_date, due_date, entity_name, "
            "category, amount, balance, status — txn_type: invoice/bill/expense/payment/journal_entry), "
            "journal_lines (journal_date, account, debit, credit, description), "
            "imports (filename, entity_type, row_count, imported_at). "
            "SELECT only. Max 500 rows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL SELECT query against the QB CSV database"},
            },
            "required": ["sql"],
        },
        "kind": "integration",
    },
    {
        "name": "qb_csv_financial_summary",
        "description": (
            "Get a financial overview from imported QuickBooks data: total income, expenses, "
            "net income, accounts receivable/payable, top expense categories, top customers "
            "by revenue, top vendors by spend, monthly trends, and entity counts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "qb_csv_find_duplicates",
        "description": (
            "Scan imported QuickBooks data for potential duplicate transactions "
            "(same date, amount, and entity within the same transaction type)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "qb_csv_find_issues",
        "description": (
            "Find data quality issues in imported QuickBooks data: "
            "uncategorized transactions (empty category and account fields)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "qb_csv_list_imports",
        "description": "List all QuickBooks CSV files that have been imported, with row counts and dates.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "kind": "integration",
    },
    {
        "name": "qb_csv_search_transactions",
        "description": (
            "Search imported transactions with filters. Supports filtering by type "
            "(invoice, bill, expense, payment, journal_entry), date range, entity name, "
            "category, and amount range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "txn_type": {
                    "type": "string",
                    "description": "Filter: invoice, bill, expense, payment, journal_entry",
                },
                "date_from": {"type": "string", "description": "Start date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "End date YYYY-MM-DD"},
                "entity_name": {"type": "string", "description": "Customer or vendor name (partial match)"},
                "category": {"type": "string", "description": "Category or account (partial match)"},
                "min_amount": {"type": "number", "description": "Minimum amount"},
                "max_amount": {"type": "number", "description": "Maximum amount"},
                "limit": {"type": "integer", "description": "Max results (default 50)", "default": 50},
            },
            "required": [],
        },
        "kind": "integration",
    },

    # ── Import & Management (2 tools) ──────────────────────────────────────────
    {
        "name": "qb_csv_import_csv",
        "description": (
            "Import a QuickBooks CSV file into persistent storage for ongoing analysis. "
            "Call this when the user uploads QBO CSV files and wants to save them. "
            "The entity type (accounts, customers, invoices, etc.) is auto-detected "
            "from column headers. After importing, use qb_csv_financial_summary to "
            "show the user an overview of their data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "csv_content": {"type": "string", "description": "The raw CSV text content"},
                "filename": {"type": "string", "description": "Original filename for detection hints"},
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Override auto-detection: accounts, customers, vendors, products, "
                        "invoices, bills, expenses, payments, journal_entries"
                    ),
                },
            },
            "required": ["csv_content", "filename"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "qb_csv_delete_import",
        "description": "Delete a previously imported CSV file and all its data. Use import_id from qb_csv_list_imports.",
        "input_schema": {
            "type": "object",
            "properties": {
                "import_id": {"type": "integer", "description": "Import ID to delete"},
            },
            "required": ["import_id"],
        },
        "kind": "integration",
        "writes": True,
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Executor Functions
# ═══════════════════════════════════════════════════════════════════════════════

def qb_csv_query(sql: str) -> dict:
    return qb.run_sql(sql)


def qb_csv_financial_summary() -> dict:
    return qb.get_financial_summary()


def qb_csv_find_duplicates() -> dict:
    return qb.find_duplicates()


def qb_csv_find_issues() -> dict:
    return qb.find_uncategorized()


def qb_csv_list_imports() -> dict:
    imports = qb.list_imports()
    return {"imports": imports, "count": len(imports)}


def qb_csv_search_transactions(
    txn_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    entity_name: str | None = None,
    category: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int = 50,
) -> dict:
    txns = qb.query_transactions(
        txn_type=txn_type, date_from=date_from, date_to=date_to,
        entity_name=entity_name, category=category,
        min_amount=min_amount, max_amount=max_amount, limit=limit,
    )
    return {"transactions": txns, "count": len(txns)}


def qb_csv_import_csv(csv_content: str, filename: str, entity_type: str | None = None) -> dict:
    return qb.import_csv_text(csv_content, filename, entity_type)


def qb_csv_delete_import(import_id: int) -> dict:
    if qb.delete_import(import_id):
        return {"deleted": True, "import_id": import_id}
    return {"error": f"Import {import_id} not found"}


# ═══════════════════════════════════════════════════════════════════════════════
# Executor Mapping (used by ToolRegistry)
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_EXECUTORS = {
    "qb_csv_query": lambda **kw: qb_csv_query(**kw),
    "qb_csv_financial_summary": lambda **kw: qb_csv_financial_summary(**kw),
    "qb_csv_find_duplicates": lambda **kw: qb_csv_find_duplicates(**kw),
    "qb_csv_find_issues": lambda **kw: qb_csv_find_issues(**kw),
    "qb_csv_list_imports": lambda **kw: qb_csv_list_imports(**kw),
    "qb_csv_search_transactions": lambda **kw: qb_csv_search_transactions(**kw),
    "qb_csv_import_csv": lambda **kw: qb_csv_import_csv(**kw),
    "qb_csv_delete_import": lambda **kw: qb_csv_delete_import(**kw),
}
