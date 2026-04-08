#  Nhóm 2 - VinFast AI Product Hackathon

Chúng tôi đang xây dựng giải pháp **VinFast Smart Assistant (VSA)** — Trợ lý AI tăng cường giúp tối ưu hóa hành trình mua xe và bảo dưỡng cho khách hàng.

---

## Đội ngũ thành viên


| Thành viên | Trách nhiệm |
| :--- | :--- |
| **Mai Tấn Thành** (Nhóm trưởng / AI Architect) | Chịu trách nhiệm thiết kế System Prompt và luồng Architecture tổng thể. Đảm bảo Agent biết khi nào gọi RAG chính sách, khi nào gọi RAG review. Setup Guardrails chống Hallucination để bảo vệ chuẩn "Precision" đã đề ra. |
| **Hồ Nhất Khoa** (Data & Pipeline Engineer) | Xây dựng RAG pipeline. Viết script crawl/xử lý data review từ các hội nhóm, thực hiện Document Chunking, Embedding và lưu vào Vector DB. Tích hợp API gọi LLM với độ trễ (latency) tối ưu < 4s. |
| **Đặng Tùng Anh** (Risk & Eval Lead) | Định nghĩa và setup framework đo lường. Tập trung test các Failure Modes. Đảm bảo chỉ số Factuality > 98% trước khi demo. Định đoạt ngưỡng "Kill criteria". |
| **Nguyễn Đức Hoàng Phúc** (Product Manager / QA) | Ánh xạ các User Stories vào thực tế. Chuẩn bị tập Golden Dataset (Baseline) gồm 100 câu hỏi hóc búa nhất của khách VinFast để test hệ thống. Đóng vai khách hàng để liên tục Red-teaming sản phẩm. |
| **Phạm Lê Hoàng Nam** (UI/UX & Frontend) | Hiện thực hóa giao diện Chatbot. Thiết kế trải nghiệm mượt mà cho 4 Paths (Happy, Low-confidence, Failure, Correction). Làm nổi bật UI phần "Trích dẫn nguồn" (Trust building) và các nút CTA "Gặp tư vấn viên", "Đặt lịch lái thử" để chốt sales. |


---


