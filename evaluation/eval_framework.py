import sys
import json
import time
from pathlib import Path

# Thêm thư mục backend vào sys.path để import trực tiếp agent (Offline mode)
backend_path = Path(__file__).parent.parent / "prototype" / "backend"
sys.path.append(str(backend_path))

# Load .env
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / "prototype" / ".env"
load_dotenv(dotenv_path=env_path)

try:
    from agent import get_graph
    from langchain_core.messages import HumanMessage
except ImportError as e:
    print(f"Lỗi Import: {e}. Vui lòng cài đặt các thư viện yêu cầu trong prototype/backend/requirements.txt (như langgraph, langchain, v.v..)")
    sys.exit(1)

def run_evaluation(dataset_path: str, output_path: str):
    """
    Load Golden Dataset và ném từng câu query vào LangGraph tĩnh.
    Đo đếm latency và ghi lại Tools mà Agent sử dụng.
    """
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    print(f"[*] Khởi tạo mô hình LangGraph...")
    graph = get_graph()
    results = []
        
    print(f"[*] Bắt đầu đánh giá offline {len(dataset)} câu hỏi...\n" + "="*50)
    
    for item in dataset:
        print(f"Đang xử lý [{item['id']}]: {item['query']}")
        thread_id = f"eval_thread_{item['id']}" # Mỗi câu 1 thread ảo độc lập
        config = {"configurable": {"thread_id": thread_id}}
        
        start_time = time.time()
        try:
            # Pass user query directly to the graph
            response = graph.invoke({"messages": [HumanMessage(content=item['query'])]}, config)
            latency = time.time() - start_time
            
            # Lấy tin nhắn cuối cùng (Final LLM Answer)
            messages = response.get("messages", [])
            final_message = messages[-1].content if messages else ""
            
            # Trích xuất các Tools mà LLM đã quyết định gọi
            tools_used = []
            for msg in messages:
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tools_used.append(tc.get("name"))
            
            error = None
        except Exception as e:
            latency = time.time() - start_time
            final_message = ""
            tools_used = []
            error = str(e)
            print(f" [!] Lỗi runtime: {error}")
            
        print(f" -> Xong trong {latency:.2f} giây. Tools dùng: {tools_used}")
        
        results.append({
            "id": item["id"],
            "query": item["query"],
            "expected_intent": item["expected_intent"],
            "is_trick_question": item["is_trick_question"],
            "ground_truth": item["ground_truth"],
            "latency_seconds": latency,
            "tools_used": tools_used,
            "final_response": final_message,
            "error": error
        })
        
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print("="*50)
    print(f"[*] Hoàn thành! Đã xuất dữ liệu thô ra file:\n    {output_path}")

if __name__ == "__main__":
    dataset_file = Path(__file__).parent / "data" / "golden_dataset.json"
    output_file = Path(__file__).parent / "outputs" / "eval_results.json"
    
    # Đảm bảo thư mục tồn tại
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    run_evaluation(dataset_file, output_file)
