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
