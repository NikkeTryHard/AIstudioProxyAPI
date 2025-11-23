from typing import Any

from models import ChatCompletionRequest

from .context_types import RequestContext


async def initialize_request_context(
    req_id: str, request: ChatCompletionRequest
) -> RequestContext:
    from server import (
        current_ai_studio_model_id,
        is_page_ready,
        logger,
        model_switching_lock,
        page_instance,
        page_params_cache,
        params_cache_lock,
        parsed_model_list,
    )

    logger.info(f"[{req_id}] 开始处理请求...")
    logger.info(f"[{req_id}]   请求参数 - Model: {request.model}, Stream: {request.stream}")

    context: RequestContext = {
        "logger": logger,
        "page": page_instance,
        "is_page_ready": is_page_ready,
        "parsed_model_list": parsed_model_list,
        "current_ai_studio_model_id": current_ai_studio_model_id,
        "model_switching_lock": model_switching_lock,
        "page_params_cache": page_params_cache,
        "params_cache_lock": params_cache_lock,
        "is_streaming": request.stream,
        "model_actually_switched": False,
        "requested_model": request.model,
        "model_id_to_use": None,
        "needs_model_switching": False,
    }

    return context
