# ============================================================
# backend/data/data_loader.py
# Module tải dữ liệu giả lập từ mock_data.json
# ============================================================

import json
from pathlib import Path

# ---- Load mock data ----
_DATA_PATH = Path(__file__).parent / "mock_data.json"

try:
    with _DATA_PATH.open(encoding="utf-8") as f:
        _DATA = json.load(f)
except FileNotFoundError:
    _DATA = {"cars": [], "reviews": [], "maintenance_schedule": {}, "service_centers": [], "policies": {}}

CARS: list[dict] = _DATA.get("cars", [])
REVIEWS: list[dict] = _DATA.get("reviews", [])
MAINTENANCE: dict = _DATA.get("maintenance_schedule", {})
CENTERS: list[dict] = _DATA.get("service_centers", [])
POLICIES: dict = _DATA.get("policies", {})
