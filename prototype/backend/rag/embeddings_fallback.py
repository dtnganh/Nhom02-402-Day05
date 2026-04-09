# ============================================================
# backend/rag/embeddings_fallback.py
# Chiến lược fallback cho Vector Embeddings:
# GitHub Models (OpenAI-compatible) → OpenAI → Gemini → HuggingFace (Local)
# Tương tự kiến trúc llm_fallback.py nhưng dành cho RAG
# ============================================================

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _try_github_models() -> Optional[object]:
    """Thử dùng GitHub Models cung cấp text-embedding-3-small miễn phí."""
    github_pat = os.getenv("GITHUB_PAT", "")
    if not github_pat or github_pat.startswith("ghp_placeholder"):
        return None
    try:
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=github_pat,
            base_url="https://models.inference.ai.azure.com",
        )
        embeddings.embed_query("ping")
        logger.info("✅ Embeddings: GitHub Models (text-embedding-3-small)")
        return embeddings
    except Exception as exc:
        logger.warning(f"❌ GitHub Models Embeddings thất bại: {exc}")
        return None


def _try_openai() -> Optional[object]:
    """Thử dùng OpenAI chính chủ."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-placeholder"):
        return None
    try:
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small", 
            api_key=api_key
        )
        embeddings.embed_query("ping")
        logger.info("✅ Embeddings: OpenAI (text-embedding-3-small)")
        return embeddings
    except Exception as exc:
        logger.warning(f"❌ OpenAI Embeddings thất bại: {exc}")
        return None


def _try_gemini() -> Optional[object]:
    """Thử dùng Google Gemini Embeddings (chất lượng rất tốt và có free tier)."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key or api_key.startswith("AIza_placeholder"):
        return None
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        embeddings = GoogleGenerativeAIEmbeddings(
            model="models/text-embedding-004", 
            google_api_key=api_key
        )
        embeddings.embed_query("ping")
        logger.info("✅ Embeddings: Google Gemini (text-embedding-004)")
        return embeddings
    except Exception as exc:
        logger.warning(f"❌ Gemini Embeddings thất bại: {exc}")
        return None


def _try_local_huggingface() -> Optional[object]:
    """
    Fallback cuối cùng: Chạy Local Embeddings (chạy bằng CPU không cần API key).
    Cần pip install sentence-transformers
    """
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
        embeddings.embed_query("ping")
        logger.info("✅ Embeddings: Local HuggingFace (all-MiniLM-L6-v2) - Không tốn phí")
        return embeddings
    except Exception as exc:
        logger.debug(f"Không thể load Local Embeddings (có thể thiếu thư viện): {exc}")
        return None


def get_embeddings():
    """
    Trả về mô hình Embeddings khả dụng đầu tiên.
    CẢNH BÁO DB: Khi đổi mô hình Embeddings (OpenAI -> Gemini), 
    Vector Database (Chroma) phải được build lại (chạy builder.py) 
    vì dimension của các mô hình là khác nhau.
    """
    embeddings = _try_github_models() or _try_openai() or _try_gemini() or _try_local_huggingface()
    if embeddings is None:
        raise RuntimeError(
            "Không thể khởi tạo mô hình Embeddings nào. "
            "Vui lòng cấu hình GITHUB_PAT, OPENAI_API_KEY, GOOGLE_API_KEY "
            "hoặc cài đặt sentence-transformers để chạy Local."
        )
    return embeddings
