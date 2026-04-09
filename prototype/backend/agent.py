# ============================================================
# backend/agent.py
# LangGraph Agent: Intent Router → Agent → Tools → Guardrails
#
# Author: Mai Tấn Thành (AI Architect — Nhóm 2)
# Phạm vi: System Prompt, Architecture tổng thể, Intent Router,
#           Guardrails chống Hallucination
# ============================================================

import json
import logging
import re
from pathlib import Path
from typing import Annotated, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
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
        if model_id:
            mid = model_id.lower()
            # Khớp chính xác HOẶC prefix (vd: "vf8" khớp "vf8plus", "vf8eco")
            if car["id"] == mid or car["id"].startswith(mid):
                results.append(car)
            continue

        # Khớp theo từ khóa trong query (không có model_id)
        car_keywords = [car["id"], car["name"].lower().split()[-1].lower()]
        if any(kw in q_lower for kw in car_keywords):
            results.append(car)


    # Nếu không khớp bất kỳ model nào → trả về tất cả (general search)
    if not results and not model_id:
        results = _CARS

    if not results:
        return json.dumps(
            {"status": "not_found", "message": "Không tìm thấy xe phù hợp với yêu cầu."},
            ensure_ascii=False,
        )

    return json.dumps(
        {"status": "ok", "cars": results, "total": len(results)},
        ensure_ascii=False,
        indent=2,
    )


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
            ensure_ascii=False,
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

    # Sắp xếp theo ngày mới nhất (time_weight)
    filtered.sort(key=lambda x: x["date"], reverse=True)
    filtered = filtered[:max_results]

    if not filtered:
        return json.dumps(
            {
                "status": "low_confidence",
                "message": f"Chưa có đủ review thực tế cho {model_id}. Thông tin chỉ từ nhà sản xuất.",
            },
            ensure_ascii=False,
        )

    sentiments = [r["sentiment"] for r in filtered]
    positive_count = sentiments.count("positive")
    total = len(sentiments)
    sentiment_pct = round(positive_count / total * 100)

    return json.dumps(
        {
            "status": "ok",
            "model_id": model_id,
            "total_reviews_found": total,
            "positive_sentiment_pct": sentiment_pct,
            "reviews": filtered,
        },
        ensure_ascii=False,
        indent=2,
    )


@tool
def book_maintenance(model_id: str, service_type: str = "periodic") -> str:
    """
    Lấy thông tin đặt lịch bảo dưỡng xe VinFast.
    service_type: 'periodic' (định kỳ), 'repair' (sửa chữa), 'inspection' (kiểm tra)
    """
    logger.info("Tool book_maintenance: model_id=%s, type=%s", model_id, service_type)
    schedule = _MAINTENANCE.get(model_id.lower(), _MAINTENANCE.get("vf8plus", []))
    centers_sample = _CENTERS[:3]

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

    return json.dumps(
        {
            "status": "ok",
            "charging_network": charging,
            "model_specific_range": {
                "model": car_info["name"] if car_info else "N/A",
                "range_wltp_km": car_info.get("range_km_wltp") if car_info else None,
                "battery_kwh": car_info.get("battery_kwh") if car_info else None,
            }
            if car_info
            else None,
        },
        ensure_ascii=False,
        indent=2,
    )


# ============================================================
# SYSTEM PROMPT (Mai Tấn Thành — AI Architect)
# Thiết kế theo nguyên tắc: Precision > Recall, Augmentation
# ============================================================

SYSTEM_PROMPT = """Bạn là **VSA — VinFast Smart Assistant**, trợ lý AI chính thức của VinFast.
Vai trò: Augmentation (tăng cường quyết định cho người dùng), KHÔNG Automation (ra quyết định thay họ).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## NGUYÊN TẮC CỐT LÕI (Bất di bất dịch)

1. **PRECISION OVER RECALL**
   → Thà từ chối trả lời còn hơn cung cấp thông tin sai.
   → Nếu không chắc chắn 100% → Thừa nhận và đề nghị kết nối tư vấn viên.

2. **ZERO-HALLUCINATION**
   → TUYỆT ĐỐI không bịa giá, thông số, chính sách, khuyến mãi.
   → Mọi con số PHẢI xuất phát trực tiếp từ kết quả tool trả về.
   → Không suy luận kiểu "VF6 gần với VF8 nên giá khoảng X".

3. **TOOL-FIRST PROTOCOL**
   → Trước khi trả lời bất kỳ câu hỏi nào về dữ liệu → GỌI TOOL trước.
   → Không trả lời từ memory/training data cho thông tin cụ thể VinFast.

4. **TRUST SIGNAL BẮT BUỘC**
   → Cuối mỗi câu trả lời có số liệu: luôn nhắc xác minh tại vinfast.vn.
   → Cung cấp hotline 1900 23 23 89 khi user cần hỗ trợ thêm.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## BẢNG ĐỊNH TUYẾN TOOL (BẮT BUỘC)

| Loại câu hỏi | Tool ưu tiên | Ví dụ trigger |
|---|---|---|
| Giá xe, thông số kỹ thuật | `search_cars` | "VF6 giá bao nhiêu?", "thông số VF8" |
| So sánh 2+ mẫu xe | `compare_models` | "So sánh VF8 và VF9", "nên mua xe nào" |
| Chính sách pin / GSM / bảo hành | `get_battery_policy` | "thuê pin", "mua pin", "bảo hành mấy năm" |
| Review thực tế / cộng đồng | `get_reviews` | "review", "ồn không", "pin thực tế", "người dùng nói gì" |
| Bảo dưỡng / đặt lịch dịch vụ | `book_maintenance` | "bảo dưỡng", "đặt lịch", "trung tâm dịch vụ" |
| Sạc điện / trạm sạc / WLTP | `get_charging_info` | "sạc bao lâu", "trạm sạc", "quãng đường thực" |

⚠️ Câu hỏi PHỨC HỢP (vừa giá vừa review): Gọi nhiều tool — KHÔNG đoán mò.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## XỬ LÝ NGƯỠNG TIN CẬY

### Khi tool trả về status = "ok" (confidence cao):
→ Trình bày đầy đủ, rõ ràng. Kết thúc bằng CTA phù hợp.

### Khi tool trả về status = "low_confidence" hoặc "not_found":
→ KHÔNG tự bịa thêm thông tin.
→ Thông báo rõ: "Tôi chưa có đủ dữ liệu về vấn đề này."
→ Đề xuất: "Để có thông tin chính xác và đảm bảo quyền lợi, tôi sẽ kết nối bạn với tư vấn viên VinFast."

### Câu hỏi về khuyến mãi/ưu đãi tháng hiện tại:
→ Luôn xử lý là low_confidence.
→ Lý do: dữ liệu khuyến mãi thay đổi thường xuyên, RAG có thể lỗi thời.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## SELF-CHECK TRƯỚC KHI PHÁT SINH PHẢN HỒI

Trước khi kết thúc câu trả lời, tự hỏi:
□ Mọi con số (giá, km, kW, ₫/tháng) có trong kết quả tool không?
□ Có câu nào suy luận ngoài tool output không? → Xóa hoặc ghi "Cần xác minh"
□ Có đề xuất CTA phù hợp chưa? (Đặt lịch / Gặp tư vấn viên / Xem chi tiết)
□ Đã nhắc user xác minh tại vinfast.vn chưa?

Nếu bất kỳ ô nào trả lời "Không" → Sửa lại trước khi gửi.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## FORMAT PHẢN HỒI THEO INTENT

**Giá/Thông số:** Dùng bảng Markdown. Dòng cuối: link vinfast.vn + hotline.
**Review:** Dùng bảng Pros/Cons. Nêu % hài lòng. Ghi nguồn (Otofun/Community) + ngày gần nhất.
**Chính sách pin:** Bảng so sánh mua pin vs thuê pin. Nêu điều kiện giới hạn km.
**Bảo dưỡng:** Danh sách timeline rõ ràng + 3 kênh đặt lịch (Phone/App/Web).
**So sánh xe:** Bảng song song. Kết thúc bằng gợi ý use-case cụ thể (không phán quyết).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## NGƯỠNG ESCALATE SANG HUMAN AGENT

Chuyển user sang tư vấn viên khi:
- Câu hỏi về hợp đồng mua bán, trả góp cụ thể, đặt cọc
- Khiếu nại, bảo hành tranh chấp
- Câu hỏi mà 2 tool liên tiếp trả về not_found
- User gõ: "gặp nhân viên", "muốn nói chuyện với người thật", "call me"

Khi escalate: Trả lời lịch sự + cung cấp: Hotline 1900 23 23 89, vinfast.vn/lien-he

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ngôn ngữ phản hồi: **Tiếng Việt** (trừ khi user dùng ngôn ngữ khác)."""


# ============================================================
# LANGGRAPH STATE
# ============================================================

class AgentState(TypedDict):
    """State của Agent trong LangGraph."""
    messages: Annotated[list, add_messages]
    intent_tag: Optional[str]       # Phân loại intent bởi intent_router node
    guardrail_triggered: Optional[bool]  # Flag: guardrails có can thiệp không


# ============================================================
# INTENT CLASSIFIER (dùng cho intent_router node)
# ============================================================

def _classify_intent(text: str) -> str:
    """
    Phân loại intent từ câu hỏi người dùng.
    Trả về một trong: review, policy, maintenance, charging, compare, spec, generic
    """
    text_lower = text.lower()

    # Review / Trải nghiệm thực tế
    if any(k in text_lower for k in [
        "review", "trải nghiệm", "độ ồn", "ồn không", "pin thực tế",
        "cộng đồng", "người dùng", "chủ xe nói", "đánh giá thực",
        "chạy đường trường", "thực tế", "pros cons",
    ]):
        return "review"

    # Chính sách / Giá / Bảo hành / Pin
    if any(k in text_lower for k in [
        "thuê pin", "mua pin", "chính sách", "bảo hành", "giá",
        "chi phí", "gsm", "phí", "km/tháng", "giới hạn", "hết hạn",
        "khuyến mãi", "ưu đãi", "promotion",
    ]):
        return "policy"

    # Bảo dưỡng / Đặt lịch
    if any(k in text_lower for k in [
        "bảo dưỡng", "đặt lịch", "service", "maintenance",
        "sửa chữa", "trung tâm dịch vụ", "showroom dịch vụ", "kiểm tra định kỳ",
    ]):
        return "maintenance"

    # Sạc điện / Range
    if any(k in text_lower for k in [
        "sạc", "trạm sạc", "wltp", "quãng đường", "km thực",
        "sạc bao lâu", "nhanh sạc", "fast charge", "mạng sạc",
    ]):
        return "charging"

    # So sánh xe
    if any(k in text_lower for k in [
        "so sánh", "khác nhau", "tốt hơn", "nên mua", "chọn cái nào",
        "hay hơn", "hơn kém", "vs", " vs ",
    ]):
        return "compare"

    # Thông số / Model cụ thể
    if any(k in text_lower for k in [
        "thông số", "vf3", "vf5", "vf6", "vf7", "vf8", "vf9",
        "lux a", "lux sa", "president", "kw", "km/h", "0-100",
    ]):
        return "spec"

    return "generic"


# ============================================================
# GRAPH NODES
# ============================================================

TOOLS = [
    search_cars,
    compare_models,
    get_battery_policy,
    get_reviews,
    book_maintenance,
    get_charging_info,
]

_memory = MemorySaver()
_llm_with_tools = None


def _get_llm_with_tools():
    """Lazy init LLM để tránh crash khi import."""
    global _llm_with_tools
    if _llm_with_tools is None:
        from llm_fallback import get_llm
        llm = get_llm()
        _llm_with_tools = llm.bind_tools(TOOLS)
    return _llm_with_tools


# ── Node 1: Intent Router ─────────────────────────────────────
def _intent_router_node(state: AgentState) -> dict:
    """
    Node đầu tiên trong graph.
    Phân loại intent từ tin nhắn của user → lưu vào state.
    Giúp: (1) debug/trace dễ hơn, (2) main.py đọc được intent chính xác.
    """
    messages = state.get("messages", [])
    last_human = next(
        (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
    )

    intent = _classify_intent(last_human.content) if last_human else "generic"
    logger.info("Intent Router: classified intent = '%s'", intent)

    return {"intent_tag": intent, "guardrail_triggered": False}


# ── Node 2: Agent (LLM) ──────────────────────────────────────
def _agent_node(state: AgentState) -> dict:
    """Node chính: gọi LLM để sinh tool calls hoặc phản hồi cuối."""
    llm = _get_llm_with_tools()
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    logger.info("Agent node: tool_calls=%d", len(getattr(response, "tool_calls", [])))
    return {"messages": [response]}


# ── Node 3: Guardrails ────────────────────────────────────────
def _guardrails_node(state: AgentState) -> dict:
    """
    Node Guardrails — chạy sau khi Agent tạo câu trả lời cuối cùng.
    Đây là lớp bảo vệ SERVER-SIDE, hoạt động im lặng (không đụng main.py).

    Kiểm tra:
    1. Số liệu trong câu trả lời có khớp với tool output không?
       → Phát hiện potential hallucination: số không có trong tool data.
    2. Tool nào trả về low_confidence / not_found?
       → Log cảnh báo để team monitoring.

    Kết quả ghi vào app.log + set flag guardrail_triggered trong state.
    Phần hiển thị cảnh báo cho user do main.py xử lý qua _compute_confidence().
    """
    messages = state.get("messages", [])

    # Lấy câu trả lời cuối cùng của agent
    final_msg = None
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.content and not getattr(m, "tool_calls", None):
            final_msg = m
            break

    if not final_msg:
        return {"guardrail_triggered": False}

    answer_content = final_msg.content

    # ── Bước 1: Thu thập số liệu từ tool outputs ──────────────
    tool_numbers: set[str] = set()
    has_low_confidence_tool = False

    for m in messages:
        if not isinstance(m, ToolMessage):
            continue
        raw_numbers = re.findall(r"\d[\d,\.]*", m.content)
        for n in raw_numbers:
            normalized = re.sub(r"[,\.]", "", n)
            if len(normalized) >= 3:
                tool_numbers.add(normalized)
        try:
            result = json.loads(m.content)
            if result.get("status") in ("low_confidence", "not_found"):
                has_low_confidence_tool = True
        except Exception:
            pass

    # ── Bước 2: Phát hiện số trong answer không có trong tool data ──
    suspicious_numbers: list[str] = []
    if tool_numbers:
        for n in re.findall(r"\d[\d,\.]*", answer_content):
            normalized = re.sub(r"[,\.]", "", n)
            if len(normalized) >= 6 and normalized not in tool_numbers:
                suspicious_numbers.append(n)

    # ── Bước 3: Log kết quả (server-side only, không đụng stream) ──
    triggered = bool(suspicious_numbers) or has_low_confidence_tool

    if triggered:
        if suspicious_numbers and tool_numbers:
            logger.warning(
                "🚨 GUARDRAIL: Potential hallucination — numbers not in tool data: %s",
                suspicious_numbers,
            )
        if has_low_confidence_tool:
            logger.warning(
                "⚠️  GUARDRAIL: Low-confidence tool output — user should verify at vinfast.vn",
            )
        logger.info("Guardrails TRIGGERED (server-side only, stream not modified)")
    else:
        logger.info("✅ Guardrails PASSED — no issues detected")

    # Không trả messages → main.py không bị ảnh hưởng gì cả
    return {"guardrail_triggered": triggered}


# ============================================================
# GRAPH ROUTING CONDITIONS
# ============================================================

def _should_continue(state: AgentState) -> Literal["tools", "guardrails"]:
    """
    Điều kiện phân nhánh sau agent node:
    - Có tool calls → sang ToolNode tiếp tục xử lý
    - Không có tool calls (câu trả lời cuối) → sang Guardrails trước khi END
    """
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return "guardrails"


# ============================================================
# BUILD GRAPH
# Flow: START → intent_router → agent → tools (loop) → guardrails → END
# ============================================================

def build_graph():
    """
    Xây dựng LangGraph StateGraph với kiến trúc đầy đủ:
      START
        ↓
      intent_router   ← Phân loại intent, lưu vào state
        ↓
      agent           ← LLM suy luận, chọn tool hoặc trả lời cuối
        ↓ (có tool calls)
      tools           ← Thực thi tool functions
        ↓
      agent (loop)    ← Tổng hợp kết quả từ tools
        ↓ (không có tool calls = câu trả lời cuối)
      guardrails      ← Kiểm tra hallucination, inject disclaimer nếu cần
        ↓
      END
    """
    graph = StateGraph(AgentState)

    tool_node = ToolNode(TOOLS)

    # Đăng ký nodes
    graph.add_node("intent_router", _intent_router_node)
    graph.add_node("agent", _agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("guardrails", _guardrails_node)

    # Định nghĩa edges
    graph.add_edge(START, "intent_router")
    graph.add_edge("intent_router", "agent")
    graph.add_conditional_edges(
        "agent",
        _should_continue,
        {"tools": "tools", "guardrails": "guardrails"},
    )
    graph.add_edge("tools", "agent")    # Sau tools → quay lại agent tổng hợp
    graph.add_edge("guardrails", END)   # Sau guardrails → kết thúc

    compiled = graph.compile(checkpointer=_memory)
    logger.info(
        "LangGraph compiled: %d tools | nodes: intent_router → agent → tools/guardrails → END",
        len(TOOLS),
    )
    return compiled


# ── Singleton graph instance ──────────────────────────────────
_graph = None


def get_graph():
    """Lấy singleton compiled graph."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
