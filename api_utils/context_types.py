from typing import Any, List, Optional, TypedDict

from playwright.async_api import Page as AsyncPage


class RequestContext(TypedDict, total=False):
    logger: Any
    page: Optional[AsyncPage]
    is_page_ready: bool
    parsed_model_list: List[dict]
    current_ai_studio_model_id: Optional[str]
    model_switching_lock: Any
    page_params_cache: dict
    params_cache_lock: Any
    is_streaming: bool
    model_actually_switched: bool
    requested_model: Optional[str]
    model_id_to_use: Optional[str]
    needs_model_switching: bool
