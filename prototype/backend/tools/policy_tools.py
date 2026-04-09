# ============================================================
# backend/tools/policy_tools.py
# Các tools liên quan đến chính sách, sạc và pin
# ============================================================

import json
import logging
from langchain_core.tools import tool
from data.data_loader import POLICIES, CARS

logger = logging.getLogger(__name__)

@tool
def get_battery_policy(model_id: str = "") -> str:
    """
    Lấy thông tin chính sách thuê pin (GSM) cho một hoặc tất cả dòng xe.
    """
    logger.info("Tool get_battery_policy: model_id=%s", model_id)
    gsm = POLICIES.get("battery_rental_gsm", {})
    warranty = POLICIES.get("warranty", {})

    # Lấy phí thuê pin cụ thể cho model
    car_info = None
    if model_id:
        for car in CARS:
            if car["id"] == model_id.lower():
                car_info = car
                break

    result = {
        "status": "ok",
        "gsm_policy": gsm,
        "warranty_policy": warranty,
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
    charging = POLICIES.get("charging", {})
    car_info = None
    if model_id:
        for car in CARS:
            if car["id"] == model_id.lower():
                car_info = car
                break

    return json.dumps({
        "status": "ok",
        "charging_network": charging,
        "model_specific_range": {
            "model": car_info["name"] if car_info else "N/A",
            "range_wltp_km": car_info.get("range_km_wltp") if car_info else None,
            "battery_kwh": car_info.get("battery_kwh") if car_info else None,
        } if car_info else None
    }, ensure_ascii=False, indent=2)
