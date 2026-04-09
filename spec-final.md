# SPEC Final — VinFast Smart Assistant (VSA)

**Nhóm:** Nhóm 2

**Track:** [x] VinFast · [ ] Vinmec · [ ] VinUni-VinSchool · [ ] XanhSM · [ ] Open

**Problem statement (1 câu):**

Khách hàng mua và bảo dưỡng xe VinFast thường bị ngợp bởi lượng lớn thông tin chính sách, tốn thời gian tra cứu review rải rác trên các hội nhóm; AI Chatbot sẽ giải quyết nỗi đau này bằng cách đóng vai trò trợ lý thông minh (RAG + Agent) giúp tổng hợp review khách quan, giải đáp chính xác chính sách và hỗ trợ đặt lịch tự động.

---

## 1. AI Product Canvas

|   | Value | Trust | Feasibility |
|---|-------|-------|-------------|
| **Câu hỏi** | User nào? Pain gì? AI giải gì? | Khi AI sai thì sao? User sửa bằng cách nào? | Cost/latency bao nhiêu? Risk chính? |
| **Trả lời** | **User:** Khách hàng tiềm năng mua xe hoặc chủ xe VinFast cần bảo dưỡng. <br>**Pain:** Ngợp thông tin chính sách (giá, thuê pin), khó tìm review thực tế đáng tin cậy. <br>**AI giải:** Tự động hóa việc tra cứu chính sách bằng RAG, dùng Agent tổng hợp review đa chiều từ cộng đồng. | **Khi AI sai:** Khách hàng có thể hiểu lầm giá/chính sách, gây bức xúc và rủi ro pháp lý/truyền thông cho hãng. <br>**User sửa:** Nút "Báo lỗi", "Dislike", hoặc click "Gặp tư vấn viên". AI luôn trích dẫn nguồn (URL) để user tự đối chiếu. | **Cost:** Chi phí API LLM + Vector DB lưu trữ (~$0.02/query). <br>**Latency:** < 3s cho câu hỏi chính sách (RAG), < 6s cho tổng hợp review (Agent). <br>**Risk chính:** Hallucination (bịa giá/thông số), data review bị lỗi thời. |

---

**Automation hay augmentation?** [ ] Automation · [x] Augmentation

**Justify:** Mua ô tô là quyết định tài chính lớn (High-stakes). AI chỉ đóng vai trò "Augmentation" (trợ lý tăng cường): tư vấn, tóm tắt, chuẩn bị thông tin để khách hàng ra quyết định dễ dàng hơn. Quyết định chốt sales, cọc tiền hay book lịch cuối cùng vẫn do khách hàng thao tác trực tiếp hoặc chuyển giao (hand-off) cho Human Agent (tư vấn viên) xử lý để đảm bảo trải nghiệm trọn vẹn nhất.

---

**Learning signal:**

1. **User correction đi vào đâu?** Nút Thumbs up/down, report lỗi, hoặc hành vi "Yêu cầu gặp nhân viên" ngay sau câu trả lời của AI. Dữ liệu này đẩy thẳng về bảng `Feedback_Logs` để team Data phân tích và refine lại System Prompt hoặc Document Chunking.

2. **Product thu signal gì để biết tốt lên hay tệ đi?** (1) Tỷ lệ chuyển đổi (Conversion Rate) từ Chat -> Đặt lịch lái thử/bảo dưỡng; (2) Tỷ lệ Deflection Rate (số case AI tự giải quyết không cần Human Agent); (3) Tỷ lệ Factuality (đo bằng auto-evaluator).

3. **Data thuộc loại nào?** [ ] User-specific · [x] Domain-specific · [x] Real-time · [ ] Human-judgment · [ ] Khác: ___

   **Có marginal value không? (Model đã biết cái này chưa?)** Rất cao. Các General LLM (như ChatGPT-4) không thể cập nhật chính sách giá VinFast tháng này, chính sách thuê pin mới nhất, hoặc các lỗi phần mềm vừa được fix trên VF8 ngày hôm qua. RAG & Real-time data là bắt buộc.

---

## 2. User Stories — 4 paths

### Feature: AI RAG giải đáp chính sách và báo giá xe

**Trigger:** Khách hàng hỏi thông tin về giá, chính sách thuê pin hoặc thông số xe trên website/app VinFast (vd: "VF6 base mua pin và thuê pin giá thế nào?").

| Path | Câu hỏi thiết kế | Mô tả |
|------|-------------------|-------|
| Happy — AI đúng, tự xử | User thấy gì? Flow kết thúc ra sao? | User nhận được bảng giá chính xác, so sánh rõ mua/thuê pin kèm link bài viết gốc trên VinFast. Flow kết thúc bằng nút CTA: "Đặt lịch lái thử ngay" hoặc "Tính toán trả góp". |
| Low-confidence — AI không chắc | System báo "không chắc" bằng cách nào? User quyết thế nào? | AI quét không thấy chính sách khuyến mãi của tháng hiện tại. AI đáp: "Dữ liệu khuyến mãi tháng này có thể đã cập nhật. Để đảm bảo quyền lợi tốt nhất, tôi có thể kết nối bạn với chuyên viên bán hàng nhé?". User click "Đồng ý". |
| Failure — AI sai | User biết AI sai bằng cách nào? Recover ra sao? | AI báo sai giá (vd rẻ hơn thực tế). User đối chiếu với link nguồn do AI cung cấp hoặc website thấy lệch. User recover bằng cách bấm "Report lỗi dữ liệu" hoặc yêu cầu gặp nhân viên. |
| Correction — user sửa | User sửa bằng cách nào? Data đó đi vào đâu? | User bấm Thumbs down, chọn lý do "Thông tin sai lệch". Log này tự động kích hoạt alert trên Slack của Dev/Content team để update lại file PDF chính sách trong Vector DB. |

---

### Feature: AI Agent tổng hợp review thực tế người dùng

**Trigger:** Khách hàng yêu cầu so sánh hoặc hỏi về trải nghiệm thực tế (vd: "VF8 bản Plus chạy đường trường có ồn không, pin thực tế đi được bao xa?").

| Path | Câu hỏi thiết kế | Mô tả |
|------|-------------------|-------|
| Happy — AI đúng, tự xử | User thấy gì? Flow kết thúc ra sao? | AI tóm tắt pros/cons dựa trên 10 topic gần nhất trên Otofun/VinFast Global. AI trích dẫn: "80% user đánh giá cách âm tốt, tuy nhiên ở dải tốc độ >100km/h có tiếng gió. Pin thực tế ~380km". Flow kết thúc bằng đề xuất: "Bạn có muốn xem chi tiết thông số cách âm không?". |
| Low-confidence — AI không chắc | System báo "không chắc" bằng cách nào? User quyết thế nào? | Model vừa ra mắt (vd VF3), chưa có đủ review thực tế. AI báo: "Hiện VF3 mới giao xe nên chưa có nhiều đánh giá đường trường. Tôi chỉ có thể cung cấp thông số từ nhà sản xuất. Bạn muốn xem không?". User chọn Có/Không. |
| Failure — AI sai | User biết AI sai bằng cách nào? Recover ra sao? | AI lấy nhầm review của bản phần mềm cũ (đã được fix) và nói xe bị lỗi màn hình. User đọc các comment mới nhất trên mạng thấy khác. User recover bằng cách chat: "Review này cũ rồi, tìm cái mới đi". |
| Correction — user sửa | User sửa bằng cách nào? Data đó đi vào đâu? | User chat chỉnh AI. Hành vi này được log lại để team cải thiện thuật toán Retrieval (phải ưu tiên `time_weight` - lấy review mới nhất thay vì review có lượng tương tác cao nhưng cũ). |

---

## 3. Eval metrics + threshold

**Optimize precision hay recall?** [x] Precision · [ ] Recall

**Tại sao?** Đối với ngành ô tô, cung cấp thông tin sai (giá cả, bảo hành, chính sách thuê pin) sẽ dẫn đến rủi ro bồi thường, khủng hoảng truyền thông và mất niềm tin nghiêm trọng. Do đó, thà AI từ chối trả lời (hy sinh Recall) và chuyển cho nhân viên thật, còn hơn là cố gắng trả lời mọi thứ nhưng bịa ra thông tin sai (tối ưu Precision).

**Nếu sai ngược lại thì chuyện gì xảy ra?** Nếu tối ưu Recall, AI sẽ đoán mò (Hallucination). Ví dụ khách hỏi "VF5 có được miễn phí sạc 2 năm không?", AI muốn chiều khách nên đáp "Có", trong khi thực tế chính sách này đã hết hạn. Hậu quả là VinFast phải xử lý khiếu nại của khách hàng mang đoạn chat ra đối chứng.

| Metric | Threshold | Red flag (dừng khi) |
|--------|-----------|---------------------|
| **Factuality/Accuracy (Độ chính xác dữ liệu)** | > 98% (So với Ground Truth) | < 95% (Dừng deploy, quay lại chỉnh RAG) |
| **Human Fallback Rate (Tỷ lệ chuyển tư vấn viên)** | < 30% (AI tự xử lý được >70%) | > 50% (AI vô dụng, làm phiền user thêm) |
| **P90 Latency (Thời gian phản hồi)** | < 3s (RAG), < 6s (Agent) | > 8s (User mất kiên nhẫn, bỏ đi) |

---

## 4. Top 3 failure modes

| # | Trigger | Hậu quả | Mitigation |
|---|---------|---------|------------|
| 1 | **Hallucination (Bịa giá / chính sách)**: User hỏi lắt léo về khuyến mãi gộp. | Khách hàng vin vào câu chat của AI để đòi quyền lợi, gây thiệt hại tài chính và tranh cãi cho hãng. | Áp dụng Strict System Prompt (chỉ trả lời dựa trên context). Dùng thuật toán **Self-Check** trước khi xuất response. Nếu low-confidence -> Chuyển Human Agent. |
| 2 | **Confusing Car Models (Nhầm lẫn dòng xe)**: User đang hỏi VF8 nhưng nhảy sang hỏi thông số VF6. | Trả lời râu ông nọ cắm cằm bà kia, khách hàng đánh giá AI ngốc nghếch, mất uy tín sản phẩm. | Sử dụng **Metadata Filtering** trong Vector DB. Yêu cầu Agent phân loại rõ Intent và trích xuất đúng Tag (Car_Model) trước khi search query. |
| 3 | **Outdated Review Data (Data lỗi thời)**: User hỏi lỗi phần mềm của năm ngoái. | Khách hàng sợ hãi không mua xe vì tưởng lỗi cũ vẫn còn tồn tại ở phiên bản hiện tại. | Thêm **Time-decay penalty** trong thuật toán search RAG. Ưu tiên trọng số cho các tài liệu/review trong vòng 3 tháng gần nhất. |

---

## 5. ROI 3 kịch bản

|   | Conservative | Realistic | Optimistic |
|---|-------------|-----------|------------|
| **Assumption** | AI chỉ trả lời FAQ cơ bản. User vẫn chuộng hỏi người thật. | AI tóm tắt review tốt, chốt được lịch lái thử cơ bản. Giảm tải tổng đài. | AI hoạt động xuất sắc như một Super Salesman, dẫn dắt user từ A-Z. |
| **Cost** | $1,000 / tháng (API + Infra) | $2,500 / tháng | $5,000 / tháng |
| **Benefit** | Giảm 10% khối lượng ticket hỗ trợ (Tương đương $3,000 nhân sự) | Giảm 30% ticket ($9,000) + Tăng 5% tỷ lệ book lái thử (Ước tính mang lại $10k) | Giảm 60% ticket ($18,000) + Tăng 15% tỷ lệ book lái thử ($30k) |
| **Net** | **+ $2,000 / tháng** | **+ $16,500 / tháng** | **+ $43,000 / tháng** |

**Kill criteria:** Tỷ lệ Hallucination vượt quá 5% trên tập test thực tế, hoặc chi phí vận hành API/query vượt quá chi phí trung bình để một nhân viên Telesales chăm sóc khách hàng đó.

---

## 6. Mini AI spec (1 trang)

### TẦM NHÌN SẢN PHẨM (VISION)

"Biến hành trình mua xe và bảo dưỡng VinFast từ việc **'bơi trong biển thông tin'** thành một trải nghiệm **'trò chuyện với chuyên gia 1:1'**".

Sản phẩm là một AI Chatbot đóng vai trò Augmentation: Trợ lý đắc lực trang bị RAG để giải đáp chính sách chuẩn xác tuyệt đối, và Agent để tóm tắt review đa chiều từ cộng đồng. Mục tiêu tối thượng: Tối ưu hóa **Precision** (Chính xác tuyệt đối), tăng tỷ lệ Lead Conversion (đặt lịch) và giảm tải cho Customer Service.

---

### KIẾN TRÚC & WORKFLOW CỐT LÕI (HOW IT WORKS)

1. **User Query Input:** Khách hàng nhập câu hỏi (VD: "VF6 pin thuê bao nhiêu? Chạy có ồn không?").

2. **Intent Router (Agent):** Phân loại câu hỏi thành 2 luồng:

   - *Luồng Chính sách/Giá (RAG Core):* Truy vấn Vector DB chứa tài liệu chính thống VinFast. Yêu cầu filter đúng Metadata dòng xe.

   - *Luồng Review (Agentic Web Search/Forum DB):* Thu thập các comment mới nhất, dùng LLM tóm tắt Pros/Cons.

3. **Response & Guardrails:** AI tổng hợp câu trả lời, đi qua lớp Guardrails (check fact). Nếu tự tin -> Phản hồi kèm Citation (link) + CTA Đặt lịch. Nếu không tự tin -> Graceful degradation (Xin lỗi và đẩy sang Human Agent).

---

### CHIẾN LƯỢC THỰC THI & PHÂN CHIA NGUỒN LỰC (NHÓM 2)

Để biến SPEC này thành MVP chiến thắng tại Hackathon, team áp dụng phương pháp Agile, chia để trị dựa trên thế mạnh của 5 thành viên:

*   **Mai Tấn Thành (Nhóm trưởng / AI Architect):** Chịu trách nhiệm thiết kế System Prompt và luồng Architecture tổng thể. Đảm bảo Agent biết khi nào gọi RAG chính sách, khi nào gọi RAG review. Setup Guardrails chống Hallucination để bảo vệ chuẩn "Precision" đã đề ra.

*   **Hồ Nhất Khoa (Data & Pipeline Engineer):** Xây dựng RAG pipeline. Viết script crawl/xử lý data review từ các hội nhóm, thực hiện Document Chunking, Embedding và lưu vào Vector DB. Tích hợp API gọi LLM với độ trễ (latency) tối ưu < 4s.

*   **Đặng Tùng Anh (Risk & Eval Lead):** Định nghĩa và setup framework đo lường. Tập trung test các Failure Modes (đặc biệt là nhầm lẫn xe VF6/VF8 và lỗi giá tiền). Đảm bảo chỉ số Factuality > 98% trước khi demo. Định đoạt ngưỡng "Kill criteria".

*   **Nguyễn Đức Hoàng Phúc (Product Manager / QA):** Ánh xạ các User Stories vào thực tế. Chuẩn bị tập Golden Dataset (Baseline) gồm 100 câu hỏi hóc búa nhất của khách VinFast để test hệ thống. Đóng vai khách hàng để liên tục Red-teaming sản phẩm.

*   **Phạm Lê Hoàng Nam (UI/UX, Frontend & Backend):** Phụ trách phát triển BE và FE cho Prototype. Hiện thực hóa giao diện Chatbot và tích hợp hệ thống Agent. Thiết kế trải nghiệm mượt mà cho 4 Paths. Làm nổi bật UI phần "Trích dẫn nguồn" và các nút CTA để chốt sales.

---

### WHY WE WILL WIN?

Giải pháp của Nhóm 2 không cố gắng làm một AI "biết tuốt" viển vông. Chúng tôi chọn **Augmentation thay vì Automation**, chọn **Precision thay vì Recall**. Bằng cách kiểm soát chặt chẽ rủi ro Hallucination và tập trung vào các Use-case ra tiền (Tóm tắt review -> Build Trust -> Book lịch), dự án không chỉ khả thi về mặt kỹ thuật mà còn mang lại ROI rõ ràng cho mảng kinh doanh của VinFast.
