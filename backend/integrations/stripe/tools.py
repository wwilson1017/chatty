"""
Chatty — Stripe integration tools.

17 agent-callable tools for Stripe payments, customers, invoices,
subscriptions, products, prices, payment links, and payouts.
"""

import logging

import stripe

from .client import StripeClient, get_client

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────────────

_ZERO_DECIMAL = {
    "bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga",
    "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
}


def _to_stripe_amount(amount: float, currency: str = "usd") -> int:
    if currency.lower() in _ZERO_DECIMAL:
        return int(round(amount))
    return int(round(amount * 100))


def _from_stripe_amount(amount: int | None, currency: str = "usd") -> float:
    if amount is None:
        return 0.0
    if currency.lower() in _ZERO_DECIMAL:
        return float(amount)
    return amount / 100.0


def _require_client() -> StripeClient:
    client = get_client()
    if not client:
        raise ValueError("Stripe not configured. Connect at Settings > Integrations.")
    return client


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _stripe_error(e: stripe.error.StripeError) -> dict:
    return {"error": str(getattr(e, "user_message", None) or e)}


def _run(fn) -> dict:
    try:
        return fn()
    except ValueError as e:
        return {"error": str(e)}
    except stripe.error.StripeError as e:
        return _stripe_error(e)


# ── Tool definitions ─────────────────────────────────────────────────────────

STRIPE_TOOL_DEFS = [
    # --- Customers ---
    {
        "name": "stripe_create_customer",
        "description": "Create a new customer in Stripe.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Customer email address"},
                "name": {"type": "string", "description": "Customer full name"},
                "phone": {"type": "string", "description": "Customer phone number"},
                "description": {"type": "string", "description": "Internal notes"},
                "address_line1": {"type": "string", "description": "Street address"},
                "address_city": {"type": "string", "description": "City"},
                "address_state": {"type": "string", "description": "State/province"},
                "address_postal_code": {"type": "string", "description": "ZIP/postal code"},
                "address_country": {"type": "string", "description": "Two-letter country code (US, GB, etc.)"},
            },
            "required": [],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "stripe_retrieve_customer",
        "description": "Retrieve a Stripe customer by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Stripe customer ID (cus_xxx)"},
            },
            "required": ["customer_id"],
        },
        "kind": "integration",
    },
    {
        "name": "stripe_update_customer",
        "description": "Update an existing Stripe customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Stripe customer ID (cus_xxx)"},
                "email": {"type": "string", "description": "New email address"},
                "name": {"type": "string", "description": "New full name"},
                "phone": {"type": "string", "description": "New phone number"},
                "description": {"type": "string", "description": "New internal notes"},
                "address_line1": {"type": "string", "description": "Street address"},
                "address_city": {"type": "string", "description": "City"},
                "address_state": {"type": "string", "description": "State/province"},
                "address_postal_code": {"type": "string", "description": "ZIP/postal code"},
                "address_country": {"type": "string", "description": "Two-letter country code"},
            },
            "required": ["customer_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "stripe_search_customers",
        "description": "Search for Stripe customers by email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email address to search for"},
            },
            "required": ["email"],
        },
        "kind": "integration",
    },
    # --- Invoices ---
    {
        "name": "stripe_create_invoice",
        "description": "Create an invoice for a customer. Include line_items to add charges.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Stripe customer ID (cus_xxx)"},
                "line_items": {
                    "type": "array",
                    "description": "Invoice line items",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string", "description": "Line item description"},
                            "amount": {"type": "number", "description": "Unit price in currency units (e.g., 49.99)"},
                            "quantity": {"type": "integer", "description": "Quantity (default: 1)"},
                        },
                        "required": ["description", "amount"],
                    },
                },
                "currency": {"type": "string", "description": "Three-letter currency code (default: usd)"},
                "days_until_due": {"type": "integer", "description": "Days until payment is due"},
                "auto_advance": {"type": "boolean", "description": "Auto-finalize the invoice (default: true)"},
                "description": {"type": "string", "description": "Invoice memo/description"},
            },
            "required": ["customer_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "stripe_retrieve_invoice",
        "description": "Retrieve a Stripe invoice by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string", "description": "Stripe invoice ID (in_xxx)"},
            },
            "required": ["invoice_id"],
        },
        "kind": "integration",
    },
    # --- Payment Intents ---
    {
        "name": "stripe_create_payment_intent",
        "description": "Create a payment intent. Amount in currency units (e.g., 49.99 for $49.99).",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "Amount in currency units (e.g., 49.99 for $49.99)"},
                "currency": {"type": "string", "description": "Three-letter currency code (default: usd)"},
                "customer_id": {"type": "string", "description": "Stripe customer ID (cus_xxx)"},
                "description": {"type": "string", "description": "Description of the charge"},
                "payment_method": {"type": "string", "description": "Payment method ID (pm_xxx)"},
                "receipt_email": {"type": "string", "description": "Email for receipt"},
            },
            "required": ["amount"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "stripe_retrieve_payment_intent",
        "description": "Retrieve a Stripe payment intent by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_intent_id": {"type": "string", "description": "Payment intent ID (pi_xxx)"},
            },
            "required": ["payment_intent_id"],
        },
        "kind": "integration",
    },
    # --- Refunds ---
    {
        "name": "stripe_create_refund",
        "description": "Create a refund for a payment. Omit amount for a full refund.",
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_intent": {"type": "string", "description": "Payment intent ID to refund (pi_xxx)"},
                "amount": {"type": "number", "description": "Partial refund amount in currency units (omit for full refund)"},
                "reason": {"type": "string", "enum": ["duplicate", "fraudulent", "requested_by_customer"], "description": "Reason for refund"},
            },
            "required": ["payment_intent"],
        },
        "kind": "integration",
        "writes": True,
    },
    # --- Products ---
    {
        "name": "stripe_create_product",
        "description": "Create a product in Stripe.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Product name"},
                "description": {"type": "string", "description": "Product description"},
                "images": {"type": "array", "items": {"type": "string"}, "description": "List of image URLs (max 8)"},
                "metadata": {"type": "object", "description": "Key-value metadata"},
            },
            "required": ["name"],
        },
        "kind": "integration",
        "writes": True,
    },
    # --- Prices ---
    {
        "name": "stripe_create_price",
        "description": "Create a price for a product (one-time or recurring). Amount in currency units.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "Stripe product ID (prod_xxx)"},
                "unit_amount": {"type": "number", "description": "Price in currency units (e.g., 25.50 for $25.50)"},
                "currency": {"type": "string", "description": "Three-letter currency code (default: usd)"},
                "recurring_interval": {
                    "type": "string",
                    "enum": ["one_time", "day", "week", "month", "year"],
                    "description": "Billing interval (default: one_time)",
                },
                "interval_count": {"type": "integer", "description": "Intervals between billings (e.g., 3 for quarterly)"},
            },
            "required": ["product_id", "unit_amount"],
        },
        "kind": "integration",
        "writes": True,
    },
    # --- Subscriptions ---
    {
        "name": "stripe_create_subscription",
        "description": "Create a subscription for a customer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Stripe customer ID (cus_xxx)"},
                "items": {
                    "type": "array",
                    "description": "Price items to subscribe to",
                    "items": {
                        "type": "object",
                        "properties": {
                            "price_id": {"type": "string", "description": "Stripe price ID (price_xxx)"},
                            "quantity": {"type": "integer", "description": "Quantity (default: 1)"},
                        },
                        "required": ["price_id"],
                    },
                },
                "collection_method": {
                    "type": "string",
                    "enum": ["charge_automatically", "send_invoice"],
                    "description": "How to collect payment",
                },
                "days_until_due": {"type": "integer", "description": "Days until invoice is due (required if send_invoice)"},
                "trial_period_days": {"type": "integer", "description": "Free trial days"},
                "default_payment_method": {"type": "string", "description": "Payment method ID (pm_xxx)"},
            },
            "required": ["customer_id", "items"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "stripe_cancel_subscription",
        "description": "Cancel a subscription immediately or at period end.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subscription_id": {"type": "string", "description": "Stripe subscription ID (sub_xxx)"},
                "cancel_at_period_end": {"type": "boolean", "description": "If true, cancel at end of current period instead of immediately (default: false)"},
            },
            "required": ["subscription_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "stripe_search_subscriptions",
        "description": "Search for subscriptions with filters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "past_due", "unpaid", "canceled", "incomplete", "trialing", "paused"],
                    "description": "Filter by status",
                },
                "customer_id": {"type": "string", "description": "Filter by customer ID"},
                "price_id": {"type": "string", "description": "Filter by price ID"},
                "limit": {"type": "integer", "description": "Max results (default: 20)"},
            },
            "required": [],
        },
        "kind": "integration",
    },
    # --- Payment Links ---
    {
        "name": "stripe_create_payment_link",
        "description": "Create a shareable payment link. Returns a URL the customer can use to pay.",
        "input_schema": {
            "type": "object",
            "properties": {
                "line_items": {
                    "type": "array",
                    "description": "Items to include in the payment link",
                    "items": {
                        "type": "object",
                        "properties": {
                            "price_id": {"type": "string", "description": "Stripe price ID (price_xxx)"},
                            "quantity": {"type": "integer", "description": "Quantity (default: 1)"},
                        },
                        "required": ["price_id"],
                    },
                },
                "after_completion_type": {
                    "type": "string",
                    "enum": ["hosted_confirmation", "redirect"],
                    "description": "What happens after payment (default: hosted_confirmation)",
                },
                "redirect_url": {"type": "string", "description": "URL to redirect to after payment (required if redirect)"},
            },
            "required": ["line_items"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "stripe_deactivate_payment_link",
        "description": "Deactivate a payment link so it can no longer be used.",
        "input_schema": {
            "type": "object",
            "properties": {
                "payment_link_id": {"type": "string", "description": "Payment link ID (plink_xxx)"},
            },
            "required": ["payment_link_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    # --- Payouts ---
    {
        "name": "stripe_retrieve_payout",
        "description": "Retrieve details of a Stripe payout.",
        "input_schema": {
            "type": "object",
            "properties": {
                "payout_id": {"type": "string", "description": "Payout ID (po_xxx)"},
            },
            "required": ["payout_id"],
        },
        "kind": "integration",
    },
]


# ── Executors ────────────────────────────────────────────────────────────────

def _build_address(**kw) -> dict:
    addr = _drop_none({
        "line1": kw.get("address_line1"),
        "city": kw.get("address_city"),
        "state": kw.get("address_state"),
        "postal_code": kw.get("address_postal_code"),
        "country": kw.get("address_country"),
    })
    return addr


def _fmt_customer(c) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "created": c.created,
    }


# --- Customers ---

def stripe_create_customer(email=None, name=None, phone=None, description=None, **kw):
    def _do():
        c = _require_client()
        params = _drop_none({"email": email, "name": name, "phone": phone, "description": description})
        address = _build_address(**kw)
        if address:
            params["address"] = address
        cust = stripe.Customer.create(api_key=c.api_key, **params)
        return {"ok": True, "customer": _fmt_customer(cust)}
    return _run(_do)


def stripe_retrieve_customer(customer_id, **_):
    def _do():
        c = _require_client()
        cust = stripe.Customer.retrieve(customer_id, api_key=c.api_key)
        return {"ok": True, "customer": _fmt_customer(cust)}
    return _run(_do)


def stripe_update_customer(customer_id, email=None, name=None, phone=None, description=None, **kw):
    def _do():
        c = _require_client()
        params = _drop_none({"email": email, "name": name, "phone": phone, "description": description})
        address = _build_address(**kw)
        if address:
            params["address"] = address
        cust = stripe.Customer.modify(customer_id, api_key=c.api_key, **params)
        return {"ok": True, "customer": _fmt_customer(cust)}
    return _run(_do)


def stripe_search_customers(email, **_):
    def _do():
        c = _require_client()
        result = stripe.Customer.search(
            api_key=c.api_key,
            query=f"email:'{email}'",
        )
        customers = [_fmt_customer(cust) for cust in result.data]
        return {"ok": True, "customers": customers, "count": len(customers)}
    return _run(_do)


# --- Invoices ---

def stripe_create_invoice(customer_id, line_items=None, currency="usd",
                          days_until_due=None, auto_advance=True, description=None, **_):
    def _do():
        c = _require_client()
        if line_items:
            for item in line_items:
                qty = item.get("quantity", 1)
                unit_price = item.get("amount", 0)
                stripe.InvoiceItem.create(
                    api_key=c.api_key,
                    customer=customer_id,
                    amount=_to_stripe_amount(unit_price * qty, currency),
                    currency=currency,
                    description=item.get("description", ""),
                    quantity=qty,
                )
        params = _drop_none({
            "customer": customer_id,
            "currency": currency,
            "auto_advance": auto_advance,
            "description": description,
            "pending_invoice_items_behavior": "include",
        })
        if days_until_due is not None:
            params["collection_method"] = "send_invoice"
            params["days_until_due"] = days_until_due
        inv = stripe.Invoice.create(api_key=c.api_key, **params)
        return {
            "ok": True,
            "invoice": {
                "id": inv.id,
                "status": inv.status,
                "amount_due": _from_stripe_amount(inv.amount_due, currency),
                "currency": inv.currency,
                "hosted_invoice_url": inv.hosted_invoice_url,
            },
        }
    return _run(_do)


def stripe_retrieve_invoice(invoice_id, **_):
    def _do():
        c = _require_client()
        inv = stripe.Invoice.retrieve(invoice_id, api_key=c.api_key)
        return {
            "ok": True,
            "invoice": {
                "id": inv.id,
                "status": inv.status,
                "amount_due": _from_stripe_amount(inv.amount_due, inv.currency or "usd"),
                "amount_paid": _from_stripe_amount(inv.amount_paid, inv.currency or "usd"),
                "currency": inv.currency,
                "customer": inv.customer,
                "hosted_invoice_url": inv.hosted_invoice_url,
            },
        }
    return _run(_do)


# --- Payment Intents ---

def stripe_create_payment_intent(amount, currency="usd", customer_id=None,
                                 description=None, payment_method=None,
                                 receipt_email=None, **_):
    def _do():
        c = _require_client()
        params = {
            "amount": _to_stripe_amount(amount, currency),
            "currency": currency.lower(),
        }
        params.update(_drop_none({
            "customer": customer_id,
            "description": description,
            "payment_method": payment_method,
            "receipt_email": receipt_email,
        }))
        intent = stripe.PaymentIntent.create(api_key=c.api_key, **params)
        return {
            "ok": True,
            "payment_intent": {
                "id": intent.id,
                "amount": _from_stripe_amount(intent.amount, currency),
                "currency": intent.currency,
                "status": intent.status,
                "client_secret": intent.client_secret,
            },
        }
    return _run(_do)


def stripe_retrieve_payment_intent(payment_intent_id, **_):
    def _do():
        c = _require_client()
        intent = stripe.PaymentIntent.retrieve(payment_intent_id, api_key=c.api_key)
        return {
            "ok": True,
            "payment_intent": {
                "id": intent.id,
                "amount": _from_stripe_amount(intent.amount, intent.currency or "usd"),
                "currency": intent.currency,
                "status": intent.status,
                "customer": intent.customer,
            },
        }
    return _run(_do)


# --- Refunds ---

def stripe_create_refund(payment_intent, amount=None, reason=None, **_):
    def _do():
        c = _require_client()
        params = {"payment_intent": payment_intent}
        if amount is not None:
            params["amount"] = _to_stripe_amount(amount, "usd")
        if reason:
            params["reason"] = reason
        refund = stripe.Refund.create(api_key=c.api_key, **params)
        return {
            "ok": True,
            "refund": {
                "id": refund.id,
                "amount": _from_stripe_amount(refund.amount, refund.currency or "usd"),
                "currency": refund.currency,
                "status": refund.status,
            },
        }
    return _run(_do)


# --- Products ---

def stripe_create_product(name, description=None, images=None, metadata=None, **_):
    def _do():
        c = _require_client()
        params = {"name": name}
        if description:
            params["description"] = description
        if images:
            params["images"] = images[:8]
        if metadata and isinstance(metadata, dict):
            params["metadata"] = metadata
        product = stripe.Product.create(api_key=c.api_key, **params)
        return {
            "ok": True,
            "product": {
                "id": product.id,
                "name": product.name,
                "description": product.description,
            },
        }
    return _run(_do)


# --- Prices ---

def stripe_create_price(product_id, unit_amount, currency="usd",
                        recurring_interval="one_time", interval_count=None, **_):
    def _do():
        c = _require_client()
        params = {
            "product": product_id,
            "unit_amount": _to_stripe_amount(unit_amount, currency),
            "currency": currency.lower(),
        }
        if recurring_interval and recurring_interval != "one_time":
            rec = {"interval": recurring_interval}
            if interval_count:
                rec["interval_count"] = interval_count
            params["recurring"] = rec
        price = stripe.Price.create(api_key=c.api_key, **params)
        return {
            "ok": True,
            "price": {
                "id": price.id,
                "unit_amount": _from_stripe_amount(price.unit_amount, currency),
                "currency": price.currency,
                "type": price.type,
            },
        }
    return _run(_do)


# --- Subscriptions ---

def stripe_create_subscription(customer_id, items, collection_method=None,
                               days_until_due=None, trial_period_days=None,
                               default_payment_method=None, **_):
    def _do():
        c = _require_client()
        sub_items = []
        for item in items:
            entry = {"price": item.get("price_id", item.get("price", ""))}
            qty = item.get("quantity")
            if qty:
                entry["quantity"] = qty
            sub_items.append(entry)
        params = {"customer": customer_id, "items": sub_items}
        params.update(_drop_none({
            "collection_method": collection_method,
            "days_until_due": days_until_due,
            "trial_period_days": trial_period_days,
            "default_payment_method": default_payment_method,
        }))
        sub = stripe.Subscription.create(api_key=c.api_key, **params)
        return {
            "ok": True,
            "subscription": {
                "id": sub.id,
                "status": sub.status,
                "current_period_end": sub.current_period_end,
                "customer": sub.customer,
            },
        }
    return _run(_do)


def stripe_cancel_subscription(subscription_id, cancel_at_period_end=False, **_):
    def _do():
        c = _require_client()
        if cancel_at_period_end:
            sub = stripe.Subscription.modify(
                subscription_id, api_key=c.api_key, cancel_at_period_end=True,
            )
        else:
            sub = stripe.Subscription.cancel(subscription_id, api_key=c.api_key)
        return {
            "ok": True,
            "subscription": {
                "id": sub.id,
                "status": sub.status,
                "cancel_at_period_end": sub.cancel_at_period_end,
            },
        }
    return _run(_do)


def stripe_search_subscriptions(status=None, customer_id=None, price_id=None,
                                limit=20, **_):
    def _do():
        c = _require_client()
        params = _drop_none({
            "status": status,
            "customer": customer_id,
            "price": price_id,
            "limit": min(limit or 20, 100),
        })
        result = stripe.Subscription.list(api_key=c.api_key, **params)
        subs = [
            {
                "id": s.id,
                "status": s.status,
                "customer": s.customer,
                "current_period_end": s.current_period_end,
                "cancel_at_period_end": s.cancel_at_period_end,
            }
            for s in result.data
        ]
        return {"ok": True, "subscriptions": subs, "count": len(subs)}
    return _run(_do)


# --- Payment Links ---

def stripe_create_payment_link(line_items, after_completion_type=None,
                               redirect_url=None, **_):
    def _do():
        c = _require_client()
        items = [
            {"price": it.get("price_id", it.get("price", "")), "quantity": it.get("quantity", 1)}
            for it in line_items
        ]
        params: dict = {"line_items": items}
        if after_completion_type:
            completion: dict = {"type": after_completion_type}
            if after_completion_type == "redirect" and redirect_url:
                completion["redirect"] = {"url": redirect_url}
            params["after_completion"] = completion
        link = stripe.PaymentLink.create(api_key=c.api_key, **params)
        return {
            "ok": True,
            "payment_link": {
                "id": link.id,
                "url": link.url,
                "active": link.active,
            },
        }
    return _run(_do)


def stripe_deactivate_payment_link(payment_link_id, **_):
    def _do():
        c = _require_client()
        link = stripe.PaymentLink.modify(payment_link_id, api_key=c.api_key, active=False)
        return {
            "ok": True,
            "payment_link": {
                "id": link.id,
                "url": link.url,
                "active": link.active,
            },
        }
    return _run(_do)


# --- Payouts ---

def stripe_retrieve_payout(payout_id, **_):
    def _do():
        c = _require_client()
        payout = stripe.Payout.retrieve(payout_id, api_key=c.api_key)
        return {
            "ok": True,
            "payout": {
                "id": payout.id,
                "amount": _from_stripe_amount(payout.amount, payout.currency or "usd"),
                "currency": payout.currency,
                "status": payout.status,
                "arrival_date": payout.arrival_date,
            },
        }
    return _run(_do)


# ── Executor map ─────────────────────────────────────────────────────────────

TOOL_EXECUTORS = {
    "stripe_create_customer": stripe_create_customer,
    "stripe_retrieve_customer": stripe_retrieve_customer,
    "stripe_update_customer": stripe_update_customer,
    "stripe_search_customers": stripe_search_customers,
    "stripe_create_invoice": stripe_create_invoice,
    "stripe_retrieve_invoice": stripe_retrieve_invoice,
    "stripe_create_payment_intent": stripe_create_payment_intent,
    "stripe_retrieve_payment_intent": stripe_retrieve_payment_intent,
    "stripe_create_refund": stripe_create_refund,
    "stripe_create_product": stripe_create_product,
    "stripe_create_price": stripe_create_price,
    "stripe_create_subscription": stripe_create_subscription,
    "stripe_cancel_subscription": stripe_cancel_subscription,
    "stripe_search_subscriptions": stripe_search_subscriptions,
    "stripe_create_payment_link": stripe_create_payment_link,
    "stripe_deactivate_payment_link": stripe_deactivate_payment_link,
    "stripe_retrieve_payout": stripe_retrieve_payout,
}
