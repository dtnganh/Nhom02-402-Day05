# VinFast AI Chatbot — Prototype

> AI Chatbot hỗ trợ mua xe, bảo dưỡng và review cho VinFast | **LangGraph + FastAPI + SSE**

---

## Cấu trúc dự án

```
prototype/
├── backend/
│   ├── evals/            # Kịch bản tự động đánh giá chất lượng (run_eval.py)
│   ├── main.py           # FastAPI app (SSE /chat, /health, /chat/history)
│   ├── agent.py          # Bộ não cấu hình Prompt & LangGraph Router
│   ├── llm_fallback.py   # LLM fallback chain: OpenRouter → Claude → OpenAI → GitHub Models → Gemini
│   ├── data/             # Nơi lưu trữ Mock data và Data Loader
│   ├── tools/            # Gói công cụ chia theo nghiệp vụ (Xe, Chính sách, Bảo dưỡng)
│   └── rag/              # Khối kiến trúc RAG chuyên sâu kèm Embeddings Fallback
├── frontend/
│   ├── index.html        # Giao diện chatbot (Brutalist + AI-Native)
│   ├── style.css         # Design system (OLED dark, Space Mono, red accent)
│   └── app.js            # Logic SSE streaming, COT panel, tool status
├── logs/                 # Thư mục chứa log ứng dụng (app.log) và dữ liệu feedback (feedback.json)
├── .env.example          # Template biến môi trường
├── .env                  # ← Tạo file này và điền API keys
├── requirements.txt      # Python dependencies
└── README.md
```

---

## Cài đặt & Chạy

### 1. Khởi tạo môi trường ảo và cài dependencies

Nên sử dụng môi trường ảo (virtual environment) để cài đặt các thư viện riêng biệt, tránh xung đột:

```powershell
cd backend
python -m venv venv

# Kích hoạt venv (trên Windows):
venv\Scripts\activate
# Hoặc trên macOS/Linux:
# source venv/bin/activate

# Cài đặt thư viện (trỏ về file requirements.txt ở thư mục gốc)
pip install -r ../requirements.txt
```

### 2. Cấu hình API Keys

Mở file `.env` và điền ít nhất **một** API key:

```env
# Ưu tiên OpenRouter → Claude → OpenAI → GitHub Models → Gemini (fallback thứ tự)
OPENROUTER_API_KEY=sk-or-v1-...    # OpenRouter (hỗ trợ nhiều model free)
ANTHROPIC_API_KEY=sk-ant-...       # Claude 3.5 Sonnet (Chỉ có mô hình Chat, không có Embeddings)
VOYAGE_API_KEY=pa-...              # Voyage AI (Bắt cặp tốt nhất với Claude để làm Embeddings)
OPENAI_API_KEY=sk-proj-...         # OpenAI (GPT-4o-mini & text-embedding-3-small)
GITHUB_PAT=ghp_...                  # GitHub Models (Hỗ trợ Azure Embeddings)
GOOGLE_API_KEY=AIza...              # Gemini 1.5 Flash (Hỗ trợ text-embedding-004)

# LangSmith tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=vinfast-ai-chatbot

# Response cache (MVP)
ENABLE_RESPONSE_CACHE=true
CACHE_TTL_POLICY_SECONDS=600
CACHE_TTL_REVIEW_SECONDS=300
```

> Nếu không có API key nào, server chạy ở **chế độ Mock** với dữ liệu giả lập. Frontend vẫn đầy đủ tính năng.

### 3. Build Vector DB cho hệ thống RAG

Hệ thống hiện tại tích hợp RAG chuyên nghiệp cho Dữ liệu phi cấu trúc (Reviews, Chính sách) bằng Chroma DB.
Mô hình Vector Embeddings cũng được cấu hình fallback đa tầng để hỗ trợ mọi thành viên trong đội:
👉 `Voyage AI` → `GitHub Models` → `OpenAI` → `Gemini` → `HuggingFace (CPU Local miễn phí)`

Trước khi chạy hệ thống, **BẮT BUỘC** bạn phải chạy lệnh sau để cắt (chunk) và nhúng (embed) data để tạo DB cục bộ trên máy mình (tùy thuộc vào bạn nhập key nào trong .env):

```powershell
python backend/rag/builder.py
```
*(Vector DB sẽ sinh ra tại `backend/rag/chroma_db` dựa trên kích thước dimension Tensor của bạn. Thư mục này nặng và được bỏ qua bởi .gitignore)*

### 4. Khởi động Backend

```powershell
python backend/main.py
```

Server chạy tại: `http://localhost:8000`

- Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

### 5. Mở Frontend

Mở file `frontend/index.html` trực tiếp trong trình duyệt.

---

## Kiến trúc hệ thống

```
User → [Frontend SSE]
         ↓ POST /chat
      FastAPI (main.py)
         ↓ stream events
      LangGraph Agent (agent.py)
         ├── intent_router
         ├── [Tools] search_cars, compare_models,
         │          get_battery_policy, get_reviews,
         │          book_maintenance, get_charging_info
         ├── MemorySaver (thread_id context)
         └── LLM Fallback (llm_fallback.py)
               Claude → OpenAI → GitHub Models → Gemini
```

### SSE Events từ `/chat`

| Event      | Nội dung                        | Mô tả                      |
| ---------- | ------------------------------- | -------------------------- |
| `start`    | `{request_id, thread_id}`       | Bắt đầu xử lý              |
| `thinking` | `{type, text}`                  | Chain-of-thought từng bước |
| `tool_end` | `{tool_name, status, summary}`  | Tool đã chạy xong          |
| `token`    | `{text}`                        | Từng từ của câu trả lời    |
| `done`     | `{tools_used, confidence, ...}` | Kết thúc, metadata         |
| `error`    | `{message, detail}`             | Lỗi xử lý                  |

`done` hiện bao gồm thêm: `status`, `citations`, `fallback_reason`, `intent_tag`, `route_reason`, `cache_hit`, `latency_ms`.

---

## Tools của Agent

| Tool                 | Chức năng                                    |
| -------------------- | -------------------------------------------- |
| `search_cars`        | Tìm kiếm thông tin và giá xe                 |
| `compare_models`     | So sánh 2+ mẫu xe                            |
| `get_battery_policy` | Chính sách thuê/mua pin GSM                  |
| `get_reviews`        | Review thực tế từ cộng đồng (có time-weight) |
| `book_maintenance`   | Thông tin đặt lịch bảo dưỡng                 |
| `get_charging_info`  | Mạng sạc VinFast                             |

---

## Verification checklist (từ plan.md)

```powershell
# 1. Health check
curl http://localhost:8000/health

# 2. Test chat với memory (thread nhớ ngữ cảnh)
# Gửi 2 tin nhắn cùng thread_id → bot phải nhớ xe đã hỏi

# 3. Kiểm tra fallback
# Đặt ANTHROPIC_API_KEY sai → server log ghi "Claude thất bại, chuyển fallback"

# 4. Kiểm tra log file
# cat app.log → thấy toàn bộ request/response history

# 5. Test tool status
# Hỏi "Tôi muốn bảo dưỡng VF8" → frontend hiển thị tool book_maintenance running

# 6. Test feedback loop
# Click thumbs up/down trên frontend, backend nhận POST /feedback

# 7. Chạy eval nhanh
python backend/evals/run_eval.py --base-url http://localhost:8000
```

## LangSmith instructions (MVP)

1. Bật các biến môi trường `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` trong `.env`.
2. Khởi động backend và thực hiện các phiên chat test trên frontend.
3. Mở LangSmith dashboard để xem traces theo từng request (`request_id`, `intent_tag`, tools gọi và latency).
4. Dùng `backend/evals/sample_dataset.json` làm bộ test khởi tạo, sau đó thay bằng Golden Dataset 100 câu trước demo.

---

## LLM Fallback Flow

```
get_llm()
  ├── 1. Claude (ANTHROPIC_API_KEY)  ✓ nếu key hợp lệ
  ├── 2. OpenAI (OPENAI_API_KEY)     ✓ nếu bước 1 thất bại
  ├── 3. GitHub Models (GITHUB_PAT)  ✓ nếu bước 2 thất bại
  ├── 4. Gemini (GOOGLE_API_KEY)     ✓ nếu bước 3 thất bại
  └── 5. MockFallback                ✓ nếu không có key nào (demo mode)
```

---

## UI Features

- **Dark OLED + Brutalist** — `border-radius: 0px`, Space Mono font, VinFast Red `#DC2626`
- **Chain of Thought Panel** — Hiển thị từng bước suy luận: SUY LUẬN / CÔNG CỤ / RAG / GUARDRAILS / KẾT QUẢ
- **Streaming tokens** — Câu trả lời xuất hiện từng từ theo thời gian thực qua SSE
- **Tool Status Strip** — Pipeline tools `pending → running → complete`
- **Confidence Badge** — ĐỘ TIN CẬY CAO / CÓ THỂ CẦN XÁC MINH / CHUYỂN TƯ VẤN VIÊN
- **Citations Block** — Link nguồn vinfast.vn (trust signal)
- **Feedback** — Thumbs up/down, copy, view reasoning
- **Memory** — Conversation context theo `thread_id`

## MVP Improvements Implemented

- **Token streaming thực**: backend nhường event loop mỗi token (`await asyncio.sleep(0)`) để frontend render theo thời gian thực thay vì dồn cuối response.
- **Lưu/Nạp hội thoại sidebar (không DB)**: frontend lưu conversations vào `localStorage`, hỗ trợ tạo hội thoại mới, mở lại hội thoại cũ và clear hội thoại hiện tại.
- **Confidence động**: backend tính `confidence_score` theo trạng thái tool + độ phủ citations + độ đa dạng nguồn; frontend hiển thị badge mức tin cậy và tooltip score.
- **Citations đa nguồn**: backend tổng hợp nhiều nguồn theo tool output, dedupe URL, giới hạn trùng domain và trả top citations liên quan.

---

_Nhóm 2 — AI Product Hackathon VinFast_
