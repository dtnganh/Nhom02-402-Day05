# ============================================================
# backend/tools/rag_tools.py
# Các tool nối vào kịch bản RAG
# ============================================================

import json
import logging
from langchain_core.tools import tool
from rag import retriever

logger = logging.getLogger(__name__)

@tool
def get_reviews(model_id: str, query: str = "Đánh giá ưu nhược điểm xe", max_results: int = 5) -> str:
    """
    RAG: Lấy review thực tế từ cộng đồng chủ xe VinFast cho một dòng xe cụ thể thông qua Vector DB.
    """
    logger.info("Tool RAG get_reviews: model_id=%s, max=%d", model_id, max_results)
    
    try:
        # Gọi xuống tầng Retrieval của Data Engineer
        rag_results = retriever.search_reviews(model_id=model_id, query=query, max_results=max_results)
        
        if not rag_results:
            return json.dumps(
                {"status": "low_confidence", "message": f"Chưa có đủ review thực tế trong Vector DB cho {model_id}."},
                ensure_ascii=False
            )

        # Tính toán thống kê sentiment
        sentiments = [r.get("sentiment") for r in rag_results]
        positive_count = sentiments.count("positive")
        total = len(sentiments)
        sentiment_pct = round(positive_count / total * 100) if total > 0 else 0

        return json.dumps({
            "status": "ok",
            "model_id": model_id,
            "total_reviews_found": total,
            "positive_sentiment_pct": sentiment_pct,
            "reviews": rag_results,
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        logger.error(f"Lỗi truy xuất RAG DB: {e}")
        return json.dumps({"status": "error", "message": "Lỗi truy xuất Vector DB"}, ensure_ascii=False)
