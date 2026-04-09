# ============================================================
# backend/rag/config.py
# Cấu hình độc lập cho RAG Pipeline
# ============================================================

import os
from pathlib import Path

# Đường dẫn DB mặc định nằm trong thư mục RAG
RAG_DIR = Path(__file__).parent
CHROMA_DB_PATH = RAG_DIR / "chroma_db"

# Tên Collection phân loại theo Data
COLLECTION_REVIEWS = "vinfast_reviews"
COLLECTION_POLICIES = "vinfast_policies"

# Tùy chỉnh Embedding Model
EMBEDDING_MODEL = "text-embedding-3-small"
