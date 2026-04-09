# Prototype — VinFast Smart Assistant (VSA)

## Mô tả

AI Chatbot hỗ trợ khách hàng mua xe và bảo dưỡng VinFast. User nhập câu hỏi tự nhiên bằng tiếng Việt, hệ thống phân loại intent, tra cứu dữ liệu thực qua 6 tool chuyên biệt (RAG + Vector DB), và trả lời chính xác kèm citation nguồn + CTA đặt lịch.

## Level: Working Prototype ✅

- Giao diện chat stream real-time (SSE)
- AI thật: Claude Sonnet (Anthropic) với fallback GPT-4o / Gemini
- 6 tool chạy thật: search_cars, compare_models, get_battery_policy, get_reviews (RAG), book_maintenance, get_charging_info
- LangGraph Agent với Intent Router + Guardrails chống hallucination

## Links

- **Prototype repo:** https://github.com/dtnganh/Nhom02-402-Day05
- **Backend:** `prototype/backend/` — FastAPI + LangGraph
- **Frontend:** `prototype/backend/frontend/` — HTML/CSS/JS OLED dark theme
- **Evaluation:** `evaluation/` — Golden Dataset 100 câu + auto-judge

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | Claude Sonnet (Anthropic) → GPT-4o → Gemini 2.5 Flash (fallback) |
| Agent | LangGraph (StateGraph + MemorySaver) |
| RAG | Vector DB + Embedding (ChromaDB / FAISS) |
| Backend | FastAPI + SSE streaming |
| Frontend | Vanilla HTML/CSS/JS |
| Eval | LLM-as-a-judge + Golden Dataset |

## Phân công

| Thành viên | Role | Output cụ thể |
|---|---|---|
| **Mai Tấn Thành** | AI Architect | `agent.py`: Intent Router node, Guardrails node (hallucination detection), System Prompt (prompts.md) — 6-tool routing, precision-first design |
| **Hồ Nhất Khoa** | Data & Pipeline Engineer | `tools/` module (RAG tools), `rag/` Vector DB pipeline, `data/` mock + embedding |
| **Đặng Tùng Anh** | Risk & Eval Lead | `evaluation/`: eval_framework.py, judge.py, test_failure_modes.py, golden_dataset.json (100 câu) |
| **Nguyễn Đức Hoàng Phúc** | Product Manager / QA | SPEC User Stories, Golden Dataset câu hỏi, Red-teaming |
| **Phạm Lê Hoàng Nam** | Backend & Frontend | `main.py` (FastAPI + SSE), `llm_fallback.py`, `frontend/` (UI) |
