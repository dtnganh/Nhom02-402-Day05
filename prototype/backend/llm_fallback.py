# ============================================================
# backend/llm_fallback.py
# Chiến lược khởi tạo LLM với cơ chế fallback xếp tầng:
#   OpenRouter → Claude (Anthropic) → OpenAI → GitHub Models → Gemini (Google)
# ============================================================

import logging
import os
from typing import Optional

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _try_claude(model: str = "claude-sonnet-4-6") -> Optional[BaseChatModel]:
    """Thử khởi tạo Claude qua Anthropic API."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key.startswith("sk-placeholder"):
        logger.debug("ANTHROPIC_API_KEY chưa thiết lập hoặc là placeholder – bỏ qua Claude")
        return None
    try:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(
            model=model,
            api_key=api_key,
            max_tokens=4096,
            temperature=0.1,        # Thấp để ưu tiên Precision
        )
        # Probe call nhẹ để xác nhận key hợp lệ
        llm.invoke("ping")
        logger.info("✅ LLM khởi tạo thành công: Claude (%s)", model)
        return llm
    except Exception as exc:
        logger.warning("❌ Claude khởi tạo thất bại: %s – chuyển fallback", exc)
        return None


def _try_github_models(model: str = "gpt-4o") -> Optional[BaseChatModel]:
    """
    Thử khởi tạo GPT-4o qua GitHub Models endpoint
    (sử dụng OpenAI-compatible API với base_url khác).
    """
    github_pat = os.getenv("GITHUB_PAT", "")
    if not github_pat or github_pat.startswith("ghp_placeholder"):
        logger.debug("GITHUB_PAT chưa thiết lập bỏ qua GitHub Models")
        return None
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model,
            api_key=github_pat,
            base_url="https://models.inference.ai.azure.com",
            max_tokens=4096,
            temperature=0.1,
        )
        llm.invoke("ping")
        logger.info("✅ LLM khởi tạo thành công: GitHub Models (%s)", model)
        return llm
    except Exception as exc:
        logger.warning("❌ GitHub Models khởi tạo thất bại: %s – chuyển fallback", exc)
        return None


def _try_openai(model: str = "gpt-4o-mini") -> Optional[BaseChatModel]:
    """
    Thử khởi tạo GPT qua native OpenAI API.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-placeholder"):
        logger.debug("OPENAI_API_KEY chưa thiết lập – bỏ qua OpenAI")
        return None
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            max_tokens=4096,
            temperature=0.1,
        )
        llm.invoke("ping")
        logger.info("✅ LLM khởi tạo thành công: OpenAI (%s)", model)
        return llm
    except Exception as exc:
        logger.warning("❌ OpenAI khởi tạo thất bại: %s – chuyển fallback", exc)
        return None


def _try_gemini(model: str = "gemini-2.5-flash") -> Optional[BaseChatModel]:
    """Thử khởi tạo Gemini qua Google Generative AI API."""
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key or api_key.startswith("AIza_placeholder"):
        logger.debug("GOOGLE_API_KEY chưa thiết lập – bỏ qua Gemini")
        return None
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            max_output_tokens=4096,
            temperature=0.1,
        )
        llm.invoke("ping")
        logger.info("✅ LLM khởi tạo thành công: Gemini (%s)", model)
        return llm
    except Exception as exc:
        logger.warning("❌ Gemini khởi tạo thất bại: %s", exc)
        return None


def _try_openrouter(model: str = "arcee-ai/trinity-large-preview:free") -> Optional[BaseChatModel]:
    """
    Thử khởi tạo LLM qua OpenRouter API.
    Hỗ trợ tham số reasoning_details của các model mới (như Gemma).
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key or api_key.startswith("sk-or-placeholder"):
        logger.debug("OPENROUTER_API_KEY chưa thiết lập – bỏ qua OpenRouter")
        return None
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            max_tokens=4096,
            temperature=0.1,
            model_kwargs={"extra_body": {"reasoning": {"enabled": True}}}
        )
        llm.invoke("ping")
        logger.info("✅ LLM khởi tạo thành công: OpenRouter (%s)", model)
        return llm
    except Exception as exc:
        logger.warning("❌ OpenRouter khởi tạo thất bại: %s – chuyển fallback", exc)
        return None


def get_llm() -> BaseChatModel:
    """
    Trả về LLM khả dụng đầu tiên theo thứ tự ưu tiên:
      OpenRouter → Claude → OpenAI → GitHub Models GPT-4o → Gemini 1.5 Flash

    Nếu không có API key nào hợp lệ, raise RuntimeError.
    """
    llm = _try_openrouter() or _try_claude() or _try_openai() or _try_github_models() or _try_gemini()
    if llm is None:
        raise RuntimeError(
            "Không thể khởi tạo bất kỳ LLM nào. "
            "Vui lòng thiết lập ít nhất một trong các biến môi trường: "
            "OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, GITHUB_PAT, hoặc GOOGLE_API_KEY trong file .env"
        )
    return llm

