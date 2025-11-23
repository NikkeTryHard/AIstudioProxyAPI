import time
from typing import Dict, Optional

from config import CHAT_COMPLETION_ID_PREFIX


def build_chat_completion_response_json(
    req_id: str,
    model_name: str,
    message_payload: Dict,
    finish_reason: str,
    usage_stats: Dict,
    system_fingerprint: str = "camoufox-proxy",
    seed: Optional[int] = None,
    response_format: Optional[Dict] = None,
) -> Dict:
    """构造 OpenAI 兼容的非流式 chat.completion JSON 响应。"""
    created_ts = int(time.time())
    resp: Dict = {
        "id": f"{CHAT_COMPLETION_ID_PREFIX}{req_id}-{created_ts}",
        "object": "chat.completion",
        "created": created_ts,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": message_payload,
                "finish_reason": finish_reason,
                "native_finish_reason": finish_reason,
            }
        ],
        "usage": usage_stats,
        "system_fingerprint": system_fingerprint,
    }
    if seed is not None:
        resp["seed"] = seed
    if response_format is not None:
        resp["response_format"] = response_format
    return resp
