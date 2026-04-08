# ============================================================
# backend/agent.py
# LangGraph Agent: Intent Router + Tools + Memory
# ============================================================

import json
import logging
from pathlib import Path
from typing import Annotated, Literal

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

# ---- Load mock data ----
_DATA_PATH = Path(__file__).parent / "mock_data.json"
with _DATA_PATH.open(encoding="utf-8") as f:
    _DATA: dict = json.load(f)

_CARS: list[dict] = _DATA["cars"]
_REVIEWS: list[dict] = _DATA["reviews"]
_MAINTENANCE: dict = _DATA["maintenance_schedule"]
_CENTERS: list[dict] = _DATA["service_centers"]
_POLICIES: dict = _DATA["policies"]


# ============================================================
# TOOLS
# ============================================================

@tool
def search_cars(query: str, model_id: str = "") -> str:
    """
    Tìm kiếm thông tin xe VinFast theo câu hỏi hoặc model_id cụ thể.
    Trả về danh sách xe phù hợp với thông số kỹ thuật và giá cả.
    """
    logger.info("Tool search_cars: query=%s, model_id=%s", query, model_id)
    results = []
    q_lower = query.lower()

    for car in _CARS:
        # Khớp theo model_id nếu được chỉ định
        if model_id and car["id"] != model_id.lower():
            continue
        # Khớp theo tên trong query
        car_name_lower = car["name"].lower()
        matches = (
            not model_id
            and any(kw in q_lower for kw in [car["id"], car["name"].lower().split()[-1].lower()])
        ) or (model_id and car["id"] == model_id.lower()) or (not model_id and not model_id)

        results.append(car)

    if not results:
        return json.dumps({"status": "not_found", "message": "Không tìm thấy xe phù hợp."}, ensure_ascii=False)

    return json.dumps({"status": "ok", "cars": results, "total": len(results)}, ensure_ascii=False, indent=2)


@tool
def compare_models(model_ids: list[str]) -> str:
    """
    So sánh nhiều mẫu xe VinFast theo model_id.
    Ví dụ: compare_models(["vf8plus", "vf9plus"])
    """
    logger.info("Tool compare_models: %s", model_ids)
    results = []
    for mid in model_ids:
        for car in _CARS:
            if car["id"] == mid.lower():
                results.append(car)
                break

    if len(results) < 2:
        return json.dumps(
            {"status": "error", "message": "Cần ít nhất 2 mẫu xe để so sánh. Kiểm tra lại model_id."},
            ensure_ascii=False
        )

    return json.dumps({"status": "ok", "comparison": results}, ensure_ascii=False, indent=2)


@tool
def get_battery_policy(model_id: str = "") -> str:
    """
    Lấy thông tin chính sách thuê pin (GSM) cho một hoặc tất cả dòng xe.
    """
    logger.info("Tool get_battery_policy: model_id=%s", model_id)
    gsm = _POLICIES["battery_rental_gsm"]
    warranty = _POLICIES["warranty"]

    # Lấy phí thuê pin cụ thể cho model
    car_info = None
    if model_id:
        for car in _CARS:
            if car["id"] == model_id.lower():
                car_info = car
                break

    result = {
        "status": "ok",
        "gsm_policy": gsm,
        "warranty_policy": warranty,
    }
    if car_info:
        result["model_specific"] = {
            "model": car_info["name"],
            "price_with_battery": car_info.get("price_buy_battery"),
            "price_without_battery": car_info.get("price_without_battery"),
            "battery_rental_monthly_vnd": car_info.get("battery_rental_monthly"),
            "battery_rental_km_limit": car_info.get("battery_rental_km_limit"),
            "battery_rental_extra_per_km": car_info.get("battery_rental_extra_per_km"),
        }

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_reviews(model_id: str, max_results: int = 5) -> str:
    """
    Lấy review thực tế từ cộng đồng chủ xe VinFast cho một dòng xe cụ thể.
    Sắp xếp theo ngày mới nhất (time_weight ưu tiên review gần đây).
    """
    logger.info("Tool get_reviews: model_id=%s, max=%d", model_id, max_results)
    filtered = [r for r in _REVIEWS if r["car_model"] == model_id.lower()]

    # Sắp xếp theo ngày mới nhất
    filtered.sort(key=lambda x: x["date"], reverse=True)
    filtered = filtered[:max_results]

    if not filtered:
        return json.dumps(
            {"status": "low_confidence", "message": f"Chưa có đủ review thực tế cho {model_id}. Thông tin chỉ từ nhà sản xuất."},
            ensure_ascii=False
        )

    # Tính tổng hợp sentiment
    sentiments = [r["sentiment"] for r in filtered]
    positive_count = sentiments.count("positive")
    total = len(sentiments)
    sentiment_pct = round(positive_count / total * 100)

    return json.dumps({
        "status": "ok",
        "model_id": model_id,
        "total_reviews_found": total,
        "positive_sentiment_pct": sentiment_pct,
        "reviews": filtered,
    }, ensure_ascii=False, indent=2)


@tool
def book_maintenance(model_id: str, service_type: str = "periodic") -> str:
    """
    Lấy thông tin đặt lịch bảo dưỡng xe VinFast.
    service_type: 'periodic' (định kỳ), 'repair' (sửa chữa), 'inspection' (kiểm tra)
    """
    logger.info("Tool book_maintenance: model_id=%s, type=%s", model_id, service_type)
    schedule = _MAINTENANCE.get(model_id.lower(), _MAINTENANCE.get("vf8plus", []))
    centers_sample = _CENTERS[:3]  # Trả về 3 trung tâm đầu

    result = {
        "status": "ok",
        "model_id": model_id,
        "service_type": service_type,
        "maintenance_intervals": schedule,
        "booking_channels": {
            "phone": "1900 23 23 89",
            "app": "VinFast App (iOS/Android)",
            "website": "https://vinfast.vn/dat-lich-dich-vu",
        },
        "nearby_service_centers": centers_sample,
        "notes": "Xe trong thời gian bảo hành 5 năm được bảo dưỡng định kỳ miễn phí theo lịch chính thức.",
    }

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_charging_info(model_id: str = "") -> str:
    """
    Lấy thông tin về mạng sạc VinFast, tốc độ sạc và chi phí.
    """
    logger.info("Tool get_charging_info: model_id=%s", model_id)
    charging = _POLICIES["charging"]
    car_info = None
    if model_id:
        for car in _CARS:
            if car["id"] == model_id.lower():
                car_info = car
                break

    return json.dumps({
        "status": "ok",
        "charging_network": charging,
        "model_specific_range": {
            "model": car_info["name"] if car_info else "N/A",
            "range_wltp_km": car_info.get("range_km_wltp") if car_info else None,
            "battery_kwh": car_info.get("battery_kwh") if car_info else None,
        } if car_info else None
    }, ensure_ascii=False, indent=2)


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """Bạn là trợ lý AI của VinFast — một chuyên gia tư vấn xe điện, chính sách và review thực tế.

## VAI TRÒ & NGUYÊN TẮC CỐT LÕI

1. **Precision over Recall**: Chỉ trả lời dựa trên thông tin từ tools. Nếu không chắc → thừa nhận và gợi ý gặp tư vấn viên.
2. **Augmentation**: Hỗ trợ khách hàng ra quyết định, KHÔNG ra quyết định thay họ.
3. **Anti-Hallucination**: KHÔNG bịa giá, thông số, chính sách. Luôn trích dẫn nguồn data từ tools.
4. **Trust signals**: Khi trả lời về giá/chính sách, luôn nhắc khách hàng xác minh lại trên website chính thức vinfast.vn.

## TOOL-BASED ROUTING (BẮT BUỘC)

- Nếu câu hỏi về **chính sách/giá/thuê pin/bảo hành/chi phí**: ưu tiên `get_battery_policy`.
- Nếu câu hỏi về **review/trải nghiệm thực tế/độ ồn/quãng đường pin thực tế**: ưu tiên `get_reviews`.
- Nếu câu hỏi về **thông số xe/giá niêm yết/model cụ thể**: dùng `search_cars` hoặc `compare_models`.
- Nếu câu hỏi về **bảo dưỡng/đặt lịch/trung tâm dịch vụ**: dùng `book_maintenance`.
- Nếu câu hỏi về **sạc điện/phạm vi WLTP/trạm sạc**: dùng `get_charging_info`.

## LUỒNG XỬ LÝ

- Câu hỏi về **giá, thông số kỹ thuật, so sánh xe**: dùng `search_cars` hoặc `compare_models`
- Câu hỏi về **chính sách thuê/mua pin**: dùng `get_battery_policy`
- Câu hỏi về **review, trải nghiệm thực tế**: dùng `get_reviews`
- Câu hỏi về **bảo dưỡng, đặt lịch**: dùng `book_maintenance`
- Câu hỏi về **sạc điện, phạm vi**: dùng `get_charging_info`

## ĐỊNH DẠNG PHẢN HỒI

- Dùng Markdown (bảng, danh sách gạch đầu) cho thông tin có cấu trúc.
- Đưa ra khuyến nghị rõ ràng sau khi cung cấp data.
- Kết thúc bằng CTA phù hợp: "Đặt lịch lái thử", "Gặp tư vấn viên", "Xem chi tiết thông số".
- Luôn nêu rõ: thông tin có thể thay đổi, cần xác minh tại vinfast.vn hoặc gọi 1900 23 23 89.

## LOW CONFIDENCE HANDLING

Nếu tool trả về `status: low_confidence` hoặc `status: not_found`:
→ Thông báo rõ ràng với khách hàng → Đề nghị kết nối với tư vấn viên thực.

## SELF-CHECK TRƯỚC KHI TRẢ LỜI

- Trước khi kết thúc, tự kiểm tra: mọi số liệu (giá, thông số, chính sách) có xuất phát từ tool output hay không.
- Nếu phát hiện số liệu không có trong tool output: không được trả ra như dữ kiện chắc chắn.
- Khi không đủ dữ liệu: dùng ngôn ngữ thận trọng và chuyển sang khuyến nghị gặp tư vấn viên.

Ngôn ngữ phản hồi: **Tiếng Việt** (trừ khi khách hàng dùng ngôn ngữ khác)."""


# ============================================================
# LANGGRAPH STATE & GRAPH
# ============================================================

class AgentState(TypedDict):
    """State của Agent trong LangGraph."""
    messages: Annotated[list, add_messages]


# Danh sách tools đăng ký
TOOLS = [
    search_cars,
    compare_models,
    get_battery_policy,
    get_reviews,
    book_maintenance,
    get_charging_info,
]

# Memory persist theo thread_id
_memory = MemorySaver()

# LLM instance (lazy init)
_llm_with_tools = None


def _get_llm_with_tools():
    """Lazy init LLM để tránh crash khi import."""
    global _llm_with_tools
    if _llm_with_tools is None:
        from llm_fallback import get_llm
        llm = get_llm()
        _llm_with_tools = llm.bind_tools(TOOLS)
    return _llm_with_tools


def _agent_node(state: AgentState) -> dict:
    """Node chính: gọi LLM để sinh tool calls hoặc phản hồi cuối."""
    llm = _get_llm_with_tools()

    # Ghép system prompt vào đầu message list
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    logger.info("Agent node: tool_calls=%d", len(getattr(response, "tool_calls", [])))
    return {"messages": [response]}


def _should_continue(state: AgentState) -> Literal["tools", END]:
    """Điều kiện phân nhánh: có tool call → sang ToolNode, còn lại → END."""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


# Build StateGraph
def build_graph():
    """Xây dựng và compile LangGraph StateGraph."""
    graph = StateGraph(AgentState)

    tool_node = ToolNode(TOOLS)

    graph.add_node("agent", _agent_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")   # Sau khi tools chạy xong → quay lại agent

    compiled = graph.compile(checkpointer=_memory)
    logger.info("LangGraph compiled thành công với %d tools", len(TOOLS))
    return compiled


# Singleton graph instance
_graph = None


def get_graph():
    """Lấy singleton compiled graph."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
