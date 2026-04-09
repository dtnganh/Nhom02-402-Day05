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

# Import toàn bộ công cụ từ thư mục tools/ đã được module hóa
from tools import (
    search_cars,
    compare_models,
    get_battery_policy,
    get_charging_info,
    book_maintenance,
    get_reviews
)

logger = logging.getLogger(__name__)



# Đọc System Prompt từ file Markdown chuyên nghiệp
_PROMPT_PATH = Path(__file__).parent / "prompts.md"
with _PROMPT_PATH.open(encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


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
