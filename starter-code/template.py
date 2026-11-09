import json
import re
import unicodedata
from typing import Any, Dict, List

from tools import TOOL_DEFINITIONS, TOOL_MAP


SYSTEM_PROMPT = """Bạn là VinAssistant, trợ lý thân thiện và chuyên nghiệp về các sản phẩm,
dịch vụ thuộc hệ sinh thái Vingroup, bao gồm VinFast và Vinpearl.

## VAI TRÒ
Giao tiếp rõ ràng, lịch sự, súc tích và chính xác. Trả lời bằng ngôn ngữ của người dùng.

## CÔNG CỤ HIỆN CÓ
- search_product_catalog(category, max_price): tra cứu sản phẩm/dịch vụ theo danh mục
  ('xe_dien' hoặc 'du_lich') và mức giá tối đa tính bằng VNĐ.
- submit_support_ticket(customer_name, issue_description, priority): tạo yêu cầu hỗ trợ
  với mức ưu tiên low, medium hoặc high.

## QUY TẮC CỐT LÕI
1. Không bịa tên sản phẩm, giá, tính năng, tình trạng hàng hóa hoặc mã ticket.
2. Dùng công cụ tra cứu khi người dùng hỏi danh sách, giá hoặc tình trạng sản phẩm/dịch vụ.
3. Dùng công cụ tạo ticket khi người dùng báo sự cố hoặc yêu cầu hỗ trợ.
4. Chỉ trả lời dựa trên dữ liệu có sẵn. Nếu thiếu thông tin, hãy nói rõ điều đó.
5. Chỉ tạo ticket khi người dùng đã nêu vấn đề và cần hỗ trợ.

## PHẠM VI HOẠT ĐỘNG
Chỉ hỗ trợ các sản phẩm và dịch vụ của Vingroup. Từ chối lịch sự các yêu cầu ngoài phạm vi
này và hướng người dùng trở lại chủ đề về Vingroup.

## ĐỊNH DẠNG TRẢ LỜI
Trong mỗi lượt, thực hiện lần lượt các bước sau:
Thought: xác định ý định của người dùng và dữ liệu cần thiết.
Action: gọi công cụ phù hợp nếu cần.
Observation: sử dụng kết quả công cụ chính xác, không tự ý thay đổi dữ liệu.
Final Answer: trả lời súc tích bằng tiếng Việt. Không tiết lộ suy luận nội bộ; chỉ đưa ra
câu trả lời và kết quả hữu ích từ công cụ.
"""


class ChatbotBaseline:
    """Mock baseline chatbot that answers without using tools."""

    def query(self, user_input: str) -> Dict[str, Any]:
        return {
            "answer": (
                "[Chatbot Baseline] Đây là câu trả lời mô phỏng chưa được xác minh "
                f"cho yêu cầu: {user_input}"
            ),
            "tool_calls": [],
            "status": "success",
            "mode": "mock_baseline",
        }


def _normalize(text: str) -> str:
    """Lowercase and remove Vietnamese accents for tolerant keyword matching."""
    text = unicodedata.normalize("NFD", text.casefold())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.replace("đ", "d")


def _extract_price(text: str) -> int:
    """Read a price limit expressed as VND, million, or billion VND."""
    normalized = _normalize(text)
    match = re.search(r"\d[\d.,]*", normalized)
    if not match:
        return 999999999999

    amount_text = match.group(0).replace(".", "").replace(",", "")
    amount = int(amount_text)
    unit = normalized[match.end():].lstrip()
    if unit.startswith(("tri", "million")):
        amount *= 1_000_000
    elif unit.startswith(("ty", "billion")):
        amount *= 1_000_000_000
    return amount


def _detect_intents(user_input: str) -> Dict[str, Any]:
    """Route Vingroup requests using normalized Vietnamese keyword matching."""
    text = _normalize(user_input)

    warranty_faq = "bao hanh pin" in text
    issue_cues = any(term in text for term in (
        "bi loi", "hong", "hu hong", "su co", "khieu nai", "ticket",
        "can ho tro", "ho tro toi", "kiem tra bao hanh",
    ))
    needs_ticket = issue_cues or ("support" in text and not warranty_faq)

    has_vehicle = "xe dien" in text or re.search(r"\bxe\s+vf\s*\d", text) is not None
    has_travel = any(term in text for term in ("du lich", "vinpearl", "resort", "khach san"))
    browse_cues = any(term in text for term in (
        "gia", "price", "xem", "tim", "mau xe", "danh sach", "xe nao", "san pham",
    ))
    needs_catalog = has_travel or (has_vehicle and browse_cues)
    if warranty_faq and not any(term in text for term in ("gia", "mau xe", "danh sach")):
        needs_catalog = False

    category = "du_lich" if has_travel else "xe_dien"
    name_match = re.search(r"\bten\s+([^,.!?]+)", text, flags=re.IGNORECASE)
    customer_name = name_match.group(1).strip() if name_match else "Khách hàng"
    # Keep the original spelling and accents from the user input.
    original_name_match = re.search(r"\bt[eê]n\s+([^,.!?]+)", user_input, flags=re.IGNORECASE)
    if original_name_match:
        customer_name = original_name_match.group(1).strip()

    is_vingroup = any(term in text for term in ("vingroup", "vinfast", "vinpearl", "xe dien", "du lich"))
    is_vingroup = is_vingroup or re.search(r"\bxe\s+vf\s*\d", text) is not None
    return {
        "needs_catalog": needs_catalog,
        "needs_ticket": needs_ticket,
        "category": category,
        "max_price": _extract_price(user_input),
        "customer_name": customer_name,
        "issue_description": user_input.strip(),
        "priority": "high" if any(term in text for term in ("gap", "nghiem trong", "urgent", "emergency")) else "medium",
        "is_vingroup": is_vingroup,
        "is_warranty_faq": warranty_faq and not issue_cues,
    }

class ToolCallingAgent:
    """Deterministic mock agent that routes requests to the lab tools."""

    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self.trace: List[Dict[str, Any]] = []

    def run(self, user_input: str) -> Dict[str, Any]:
        self.trace = [{"step": "init", "user_input": user_input}]
        intents = _detect_intents(user_input)
        self.trace.append({"step": "intent_detection", "intents": intents})

        if not intents["is_vingroup"]:
            answer = "Xin lỗi, tôi chỉ hỗ trợ thông tin về sản phẩm và dịch vụ Vingroup."
            self.trace.append({"step": "final_answer", "answer": answer})
            return {"answer": answer, "trace": self.trace, "iterations": 1,
                    "status": "completed"}

        planned_tools = []
        if intents["needs_catalog"]:
            planned_tools.append(("search_product_catalog", {
                "category": intents["category"], "max_price": intents["max_price"]
            }))
        if intents["needs_ticket"]:
            planned_tools.append(("submit_support_ticket", {
                "customer_name": intents["customer_name"],
                "issue_description": intents["issue_description"],
                "priority": intents["priority"],
            }))

        # The FAQ is grounded in the sample catalog included with this lab.
        observations: Dict[str, Any] = {}
        if not planned_tools:
            if intents["is_warranty_faq"]:
                answer = "Theo dữ liệu mẫu của lab, pin VinFast được bảo hành 10 năm."
            else:
                answer = ("Tôi có thể hỗ trợ tra cứu sản phẩm, giá VinFast/Vinpearl "
                          "hoặc ghi nhận yêu cầu hỗ trợ. Bạn muốn tìm thông tin nào?")
            self.trace.append({"step": "final_answer", "answer": answer})
            return {"answer": answer, "trace": self.trace, "iterations": 1,
                    "status": "completed"}

        if self.max_iterations < len(planned_tools):
            answer = "Lỗi: Vượt quá số bước xử lý tối đa."
            self.trace.append({"step": "max_iterations", "answer": answer})
            return {"answer": answer, "trace": self.trace,
                    "iterations": self.max_iterations,
                    "status": "max_iterations_reached"}

        for iteration, (tool_name, arguments) in enumerate(planned_tools, start=1):
            result = TOOL_MAP[tool_name](**arguments)
            observations[tool_name] = result
            self.trace.append({
                "step": "tool_call", "iteration": iteration,
                "tool": tool_name, "arguments": arguments,
                "observation": result,
            })

        answer_parts = []
        products = observations.get("search_product_catalog")
        if products is not None:
            if not products or (len(products) == 1 and "error" in products[0]):
                answer_parts.append("Rất tiếc, không tìm thấy sản phẩm phù hợp.")
            else:
                lines = ["Sản phẩm phù hợp:"]
                for product in products:
                    price = f"{product['price_vnd']:,}".replace(",", ".")
                    lines.append(f"- {product['name']}: {price} VNĐ")
                answer_parts.append("\n".join(lines))

        ticket = observations.get("submit_support_ticket")
        if ticket:
            answer_parts.append(
                f"Đã tạo yêu cầu hỗ trợ cho {ticket['customer_name']}. "
                f"Mã ticket: {ticket['ticket_id']} (ưu tiên {ticket['priority']})."
            )

        answer = "\n".join(answer_parts)
        self.trace.append({"step": "final_answer", "answer": answer})
        return {
            "answer": answer,
            "trace": self.trace,
            "iterations": len(planned_tools),
            "status": "completed",
        }


def main() -> None:
    user_query = "Tôi muốn xem xe điện VinFast giá dưới 600 triệu."
    print("=== RUNNING CHATBOT BASELINE ===")
    print(ChatbotBaseline().query(user_query))
    print("\n=== RUNNING TOOL CALLING AGENT ===")
    agent = ToolCallingAgent(max_iterations=5)
    result = agent.run(user_query)
    print("Result:", result["answer"])
    print("Trace Log:", json.dumps(agent.trace, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
