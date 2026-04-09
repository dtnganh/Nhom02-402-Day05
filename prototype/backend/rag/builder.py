# ============================================================
# backend/rag/builder.py
# Kịch bản Crawler & Builder: Đọc mock_data, chunk, embed, và lưu Vector DB
# Được chạy bởi Data Engineer (Hồ Nhất Khoa) độc lập với vòng đời Agent
# ============================================================

import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

import sys
sys.path.append(str(Path(__file__).parent.parent))

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

from rag.config import CHROMA_DB_PATH, COLLECTION_REVIEWS, COLLECTION_POLICIES, EMBEDDING_MODEL

# Khởi tạo Log
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Load .env cho API Key
ENV_PATH = Path(__file__).parent.parent.parent / ".env"
load_dotenv(ENV_PATH)

def build_vector_db():
    logger.info("🚀 Bắt đầu quá trình Build Vector DB...")

    if not ENV_PATH.exists():
        logger.warning(f"Cảnh báo: Không tìm thấy file .env tại {ENV_PATH}")

    # 1. Khởi tạo Embeddings thông minh (có Fallback tự động)
    from rag.embeddings_fallback import get_embeddings
    embeddings = get_embeddings()

    # 2. Khởi tạo Kho RAG (Chroma)
    str_db_path = str(CHROMA_DB_PATH)
    review_store = Chroma(
        collection_name=COLLECTION_REVIEWS,
        embedding_function=embeddings,
        persist_directory=str_db_path
    )
    policy_store = Chroma(
        collection_name=COLLECTION_POLICIES,
        embedding_function=embeddings,
        persist_directory=str_db_path
    )

    # 3. Quét Data từ Mock (giả lập bước Crawling Data thực tế ở Backend)
    data_path = Path(__file__).parent.parent / "data" / "mock_data.json"
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # -- Nhúng Data Review --
    logger.info("🔄 Đang xử lý dữ liệu Review...")
    review_docs = []
    for review in data.get("reviews", []):
        if "review_text" in review:
            page_content = f"Đánh giá xe {review.get('car_model', '')} từ {review.get('reviewer_name', 'Khách hàng')}:\n{review.get('review_text', '')}"
            metadata = {
                "car_model": review.get("car_model", ""),
                "sentiment": review.get("sentiment", "unknown"),
                "source": review.get("source", "Hệ thống"),
                "date": review.get("date", ""),
                "rating": review.get("rating", 0)
            }
        else:
            page_content = f"Đánh giá xe {review.get('car_model', '')} từ {review.get('source', '')}:\n{review.get('summary', '')}\nƯu điểm: {', '.join(review.get('pros', []))}\nNhược điểm: {', '.join(review.get('cons', []))}"
            metadata = {
                "car_model": review.get("car_model", ""),
                "sentiment": review.get("sentiment", "unknown"),
                "source": review.get("source", ""),
                "date": review.get("date", ""),
                "rating": review.get("rating", 0)
            }
        review_docs.append(Document(page_content=page_content, metadata=metadata))

    if review_docs:
        review_store.add_documents(review_docs)
        logger.info(f"✅ Đã lưu {len(review_docs)} Review chunks vào DB.")

    # -- Nhúng Data Policies --
    logger.info("🔄 Đang xử lý dữ liệu Chính sách (Policies)...")
    policy_docs = []
    for pol_key, pol_val in data.get("policies", {}).items():
        if isinstance(pol_val, dict):
            # Nếu là Dict, flatten thành chuỗi
            pol_text = "\\n".join([f"{k}: {v}" for k,v in pol_val.items()])
        else:
            pol_text = str(pol_val)
        
        page_content = f"Quy định, chính sách {pol_key}:\n{pol_text}"
        metadata = {
            "policy_type": pol_key
        }
        policy_docs.append(Document(page_content=page_content, metadata=metadata))

    if policy_docs:
        policy_store.add_documents(policy_docs)
        logger.info(f"✅ Đã lưu {len(policy_docs)} Policy chunks vào DB.")

    logger.info(f"🎉 Build RAG thành công! Database cục bộ đặt tại {str_db_path}")

if __name__ == "__main__":
    build_vector_db()
