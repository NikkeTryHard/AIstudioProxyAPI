import asyncio
from typing import Callable

from playwright.async_api import expect as expect_async

from browser_utils.debug_utils import capture_error_snapshot
from browser_utils.operations import (
    _get_final_response_content,
    _wait_for_response_completion,
    save_error_snapshot,
)
from config import (
    EDIT_MESSAGE_BUTTON_SELECTOR,
    PROMPT_TEXTAREA_SELECTOR,
    RESPONSE_CONTAINER_SELECTOR,
    RESPONSE_TEXT_SELECTOR,
    SUBMIT_BUTTON_SELECTOR,
)
from models import ClientDisconnectedError

from .base import BaseController


class ResponseController(BaseController):
    """Handles retrieval of AI responses."""

    @capture_error_snapshot
    async def get_response(self, check_client_disconnected: Callable) -> str:
        """获取响应内容。"""
        self.logger.info(f"[{self.req_id}] 等待并获取响应...")

        try:
            # 等待响应容器出现
            response_container_locator = self.page.locator(
                RESPONSE_CONTAINER_SELECTOR
            ).last
            response_element_locator = response_container_locator.locator(
                RESPONSE_TEXT_SELECTOR
            )

            self.logger.info(f"[{self.req_id}] 等待响应元素附加到DOM...")
            await expect_async(response_element_locator).to_be_attached(timeout=90000)
            await self._check_disconnect(check_client_disconnected, "获取响应 - 响应元素已附加")

            # 等待响应完成
            submit_button_locator = self.page.locator(SUBMIT_BUTTON_SELECTOR)
            edit_button_locator = self.page.locator(EDIT_MESSAGE_BUTTON_SELECTOR)
            input_field_locator = self.page.locator(PROMPT_TEXTAREA_SELECTOR)

            self.logger.info(f"[{self.req_id}] 等待响应完成...")
            completion_detected = await _wait_for_response_completion(
                self.page,
                input_field_locator,
                submit_button_locator,
                edit_button_locator,
                self.req_id,
                check_client_disconnected,
                None,
            )

            if not completion_detected:
                self.logger.warning(f"[{self.req_id}] 响应完成检测失败，尝试获取当前内容")
            else:
                self.logger.info(f"[{self.req_id}] ✅ 响应完成检测成功")

            # 获取最终响应内容
            final_content = await _get_final_response_content(
                self.page, self.req_id, check_client_disconnected
            )

            if not final_content or not final_content.strip():
                self.logger.warning(f"[{self.req_id}] ⚠️ 获取到的响应内容为空")
                await save_error_snapshot(f"empty_response_{self.req_id}")
                # 不抛出异常，返回空内容让上层处理
                return ""

            # --- DEBUG: Check for function call and sleep ---
            import json

            try:
                if final_content and final_content.strip().startswith("{"):
                    data = json.loads(final_content)
                    if (
                        isinstance(data, dict)
                        and "name" in data
                        and "arguments" in data
                    ):
                        print(f"\n[DEBUG] Detected Function Call in response.py!")
                        print(f"[DEBUG] Content: {final_content[:200]}...")
                        print(f"[DEBUG] Sleeping 10s for inspection...")
                        await asyncio.sleep(10)
                        print(f"[DEBUG] Sleep finished.")
            except Exception:
                pass
            # ------------------------------------------------

            self.logger.info(f"[{self.req_id}] ✅ 成功获取响应内容 ({len(final_content)} chars)")
            return final_content

        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 获取响应时出错: {e}")
            # Snapshot handled by decorator
            raise
