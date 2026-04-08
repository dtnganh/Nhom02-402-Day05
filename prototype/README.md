# VinFast AI Chatbot — Prototype

> AI Chatbot hỗ trợ mua xe, bảo dưỡng và review cho VinFast | **LangGraph + FastAPI + SSE**

---

## Cấu trúc dự án

```
prototype/
├── backend/
│   ├── main.py           # FastAPI app (SSE /chat, /health, /chat/history)
│   ├── agent.py          # LangGraph StateGraph + 6 Tools + MemorySaver
│   ├── llm_fallback.py   # LLM fallback chain: Claude → GitHub Models → Gemini
│   └── mock_data.json    # Dữ liệu giả lập VinFast (xe, giá, review, policy)
├── frontend/
│   ├── index.html        # Giao diện chatbot (Brutalist + AI-Native)
│   ├── style.css         # Design system (OLED dark, Space Mono, red accent)
│   └── app.js            # Logic SSE streaming, COT panel, tool status
├── .env.example          # Template biến môi trường
├── .env                  # ← Tạo file này và điền API keys
├── requirements.txt      # Python dependencies
└── README.md
```

---

## Cài đặt & Chạy

### 1. Cài Python dependencies

```powershell
pip install -r requirements.txt
```

### 2. Cấu hình API Keys

Mở file `.env` và điền ít nhất **một** API key:

```env
# Ưu tiên Claude → GitHub Models → Gemini (fallback thứ tự)
ANTHROPIC_API_KEY=sk-ant-...       # Claude 3.5 Sonnet
GITHUB_PAT=ghp_...                  # GitHub Models (GPT-4o)
GOOGLE_API_KEY=AIza...              # Gemini 1.5 Flash
```

> Nếu không có API key nào, server chạy ở **chế độ Mock** với dữ liệu giả lập. Frontend vẫn đầy đủ tính năng.

### 3. Khởi động Backend

```powershell
python backend/main.py
```

Server chạy tại: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

### 4. Mở Frontend

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
               Claude → GitHub Models → Gemini
```

### SSE Events từ `/chat`

| Event | Nội dung | Mô tả |
|-------|----------|-------|
| `start` | `{request_id, thread_id}` | Bắt đầu xử lý |
| `thinking` | `{type, text}` | Chain-of-thought từng bước |
| `tool_end` | `{tool_name, status, summary}` | Tool đã chạy xong |
| `token` | `{text}` | Từng từ của câu trả lời |
| `done` | `{tools_used, confidence, ...}` | Kết thúc, metadata |
| `error` | `{message, detail}` | Lỗi xử lý |

---

## Tools của Agent

| Tool | Chức năng |
|------|-----------|
| `search_cars` | Tìm kiếm thông tin và giá xe |
| `compare_models` | So sánh 2+ mẫu xe |
| `get_battery_policy` | Chính sách thuê/mua pin GSM |
| `get_reviews` | Review thực tế từ cộng đồng (có time-weight) |
| `book_maintenance` | Thông tin đặt lịch bảo dưỡng |
| `get_charging_info` | Mạng sạc VinFast |

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
```

---

## LLM Fallback Flow

```
get_llm()
  ├── 1. Claude (ANTHROPIC_API_KEY)  ✓ nếu key hợp lệ
  ├── 2. GitHub Models (GITHUB_PAT)  ✓ nếu bước 1 thất bại
  ├── 3. Gemini (GOOGLE_API_KEY)     ✓ nếu bước 2 thất bại
  └── 4. MockFallback                ✓ nếu không có key nào (demo mode)
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

---

*Nhóm 2 — AI Product Hackathon VinFast*
