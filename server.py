import asyncio
import json
import logging
import logging.handlers
import multiprocessing
import os
import platform
import random
import socket  # 保留 socket 以便在 __main__ 中进行简单的直接运行提示
import sys
import time
import traceback
from asyncio import Event, Future, Lock, Queue, Task
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

# 新增: 导入 load_dotenv
from dotenv import load_dotenv

# 新增: 在所有其他导入之前加载 .env 文件
load_dotenv()

import datetime
import queue
import uuid
from urllib.parse import urljoin, urlparse

import aiohttp
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from playwright.async_api import Browser as AsyncBrowser
from playwright.async_api import BrowserContext as AsyncBrowserContext
from playwright.async_api import Error as PlaywrightAsyncError
from playwright.async_api import Locator
from playwright.async_api import Page as AsyncPage
from playwright.async_api import Playwright as AsyncPlaywright
from playwright.async_api import TimeoutError, async_playwright
from playwright.async_api import expect as expect_async
from pydantic import BaseModel

import stream

# --- api_utils模块导入 ---
from api_utils import (
    _process_request_refactored,
    clear_stream_queue,
    create_app,
    generate_sse_chunk,
    generate_sse_error_chunk,
    generate_sse_stop_chunk,
    prepare_combined_prompt,
    queue_worker,
    use_helper_get_response,
    use_stream_response,
    validate_chat_request,
)

# --- browser_utils模块导入 ---
from browser_utils import (
    _close_page_logic,
    _get_final_response_content,
    _handle_initial_model_state_and_storage,
    _handle_model_list_response,
    _initialize_page_logic,
    _set_model_from_page_display,
    _wait_for_response_completion,
    detect_and_extract_page_error,
    get_raw_text_content,
    get_response_via_copy_button,
    get_response_via_edit_button,
    load_excluded_models,
    save_error_snapshot,
    signal_camoufox_shutdown,
    switch_ai_studio_model,
)

# --- 配置模块导入 ---
from config import RESPONSE_COMPLETION_TIMEOUT

# --- logging_utils模块导入 ---
from logging_utils import restore_original_streams, setup_server_logging

# --- models模块导入 ---
from models import (
    ChatCompletionRequest,
    ClientDisconnectedError,
    FunctionCall,
    Message,
    MessageContentItem,
    StreamToLogger,
    ToolCall,
    WebSocketConnectionManager,
    WebSocketLogHandler,
)

# --- stream queue ---
STREAM_QUEUE: Optional[multiprocessing.Queue] = None
STREAM_PROCESS = None

# --- Global State ---
playwright_manager: Optional[AsyncPlaywright] = None
browser_instance: Optional[AsyncBrowser] = None
page_instance: Optional[AsyncPage] = None
is_playwright_ready = False
is_browser_connected = False
is_page_ready = False
is_initializing = False

# --- 全局代理配置 ---
PLAYWRIGHT_PROXY_SETTINGS: Optional[Dict[str, str]] = None

global_model_list_raw_json: Optional[List[Any]] = None
parsed_model_list: List[Dict[str, Any]] = []
model_list_fetch_event = asyncio.Event()

current_ai_studio_model_id: Optional[str] = None
model_switching_lock: Optional[Lock] = None

excluded_model_ids: Set[str] = set()

request_queue: Optional[Queue] = None
processing_lock: Optional[Lock] = None
worker_task: Optional[Task] = None

page_params_cache: Dict[str, Any] = {}
params_cache_lock: Optional[Lock] = None

# --- Debug Logging State (for comprehensive error snapshots) ---
console_logs: List[Dict[str, Any]] = []
network_log: Dict[str, List[Dict[str, Any]]] = {"requests": [], "responses": []}

logger = logging.getLogger("AIStudioProxyServer")
log_ws_manager = None


def clear_debug_logs() -> None:
    """Clear console and network logs (called after each request)."""
    global console_logs, network_log
    console_logs = []
    network_log = {"requests": [], "responses": []}


# --- FastAPI App 定义 ---
app = create_app()

# --- Main Guard ---
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 2048))
    uvicorn.run(
        "server:app", host="0.0.0.0", port=port, log_level="info", access_log=False
    )
