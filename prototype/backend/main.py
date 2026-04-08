# ============================================================
# backend/main.py
# FastAPI app: Logging setup, CORS, SSE streaming /chat endpoint
# ============================================================

import json
import hashlib
import asyncio
import logging
import logging.config
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
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


class FeedbackRequest(BaseModel):
    request_id: str = Field(..., min_length=4, max_length=64)
    thread_id: str = Field(..., min_length=4, max_length=64)
    action: str = Field(..., pattern="^(liked|disliked)$")
    reason: str = Field(default="", max_length=500)
    intent_tag: str = Field(default="unknown", max_length=64)
    status: str = Field(default="ok", max_length=32)


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
    allow_credentials=False,
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
# 6.1 CACHE + INTENT HELPERS
# ============================================================

_CACHE: dict[str, dict] = {}
_CACHE_ENABLED = os.getenv("ENABLE_RESPONSE_CACHE", "true").lower() == "true"
_CACHE_TTL_SECONDS = {
    "policy": int(os.getenv("CACHE_TTL_POLICY_SECONDS", "600")),
    "review": int(os.getenv("CACHE_TTL_REVIEW_SECONDS", "300")),
    "maintenance": int(os.getenv("CACHE_TTL_MAINTENANCE_SECONDS", "300")),
    "spec": int(os.getenv("CACHE_TTL_SPEC_SECONDS", "600")),
    "charging": int(os.getenv("CACHE_TTL_CHARGING_SECONDS", "600")),
    "generic": int(os.getenv("CACHE_TTL_GENERIC_SECONDS", "300")),
}


def _normalize_query(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.lower().strip())
    return normalized


def _infer_intent_tag(message: str) -> tuple[str, str]:
    msg = message.lower()
    if any(k in msg for k in ["review", "trải nghiệm", "độ ồn", "ồn", "pin thực tế", "community"]):
        return "review", "Detected review keywords"
    if any(k in msg for k in ["thuê pin", "chính sách", "bảo hành", "giá", "chi phí", "gsm"]):
        return "policy", "Detected policy/price keywords"
    if any(k in msg for k in ["bảo dưỡng", "đặt lịch", "service", "maintenance"]):
        return "maintenance", "Detected maintenance keywords"
    if any(k in msg for k in ["sạc", "trạm sạc", "wltp", "quãng đường"]):
        return "charging", "Detected charging/range keywords"
    if any(k in msg for k in ["so sánh", "thông số", "vf", "model"]):
        return "spec", "Detected model/spec keywords"
    return "generic", "No strong keyword signal"


def _cache_key(message: str, intent_tag: str) -> str:
    raw = f"{intent_tag}::{_normalize_query(message)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    item = _CACHE.get(key)
    if not item:
        return None
    if item["expires_at"] < time.time():
        _CACHE.pop(key, None)
        return None
    return item["value"]


def _cache_set(key: str, value: dict, intent_tag: str) -> None:
    ttl = _CACHE_TTL_SECONDS.get(intent_tag, _CACHE_TTL_SECONDS["generic"])
    _CACHE[key] = {
        "value": value,
        "expires_at": time.time() + ttl,
    }


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
    started = time.perf_counter()
    intent_tag, route_reason = _infer_intent_tag(message)
    key = _cache_key(message, intent_tag)

    logger.info("Chat request [%s] thread=%s: %.80s", request_id, thread_id, message)

    yield _sse("start", {"request_id": request_id, "thread_id": thread_id})

    cached = _cache_get(key) if _CACHE_ENABLED else None
    if cached:
        logger.info("Cache HIT [%s] intent=%s", request_id, intent_tag)
        yield _sse("thinking", {"type": "retrieval", "text": "Cache hit: dùng phản hồi đã xác thực gần nhất"})
        cached_words = cached["answer"].split(" ")
        for i, word in enumerate(cached_words):
            chunk_text = word + (" " if i < len(cached_words) - 1 else "")
            yield _sse("token", {"text": chunk_text})
            await asyncio.sleep(0)
        yield _sse("done", {
            "tools_used": cached["tools_used"],
            "confidence": cached["confidence"],
            "status": cached["status"],
            "citations": cached["citations"],
            "fallback_reason": cached.get("fallback_reason", ""),
            "request_id": request_id,
            "thread_id": thread_id,
            "intent_tag": intent_tag,
            "route_reason": route_reason,
            "cache_hit": True,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        })
        return

    try:
        from agent import get_graph
        graph = get_graph()

        config = {"configurable": {"thread_id": thread_id}}
        input_state = {"messages": [HumanMessage(content=message)]}

        tools_executed: list[str] = []
        tool_statuses: list[str] = []
        tool_outputs: list[dict] = []
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
                            tool_outputs.append({
                                "tool_name": tool_name,
                                "status": status,
                                "payload": tool_result,
                            })
                        except Exception:
                            tool_result = {"status": "ok"}
                            status = "ok"
                            summary = f"Tool {tool_name} chạy xong"

                        tool_statuses.append(status)
                        tool_conf = _tool_confidence_from_result(tool_name, tool_result)

                        yield _sse("tool_end", {
                            "tool_name": tool_name,
                            "status": status,
                            "summary": summary,
                            "confidence_score": tool_conf["score"],
                            "confidence_level": tool_conf["level"],
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
        citations = _build_citations(tool_outputs, intent_tag)
        confidence_meta = _compute_confidence(final_answer, tools_executed, tool_statuses, citations)
        confidence = confidence_meta["level"]
        status = _derive_status(confidence, tool_statuses)
        fallback_reason = ""
        if status == "low_confidence":
            fallback_reason = "Insufficient evidence or low-confidence tool output"

        # Stream từng từ của câu trả lời
        words = final_answer.split(" ")
        for i, word in enumerate(words):
            chunk_text = word + (" " if i < len(words) - 1 else "")
            yield _sse("token", {"text": chunk_text})
            await asyncio.sleep(0.02)

        # ── Done event ──────────────────────────────────────────
        done_payload = {
            "tools_used": tools_executed,
            "confidence": confidence,
            "confidence_score": confidence_meta["score"],
            "status": status,
            "citations": citations,
            "fallback_reason": fallback_reason,
            "request_id": request_id,
            "thread_id": thread_id,
            "intent_tag": intent_tag,
            "route_reason": route_reason,
            "cache_hit": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }

        yield _sse("done", done_payload)

        if _CACHE_ENABLED and status == "ok":
            _cache_set(key, {
                "answer": final_answer,
                "tools_used": tools_executed,
                "confidence": confidence,
                "confidence_score": confidence_meta["score"],
                "status": status,
                "citations": citations,
                "fallback_reason": fallback_reason,
            }, intent_tag)

        logger.info(
            "Chat done [%s]: %d steps, confidence=%s, status=%s, cache_hit=%s",
            request_id,
            step_count,
            confidence,
            status,
            False,
        )

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


def _tool_confidence_from_result(tool_name: str, result: dict) -> dict:
    """Tạo confidence score/level cho từng tool để frontend map màu động."""
    status = result.get("status", "ok")
    base_by_status = {
        "ok": 0.82,
        "low_confidence": 0.36,
        "not_found": 0.30,
        "error": 0.18,
    }
    score = base_by_status.get(status, 0.5)

    # Evidence bonus/penalty từ payload để score không bị cố định.
    evidence_count = 0
    for field in ("cars", "comparison", "reviews", "sources"):
        value = result.get(field)
        if isinstance(value, list):
            evidence_count += len(value)
    if result.get("model_specific"):
        evidence_count += 1

    score += min(0.12, evidence_count * 0.03)
    if tool_name == "get_reviews":
        score -= 0.05  # nguồn cộng đồng cần thận trọng hơn nguồn official

    score = max(0.0, min(1.0, score))
    if score < 0.4:
        level = "low"
    elif score < 0.7:
        level = "mid"
    else:
        level = "high"
    return {"score": round(score, 2), "level": level}


def _compute_confidence(answer: str, tools_used: list[str], tool_statuses: list[str], citations: list[dict]) -> dict:
    """Tính confidence score động theo evidence/tool/citation signals."""
    answer_lower = answer.lower()
    low_confidence_signals = [
        "không chắc", "có thể", "cần xác minh", "liên hệ tư vấn",
        "không tìm thấy", "chưa có đủ", "không đủ thông tin",
    ]

    tool_ok_ratio = (sum(1 for s in tool_statuses if s == "ok") / max(len(tool_statuses), 1)) if tool_statuses else 0.5
    uncertainty_penalty = 0.2 if any(sig in answer_lower for sig in low_confidence_signals) else 0.0
    citation_coverage = min(1.0, len(citations) / 3)
    diversity_domains = len({c.get("domain", "") for c in citations if c.get("domain")})
    citation_diversity = min(1.0, diversity_domains / 2)

    score = 0.55 * tool_ok_ratio + 0.25 * citation_coverage + 0.20 * citation_diversity - uncertainty_penalty
    if any(s == "error" for s in tool_statuses):
        score -= 0.2
    score = max(0.0, min(1.0, score))

    if score >= 0.7:
        level = "high"
    elif score >= 0.4:
        level = "mid"
    else:
        level = "low"

    return {"level": level, "score": round(score, 2)}


def _derive_status(confidence: str, tool_statuses: list[str]) -> str:
    if any(st == "error" for st in tool_statuses):
        return "error"
    if confidence == "low" or any(st in ("low_confidence", "not_found") for st in tool_statuses):
        return "low_confidence"
    return "ok"


def _source_url_from_name(source_name: str) -> str:
    source = (source_name or "").lower()
    if "otofun" in source:
        return "https://www.otofun.net"
    if "community" in source:
        return "https://www.facebook.com/groups/vinfast"
    return "https://vinfast.vn"


def _build_citations(tool_outputs: list[dict], intent_tag: str) -> list[dict]:
    """Sinh nhiều citation đa dạng dựa trên kết quả tool, có dedupe và domain diversity."""
    candidates: list[dict] = []

    for item in tool_outputs:
        tool = item.get("tool_name", "")
        payload = item.get("payload", {})

        if tool in ("search_cars", "compare_models"):
            for car in payload.get("cars", [])[:2]:
                model_id = car.get("id", "")
                name = car.get("name", "VinFast")
                candidates.append({
                    "label": f"{name} - Thông số chính thức",
                    "url": f"https://vinfast.vn/{model_id}" if model_id else "https://vinfast.vn",
                    "domain": "vinfast.vn",
                    "source_type": "official",
                    "score": 0.95,
                })
            for car in payload.get("comparison", [])[:2]:
                model_id = car.get("id", "")
                name = car.get("name", "VinFast")
                candidates.append({
                    "label": f"{name} - So sánh thông số",
                    "url": f"https://vinfast.vn/{model_id}" if model_id else "https://vinfast.vn",
                    "domain": "vinfast.vn",
                    "source_type": "official",
                    "score": 0.93,
                })

        if tool == "get_battery_policy":
            model = payload.get("model_specific", {}).get("model", "VinFast")
            candidates.extend([
                {
                    "label": f"{model} - Chính sách pin",
                    "url": "https://vinfast.vn/chinh-sach-pin",
                    "domain": "vinfast.vn",
                    "source_type": "official",
                    "score": 0.98,
                },
                {
                    "label": "Chính sách bảo hành VinFast",
                    "url": "https://vinfast.vn/chinh-sach-bao-hanh",
                    "domain": "vinfast.vn",
                    "source_type": "official",
                    "score": 0.92,
                },
            ])

        if tool == "get_reviews":
            model_id = payload.get("model_id", "")
            for review in payload.get("reviews", [])[:3]:
                source = review.get("source", "Community")
                source_url = _source_url_from_name(source)
                domain = source_url.replace("https://", "").split("/")[0]
                candidates.append({
                    "label": f"{source} - Review {model_id}",
                    "url": source_url,
                    "domain": domain,
                    "source_type": "community",
                    "score": 0.72,
                })

        if tool == "book_maintenance":
            candidates.extend([
                {
                    "label": "Đặt lịch dịch vụ VinFast",
                    "url": "https://vinfast.vn/dat-lich-dich-vu",
                    "domain": "vinfast.vn",
                    "source_type": "official",
                    "score": 0.96,
                },
                {
                    "label": "Hệ thống trung tâm dịch vụ",
                    "url": "https://vinfast.vn/he-thong-showroom",
                    "domain": "vinfast.vn",
                    "source_type": "official",
                    "score": 0.88,
                },
            ])

        if tool == "get_charging_info":
            candidates.append({
                "label": "Mạng lưới trạm sạc VinFast",
                "url": "https://vinfast.vn/tram-sac",
                "domain": "vinfast.vn",
                "source_type": "official",
                "score": 0.94,
            })

    if not candidates:
        candidates.append({
            "label": "vinfast.vn - Trang chính thức",
            "url": "https://vinfast.vn",
            "domain": "vinfast.vn",
            "source_type": "official",
            "score": 0.80,
        })

    # Deduplicate by URL (keep best score)
    best_by_url: dict[str, dict] = {}
    for c in candidates:
        url = c.get("url", "")
        if url not in best_by_url or c.get("score", 0) > best_by_url[url].get("score", 0):
            best_by_url[url] = c

    ranked = sorted(best_by_url.values(), key=lambda x: x.get("score", 0), reverse=True)

    # Domain diversity: avoid too many links from the same domain
    result: list[dict] = []
    domain_count: dict[str, int] = {}
    for c in ranked:
        d = c.get("domain", "unknown")
        if domain_count.get(d, 0) >= 2:
            continue
        domain_count[d] = domain_count.get(d, 0) + 1
        result.append(c)
        if len(result) >= 5:
            break

    return result


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
        yield _sse("thinking", {"type": step_type, "text": step_text})

    # Phát tool_end events
    for tool_name in tools:
        mock_tool_conf = _tool_confidence_from_result(tool_name, {"status": "ok"})
        yield _sse("tool_end", {
            "tool_name": tool_name,
            "status": "ok",
            "summary": f"Tool {tool_name} hoàn thành",
            "confidence_score": mock_tool_conf["score"],
            "confidence_level": mock_tool_conf["level"],
        })

    # Stream câu trả lời
    words = answer.split(" ")
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        yield _sse("token", {"text": chunk})
        await asyncio.sleep(0.02)

    status = "ok" if confidence in ("high", "mid") else "low_confidence"
    intent_tag, route_reason = _infer_intent_tag(message)

    mock_citations = {
        "compare": [
            {"label": "VF8 Plus - Thông số", "url": "https://vinfast.vn/vf8", "domain": "vinfast.vn", "score": 0.95},
            {"label": "VF9 Plus - Thông số", "url": "https://vinfast.vn/vf9", "domain": "vinfast.vn", "score": 0.94},
        ],
        "battery": [
            {"label": "Chính sách pin VinFast", "url": "https://vinfast.vn/chinh-sach-pin", "domain": "vinfast.vn", "score": 0.98},
            {"label": "Bảo hành VinFast", "url": "https://vinfast.vn/chinh-sach-bao-hanh", "domain": "vinfast.vn", "score": 0.92},
        ],
        "review": [
            {"label": "Otofun - Review VF8", "url": "https://www.otofun.net", "domain": "otofun.net", "score": 0.72},
            {"label": "VinFast Community", "url": "https://www.facebook.com/groups/vinfast", "domain": "facebook.com", "score": 0.70},
            {"label": "Thông tin chính thức VF8", "url": "https://vinfast.vn/vf8", "domain": "vinfast.vn", "score": 0.90},
        ],
        "maintenance": [
            {"label": "Đặt lịch dịch vụ", "url": "https://vinfast.vn/dat-lich-dich-vu", "domain": "vinfast.vn", "score": 0.96},
            {"label": "Showroom và xưởng dịch vụ", "url": "https://vinfast.vn/he-thong-showroom", "domain": "vinfast.vn", "score": 0.88},
        ],
        "generic": [
            {"label": "vinfast.vn - Trang chính thức", "url": "https://vinfast.vn", "domain": "vinfast.vn", "score": 0.80},
        ],
    }
    citations = mock_citations.get(intent, mock_citations["generic"])
    confidence_meta = _compute_confidence(answer, tools, ["ok"] * len(tools), citations)

    yield _sse("done", {
        "tools_used": tools,
        "confidence": confidence_meta["level"],
        "confidence_score": confidence_meta["score"],
        "status": status,
        "citations": citations,
        "fallback_reason": "Mock fallback mode" if status != "ok" else "",
        "request_id": request_id,
        "thread_id": thread_id,
        "intent_tag": intent_tag,
        "route_reason": route_reason,
        "cache_hit": False,
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
        f"| Công suất | {a['power_kw']} kW ({a.get('power_hp', 'N/A')} hp) | {b['power_kw']} kW ({b.get('power_hp', 'N/A')} hp) |\n"
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
        "## Bảo Dưỡng Định Kỳ VF8 Plus\n\n"
        "**Lịch bảo dưỡng 6 tháng / 10.000 km** (miễn phí trong 5 năm bảo hành)\n\n"
        + "".join(f"- {item}\n" for item in s.get("items", []))
        + f"\n**Thời gian dự kiến:** {s.get('estimated_duration_hours', 2.5)} giờ\n\n"
        "**Đặt lịch qua:**\n"
        "- 📞 Hotline: **1900 23 23 89** (24/7)\n"
        "- 📱 App VinFast (iOS/Android)\n"
        "- 🌐 vinfast.vn/dat-lich-dich-vu\n\n"
        "**Trung tâm dịch vụ gần nhất:**\n"
        + "".join(f"- **{c['name']}** ({c['city']}) — {c['hours']}\n" for c in centers)
        + "\n> Xe trong thời gian bảo hành 5 năm được bảo dưỡng định kỳ **miễn phí** theo lịch chính thức."
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


@app.post("/feedback", tags=["Chat"])
async def submit_feedback(body: FeedbackRequest):
    """Nhận phản hồi thumbs up/down cho mỗi phản hồi AI."""
    logger.info(
        "Feedback: request_id=%s thread=%s action=%s intent=%s status=%s reason=%s",
        body.request_id,
        body.thread_id,
        body.action,
        body.intent_tag,
        body.status,
        body.reason,
    )
    return {"status": "ok", "message": "Đã ghi nhận phản hồi", "request_id": body.request_id}


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
