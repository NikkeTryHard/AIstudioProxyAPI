import asyncio
import json
from typing import Any, AsyncGenerator


async def use_stream_response(
    req_id: str, page: Any = None
) -> AsyncGenerator[Any, None]:
    import queue
    import time

    from browser_utils.operations import get_response_via_function_card
    from server import STREAM_QUEUE, logger

    if STREAM_QUEUE is None:
        logger.warning(f"[{req_id}] STREAM_QUEUE is None, 无法使用流响应")
        return

    logger.info(f"[{req_id}] 开始使用流响应")

    empty_count = 0
    max_empty_retries = 300
    data_received = False
    has_content = False
    received_items_count = 0
    stale_done_ignored = False

    # DOM Polling state
    POLL_INTERVAL = 1.0
    last_queue_activity_time = time.time()

    try:
        while True:
            try:
                data = STREAM_QUEUE.get_nowait()
                last_queue_activity_time = time.time()
                if data is None:
                    logger.info(f"[{req_id}] 接收到流结束标志 (None)")
                    break
                empty_count = 0
                data_received = True
                received_items_count += 1
                logger.debug(
                    f"[{req_id}] 接收到流数据[#{received_items_count}]: {type(data)}"
                )

                if isinstance(data, str):
                    try:
                        parsed_data = json.loads(data)
                        if parsed_data.get("done") is True:
                            body = parsed_data.get("body", "")
                            reason = parsed_data.get("reason", "")
                            if body or reason:
                                has_content = True
                            logger.info(
                                f"[{req_id}] 接收到JSON格式的完成标志 (body长度:{len(body)}, reason长度:{len(reason)}, 已收到项目数:{received_items_count})"
                            )
                            if (
                                not has_content
                                and received_items_count == 1
                                and not stale_done_ignored
                            ):
                                logger.warning(
                                    f"[{req_id}] ⚠️ 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待..."
                                )
                                stale_done_ignored = True
                                continue
                            yield parsed_data
                            break
                        else:
                            body = parsed_data.get("body", "")
                            reason = parsed_data.get("reason", "")
                            if body or reason:
                                has_content = True
                            stale_done_ignored = False
                            yield parsed_data
                    except json.JSONDecodeError:
                        logger.debug(f"[{req_id}] 返回非JSON字符串数据")
                        has_content = True
                        stale_done_ignored = False
                        yield data
                else:
                    yield data
                    if isinstance(data, dict):
                        body = data.get("body", "")
                        reason = data.get("reason", "")
                        if body or reason:
                            has_content = True
                        if data.get("done") is True:
                            logger.info(
                                f"[{req_id}] 接收到字典格式的完成标志 (body长度:{len(body)}, reason长度:{len(reason)}, 已收到项目数:{received_items_count})"
                            )
                            if (
                                not has_content
                                and received_items_count == 1
                                and not stale_done_ignored
                            ):
                                logger.warning(
                                    f"[{req_id}] ⚠️ 收到done=True但没有任何内容，且这是第一个接收的项目！可能是队列残留的旧数据，尝试忽略并继续等待..."
                                )
                                stale_done_ignored = True
                                continue
                            break
                        else:
                            stale_done_ignored = False
            except (queue.Empty, asyncio.QueueEmpty):
                empty_count += 1

                # DOM Fallback for Function Calls
                time_since_last_activity = time.time() - last_queue_activity_time
                if page and time_since_last_activity > POLL_INTERVAL:
                    # Poll DOM
                    try:
                        func_call_json = await get_response_via_function_card(
                            page, req_id
                        )
                        if func_call_json:
                            logger.info(
                                f"[{req_id}] [非流式] 检测到 DOM 中的函数调用，正在回退到 DOM 提取..."
                            )

                            # Parse the JSON to get tool calls list
                            try:
                                tool_calls_data = json.loads(func_call_json)

                                # Convert to internal format expected by consumer
                                # The consumer expects: {"function": [{"name":..., "params":...}]}
                                # get_response_via_function_card returns OpenAI format or list of it?
                                # It returns {"name":..., "arguments":...} (dict) or list of dicts.

                                functions_list = []
                                if isinstance(tool_calls_data, dict):
                                    tool_calls_data = [tool_calls_data]

                                for tc in tool_calls_data:
                                    # tc has "name", "arguments" (dict or obj)
                                    fn_name = tc.get("name")
                                    fn_args = tc.get("arguments")
                                    # Ensure args is dict
                                    if isinstance(fn_args, str):
                                        try:
                                            fn_args = json.loads(fn_args)
                                        except:
                                            pass
                                    functions_list.append(
                                        {"name": fn_name, "params": fn_args}
                                    )

                                # DEBUG: Log function call content (no sleep)
                                logger.info(
                                    f"[{req_id}] Function Call Detected via DOM Fallback: {len(functions_list)} calls"
                                )

                                # Yield constructed packet
                                yield {
                                    "done": True,
                                    "body": "",
                                    "reason": "function_call",
                                    "function": functions_list,
                                }

                                return  # End generator
                            except Exception as parse_err:
                                logger.error(f"[{req_id}] 解析 DOM 函数调用数据失败: {parse_err}")
                    except Exception as dom_err:
                        logger.warning(f"[{req_id}] DOM 回退轮询出错: {dom_err}")

                    # Reset timer to avoid spamming poll
                    last_queue_activity_time = time.time()

                if empty_count % 50 == 0:
                    logger.info(
                        f"[{req_id}] 等待流数据... ({empty_count}/{max_empty_retries}, 已收到:{received_items_count}项)"
                    )
                if empty_count >= max_empty_retries:
                    if not data_received:
                        logger.error(f"[{req_id}] 流响应队列空读取次数达到上限且未收到任何数据，可能是辅助流未启动或出错")
                    else:
                        logger.warning(
                            f"[{req_id}] 流响应队列空读取次数达到上限 ({max_empty_retries})，结束读取"
                        )
                    yield {
                        "done": True,
                        "reason": "internal_timeout",
                        "body": "",
                        "function": [],
                    }
                    return
                await asyncio.sleep(0.1)
                continue
    except Exception as e:
        logger.error(f"[{req_id}] 使用流响应时出错: {e}", exc_info=True)
        raise
    finally:
        logger.info(
            f"[{req_id}] 流响应使用完成, 数据接收状态: {data_received}, 有内容: {has_content}, 收到项目数: {received_items_count}, "
            f"曾忽略空done: {stale_done_ignored}"
        )


async def clear_stream_queue():
    import queue

    from server import STREAM_QUEUE, logger

    if STREAM_QUEUE is None:
        logger.info("流队列未初始化或已被禁用，跳过清空操作。")
        return

    cleared_count = 0
    while True:
        try:
            data_chunk = await asyncio.to_thread(STREAM_QUEUE.get_nowait)
            cleared_count += 1
            if cleared_count <= 3:
                logger.debug(
                    f"清空流式队列项 #{cleared_count}: {type(data_chunk)} - {str(data_chunk)[:100]}..."
                )
        except queue.Empty:
            logger.info(f"流式队列已清空 (捕获到 queue.Empty)。清空项数: {cleared_count}")
            break
        except Exception as e:
            logger.error(
                f"清空流式队列时发生意外错误 (已清空{cleared_count}项): {e}",
                exc_info=True,
            )
            break

    if cleared_count > 0:
        logger.warning(f"⚠️ 流式队列缓存清空完毕，共清理了 {cleared_count} 个残留项目！")
    else:
        logger.info("流式队列缓存清空完毕（队列为空）。")
