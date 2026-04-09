# ============================================================
# backend/tools/car_tools.py
# Các tools liên quan đến thông tin và so sánh mẫu xe
# ============================================================

import json
import logging
from langchain_core.tools import tool
from data.data_loader import CARS

logger = logging.getLogger(__name__)

@tool
def search_cars(query: str, model_id: str = "") -> str:
    """
    Tìm kiếm thông tin xe VinFast theo câu hỏi hoặc model_id cụ thể.
    Trả về danh sách xe phù hợp với thông số kỹ thuật và giá cả.
    """
    logger.info("Tool search_cars: query=%s, model_id=%s", query, model_id)
    results = []
    q_lower = query.lower()

    if not model_id and not q_lower:
        results = CARS
    else:
        for car in CARS:
            if model_id:
                if model_id.lower() in car["id"].lower():
                    results.append(car)
            else:
                # Nếu LLM truyền query="vf9", tìm các xe có id="vf9..."
                car_base = car["id"].split("_")[0]
                if car_base in q_lower or car["id"].lower() in q_lower or car["name"].lower() in q_lower:
                    results.append(car)
        
        # Fallback: Nếu câu hỏi chung chung (không chứa tên xe), trả về hết
        if not model_id and not results:
            results = CARS

    if not results:
        return json.dumps({"status": "not_found", "message": "Không tìm thấy xe phù hợp."}, ensure_ascii=False)

    return json.dumps({"status": "ok", "cars": results, "total": len(results)}, ensure_ascii=False, indent=2)


@tool
def compare_models(model_ids: list[str]) -> str:
    """
    So sánh nhiều mẫu xe VinFast theo model_id.
    Ví dụ: compare_models(["vf8plus", "vf9plus"])
    """
    logger.info("Tool compare_models: %s", model_ids)
    results = []
    for mid in model_ids:
        for car in CARS:
            if car["id"] == mid.lower():
                results.append(car)
                break

    if len(results) < 2:
        return json.dumps(
            {"status": "error", "message": "Cần ít nhất 2 mẫu xe để so sánh. Kiểm tra lại model_id."},
            ensure_ascii=False
        )

    return json.dumps({"status": "ok", "comparison": results}, ensure_ascii=False, indent=2)
