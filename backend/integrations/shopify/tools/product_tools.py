from integrations.shopify.client import get_client

PRODUCT_TOOL_DEFS = [
    {
        "name": "shopify_get_products",
        "description": "List Shopify products with optional filters. Returns products with pagination support.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Filter by title (partial match)"},
                "product_type": {"type": "string", "description": "Filter by product type"},
                "vendor": {"type": "string", "description": "Filter by vendor"},
                "status": {"type": "string", "enum": ["active", "draft", "archived"], "description": "Product status filter"},
                "collection_id": {"type": "string", "description": "Filter by collection ID"},
                "limit": {"type": "integer", "description": "Max results per page (default 50, max 250)"},
                "page_info": {"type": "string", "description": "Cursor for next page"},
            },
            "required": [],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_get_product",
        "description": "Get a single Shopify product by ID with its variants.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "The product ID"},
            },
            "required": ["product_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_create_product",
        "description": "Create a new Shopify product.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Product title"},
                "body_html": {"type": "string", "description": "Product description (HTML)"},
                "vendor": {"type": "string", "description": "Product vendor"},
                "product_type": {"type": "string", "description": "Product type/category"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "status": {"type": "string", "enum": ["active", "draft", "archived"], "description": "Product status (default: draft)"},
                "variants": {
                    "type": "array",
                    "description": "Product variants with price, sku, etc.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "price": {"type": "string"},
                            "sku": {"type": "string"},
                            "inventory_quantity": {"type": "integer"},
                        },
                    },
                },
            },
            "required": ["title"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_update_product",
        "description": "Update an existing Shopify product.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "The product ID to update"},
                "title": {"type": "string", "description": "Product title"},
                "body_html": {"type": "string", "description": "Product description (HTML)"},
                "vendor": {"type": "string", "description": "Product vendor"},
                "product_type": {"type": "string", "description": "Product type/category"},
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "status": {"type": "string", "enum": ["active", "draft", "archived"], "description": "Product status"},
            },
            "required": ["product_id"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_get_product_variant",
        "description": "Get a specific Shopify product variant by ID (price, SKU, inventory).",
        "input_schema": {
            "type": "object",
            "properties": {
                "variant_id": {"type": "string", "description": "The variant ID"},
            },
            "required": ["variant_id"],
        },
        "kind": "integration",
        "writes": False,
    },
    {
        "name": "shopify_upload_product_image",
        "description": "Upload an image to a Shopify product from a URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "The product ID"},
                "src": {"type": "string", "description": "Image URL to upload"},
                "position": {"type": "integer", "description": "Image position (1 = main image)"},
            },
            "required": ["product_id", "src"],
        },
        "kind": "integration",
        "writes": True,
    },
    {
        "name": "shopify_add_product_to_collection",
        "description": "Add a Shopify product to a collection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "description": "The product ID"},
                "collection_id": {"type": "string", "description": "The collection ID"},
            },
            "required": ["product_id", "collection_id"],
        },
        "kind": "integration",
        "writes": True,
    },
]


def shopify_get_products(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    params = {}
    if kwargs.get("page_info"):
        params["page_info"] = kwargs["page_info"]
    else:
        for key in ("title", "product_type", "vendor", "status", "collection_id"):
            if kwargs.get(key):
                params[key] = kwargs[key]
    params["limit"] = min(kwargs.get("limit", 50), 250)
    result = client.get("/products.json", params=params)
    if not result["ok"]:
        return f"Failed to fetch products: {result['data']}"
    products = result["data"].get("products", [])
    return {"products": products, "count": len(products), "next_page_info": result["next_page_info"]}


def shopify_get_product(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/products/{kwargs['product_id']}.json")
    if not result["ok"]:
        return f"Failed to fetch product: {result['data']}"
    return result["data"].get("product", result["data"])


def shopify_create_product(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    product: dict = {"title": kwargs["title"]}
    for key in ("body_html", "vendor", "product_type", "tags"):
        if kwargs.get(key):
            product[key] = kwargs[key]
    product["status"] = kwargs.get("status", "draft")
    if kwargs.get("variants"):
        product["variants"] = kwargs["variants"]
    result = client.post("/products.json", json_body={"product": product})
    if not result["ok"]:
        return f"Failed to create product: {result['data']}"
    return result["data"].get("product", result["data"])


def shopify_update_product(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    product: dict = {}
    for key in ("title", "body_html", "vendor", "product_type", "tags", "status"):
        if kwargs.get(key) is not None:
            product[key] = kwargs[key]
    result = client.put(f"/products/{kwargs['product_id']}.json", json_body={"product": product})
    if not result["ok"]:
        return f"Failed to update product: {result['data']}"
    return result["data"].get("product", result["data"])


def shopify_get_product_variant(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.get(f"/variants/{kwargs['variant_id']}.json")
    if not result["ok"]:
        return f"Failed to fetch variant: {result['data']}"
    return result["data"].get("variant", result["data"])


def shopify_upload_product_image(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    image: dict = {"src": kwargs["src"]}
    if kwargs.get("position"):
        image["position"] = kwargs["position"]
    result = client.post(f"/products/{kwargs['product_id']}/images.json", json_body={"image": image})
    if not result["ok"]:
        return f"Failed to upload image: {result['data']}"
    return result["data"].get("image", result["data"])


def shopify_add_product_to_collection(**kwargs) -> dict | str:
    client = get_client()
    if not client:
        return "Shopify is not connected. Set it up in Settings → Integrations."
    result = client.post("/collects.json", json_body={
        "collect": {"product_id": int(kwargs["product_id"]), "collection_id": int(kwargs["collection_id"])}
    })
    if not result["ok"]:
        return f"Failed to add product to collection: {result['data']}"
    return result["data"].get("collect", result["data"])


PRODUCT_EXECUTORS = {
    "shopify_get_products": lambda **kw: shopify_get_products(**kw),
    "shopify_get_product": lambda **kw: shopify_get_product(**kw),
    "shopify_create_product": lambda **kw: shopify_create_product(**kw),
    "shopify_update_product": lambda **kw: shopify_update_product(**kw),
    "shopify_get_product_variant": lambda **kw: shopify_get_product_variant(**kw),
    "shopify_upload_product_image": lambda **kw: shopify_upload_product_image(**kw),
    "shopify_add_product_to_collection": lambda **kw: shopify_add_product_to_collection(**kw),
}
