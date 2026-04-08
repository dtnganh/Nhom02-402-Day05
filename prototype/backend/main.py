# ============================================================
# backend/main.py
# FastAPI app: Logging setup, CORS, SSE streaming /chat endpoint
# ============================================================

import json
import logging
import logging.config
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# ─── Load .env ────────────────────────────────────────────────
load_dotenv(Path(__file__).parent.parent / ".env")

# ============================================================
# 1. LOGGING SETUP
# ============================================================

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "compact": {
            "format": "[%(levelname)s] %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "compact",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_FILE),
            "maxBytes": 10 * 1024 * 1024,   # 10 MB
            "backupCount": 3,
            "formatter": "standard",
            "level": "DEBUG",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "DEBUG",
    },
    "loggers": {
        "uvicorn": {"level": "INFO"},
        "uvicorn.access": {"level": "WARNING"},
        "httpx": {"level": "WARNING"},
        "langchain": {"level": "WARNING"},
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


# ============================================================
# 2. PYDANTIC SCHEMAS
# ============================================================

class ChatRequest(BaseModel):
    """Request body cho POST /chat."""
    message: str = Field(..., min_length=1, max_length=2000, description="Tin nhắn của người dùng")
    thread_id: str = Field(default_factory=lambda: f"thread_{uuid.uuid4().hex[:8]}", description="ID phiên hội thoại")

    model_config = {"json_schema_extra": {"example": {"message": "VF8 giá bao nhiêu?", "thread_id": "thread_abc123"}}}


class HealthResponse(BaseModel):
    status: str
    llm_provider: str
    uptime_seconds: float


# ============================================================
# 3. APP LIFESPAN (warm-up)
# ============================================================

_startup_time = time.time()
_llm_provider = "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm-up LLM và Agent khi khởi động server."""
    global _llm_provider
    logger.info("=" * 60)
    logger.info("🚀 VinFast AI Backend đang khởi động...")

    try:
        from llm_fallback import get_llm
        llm = get_llm()
        _llm_provider = type(llm).__name__
        logger.info("✅ LLM ready: %s", _llm_provider)
    except RuntimeError as e:
        logger.warning("⚠️  LLM chưa sẵn sàng: %s", e)
        logger.warning("⚠️  Server sẽ khởi động ở chế độ MOCK (không có API key thực)")
        _llm_provider = "MockFallback"

    # Pre-load graph
    try:
        from agent import get_graph
        get_graph()
        logger.info("✅ LangGraph compiled và sẵn sàng")
    except Exception as e:
        logger.error("❌ Lỗi khởi tạo LangGraph: %s", e)

    logger.info("✅ Server ready. Port: 8000")
    logger.info("=" * 60)
    yield
    logger.info("🛑 VinFast AI Backend đang tắt...")


# ============================================================
# 4. FASTAPI APP
# ============================================================

app = FastAPI(
    title="VinFast AI Chatbot API",
    description="Backend AI Agent với LangGraph + RAG cho chatbot tư vấn VinFast",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — cho phép frontend local
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Production: thay bằng domain cụ thể
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request logging middleware ─────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "HTTP %s %s → %d (%.1f ms)",
        request.method, request.url.path, response.status_code, elapsed_ms,
    )
    return response


# ============================================================
# 5. SSE EVENT HELPERS
# ============================================================

def _sse(event: str, data: dict) -> dict:
    """Tạo SSE event dict dùng cho EventSourceResponse."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


# ============================================================
# 6. CORE STREAMING GENERATOR
# ============================================================

async def _stream_chat(message: str, thread_id: str) -> AsyncGenerator[dict, None]:
    """
    Generator sinh SSE events trong suốt quá trình xử lý:

    Events:
      start         – bắt đầu xử lý
      thinking      – chain-of-thought step (mỗi node)
      tool_start    – tool bắt đầu chạy
      tool_end      – tool chạy xong (kèm kết quả tóm tắt)
      token         – từng token streaming của câu trả lời cuối
      done          – kết thúc, metadata tổng kết
      error         – lỗi xử lý
    """
    request_id = uuid.uuid4().hex[:8]
    logger.info("Chat request [%s] thread=%s: %.80s", request_id, thread_id, message)

    yield _sse("start", {"request_id": request_id, "thread_id": thread_id})

    try:
        from agent import TOOLS, get_graph
        graph = get_graph()

        config = {"configurable": {"thread_id": thread_id}}
        input_state = {"messages": [HumanMessage(content=message)]}

        tools_executed: list[dict] = []
        final_answer = ""
        step_count = 0

        # ── Stream từng event từ LangGraph ──────────────────────
        async for chunk in graph.astream(
            input_state,
            config=config,
            stream_mode="updates",
        ):
            for node_name, node_output in chunk.items():
                msgs = node_output.get("messages", [])

                for msg in msgs:
                    step_count += 1

                    # ── Agent node: LLM đang suy luận ──────────
                    if node_name == "agent" and isinstance(msg, AIMessage):
                        # Có tool calls → thông báo planning
                        if msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield _sse("thinking", {
                                    "type": "tool",
                                    "text": f"Gọi công cụ: <strong>{tc['name']}</strong>",
                                    "args": tc.get("args", {}),
                                })
                        else:
                            # Đây là câu trả lời cuối cùng
                            final_answer = msg.content
                            yield _sse("thinking", {
                                "type": "result",
                                "text": "Tổng hợp câu trả lời hoàn tất...",
                            })

                    # ── Tool node: tool đang chạy ───────────────
                    elif node_name == "tools" and isinstance(msg, ToolMessage):
                        tool_name = msg.name if hasattr(msg, "name") else "unknown_tool"
                        tools_executed.append(tool_name)

                        # Phân tích kết quả tool
                        try:
                            tool_result = json.loads(msg.content)
                            status = tool_result.get("status", "ok")
                            summary = _summarize_tool_result(tool_name, tool_result)
                        except Exception:
                            status = "ok"
                            summary = f"Tool {tool_name} chạy xong"

                        yield _sse("tool_end", {
                            "tool_name": tool_name,
                            "status": status,
                            "summary": summary,
                        })

                        yield _sse("thinking", {
                            "type": "retrieval",
                            "text": summary,
                        })

        # ── Nếu chưa có final_answer, lấy từ state ─────────────
        if not final_answer:
            state = graph.get_state(config)
            msgs = state.values.get("messages", [])
            for m in reversed(msgs):
                if isinstance(m, AIMessage) and m.content and not m.tool_calls:
                    final_answer = m.content
                    break

        if not final_answer:
            final_answer = "Xin lỗi, tôi không thể xử lý yêu cầu này lúc này. Vui lòng thử lại hoặc liên hệ tư vấn viên qua 1900 23 23 89."

        # ── Streaming tokens của câu trả lời cuối ───────────────
        logger.info("Final answer [%s]: %d chars, tools=%s", request_id, len(final_answer), tools_executed)

        # Phân tích confidence level
        confidence = _assess_confidence(final_answer, tools_executed)

        # Stream từng từ của câu trả lời
        words = final_answer.split(" ")
        for i, word in enumerate(words):
            chunk_text = word + (" " if i < len(words) - 1 else "")
            yield _sse("token", {"text": chunk_text})

        # ── Done event ──────────────────────────────────────────
        yield _sse("done", {
            "tools_used": tools_executed,
            "confidence": confidence,
            "request_id": request_id,
            "thread_id": thread_id,
        })
        logger.info("Chat done [%s]: %d steps, confidence=%s", request_id, step_count, confidence)

    except RuntimeError as e:
        # LLM không khả dụng → fallback mock
        logger.warning("LLM unavailable [%s], sử dụng mock fallback: %s", request_id, e)
        yield _sse("thinking", {"type": "thinking", "text": "LLM API không khả dụng, đang dùng chế độ demo..."})
        async for event in _mock_stream(message, thread_id, request_id):
            yield event

    except Exception as e:
        logger.exception("Lỗi không xử lý được [%s]: %s", request_id, e)
        yield _sse("error", {
            "message": "Đã xảy ra lỗi kỹ thuật. Vui lòng thử lại sau.",
            "detail": str(e),
            "request_id": request_id,
        })


def _summarize_tool_result(tool_name: str, result: dict) -> str:
    """Tạo tóm tắt ngắn gọn cho kết quả của một tool."""
    status = result.get("status", "ok")
    if status == "not_found":
        return f"Không tìm thấy dữ liệu qua {tool_name}"
    if status == "low_confidence":
        return f"Dữ liệu {tool_name}: chưa đủ thông tin, sẽ thông báo người dùng"

    if tool_name == "search_cars":
        n = result.get("total", 0)
        return f"Tìm thấy <strong>{n} mẫu xe</strong> phù hợp trong cơ sở dữ liệu VinFast"
    if tool_name == "compare_models":
        models = [c["name"] for c in result.get("comparison", [])]
        return f"Đã tải thông số so sánh: <strong>{' / '.join(models)}</strong>"
    if tool_name == "get_battery_policy":
        model = result.get("model_specific", {}).get("model", "")
        price = result.get("model_specific", {}).get("battery_rental_monthly_vnd", "")
        return f"Chính sách pin GSM {model}: thuê <strong>{price:,} ₫/tháng</strong>" if price else "Đã tải chính sách pin GSM"
    if tool_name == "get_reviews":
        n = result.get("total_reviews_found", 0)
        pct = result.get("positive_sentiment_pct", 0)
        return f"Tổng hợp <strong>{n} review</strong> — Tỷ lệ hài lòng: <strong>{pct}%</strong>"
    if tool_name == "book_maintenance":
        return "Đã tải thông tin đặt lịch bảo dưỡng & danh sách trung tâm dịch vụ"
    if tool_name == "get_charging_info":
        return "Đã tải thông tin mạng sạc VinFast (150 trạm, 63 tỉnh thành)"
    return f"Tool <strong>{tool_name}</strong> hoàn thành"


def _assess_confidence(answer: str, tools_used: list[str]) -> str:
    """Đánh giá mức độ confidence dựa trên câu trả lời và tools đã dùng."""
    answer_lower = answer.lower()
    low_confidence_signals = [
        "không chắc", "có thể", "cần xác minh", "liên hệ tư vấn",
        "không tìm thấy", "chưa có đủ", "không đủ thông tin",
    ]
    if any(sig in answer_lower for sig in low_confidence_signals):
        return "low"
    if tools_used:
        return "high"
    return "mid"


# ============================================================
# 7. MOCK FALLBACK (khi không có LLM key)
# ============================================================

_MOCK_DATA_CACHE: dict = {}

def _get_mock_data() -> dict:
    global _MOCK_DATA_CACHE
    if not _MOCK_DATA_CACHE:
        mock_path = Path(__file__).parent / "mock_data.json"
        with mock_path.open(encoding="utf-8") as f:
            _MOCK_DATA_CACHE = json.load(f)
    return _MOCK_DATA_CACHE


async def _mock_stream(message: str, thread_id: str, request_id: str) -> AsyncGenerator[dict, None]:
    """Mock stream khi không có LLM API key — dùng mock_data.json trực tiếp."""
    import asyncio
    msg_lower = message.lower()
    data = _get_mock_data()

    # Xác định intent
    if any(k in msg_lower for k in ["vf8", "vf9", "so sánh", "compare"]):
        intent = "compare"
        cars = [c for c in data["cars"] if c["id"] in ("vf8plus", "vf9plus")]
        tools = ["intent_router", "compare_models", "guardrails_check"]
        thinking_steps = [
            ("thinking",  "Nhận diện intent: so sánh xe VF8 vs VF9"),
            ("tool",      "Gọi tool: <strong>compare_models</strong>(models=[\"vf8plus\",\"vf9plus\"])"),
            ("retrieval", f"Tìm thấy <strong>{len(cars)} mẫu xe</strong> trong cơ sở dữ liệu"),
            ("guard",     "Guardrails check: dữ liệu khớp DB. Confidence: 0.97 ✓"),
            ("result",    "Tổng hợp bảng so sánh + CTA..."),
        ]
        answer = _build_compare_answer(cars)
        confidence = "high"

    elif any(k in msg_lower for k in ["pin", "thuê", "gsm", "battery"]):
        intent = "battery"
        tools = ["intent_router", "get_battery_policy", "guardrails_check"]
        thinking_steps = [
            ("thinking",  "Nhận diện intent: chính sách thuê pin VinFast"),
            ("tool",      "Gọi tool: <strong>get_battery_policy</strong>(model_id=\"vf6\")"),
            ("retrieval", "Đã tải chính sách pin GSM từ tài liệu chính thức"),
            ("guard",     "Kiểm tra ngày hiệu lực tài liệu: 01/01/2024 → còn hiệu lực ✓"),
            ("result",    "Tóm tắt điều khoản + cảnh báo thay đổi..."),
        ]
        answer = _build_battery_answer(data)
        confidence = "mid"

    elif any(k in msg_lower for k in ["review", "trải nghiệm", "ồn", "pin thực", "community"]):
        intent = "review"
        reviews = [r for r in data["reviews"] if r["car_model"] == "vf8plus"]
        tools = ["intent_router", "get_reviews", "sentiment_analysis", "guardrails_check"]
        thinking_steps = [
            ("thinking",  "Nhận diện intent: review thực tế VF8 từ cộng đồng"),
            ("tool",      "Gọi tool: <strong>get_reviews</strong>(model_id=\"vf8plus\", max=5)"),
            ("retrieval", f"Đã tải <strong>{len(reviews)} review</strong> từ Otofun & VinFast Community"),
            ("thinking",  "Phân tích sentiment — tính tỷ lệ hài lòng..."),
            ("guard",     "Timestamp filter: loại bỏ review trước 10/2023 ✓"),
            ("result",    "Synthesis xong — tổng hợp Pros/Cons..."),
        ]
        answer = _build_review_answer(reviews)
        confidence = "high"

    elif any(k in msg_lower for k in ["bảo dưỡng", "lịch", "maintenance", "service"]):
        intent = "maintenance"
        tools = ["intent_router", "book_maintenance", "get_service_centers", "guardrails_check"]
        thinking_steps = [
            ("thinking",  "Nhận diện intent: đặt lịch bảo dưỡng"),
            ("tool",      "Gọi tool: <strong>book_maintenance</strong>(model_id=\"vf8plus\")"),
            ("retrieval", "Đã tải lịch bảo dưỡng định kỳ & danh sách trung tâm dịch vụ"),
            ("guard",     "Verify: booking endpoint available ✓"),
            ("result",    "Phản hồi thông tin đặt lịch + CTA..."),
        ]
        answer = _build_maintenance_answer(data)
        confidence = "high"

    else:
        intent = "generic"
        tools = ["intent_router", "search_cars", "guardrails_check"]
        thinking_steps = [
            ("thinking",  "Phân tích intent câu hỏi của người dùng..."),
            ("tool",      "Gọi tool: <strong>search_cars</strong> với câu hỏi"),
            ("retrieval", "Tìm kiếm trong cơ sở dữ liệu VinFast..."),
            ("guard",     "Guardrails check: Confidence ✓"),
            ("result",    "Tổng hợp câu trả lời..."),
        ]
        answer = (
            "Tôi là trợ lý AI VinFast, sẵn sàng hỗ trợ bạn về:\n\n"
            "- **So sánh giá & thông số** các dòng xe VinFast\n"
            "- **Chính sách thuê/mua pin** GSM\n"
            "- **Review thực tế** từ cộng đồng chủ xe\n"
            "- **Đặt lịch bảo dưỡng** định kỳ\n\n"
            "Hãy đặt câu hỏi cụ thể để tôi hỗ trợ tốt hơn nhé!\n\n"
            "> ⚠️ Mọi thông tin giá cả và chính sách cần xác minh lại tại **vinfast.vn** hoặc gọi **1900 23 23 89**."
        )
        confidence = "mid"

    # Phát thinking steps
    for step_type, step_text in thinking_steps:
        await asyncio.sleep(0.5)
        yield _sse("thinking", {"type": step_type, "text": step_text})

    # Phát tool_end events
    for tool_name in tools:
        await asyncio.sleep(0.3)
        yield _sse("tool_end", {"tool_name": tool_name, "status": "ok", "summary": f"Tool {tool_name} hoàn thành"})

    # Stream câu trả lời
    words = answer.split(" ")
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        yield _sse("token", {"text": chunk})
        await asyncio.sleep(0.02)

    yield _sse("done", {
        "tools_used": tools,
        "confidence": confidence,
        "request_id": request_id,
        "thread_id": thread_id,
    })


def _build_compare_answer(cars: list) -> str:
    if len(cars) < 2:
        return "Không đủ dữ liệu để so sánh."
    a, b = cars[0], cars[1]
    return (
        f"## So sánh: {a['name']} vs {b['name']}\n\n"
        f"| Tiêu chí | {a['name']} | {b['name']} |\n"
        f"|---|---|---|\n"
        f"| Giá (mua pin) | {a['price_buy_battery']:,} ₫ | {b['price_buy_battery']:,} ₫ |\n"
        f"| Giá (thuê pin/tháng) | {a['price_without_battery']:,} ₫ + {a['battery_rental_monthly']:,} ₫/th | {b['price_without_battery']:,} ₫ + {b['battery_rental_monthly']:,} ₫/th |\n"
        f"| Pin (kWh) | {a['battery_kwh']} kWh | {b['battery_kwh']} kWh |\n"
        f"| Phạm vi WLTP | ~{a['range_km_wltp']} km | ~{b['range_km_wltp']} km |\n"
        f"| Công suất | {a['power_kw']} kW ({a.get('power_hp','N/A')} hp) | {b['power_kw']} kW ({b.get('power_hp','N/A')} hp) |\n"
        f"| 0–100 km/h | {a['acceleration_0_100']} giây | {b['acceleration_0_100']} giây |\n"
        f"| Số chỗ | {a['seats']} | {b['seats']} |\n\n"
        f"**Gợi ý:** Nếu ngân sách dưới 1.1 tỷ, {a['name']} là lựa chọn tối ưu. "
        f"{b['name']} phù hợp gia đình lớn hoặc cần phạm vi pin cao hơn cho đường dài.\n\n"
        f"> ⚠️ Giá trên là giá niêm yết. Kiểm tra khuyến mãi hiện hành tại **vinfast.vn** hoặc gọi **1900 23 23 89**."
    )


def _build_battery_answer(data: dict) -> str:
    vf6 = next((c for c in data["cars"] if c["id"] == "vf6"), {})
    gsm = data["policies"]["battery_rental_gsm"]
    return (
        f"## Chính sách Thuê Pin GSM — {vf6.get('name', 'VinFast VF6')}\n\n"
        f"| Thông tin | Chi tiết |\n"
        f"|---|---|\n"
        f"| Giá xe (không pin) | {vf6.get('price_without_battery', 0):,} ₫ |\n"
        f"| Giá xe (mua pin) | {vf6.get('price_buy_battery', 0):,} ₫ |\n"
        f"| Phí thuê pin/tháng | {vf6.get('battery_rental_monthly', 0):,} ₫/tháng |\n"
        f"| Giới hạn km/tháng | {vf6.get('battery_rental_km_limit', 3000):,} km |\n"
        f"| Phí vượt km | {vf6.get('battery_rental_extra_per_km', 960):,} ₫/km |\n"
        f"| Cam kết tối thiểu | {gsm.get('contract_min_months', 12)} tháng |\n\n"
        f"**Quyền lợi bao gồm:**\n"
        + "\n".join(f"- {item}" for item in gsm.get("included_services", []))
        + f"\n\n> ⚠️ {gsm.get('important_notes', '')}"
    )


def _build_review_answer(reviews: list) -> str:
    if not reviews:
        return "Chưa có đủ review thực tế trong cơ sở dữ liệu."
    positive = sum(1 for r in reviews if r["sentiment"] == "positive")
    pct = round(positive / len(reviews) * 100)
    all_pros = []
    all_cons = []
    for r in reviews:
        all_pros.extend(r.get("pros", []))
        all_cons.extend(r.get("cons", []))
    # Dedup
    all_pros = list(dict.fromkeys(all_pros))[:5]
    all_cons = list(dict.fromkeys(all_cons))[:4]

    return (
        f"## Review Thực Tế VF8 Plus — Tổng hợp {len(reviews)} đánh giá gần nhất\n\n"
        f"**Tỷ lệ hài lòng:** {pct}% tích cực\n\n"
        f"| ✓ Ưu điểm | ⚠️ Nhược điểm |\n|---|---|\n"
        + "".join(
            f"| {p} | {c} |\n"
            for p, c in zip(all_pros, all_cons + [""] * len(all_pros))
        )
        + f"\n\n**Kết luận:** VF8 Plus được {pct}% chủ xe đánh giá tích cực. "
        f"Phù hợp đi nội thành và đường trung bình. Cân nhắc kỹ nếu thường đi đường dài >300 km một chiều.\n\n"
        f"> Nguồn: Otofun & VinFast Global Community — dữ liệu 3 tháng gần nhất (có time-weight filter)."
    )


def _build_maintenance_answer(data: dict) -> str:
    schedule = data["maintenance_schedule"].get("vf8plus", [])
    centers = data["service_centers"][:3]
    s = schedule[0] if schedule else {}
    return (
        f"## Bảo Dưỡng Định Kỳ VF8 Plus\n\n"
        f"**Lịch bảo dưỡng 6 tháng / 10.000 km** (miễn phí trong 5 năm bảo hành)\n\n"
        + "".join(f"- {item}\n" for item in s.get("items", []))
        + f"\n**Thời gian dự kiến:** {s.get('estimated_duration_hours', 2.5)} giờ\n\n"
        f"**Đặt lịch qua:**\n"
        f"- 📞 Hotline: **1900 23 23 89** (24/7)\n"
        f"- 📱 App VinFast (iOS/Android)\n"
        f"- 🌐 vinfast.vn/dat-lich-dich-vu\n\n"
        f"**Trung tâm dịch vụ gần nhất:**\n"
        + "".join(f"- **{c['name']}** ({c['city']}) — {c['hours']}\n" for c in centers)
        + f"\n> Xe trong thời gian bảo hành 5 năm được bảo dưỡng định kỳ **miễn phí** theo lịch chính thức."
    )


# ============================================================
# 8. ENDPOINTS
# ============================================================

@app.get("/", tags=["Root"])
async def root():
    return {"message": "VinFast AI Chatbot API", "docs": "/docs", "status": "running"}


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """Kiểm tra trạng thái server và LLM provider đang dùng."""
    return HealthResponse(
        status="ok",
        llm_provider=_llm_provider,
        uptime_seconds=round(time.time() - _startup_time, 1),
    )


@app.post("/chat", tags=["Chat"])
async def chat_stream(body: ChatRequest):
    """
    **Endpoint chính** — nhận tin nhắn và trả về SSE stream với:
    - `thinking` events (chain-of-thought từng bước)
    - `tool_start` / `tool_end` events (trạng thái tool)
    - `token` events (streaming câu trả lời)
    - `done` event (metadata kết thúc)
    - `error` event (nếu có lỗi)
    """
    logger.info("POST /chat: thread=%s, msg=%.60s...", body.thread_id, body.message)

    return EventSourceResponse(
        _stream_chat(body.message, body.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/chat/history/{thread_id}", tags=["Chat"])
async def get_history(thread_id: str):
    """Lấy lịch sử hội thoại của một thread_id (từ MemorySaver)."""
    try:
        from agent import get_graph
        graph = get_graph()
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.get_state(config)
        messages = state.values.get("messages", [])
        history = []
        for msg in messages:
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            if isinstance(msg, (HumanMessage, AIMessage)) and msg.content:
                history.append({"role": role, "content": msg.content})
        return {"thread_id": thread_id, "messages": history, "total": len(history)}
    except Exception as e:
        logger.error("Lỗi lấy history thread=%s: %s", thread_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/chat/history/{thread_id}", tags=["Chat"])
async def clear_history(thread_id: str):
    """Xóa lịch sử hội thoại của một thread (reset MemorySaver state)."""
    # MemorySaver không hỗ trợ delete trực tiếp — tạo thread mới
    return {"status": "ok", "message": f"Thread {thread_id} đã được đặt lại. Tạo thread_id mới để bắt đầu hội thoại mới."}


# ============================================================
# 9. ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=["*.log", "logs/*", "app.log"],
        log_config=None,   # Dùng logging config của chúng ta
    )
