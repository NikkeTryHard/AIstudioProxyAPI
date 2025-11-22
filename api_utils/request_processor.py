"""
请求处理器模块
包含核心的请求处理逻辑
"""

import asyncio
import json
import os
from asyncio import Event, Future
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    cast,
)

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from playwright.async_api import Error as PlaywrightAsyncError
from playwright.async_api import Locator
from playwright.async_api import Page as AsyncPage

# --- browser_utils模块导入 ---
from browser_utils import save_error_snapshot
from browser_utils.page_controller import PageController

# --- 配置模块导入 ---
from config import (
    MODEL_NAME,
    ONLY_COLLECT_CURRENT_USER_ATTACHMENTS,
    SUBMIT_BUTTON_SELECTOR,
)

# --- models模块导入 ---
from models import ChatCompletionRequest, ClientDisconnectedError

from .client_connection import (
    setup_disconnect_monitoring as _setup_disconnect_monitoring,
)
from .client_connection import test_client_connection as _test_client_connection
from .common_utils import random_id as _random_id
from .context_init import initialize_request_context as _init_request_context
from .context_types import RequestContext
from .error_utils import bad_request, client_disconnected, server_error, upstream_error
from .model_switching import analyze_model_requirements as ms_analyze
from .model_switching import handle_model_switching as ms_switch
from .model_switching import handle_parameter_cache as ms_param_cache
from .page_response import locate_response_elements
from .response_generators import gen_sse_from_aux_stream, gen_sse_from_playwright
from .response_payloads import build_chat_completion_response_json

# --- api_utils模块导入 ---
from .utils import (
    calculate_usage_stats,
    maybe_execute_tools,
    prepare_combined_prompt,
    use_stream_response,
    validate_chat_request,
)

_initialize_request_context = _init_request_context


async def _analyze_model_requirements(
    req_id: str, context: RequestContext, request: ChatCompletionRequest
) -> RequestContext:
    """代理到 model_switching.analyze_model_requirements"""
    return await ms_analyze(req_id, context, request.model or MODEL_NAME, MODEL_NAME)


# 直接使用导入的实现

# 直接使用导入的实现


async def _validate_page_status(
    req_id: str, context: RequestContext, check_client_disconnected: Callable
) -> None:
    """验证页面状态"""
    page = context["page"]
    is_page_ready = context["is_page_ready"]

    if not page or page.is_closed() or not is_page_ready:
        raise HTTPException(
            status_code=503,
            detail=f"[{req_id}] AI Studio 页面丢失或未就绪。",
            headers={"Retry-After": "30"},
        )

    check_client_disconnected("Initial Page Check")


async def _handle_model_switching(
    req_id: str, context: RequestContext, check_client_disconnected: Callable
) -> RequestContext:
    """代理到 model_switching.handle_model_switching"""
    return await ms_switch(req_id, context)


async def _handle_model_switch_failure(
    req_id: str,
    page: AsyncPage,
    model_id_to_use: str,
    model_before_switch: str,
    logger: Any,
) -> None:
    """处理模型切换失败的情况"""
    import server

    logger.warning(f"[{req_id}] ❌ 模型切换至 {model_id_to_use} 失败。")
    # 尝试恢复全局状态
    server.current_ai_studio_model_id = model_before_switch

    raise HTTPException(
        status_code=422, detail=f"[{req_id}] 未能切换到模型 '{model_id_to_use}'。请确保模型可用。"
    )


async def _handle_parameter_cache(req_id: str, context: RequestContext) -> None:
    """代理到 model_switching.handle_parameter_cache"""
    await ms_param_cache(req_id, context)


async def _prepare_and_validate_request(
    req_id: str,
    request: ChatCompletionRequest,
    check_client_disconnected: Callable,
) -> Tuple[str, List[str], Optional[str]]:
    """准备和验证请求，返回 (组合提示, 图片路径列表, 函数定义JSON)。"""
    try:
        validate_chat_request(request.messages, req_id)
    except ValueError as e:
        raise bad_request(req_id, f"无效请求: {e}")

    # 直接传递消息列表，不再手动分离和前置末尾的工具结果
    # 满足用户新需求：make that tool call result where it should be, under that tool call function request in chat history
    messages_to_process = list(request.messages) if request.messages else []

    prepared_prompt, images_list, functions_json = prepare_combined_prompt(
        messages_to_process,
        req_id,
        getattr(request, "tools", None),
        getattr(request, "tool_choice", None),
    )

    # 基于 tools/tool_choice 的主动函数执行（支持 per-request MCP 端点）
    try:
        # 将 mcp_endpoint 注入 utils.maybe_execute_tools 的注册逻辑
        if hasattr(request, "mcp_endpoint") and request.mcp_endpoint:
            from .tools_registry import register_runtime_tools

            register_runtime_tools(
                getattr(request, "tools", None), request.mcp_endpoint
            )
        tool_exec_results: Optional[List[Dict[str, Any]]] = await maybe_execute_tools(
            request.messages, request.tools, getattr(request, "tool_choice", None)
        )
    except Exception:
        tool_exec_results = None
    check_client_disconnected("After Prompt Prep")
    # 将结果内联到提示末尾，供网页端一并提交
    if tool_exec_results:
        try:
            for res in tool_exec_results:
                name = res.get("name")
                args = res.get("arguments")
                result_str = res.get("result")
                prepared_prompt += (
                    f"\n---\n工具执行: {name}\n参数:\n{args}\n结果:\n{result_str}\n"
                )
        except Exception:
            pass
    # 若配置仅收集当前用户消息附件，则在此过滤附件
    try:
        if ONLY_COLLECT_CURRENT_USER_ATTACHMENTS:
            latest_user = None
            for msg in reversed(request.messages or []):
                if getattr(msg, "role", None) == "user":
                    latest_user = msg
                    break
            if latest_user is not None:
                filtered: List[str] = []
                from urllib.parse import unquote, urlparse

                from api_utils.utils import extract_data_url_to_local

                # 收集该条 user 消息上的 data:/file:/绝对路径（存在的）
                # 统一从 messages 附件字段抽取
                for key in ("attachments", "images", "files", "media"):
                    arr = getattr(latest_user, key, None)
                    if not isinstance(arr, list):
                        continue
                    for it in arr:
                        url_value = None
                        if isinstance(it, str):
                            url_value = it
                        elif isinstance(it, dict):
                            url_value = it.get("url") or it.get("path")
                        url_value = (url_value or "").strip()
                        if not url_value:
                            continue
                        if url_value.startswith("data:"):
                            fp = extract_data_url_to_local(url_value)
                            if fp:
                                filtered.append(fp)
                        elif url_value.startswith("file:"):
                            parsed = urlparse(url_value)
                            lp = unquote(parsed.path)
                            if os.path.exists(lp):
                                filtered.append(lp)
                        elif os.path.isabs(url_value) and os.path.exists(url_value):
                            filtered.append(url_value)
                images_list = filtered
    except Exception:
        pass

    return prepared_prompt, images_list, functions_json


async def _handle_response_processing(
    req_id: str,
    request: ChatCompletionRequest,
    page: AsyncPage,
    context: RequestContext,
    result_future: Future,
    submit_button_locator: Locator,
    check_client_disconnected: Callable,
) -> Optional[Tuple[Optional[Event], Optional[Locator], Optional[Callable], bool]]:
    """处理响应生成"""

    # 检查是否使用辅助流
    from config import get_environment_variable

    stream_port = get_environment_variable("STREAM_PORT")
    use_stream = stream_port != "0"

    if use_stream:
        return await _handle_auxiliary_stream_response(
            req_id,
            request,
            context,
            result_future,
            submit_button_locator,
            check_client_disconnected,
        )
    else:
        return await _handle_playwright_response(
            req_id,
            request,
            page,
            context,
            result_future,
            submit_button_locator,
            check_client_disconnected,
        )


async def _handle_auxiliary_stream_response(
    req_id: str,
    request: ChatCompletionRequest,
    context: RequestContext,
    result_future: Future,
    submit_button_locator: Locator,
    check_client_disconnected: Callable,
) -> Optional[Tuple[Optional[Event], Optional[Locator], Optional[Callable], bool]]:
    """辅助流响应处理路径：负责将 STREAM_QUEUE 的数据转换为 OpenAI 兼容 SSE/JSON。

    - 流式模式：返回 StreamingResponse，逐步推送 delta 与最终 usage。
    - 非流式模式：聚合最终内容与函数调用，返回 JSONResponse。
    """
    from server import logger

    is_streaming: bool = request.stream or False
    current_ai_studio_model_id = context.get("current_ai_studio_model_id")

    # 兼容旧逻辑的随机ID函数移除，统一使用 _random_id()

    if is_streaming:
        try:
            completion_event = Event()
            # 使用生成器作为响应体，交由 FastAPI 进行 SSE 推送
            stream_gen_func = gen_sse_from_aux_stream(
                req_id,
                request,
                current_ai_studio_model_id or MODEL_NAME,
                check_client_disconnected,
                completion_event,
                page=context["page"],
                logger=logger,
            )
            if not result_future.done():
                result_future.set_result(
                    StreamingResponse(stream_gen_func, media_type="text/event-stream")
                )
            else:
                if not completion_event.is_set():
                    completion_event.set()

            return (
                completion_event,
                submit_button_locator,
                check_client_disconnected,
                False,
            )

        except Exception as e:
            logger.error(f"[{req_id}] 从队列获取流式数据时出错: {e}", exc_info=True)
            if completion_event and not completion_event.is_set():
                completion_event.set()
            raise

    else:  # 非流式
        content = None
        reasoning_content = None
        functions = None
        final_data_from_aux_stream = None

        # 非流式：消费辅助队列的最终结果并组装 JSON 响应
        async for raw_data in use_stream_response(req_id, page=context["page"]):
            check_client_disconnected(f"非流式辅助流 - 循环中 ({req_id}): ")

            # 确保 data 是字典类型
            if isinstance(raw_data, str):
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(f"[{req_id}] 无法解析非流式数据JSON: {raw_data}")
                    continue
            elif isinstance(raw_data, dict):
                data = raw_data
            else:
                logger.warning(f"[{req_id}] 非流式未知数据类型: {type(raw_data)}")
                continue

            # 确保数据是字典类型
            if not isinstance(data, dict):
                logger.warning(f"[{req_id}] 非流式数据不是字典类型: {data}")
                continue

            final_data_from_aux_stream = data
            if data.get("done"):
                content = data.get("body")
                reasoning_content = data.get("reason")
                functions = data.get("function")
                break

        if (
            final_data_from_aux_stream
            and final_data_from_aux_stream.get("reason") == "internal_timeout"
        ):
            logger.error(f"[{req_id}] 非流式请求通过辅助流失败: 内部超时")
            raise HTTPException(status_code=502, detail=f"[{req_id}] 辅助流处理错误 (内部超时)")

        if (
            final_data_from_aux_stream
            and final_data_from_aux_stream.get("done") is True
            and content is None
        ):
            logger.error(f"[{req_id}] 非流式请求通过辅助流完成但未提供内容")
            raise HTTPException(status_code=502, detail=f"[{req_id}] 辅助流完成但未提供内容")

        model_name_for_json = current_ai_studio_model_id or MODEL_NAME
        message_payload = {"role": "assistant", "content": content}
        finish_reason_val = "stop"

        if functions and len(functions) > 0:
            tool_calls_list = []
            for func_idx, function_call_data in enumerate(functions):
                tool_calls_list.append(
                    {
                        "id": f"call_{_random_id()}",
                        "index": func_idx,
                        "type": "function",
                        "function": {
                            "name": function_call_data["name"],
                            "arguments": json.dumps(function_call_data["params"]),
                        },
                    }
                )
            message_payload["tool_calls"] = tool_calls_list
            finish_reason_val = "tool_calls"
            message_payload["content"] = None

        if reasoning_content:
            message_payload["reasoning_content"] = reasoning_content

        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            content or "",
            reasoning_content,
        )

        response_payload = build_chat_completion_response_json(
            req_id,
            model_name_for_json,
            message_payload,
            finish_reason_val,
            usage_stats,
            system_fingerprint="camoufox-proxy",
            seed=request.seed if hasattr(request, "seed") else None,
            response_format=(
                request.response_format if hasattr(request, "response_format") else None
            ),
        )

        if not result_future.done():
            result_future.set_result(JSONResponse(content=response_payload))
        return None, submit_button_locator, check_client_disconnected, (finish_reason_val == "tool_calls")


def _try_parse_tool_calls(content: str) -> Optional[List[Dict[str, Any]]]:
    """尝试从内容中解析工具调用 JSON。"""
    if not content:
        return None

    clean_text = content.strip()
    # 处理 markdown 代码块
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]

    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    clean_text = clean_text.strip()

    try:
        data = json.loads(clean_text)
        tool_calls = []

        # 它可以是一个列表
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and (
                    "name" in item or "function_name" in item
                ):
                    # 转换为 OpenAI tool_call 格式
                    # 假设 item 是 {"name": "...", "arguments": {...}}
                    # 或者 {"function": "...", "parameters": ...}
                    # 我们需要生成一个随机 id
                    fn_name = item.get("name") or item.get("function_name")
                    fn_args = (
                        item.get("arguments")
                        or item.get("parameters")
                        or item.get("args")
                        or {}
                    )

                    if isinstance(fn_args, dict):
                        fn_args = json.dumps(fn_args)

                    tool_calls.append(
                        {
                            "id": f"call_{_random_id()}",
                            "type": "function",
                            "function": {"name": fn_name, "arguments": str(fn_args)},
                        }
                    )

        # 或者是一个单独的对象
        elif isinstance(data, dict):
            # Google AI Studio 可能会返回单个对象
            if "name" in data or "function_name" in data:
                fn_name = data.get("name") or data.get("function_name")
                fn_args = (
                    data.get("arguments")
                    or data.get("parameters")
                    or data.get("args")
                    or {}
                )
                if isinstance(fn_args, dict):
                    fn_args = json.dumps(fn_args)

                tool_calls.append(
                    {
                        "id": f"call_{_random_id()}",
                        "type": "function",
                        "function": {"name": fn_name, "arguments": str(fn_args)},
                    }
                )

        return tool_calls if tool_calls else None
    except json.JSONDecodeError:
        return None


async def _handle_playwright_response(
    req_id: str,
    request: ChatCompletionRequest,
    page: AsyncPage,
    context: Dict[str, Any],
    result_future: Future,
    submit_button_locator: Locator,
    check_client_disconnected: Callable,
) -> Optional[Tuple[Optional[Event], Optional[Locator], Optional[Callable], bool]]:
    """使用Playwright处理响应"""
    from server import logger

    is_streaming: bool = request.stream or False
    current_ai_studio_model_id = context.get("current_ai_studio_model_id")

    await locate_response_elements(page, req_id, logger, check_client_disconnected)

    check_client_disconnected("After Response Element Located: ")

    if is_streaming:
        completion_event = Event()
        stream_gen_func = gen_sse_from_playwright(
            page,
            logger,
            req_id,
            current_ai_studio_model_id or MODEL_NAME,
            request,
            check_client_disconnected,
            completion_event,
        )
        if not result_future.done():
            result_future.set_result(
                StreamingResponse(stream_gen_func, media_type="text/event-stream")
            )

        return completion_event, submit_button_locator, check_client_disconnected, False
    else:
        # 使用PageController获取响应
        page_controller = PageController(page, logger, req_id)
        final_content = await page_controller.get_response(check_client_disconnected)

        # 尝试解析工具调用
        tool_calls = _try_parse_tool_calls(final_content)

        # 计算token使用统计
        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            final_content,
            "",  # Playwright模式没有reasoning content
        )
        logger.info(f"[{req_id}] Playwright非流式计算的token使用统计: {usage_stats}")

        # 统一使用构造器生成 OpenAI 兼容响应
        model_name_for_json = current_ai_studio_model_id or MODEL_NAME

        if tool_calls:
            message_payload = {
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            }
            finish_reason_val = "tool_calls"
            logger.info(f"[{req_id}] ✅ 检测到工具调用响应，已转换格式。")
        else:
            message_payload = {"role": "assistant", "content": final_content}
            finish_reason_val = "stop"

        response_payload = build_chat_completion_response_json(
            req_id,
            model_name_for_json,
            message_payload,
            finish_reason_val,
            usage_stats,
            system_fingerprint="camoufox-proxy",
            seed=request.seed if hasattr(request, "seed") else None,
            response_format=(
                request.response_format if hasattr(request, "response_format") else None
            ),
        )

        if not result_future.done():
            result_future.set_result(JSONResponse(content=response_payload))

        return None, submit_button_locator, check_client_disconnected, (finish_reason_val == "tool_calls")


async def _cleanup_request_resources(
    req_id: str,
    disconnect_check_task: Optional[asyncio.Task],
    completion_event: Optional[Event],
    result_future: Future,
    is_streaming: bool,
) -> None:
    """清理请求资源"""
    import shutil

    from config import UPLOAD_FILES_DIR
    from server import logger

    if disconnect_check_task and not disconnect_check_task.done():
        disconnect_check_task.cancel()
        try:
            await disconnect_check_task
        except asyncio.CancelledError:
            pass
        except Exception as task_clean_err:
            logger.error(f"[{req_id}] 清理任务时出错: {task_clean_err}")

    logger.info(f"[{req_id}] 处理完成。")

    # 清理本次请求的上传子目录，避免磁盘累积
    try:
        req_dir = os.path.join(UPLOAD_FILES_DIR, req_id)
        if os.path.isdir(req_dir):
            shutil.rmtree(req_dir, ignore_errors=True)
            logger.info(f"[{req_id}] 已清理请求上传目录: {req_dir}")
    except Exception as clean_err:
        logger.warning(f"[{req_id}] 清理上传目录失败: {clean_err}")

    if (
        is_streaming
        and completion_event
        and not completion_event.is_set()
        and (result_future.done() and result_future.exception() is not None)
    ):
        logger.warning(f"[{req_id}] 流式请求异常，确保完成事件已设置。")
        completion_event.set()


async def _process_request_refactored(
    req_id: str,
    request: ChatCompletionRequest,
    http_request: Request,
    result_future: Future,
) -> Optional[Tuple[Optional[Event], Optional[Locator], Optional[Callable], bool]]:
    """核心请求处理函数 - 重构版本"""

    # 优化：在开始任何处理前主动检测客户端连接状态
    from config import get_environment_variable
    from server import logger

    is_connected = await _test_client_connection(req_id, http_request)
    if not is_connected:
        logger.info(f"[{req_id}] ✅ 核心处理前检测到客户端断开，提前退出节省资源")
        if not result_future.done():
            result_future.set_exception(
                HTTPException(status_code=499, detail=f"[{req_id}] 客户端在处理开始前已断开连接")
            )
        return None

    stream_port = get_environment_variable("STREAM_PORT")
    use_stream = stream_port != "0"
    if use_stream:
        logger.info(f"[{req_id}] 🔧 请求开始前清空流式队列（防止残留数据）...")
        try:
            from api_utils import clear_stream_queue

            await clear_stream_queue()
            logger.info(f"[{req_id}] ✅ 流式队列已清空")
        except Exception as clear_err:
            logger.warning(f"[{req_id}] ⚠️ 清空流式队列时出错: {clear_err}")

    context: RequestContext = cast(
        RequestContext, await _initialize_request_context(req_id, request)
    )
    context = await _analyze_model_requirements(req_id, context, request)

    (
        client_disconnected_event,
        disconnect_check_task,
        check_client_disconnected,
    ) = await _setup_disconnect_monitoring(req_id, http_request, result_future)

    page = context["page"]
    submit_button_locator = page.locator(SUBMIT_BUTTON_SELECTOR) if page else None
    completion_event = None

    try:
        await _validate_page_status(req_id, context, check_client_disconnected)

        page_controller = PageController(page, context["logger"], req_id)

        await _handle_model_switching(req_id, context, check_client_disconnected)
        await _handle_parameter_cache(req_id, context)

        (
            prepared_prompt,
            image_list,
            functions_json,
        ) = await _prepare_and_validate_request(
            req_id, request, check_client_disconnected
        )
        # 额外合并顶层与消息级 attachments/files（兼容历史记录）已在下方处理；此处确保路径存在
        try:
            valid_images: List[str] = []
            for p in image_list:
                if isinstance(p, str) and p and os.path.isabs(p) and os.path.exists(p):
                    valid_images.append(p)
            if len(valid_images) != len(image_list):
                from server import logger

                logger.warning(
                    f"[{req_id}] 过滤掉不存在的附件路径: {set(image_list) - set(valid_images)}"
                )
            # Reassigning image_list (type: List[Optional[str]]) to valid_images (type: List[str])
            # We need to make sure subsequent usage expects List[str]
            image_list_str: List[str] = valid_images
        except Exception:
            pass
        # 兼容: 顶层与消息级附件字段合并到上传列表（仅 data:/file:/绝对路径）
        # 附件来源策略：仅接受当前请求显式提供的 data:/file:/绝对路径（存在的）
        try:
            from urllib.parse import unquote, urlparse

            from api_utils.utils import extract_data_url_to_local

            # 顶层 attachments
            top_level_atts = getattr(request, "attachments", None)
            if isinstance(top_level_atts, list) and len(top_level_atts) > 0:
                for it in top_level_atts:
                    url_value = None
                    if isinstance(it, str):
                        url_value = it
                    elif isinstance(it, dict):
                        url_value = it.get("url") or it.get("path")
                    url_value = (url_value or "").strip()
                    if not url_value:
                        continue
                    if url_value.startswith("data:"):
                        fp = extract_data_url_to_local(url_value, req_id=req_id)
                        if fp:
                            image_list_str.append(fp)
                    elif url_value.startswith("file:"):
                        parsed = urlparse(url_value)
                        lp = unquote(parsed.path)
                        if os.path.exists(lp):
                            image_list_str.append(lp)
                    elif os.path.isabs(url_value) and os.path.exists(url_value):
                        image_list_str.append(url_value)
            # 消息级 attachments/images/files/media（全量收集，但仅保留有效本地/data）
            for msg in request.messages or []:
                for key in ("attachments", "images", "files", "media"):
                    arr = getattr(msg, key, None)
                    if not isinstance(arr, list):
                        continue
                    for it in arr:
                        url_value = None
                        if isinstance(it, str):
                            url_value = it
                        elif isinstance(it, dict):
                            url_value = it.get("url") or it.get("path")
                        url_value = (url_value or "").strip()
                        if not url_value:
                            continue
                        if url_value.startswith("data:"):
                            fp = extract_data_url_to_local(url_value, req_id=req_id)
                            if fp:
                                image_list_str.append(fp)
                        elif url_value.startswith("file:"):
                            parsed = urlparse(url_value)
                            lp = unquote(parsed.path)
                            if os.path.exists(lp):
                                image_list_str.append(lp)
                        elif os.path.isabs(url_value) and os.path.exists(url_value):
                            image_list_str.append(url_value)
        except Exception:
            pass

        # 使用PageController处理页面交互
        # 注意：聊天历史清空已移至队列处理锁释放后执行

        await page_controller.adjust_parameters(
            request.model_dump(exclude_none=True),  # 使用 exclude_none=True 避免传递None值
            context.get("page_params_cache", {}),
            context.get("params_cache_lock"),
            context.get("model_id_to_use", MODEL_NAME),
            context.get("parsed_model_list", []),
            check_client_disconnected,
        )

        # 优化：在提交提示前再次检查客户端连接，避免不必要的后台请求
        check_client_disconnected("提交提示前最终检查")

        # 直接提交组合好的提示（包含完整的历史记录和工具结果）
        # 无状态模式：每次请求都是一个新的聊天会话，因此需要提交完整的上下文
        await page_controller.submit_prompt(
            prepared_prompt,
            image_list_str,
            functions_json,
            check_client_disconnected,
        )

        # 响应处理仍然需要在这里，因为它决定了是流式还是非流式，并设置future
        response_result = await _handle_response_processing(
            req_id,
            request,
            page,
            context,
            result_future,
            submit_button_locator,
            check_client_disconnected,
        )

        if response_result:
            return response_result

        return None, None, None, False

    except ClientDisconnectedError as disco_err:
        context["logger"].info(f"[{req_id}] 捕获到客户端断开连接信号: {disco_err}")
        if not result_future.done():
            result_future.set_exception(
                client_disconnected(req_id, "Client disconnected during processing.")
            )
    except HTTPException as http_err:
        context["logger"].warning(
            f"[{req_id}] 捕获到 HTTP 异常: {http_err.status_code} - {http_err.detail}"
        )
        if not result_future.done():
            result_future.set_exception(http_err)
    except PlaywrightAsyncError as pw_err:
        context["logger"].error(f"[{req_id}] 捕获到 Playwright 错误: {pw_err}")
        await save_error_snapshot(f"process_playwright_error_{req_id}")
        if not result_future.done():
            result_future.set_exception(
                upstream_error(req_id, f"Playwright interaction failed: {pw_err}")
            )
    except Exception as e:
        context["logger"].exception(f"[{req_id}] 捕获到意外错误")
        await save_error_snapshot(f"process_unexpected_error_{req_id}")
        if not result_future.done():
            result_future.set_exception(
                server_error(req_id, f"Unexpected server error: {e}")
            )
    finally:
        await _cleanup_request_resources(
            req_id,
            disconnect_check_task,
            completion_event,
            result_future,
            request.stream,
        )
