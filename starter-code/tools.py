
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "raw-data")


def search_product_catalog(
    category: str, max_price: int = 999999999999
) -> List[Dict[str, Any]]:
    """Return catalog entries matching a category and maximum VND price.

    Category matching is case-insensitive. If the catalog is missing, return
    an error object in a list so the function keeps its documented return type.
    """
    catalog_file = os.path.join(RAW_DATA_DIR, "product_catalog.json")
    if not os.path.exists(catalog_file):
        return [{"error": "Product catalog file not found."}]

    with open(catalog_file, "r", encoding="utf-8") as file:
        products = json.load(file)

    normalized_category = category.strip().casefold()
    return [
        product
        for product in products
        if str(product.get("category", "")).casefold() == normalized_category
        and isinstance(product.get("price_vnd"), (int, float))
        and product["price_vnd"] <= max_price
    ]


def submit_support_ticket(
    customer_name: str,
    issue_description: str,
    priority: str = "medium",
) -> Dict[str, Any]:
    """Create and persist a support ticket, returning its confirmation."""
    tickets_file = os.path.join(RAW_DATA_DIR, "support_tickets.json")
    os.makedirs(RAW_DATA_DIR, exist_ok=True)

    existing_tickets: List[Dict[str, Any]] = []
    if os.path.exists(tickets_file):
        with open(tickets_file, "r", encoding="utf-8") as file:
            existing_tickets = json.load(file)
        if not isinstance(existing_tickets, list):
            raise ValueError("support_tickets.json must contain a JSON list.")

    now = datetime.now(timezone(timedelta(hours=7)))
    today = now.strftime("%Y%m%d")
    prefix = f"TK-{today}-"
    # Continue today's sequence while avoiding collisions with older records.
    todays_sequences = []
    for ticket in existing_tickets:
        ticket_id = str(ticket.get("ticket_id", ""))
        if ticket_id.startswith(prefix):
            try:
                todays_sequences.append(int(ticket_id[len(prefix):]))
            except ValueError:
                continue
    seq = max(todays_sequences, default=0) + 1
    ticket_id = f"{prefix}{seq:03d}"
    normalized_priority = priority.strip().lower()

    new_ticket = {
        "ticket_id": ticket_id,
        "customer_name": customer_name,
        "issue_description": issue_description,
        "priority": normalized_priority,
        "status": "open",
        "created_at": now.isoformat(),
        "category": "general",
    }
    existing_tickets.append(new_ticket)

    with open(tickets_file, "w", encoding="utf-8") as file:
        json.dump(existing_tickets, file, indent=2, ensure_ascii=False)

    return {
        "ticket_id": ticket_id,
        "customer_name": customer_name,
        "priority": normalized_priority,
        "status": "open",
        "message": f"Ticket {ticket_id} đã được tạo thành công.",
    }


TOOL_DEFINITIONS = [
    {
        "name": "search_product_catalog",
        "description": "Tra cứu sản phẩm/dịch vụ Vingroup theo danh mục và giá tối đa.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Loại sản phẩm: 'xe_dien' hoặc 'du_lich'.",
                    "enum": ["xe_dien", "du_lich"],
                },
                "max_price": {
                    "type": "integer",
                    "description": "Giá tối đa tính bằng VNĐ.",
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "submit_support_ticket",
        "description": "Tạo yêu cầu hỗ trợ mới cho khách hàng Vingroup.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "description": "Tên khách hàng.",
                },
                "issue_description": {
                    "type": "string",
                    "description": "Mô tả vấn đề cần hỗ trợ.",
                },
                "priority": {
                    "type": "string",
                    "description": "Mức độ ưu tiên của yêu cầu.",
                    "enum": ["low", "medium", "high"],
                },
            },
            "required": ["customer_name", "issue_description"],
        },
    },
]


TOOL_MAP = {
    "search_product_catalog": search_product_catalog,
    "submit_support_ticket": submit_support_ticket,
}
