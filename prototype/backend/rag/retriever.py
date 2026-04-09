# ============================================================
# backend/rag/retriever.py
# Module cung cấp hàm Query Database, ẩn đi sự phức tạp của RAG với Agent
# ============================================================

import logging
import os
from typing import List, Dict, Any, Optional

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

from rag.config import CHROMA_DB_PATH, COLLECTION_REVIEWS, COLLECTION_POLICIES, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# Lazy init
_embeddings = None
_review_store = None
_policy_store = None

def _get_stores():
    """Khởi tạo kết nối Vector DB ở chế độ Đọc - Lazy Loading"""
    global _embeddings, _review_store, _policy_store
    
    if _review_store is not None and _policy_store is not None:
        return _review_store, _policy_store

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-placeholder"):
        logger.warning("OPENAI_API_KEY không có. RAG Retriever có thể gặp lỗi.")

    try:
        _embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
        str_db_path = str(CHROMA_DB_PATH)
        
        # Chỉ tạo kết nối, không mutate data
        _review_store = Chroma(
            collection_name=COLLECTION_REVIEWS,
            embedding_function=_embeddings,
            persist_directory=str_db_path
        )
        
        _policy_store = Chroma(
            collection_name=COLLECTION_POLICIES,
            embedding_function=_embeddings,
            persist_directory=str_db_path
        )
        
        logger.info("✅ Load Vector DB thành công cho RAG")
    except Exception as e:
        logger.error(f"❌ Lỗi khởi tạo Vector DB: {e}")
        
    return _review_store, _policy_store


def search_reviews(model_id: str, query: str = "", max_results: int = 5) -> List[Dict[str, Any]]:
    """Tìm kiếm Reviews bằng Semantic Search kết hợp Metadata Filter"""
    store, _ = _get_stores()
    if store is None:
        return []

    # Xây dựng Query bằng Semantic
    search_query = query if query else f"Ưu điểm nhược điểm đánh giá review về xe {model_id}"
    
    # Pre-filtering: Phải đúng dòng xe (Hỗ trợ biến thể như plus, eco)
    search_kwargs = {"k": max_results}
    if model_id:
        model_base = model_id.lower().replace("plus", "").replace("eco", "").strip()
        search_kwargs["filter"] = {
            "car_model": {
                "$in": [model_base, f"{model_base}plus", f"{model_base}eco"]
            }
        }

    retriever = store.as_retriever(search_kwargs=search_kwargs)
    docs = retriever.invoke(search_query)

    # Chuyển Docs thành Dict sạch sẽ trả về Tool
    results = []
    for d in docs:
        results.append({
            "content": d.page_content,
            "source": d.metadata.get("source", "Unknown"),
            "sentiment": d.metadata.get("sentiment", "Unknown"),
            "date": d.metadata.get("date", "Unknown"),
        })

    return results


def search_policy(query: str, max_results: int = 2) -> List[Dict[str, Any]]:
    """Tìm kiếm chính sách (Pin, Bảo hành, Sạc)"""
    _, store = _get_stores()
    if store is None:
        return []

    retriever = store.as_retriever(search_kwargs={"k": max_results})
    docs = retriever.invoke(query)

    results = []
    for d in docs:
        results.append({
            "policy_type": d.metadata.get("policy_type", "Unknown"),
            "content": d.page_content
        })
    return results
