# Nhóm 2 - VinFast AI Product Hackathon

Chúng tôi đang xây dựng giải pháp **VinFast Smart Assistant (VSA)** — Trợ lý AI tăng cường giúp tối ưu hóa hành trình mua xe và bảo dưỡng cho khách hàng.

---

## Đội ngũ thành viên

| Thành viên                                        | Trách nhiệm                                                                                                                                                                                                               |
| :------------------------------------------------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Mai Tấn Thành** (Nhóm trưởng / AI Architect)    | Chịu trách nhiệm thiết kế System Prompt và luồng Architecture tổng thể. Đảm bảo Agent biết khi nào gọi RAG chính sách, khi nào gọi RAG review. Setup Guardrails chống Hallucination để bảo vệ chuẩn "Precision" đã đề ra. |
| **Hồ Nhất Khoa** (Data & Pipeline Engineer)       | Xây dựng RAG pipeline. Viết script crawl/xử lý data review từ các hội nhóm, thực hiện Document Chunking, Embedding và lưu vào Vector DB. Tích hợp API gọi LLM với độ trễ (latency) tối ưu < 4s.                           |
| **Đặng Tùng Anh** (Risk & Eval Lead)              | Định nghĩa và setup framework đo lường. Tập trung test các Failure Modes. Đảm bảo chỉ số Factuality > 95% trước khi demo. Định đoạt ngưỡng "Kill criteria".                                                               |
| **Nguyễn Đức Hoàng Phúc** (Product Manager / QA)  | Ánh xạ các User Stories vào thực tế. Chuẩn bị tập Golden Dataset (Baseline) gồm 100 câu hỏi hóc búa nhất của khách VinFast để test hệ thống. Đóng vai khách hàng để liên tục Red-teaming sản phẩm.                        |
| **Phạm Lê Hoàng Nam** (UI/UX, Frontend & Backend) | Phụ trách phát triển BE và FE cho Prototype. Hiện thực hóa giao diện Chatbot và tích hợp hệ thống Agent. Thiết kế trải nghiệm mượt mà cho 4 Paths. Làm nổi bật UI phần "Trích dẫn nguồn" và các nút CTA để chốt sales.    |

---

## Prototype / Mã nguồn thử nghiệm

Thư mục `prototype/` chứa mã nguồn thực nghiệm cho hệ thống AI Chatbot hỗ trợ mua xe, bảo dưỡng và review cho VinFast, sử dụng kiến trúc **LangGraph + FastAPI + Server-Sent Events (SSE)**.

### Cấu trúc dự án

- `backend/`: Khung xử lý chính bằng FastAPI (`main.py`), LangGraph Agent với 6 tools chức năng (`agent.py`) và cơ chế dự phòng LLM liên hoàn (`llm_fallback.py`).
- `frontend/`: Giao diện chatbot xử lý SSE streaming (`app.js`, `index.html`, `style.css`).
- `design-system/`: Các mockup và hướng dẫn thiết kế UI/UX chuyên sâu.

### Kiến trúc & Luồng hoạt động

- **LangGraph Agent & Tools**: Tích hợp các tool như: `search_cars`, `compare_models`, `get_battery_policy`, `get_reviews`, `book_maintenance`, và `get_charging_info`.
- **LLM Fallback Flow**: Cơ chế luân chuyển model thông minh để chống sập server: `Claude 3.5 Sonnet` → `GitHub Models (GPT-4o)` → `Gemini 1.5 Flash` → `MockFallback` (chế độ demo).
- **Conversation Memory**: Quản lý lịch sử hội thoại xuyên suốt phiên làm việc nhờ `thread_id`.

### Điểm nổi bật của UI/UX

- Giao diện **Dark OLED + Brutalist** (font Space Mono, VinFast Red `#DC2626`).
- **Chain of Thought Panel**: Hiển thị rõ các bước: _Suy luận / Công cụ / RAG / Guardrails / Kết quả_.
- **Theo dõi thời gian thực**: Trải nghiệm Streaming tokens (chữ ra từng dòng) và hiển thị thanh trạng thái pipeline tools (_pending → running → complete_).
- **Citations & Confidence Badge**: Cảnh báo độ tin cậy và hiển thị các trích dẫn link nguồn về `vinfast.vn` để xây dựng niềm tin (Trust building).
