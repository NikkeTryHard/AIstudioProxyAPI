import asyncio
from asyncio import Event
from typing import Callable, Tuple

from fastapi import HTTPException, Request


async def test_client_connection(req_id: str, http_request: Request) -> bool:
    try:
        if hasattr(http_request, "_receive"):
            try:
                receive_task = asyncio.create_task(http_request._receive())
                done, pending = await asyncio.wait([receive_task], timeout=0.01)
                if done:
                    message = receive_task.result()
                    if message.get("type") == "http.disconnect":
                        return False
                else:
                    receive_task.cancel()
                    try:
                        await receive_task
                    except asyncio.CancelledError:
                        pass
            except Exception:
                return False
        return True
    except Exception:
        return False


async def setup_disconnect_monitoring(
    req_id: str, http_request: Request, result_future
) -> Tuple[Event, asyncio.Task, Callable]:
    from server import logger

    client_disconnected_event = Event()

    async def check_disconnect_periodically():
        while not client_disconnected_event.is_set():
            try:
                is_connected = await test_client_connection(req_id, http_request)
                if not is_connected:
                    logger.info(f"[{req_id}] 主动检测到客户端断开连接。")
                    client_disconnected_event.set()
                    if not result_future.done():
                        result_future.set_exception(
                            HTTPException(
                                status_code=499, detail=f"[{req_id}] 客户端关闭了请求"
                            )
                        )
                    break

                if await http_request.is_disconnected():
                    logger.info(f"[{req_id}] 备用检测到客户端断开连接。")
                    client_disconnected_event.set()
                    if not result_future.done():
                        result_future.set_exception(
                            HTTPException(
                                status_code=499, detail=f"[{req_id}] 客户端关闭了请求"
                            )
                        )
                    break
                await asyncio.sleep(0.3)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{req_id}] (Disco Check Task) 错误: {e}")
                client_disconnected_event.set()
                if not result_future.done():
                    result_future.set_exception(
                        HTTPException(
                            status_code=500,
                            detail=f"[{req_id}] Internal disconnect checker error: {e}",
                        )
                    )
                break

    disconnect_check_task = asyncio.create_task(check_disconnect_periodically())

    def check_client_disconnected(stage: str = ""):
        if client_disconnected_event.is_set():
            logger.info(f"[{req_id}] 在 '{stage}' 检测到客户端断开连接。")
            from models import ClientDisconnectedError

            raise ClientDisconnectedError(
                f"[{req_id}] Client disconnected at stage: {stage}"
            )
        return False

    return client_disconnected_event, disconnect_check_task, check_client_disconnected
