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


def _init_embeddings_with_fallback() -> Optional[OpenAIEmbeddings]:
    """
    Khởi tạo embeddings theo thứ tự ưu tiên:
    1) OpenAI API (OPENAI_API_KEY)
    2) GitHub Models (GITHUB_PAT)
    """
    openai_key = os.getenv("OPENAI_API_KEY", "")
    github_pat = os.getenv("GITHUB_PAT", "")

    if openai_key and not openai_key.startswith("sk-proj-placeholder"):
        try:
            logger.info("🔄 Retriever: thử OPENAI_API_KEY cho embeddings...")
            emb = OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=openai_key)
            emb.embed_query("test")
            logger.info("✅ Retriever: dùng OpenAI Embeddings thành công")
            return emb
        except Exception as exc:
            logger.warning("⚠️ OpenAI embeddings lỗi (%s). Chuyển fallback GitHub PAT...", exc)

    if github_pat and not github_pat.startswith("ghp_placeholder"):
        try:
            logger.info("🔄 Retriever: thử GITHUB_PAT cho embeddings...")
            emb = OpenAIEmbeddings(
                model=EMBEDDING_MODEL,
                api_key=github_pat,
                base_url="https://models.inference.ai.azure.com",
            )
            emb.embed_query("test")
            logger.info("✅ Retriever: dùng GitHub Models Embeddings thành công")
            return emb
        except Exception as exc:
            logger.error("❌ GitHub PAT embeddings lỗi: %s", exc)

    logger.error(
        "❌ Không khởi tạo được embeddings. Hãy cấu hình OPENAI_API_KEY hoặc GITHUB_PAT trong file .env"
    )
    return None

def _get_stores():
    """Khởi tạo kết nối Vector DB ở chế độ Đọc - Lazy Loading"""
    global _embeddings, _review_store, _policy_store
    
    if _review_store is not None and _policy_store is not None:
        return _review_store, _policy_store

    try:
        _embeddings = _init_embeddings_with_fallback()
        if _embeddings is None:
            return None, None

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
    
    # Bỏ qua filter nếu LLM truyền rỗng hoặc truyền chung chung "vf" / "vinfast"
    if model_id and model_id.lower() not in ["", "vf", "vinfast"]:
        # Chuẩn hóa (lọc bỏ các hậu tố và dấu gạch)
        clean_id = model_id.lower().replace("_", "").replace("plus", "").replace("eco", "").replace("lux", "").strip()
        
        search_kwargs["filter"] = {
            "car_model": {
                "$in": [
                    clean_id, 
                    f"{clean_id}plus", f"{clean_id}_plus", 
                    f"{clean_id}eco", f"{clean_id}_eco",
                    f"{clean_id}lux", f"{clean_id}_lux"
                ]
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

    # [INTEGRATION] Sắp xếp theo ngày mới nhất (time_weight ưu tiên review gần đây) - Theo logic của nhánh main
    results.sort(key=lambda x: x.get("date", ""), reverse=True)

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
