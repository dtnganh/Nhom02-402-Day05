# ============================================================
# backend/tools/maintenance_tools.py
# Tool tra cứu bảo dưỡng xe
# ============================================================

import json
import logging
from langchain_core.tools import tool
from data.data_loader import MAINTAINANCE, CENTERS

logger = logging.getLogger(__name__)

@tool
def book_maintenance(model_id: str, service_type: str = "periodic") -> str:
    """
    Lấy thông tin đặt lịch bảo dưỡng xe VinFast.
    service_type: 'periodic' (định kỳ), 'repair' (sửa chữa), 'inspection' (kiểm tra)
    """
    logger.info("Tool book_maintenance: model_id=%s, type=%s", model_id, service_type)
    schedule = MAINTAINANCE.get(model_id.lower(), MAINTAINANCE.get("vf8plus", []))
    centers_sample = CENTERS[:3]  # Trả về 3 trung tâm đầu

    result = {
        "status": "ok",
        "model_id": model_id,
        "service_type": service_type,
        "maintenance_intervals": schedule,
        "booking_channels": {
            "phone": "1900 23 23 89",
            "app": "VinFast App (iOS/Android)",
            "website": "https://vinfast.vn/dat-lich-dich-vu",
        },
        "nearby_service_centers": centers_sample,
        "notes": "Xe trong thời gian bảo hành 5 năm được bảo dưỡng định kỳ miễn phí theo lịch chính thức.",
    }

    return json.dumps(result, ensure_ascii=False, indent=2)
