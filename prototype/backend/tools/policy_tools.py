# ============================================================
# backend/tools/policy_tools.py
# Các tools liên quan đến chính sách, sạc và pin
# ============================================================

import json
import logging
from langchain_core.tools import tool
from data.data_loader import POLICIES, CARS

from rag.retriever import search_policy

logger = logging.getLogger(__name__)

@tool
def get_battery_policy(model_id: str = "") -> str:
    """
    Lấy thông tin chính sách thuê pin (GSM) cho một hoặc tất cả dòng xe.
    """
    logger.info("Tool get_battery_policy: model_id=%s", model_id)
    
    # 1. Dùng RAG để query văn bản chính sách (luật, quy định)
    # CẢNH BÁO RAG: Do số lượng tài liệu chính sách tăng lên (thêm gói 2026), 
    # nếu để max_results=2 sẽ bị "rớt" mất luật mới. Cần tăng max_result!
    rag_docs = search_policy("Chính sách thuê pin GSM, bảo hành và gói thuê pin 2026", max_results=5)
    policies_text = [doc["content"] for doc in rag_docs]

    # 2. Vẫn dùng Data cứng (JSON) để bốc chính xác con số tiền tệ/thông số của từng xe
    car_info = None
    if model_id:
        for car in CARS:
            if car["id"] == model_id.lower():
                car_info = car
                break

    result = {
        "status": "ok",
        "rag_policies_context": policies_text, # Đưa Context từ AI Vector search vào
    }
    if car_info:
        result["model_specific"] = {
            "model": car_info["name"],
            "price_with_battery": car_info.get("price_buy_battery"),
            "price_without_battery": car_info.get("price_without_battery"),
            "battery_rental_monthly_vnd": car_info.get("battery_rental_monthly"),
            "battery_rental_km_limit": car_info.get("battery_rental_km_limit"),
            "battery_rental_extra_per_km": car_info.get("battery_rental_extra_per_km"),
        }

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def get_charging_info(model_id: str = "") -> str:
    """
    Lấy thông tin về mạng sạc VinFast, tốc độ sạc và chi phí.
    """
    logger.info("Tool get_charging_info: model_id=%s", model_id)
    
    # 1. Dùng RAG tìm bối cảnh mạng lưới sạc
    rag_docs = search_policy("Mạng lưới trạm sạc, tốc độ sạc DC AC, V-GREEN", max_results=5)
    charging_context = [doc["content"] for doc in rag_docs]
    
    # 2. Lấy dung lượng pin xe cụ thể từ JSON
    car_info = None
    if model_id:
        for car in CARS:
            if car["id"] == model_id.lower():
                car_info = car
                break

    return json.dumps({
        "status": "ok",
        "rag_charging_context": charging_context,
        "model_specific_range": {
            "model": car_info["name"] if car_info else "N/A",
            "range_wltp_km": car_info.get("range_km_nedc") or car_info.get("range_km_wltp") if car_info else None,
            "battery_kwh": car_info.get("battery_kwh") if car_info else None,
        } if car_info else None
    }, ensure_ascii=False, indent=2)
