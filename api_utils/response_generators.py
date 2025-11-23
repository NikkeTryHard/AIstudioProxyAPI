import asyncio
import json
import random
import time
from asyncio import Event
from typing import Any, AsyncGenerator, Callable

from playwright.async_api import Page as AsyncPage

from config import CHAT_COMPLETION_ID_PREFIX
from models import ChatCompletionRequest, ClientDisconnectedError

from .common_utils import random_id
from .utils import (
    calculate_usage_stats,
    generate_sse_chunk,
    generate_sse_stop_chunk,
    use_stream_response,
)


async def gen_sse_from_aux_stream(
    req_id: str,
    request: ChatCompletionRequest,
    model_name_for_stream: str,
    check_client_disconnected: Callable,
    event_to_set: Event,
    page: AsyncPage = None,
    logger: Any = None,
) -> AsyncGenerator[str, None]:
    """辅助流队列 -> OpenAI 兼容 SSE 生成器。

    产出增量、tool_calls、最终 usage 与 [DONE]。
    """
    from server import logger

    logger.info(f"[{req_id}] 开始生成 SSE 响应流")

    last_reason_pos = 0
    last_body_pos = 0
    chat_completion_id = f"{CHAT_COMPLETION_ID_PREFIX}{req_id}-{int(time.time())}-{random.randint(100, 999)}"
    created_timestamp = int(time.time())

    full_reasoning_content = ""
    full_body_content = ""
    from browser_utils.operations import get_response_via_function_card

    data_receiving = False

    # Queue handling variables
    import queue

    from server import STREAM_QUEUE

    empty_count = 0
    max_empty_retries = 300
    received_items_count = 0
    stale_done_ignored = False

    # Polling variables
    last_queue_activity_time = time.time()
    POLL_INTERVAL = 1.0  # Check DOM every 1 second if queue is silent

    try:
        if STREAM_QUEUE is None:
            logger.warning(f"[{req_id}] STREAM_QUEUE is None, 无法使用流响应")
            return

        logger.info(f"[{req_id}] 开始使用流响应 (含DOM轮询回退)")

        while True:
            # 1. Try to get data from Queue
            try:
                raw_data = STREAM_QUEUE.get_nowait()
                # Reset timeout counters on activity
                last_queue_activity_time = time.time()
                empty_count = 0

                if raw_data is None:
                    logger.info(f"[{req_id}] 接收到流结束标志 (None)")
                    break

                data_receiving = True
                received_items_count += 1

                # Process raw_data (logic from use_stream_response)
                data = None
                if isinstance(raw_data, str):
                    try:
                        parsed_data = json.loads(raw_data)
                        data = parsed_data
                    except json.JSONDecodeError:
                        logger.debug(f"[{req_id}] 返回非JSON字符串数据")
                        # Treat as body content? use_stream_response yields raw string if decode fails?
                        # use_stream_response implementation: yields raw_data if decode fails.
                        # But here we expect dict for gen_sse logic.
                        # Let's try to wrap it.
                        data = {"body": raw_data}
                elif isinstance(raw_data, dict):
                    data = raw_data
                else:
                    logger.warning(f"[{req_id}] 未知的流数据类型: {type(raw_data)}")
                    continue

                # Check for stale done (logic from use_stream_response)
                if data:
                    body = data.get("body", "")
                    reason = data.get("reason", "")
                    done = data.get("done", False)

                    # Logic to ignore stale done
                    has_content = bool(body or reason)
                    if (
                        done
                        and not has_content
                        and received_items_count == 1
                        and not stale_done_ignored
                    ):
                        logger.warning(
                            f"[{req_id}] ⚠️ 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待..."
                        )
                        stale_done_ignored = True
                        continue
                    else:
                        stale_done_ignored = False

                    # --- Proceed to SSE generation with 'data' ---
                    function = data.get("function", [])

                    if reason:
                        full_reasoning_content = reason
                    if body:
                        full_body_content = body

                    if len(reason) > last_reason_pos:
                        output = {
                            "id": chat_completion_id,
                            "object": "chat.completion.chunk",
                            "model": model_name_for_stream,
                            "created": created_timestamp,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "role": "assistant",
                                        "content": None,
                                        "reasoning_content": reason[last_reason_pos:],
                                    },
                                    "finish_reason": None,
                                    "native_finish_reason": None,
                                    "logprobs": None,
                                }
                            ],
                        }
                        last_reason_pos = len(reason)
                        yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"

                    if len(body) > last_body_pos:
                        finish_reason_val = None
                        if done:
                            finish_reason_val = "stop"

                        delta_content = {
                            "role": "assistant",
                            "content": body[last_body_pos:],
                        }
                        choice_item = {
                            "index": 0,
                            "delta": delta_content,
                            "finish_reason": finish_reason_val,
                            "native_finish_reason": finish_reason_val,
                            "logprobs": None,
                        }

                        if done and function and len(function) > 0:
                            tool_calls_list = []
                            for func_idx, function_call_data in enumerate(function):
                                tool_calls_list.append(
                                    {
                                        "id": f"call_{random_id()}",
                                        "index": func_idx,
                                        "type": "function",
                                        "function": {
                                            "name": function_call_data["name"],
                                            "arguments": json.dumps(
                                                function_call_data["params"]
                                            ),
                                        },
                                    }
                                )
                            delta_content["tool_calls"] = tool_calls_list
                            choice_item["finish_reason"] = "tool_calls"
                            choice_item["native_finish_reason"] = "tool_calls"
                            delta_content["content"] = None

                        output = {
                            "id": chat_completion_id,
                            "object": "chat.completion.chunk",
                            "model": model_name_for_stream,
                            "created": created_timestamp,
                            "choices": [choice_item],
                        }
                        last_body_pos = len(body)
                        yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"
                    elif done:
                        if function and len(function) > 0:
                            tool_calls_list = []
                            for func_idx, function_call_data in enumerate(function):
                                tool_calls_list.append(
                                    {
                                        "id": f"call_{random_id()}",
                                        "index": func_idx,
                                        "type": "function",
                                        "function": {
                                            "name": function_call_data["name"],
                                            "arguments": json.dumps(
                                                function_call_data["params"]
                                            ),
                                        },
                                    }
                                )
                            delta_content = {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": tool_calls_list,
                            }
                            choice_item = {
                                "index": 0,
                                "delta": delta_content,
                                "finish_reason": "tool_calls",
                                "native_finish_reason": "tool_calls",
                                "logprobs": None,
                            }
                        else:
                            choice_item = {
                                "index": 0,
                                "delta": {"role": "assistant"},
                                "finish_reason": "stop",
                                "native_finish_reason": "stop",
                                "logprobs": None,
                            }

                        output = {
                            "id": chat_completion_id,
                            "object": "chat.completion.chunk",
                            "model": model_name_for_stream,
                            "created": created_timestamp,
                            "choices": [choice_item],
                        }
                        yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"
                        break  # Done processing

            except (queue.Empty, asyncio.QueueEmpty):
                # Queue is empty
                empty_count += 1

                # Check timeout/fallback conditions
                time_since_last_activity = time.time() - last_queue_activity_time

                # 2. Polling Fallback (if queue silent for > 1s)
                if page and time_since_last_activity > POLL_INTERVAL:
                    # Poll DOM
                    # logger.debug(f"[{req_id}] Queue silent for {time_since_last_activity:.1f}s, polling DOM for function calls...")
                    try:
                        func_call_json = await get_response_via_function_card(
                            page, req_id
                        )
                        if func_call_json:
                            logger.info(
                                f"[{req_id}] [流式] 检测到 DOM 中的函数调用，正在回退到 DOM 提取..."
                            )

                            # Parse the JSON
                            try:
                                tool_calls_data = json.loads(func_call_json)
                                # Ensure it's a list
                                if isinstance(tool_calls_data, dict):
                                    tool_calls_data = [tool_calls_data]

                                # Construct Tool Calls Delta
                                tool_calls_list = []
                                for func_idx, tc in enumerate(tool_calls_data):
                                    # Heuristic: if "name" is in tc, use it. Else default to "unknown" or try to parse.
                                    fn_name = (
                                        tc.get("name")
                                        or tc.get("function_name")
                                        or "Bash"
                                    )

                                    fn_args = (
                                        tc.get("arguments") or tc.get("params") or tc
                                    )
                                    if isinstance(fn_args, dict):
                                        fn_args = json.dumps(fn_args)

                                    tool_calls_list.append(
                                        {
                                            "id": f"call_{random_id()}",
                                            "index": func_idx,
                                            "type": "function",
                                            "function": {
                                                "name": fn_name,
                                                "arguments": fn_args,  # String
                                            },
                                        }
                                    )

                                delta_content = {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": tool_calls_list,
                                }
                                choice_item = {
                                    "index": 0,
                                    "delta": delta_content,
                                    "finish_reason": "tool_calls",
                                    "native_finish_reason": "tool_calls",
                                    "logprobs": None,
                                }
                                output = {
                                    "id": chat_completion_id,
                                    "object": "chat.completion.chunk",
                                    "model": model_name_for_stream,
                                    "created": created_timestamp,
                                    "choices": [choice_item],
                                }
                                yield f"data: {json.dumps(output, ensure_ascii=False, separators=(',', ':'))}\n\n"

                                # Found function calls via DOM fallback, finish stream
                                break

                            except Exception as parse_err:
                                logger.error(
                                    f"[{req_id}] Error parsing fallback JSON: {parse_err}"
                                )

                    except Exception as poll_err:
                        logger.warning(
                            f"[{req_id}] Error during DOM polling: {poll_err}"
                        )

                    # Reset activity timer to avoid hammering DOM?
                    # No, if we found nothing, we should wait a bit.
                    # But we are in the empty loop.
                    last_queue_activity_time = (
                        time.time()
                    )  # Reset to wait another interval

                    if func_call_json:
                        break

                try:
                    check_client_disconnected(f"流式生成器循环 ({req_id}): ")
                except ClientDisconnectedError:
                    logger.info(f"[{req_id}] 客户端断开连接，终止流式生成")
                    if data_receiving and not event_to_set.is_set():
                        event_to_set.set()
                    break

                if empty_count % 50 == 0:
                    # Only log occasionally
                    pass

                if empty_count >= max_empty_retries:
                    logger.warning(
                        f"[{req_id}] 流响应队列空读取次数达到上限 ({max_empty_retries})，且DOM轮询未获结果。"
                    )
                    yield f"data: {json.dumps({'error': 'timeout'}, ensure_ascii=False)}\n\n"
                    break

                await asyncio.sleep(0.1)
                continue

    except ClientDisconnectedError:
        logger.info(f"[{req_id}] 流式生成器中检测到客户端断开连接")
        if data_receiving and not event_to_set.is_set():
            logger.info(f"[{req_id}] 客户端断开异常处理中立即设置done信号")
            event_to_set.set()
    except Exception as e:
        logger.error(f"[{req_id}] 流式生成器处理过程中发生错误: {e}", exc_info=True)
        try:
            error_chunk = {
                "id": chat_completion_id,
                "object": "chat.completion.chunk",
                "model": model_name_for_stream,
                "created": created_timestamp,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": f"\n\n[错误: {str(e)}]",
                        },
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                    }
                ],
            }
            yield f"data: {json.dumps(error_chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
        except Exception:
            pass
    finally:
        logger.info(f"[{req_id}] SSE 响应流生成结束")
        try:
            usage_stats = calculate_usage_stats(
                [msg.model_dump() for msg in request.messages],
                full_body_content,
                full_reasoning_content,
            )
            logger.info(f"[{req_id}] 计算的token使用统计: {usage_stats}")
            final_chunk = {
                "id": chat_completion_id,
                "object": "chat.completion.chunk",
                "model": model_name_for_stream,
                "created": created_timestamp,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                        "native_finish_reason": "stop",
                    }
                ],
                "usage": usage_stats,
            }
            yield f"data: {json.dumps(final_chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
        except Exception as usage_err:
            logger.error(f"[{req_id}] 计算或发送usage统计时出错: {usage_err}")
        try:
            logger.info(f"[{req_id}] 流式生成器完成，发送 [DONE] 标记")
            yield "data: [DONE]\n\n"
        except Exception as done_err:
            logger.error(f"[{req_id}] 发送 [DONE] 标记时出错: {done_err}")
        if not event_to_set.is_set():
            event_to_set.set()
            logger.info(f"[{req_id}] 流式生成器完成事件已设置")


async def gen_sse_from_playwright(
    page: AsyncPage,
    logger: Any,
    req_id: str,
    model_name_for_stream: str,
    request: ChatCompletionRequest,
    check_client_disconnected: Callable,
    completion_event: Event,
) -> AsyncGenerator[str, None]:
    """Playwright 最终响应 -> OpenAI 兼容 SSE 生成器。"""
    # Reuse already-imported helpers from utils to avoid repeated imports
    from browser_utils.page_controller import PageController
    from models import ClientDisconnectedError

    data_receiving = False
    try:
        page_controller = PageController(page, logger, req_id)
        final_content = await page_controller.get_response(check_client_disconnected)
        data_receiving = True
        lines = final_content.split("\n")
        for line_idx, line in enumerate(lines):
            try:
                check_client_disconnected(f"Playwright流式生成器循环 ({req_id}): ")
            except ClientDisconnectedError:
                logger.info(f"[{req_id}] Playwright流式生成器中检测到客户端断开连接")
                if data_receiving and not completion_event.is_set():
                    logger.info(f"[{req_id}] Playwright数据接收中客户端断开，立即设置done信号")
                    completion_event.set()
                break
            if line:
                chunk_size = 5
                for i in range(0, len(line), chunk_size):
                    chunk = line[i : i + chunk_size]
                    yield generate_sse_chunk(chunk, req_id, model_name_for_stream)
                    await asyncio.sleep(0.03)
            if line_idx < len(lines) - 1:
                yield generate_sse_chunk("\n", req_id, model_name_for_stream)
                await asyncio.sleep(0.01)
        usage_stats = calculate_usage_stats(
            [msg.model_dump() for msg in request.messages],
            final_content,
            "",
        )
        logger.info(f"[{req_id}] Playwright非流式计算的token使用统计: {usage_stats}")
        yield generate_sse_stop_chunk(
            req_id, model_name_for_stream, "stop", usage_stats
        )
    except ClientDisconnectedError:
        logger.info(f"[{req_id}] Playwright流式生成器中检测到客户端断开连接")
        if data_receiving and not completion_event.is_set():
            logger.info(f"[{req_id}] Playwright客户端断开异常处理中立即设置done信号")
            completion_event.set()
    except Exception as e:
        logger.error(f"[{req_id}] Playwright流式生成器处理过程中发生错误: {e}", exc_info=True)
        try:
            yield generate_sse_chunk(
                f"\n\n[错误: {str(e)}]", req_id, model_name_for_stream
            )
            yield generate_sse_stop_chunk(req_id, model_name_for_stream)
        except Exception:
            pass
    finally:
        if not completion_event.is_set():
            completion_event.set()
            logger.info(f"[{req_id}] Playwright流式生成器完成事件已设置")
