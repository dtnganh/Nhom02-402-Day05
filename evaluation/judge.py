import sys
import json
import time
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / "prototype" / ".env"
load_dotenv(dotenv_path=env_path)

backend_path = Path(__file__).parent.parent / "prototype" / "backend"
sys.path.append(str(backend_path))

try:
    from llm_fallback import get_llm
except ImportError as e:
    print(f"Lỗi Import: {e}")
    sys.exit(1)

def calc_p90(data_list):
    if not data_list: return 0
    sorted_data = sorted(data_list)
    index = int(0.9 * len(sorted_data))
    # Xử lý list nhỏ
    if index >= len(sorted_data):
        index = len(sorted_data) - 1
    return sorted_data[index]

def grade_response(llm, query, ground_truth, ai_response):
    if not ai_response:
        return "FAIL", True, "Không có câu trả lời từ AI"
        
    prompt = f"""Bạn là một trọng tài chấm điểm tự động chuyên nghiệp (AI Judge) cho hãng xe VinFast.
Nhiệm vụ của bạn là đánh giá xem câu trả lời của AI_BOT có tuân thủ đúng định hướng (GROUND_TRUTH) hay không và AI_BOT có bị rơi vào trạng thái Fallback (bất lực) hay không.

Câu hỏi của người dùng: "{query}"
Tiêu chí đúng (GROUND_TRUTH): "{ground_truth}"
Câu trả lời thực tế của AI_BOT:\n"{ai_response}"

THỂ THỨC CHẤM ĐIỂM (FACTUALITY):
- PASS: AI trả lời đúng trọng tâm KHÔNG bịa đặt. Đặc biệt với câu bẫy, nếu AI từ chối hoặc đính chính thì là PASS.
- FAIL: AI bịa đặt, cung cấp thông tin sai lệch.

THỂ THỨC CHẤM FALLBACK (HUMAN FALLBACK):
- CÓ FALLBACK: Khi AI_BOT hoàn toàn KHÔNG trả lời được trọng tâm câu hỏi do thiếu dữ liệu hoặc không chắc chắn, VÀ yêu cầu người dùng phải tự đi hỏi tổng đài/tư vấn viên để biết đáp án.
- KHÔNG FALLBACK: Khi AI_BOT vẫn phân tích/trả lời được thông tin một cách đầy đủ bổ ích, và chỉ chèn thêm câu gợi ý/khuyến cáo (gọi hotline để đặt lịch/xác nhận tùy thích) ở đuôi câu trả lời như một disclaimer.

YÊU CẦU ĐẦU RA:
Dòng 1: Ghi chính xác chữ PASS hoặc FAIL
Dòng 2: Ghi chính xác chữ FALLBACK hoặc NO_FALLBACK
Dòng 3: Giải thích ngắn gọn (dưới 3 câu) lý do.
"""
    try:
        res = llm.invoke(prompt)
        text = res.content.strip()
        lines = text.split("\n")
        score_fact = "PASS" if "PASS" in lines[0].upper() else "FAIL"
        is_fallback = True if "FALLBACK" in lines[1].upper() and "NO_FALLBACK" not in lines[1].upper() else False
        reason = "\n".join(lines[2:]).strip()
        return score_fact, is_fallback, reason
    except Exception as e:
        return "ERROR", False, str(e)


def main():
    results_path = Path(__file__).parent / "outputs" / "eval_results.json"
    judge_output_path = Path(__file__).parent / "outputs" / "judge_results.json"
    
    # Đảm bảo thư mục tồn tại
    judge_output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not results_path.exists():
        print(f"Không tìm thấy file {results_path}. Hãy chạy eval_framework.py trước!")
        return
        
    print("[*] Khởi tạo LLM Judge (Trọng tài chấm điểm)...")
    llm = get_llm()
    
    with open(results_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    total_q = len(data)
    passed_count = 0
    fallback_count = 0
    latencies = []
    
    print(f"[*] Đang chấm điểm {total_q} câu hỏi...\n" + "="*50)
    for i, item in enumerate(data):
        print(f" -> Đang chấm câu {i+1}: {item['id']}")
        latencies.append(item.get("latency_seconds", 0))
        
        # Grading Factuality & Fallback
        score, is_fallback, reason = grade_response(llm, item["query"], item["ground_truth"], item["final_response"])
        item["judge_score"] = score
        item["judge_reason"] = reason
        item["is_fallback"] = is_fallback
        
        if score == "PASS":
            passed_count += 1
        if is_fallback:
            fallback_count += 1
            
    print("\nĐang tổng hợp báo cáo...")
    
    factuality_rate = (passed_count / total_q) * 100
    fallback_rate = (fallback_count / total_q) * 100
    p90_latency = calc_p90(latencies)
    
    # Quyết định Kill criteria
    if factuality_rate < 95:
        decision = "🚨 RED FLAG (THẤT BẠI): Độ chính xác dưới 95%. AI bịa đặt quá nhiều (Hallucination cao). Yêu cầu dừng Deploy! Gọi team Dev sửa lỗi!"
    elif fallback_rate > 50:
        decision = "🚨 WARNING (CẢNH BÁO): Tỷ lệ chuyển sang Human Agent > 50%. AI quá vô dụng, sẽ làm phiền thêm cho Sale. Cần cải thiện System Prompt."
    else:
        decision = "✅ GREEN LIGHT (THÀNH CÔNG): Hệ thống ổn định, đạt ngưỡng an toàn, sẵn sàng đem đi trình diễn Demo!"
        
    # Tạo Text Report
    report_text = f"""==================================================
[📊 BÁO CÁO KẾT QUẢ ĐÁNH GIÁ - RISK & EVAL]
- Số lượng câu hỏi đã chấm: {total_q}
- Factuality / Accuracy:    {factuality_rate:.1f}%  (Mục tiêu: > 95%)
- Human Fallback Rate:      {fallback_rate:.1f}%  (Mục tiêu: < 30%)
- P90 Latency:              {p90_latency:.2f} s  (Mục tiêu: < 10s)

[⚖️ QUYẾT ĐỊNH CỦA HỆ THỐNG (KILL CRITERIA)]
{decision}
=================================================="""

    # In ra Terminal
    print(f"\n{report_text}")
    
    # Lưu ra file log
    report_file_path = Path(__file__).parent / "outputs" / "final_eval_report.log"
    with open(report_file_path, "w", encoding="utf-8") as f:
        f.write(report_text)
        
    # Chuẩn bị lưu Report ra file JSON tổng hợp
    final_output = {
        "summary": {
            "total_questions": total_q,
            "factuality_rate": round(factuality_rate, 2),
            "fallback_rate": round(fallback_rate, 2),
            "p90_latency_seconds": round(p90_latency, 2),
            "kill_criteria_decision": decision
        },
        "detailed_results": data
    }
        
    with open(judge_output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
        
    print(f"\n[*] Chi tiết lời phê từng câu được lưu tải file: {judge_output_path}")

if __name__ == "__main__":
    main()
