import asyncio
import base64
import mimetypes
from typing import Callable, List, Optional

from playwright.async_api import expect as expect_async

from browser_utils.debug_utils import capture_error_snapshot
from browser_utils.operations import save_error_snapshot
from config import (
    PROMPT_TEXTAREA_SELECTOR,
    RESPONSE_CONTAINER_SELECTOR,
    SUBMIT_BUTTON_SELECTOR,
    AUTOSIZE_WRAPPER_SELECTOR,
    EDIT_FUNCTION_BUTTON_SELECTOR,
    FUNCTION_EDITOR_TEXTAREA_SELECTOR,
    CODE_EDITOR_TAB_SELECTOR,
    SAVE_FUNCTION_BUTTON_SELECTOR,
    INSERT_ASSETS_BUTTON_SELECTOR,
    UPLOAD_MENU_CONTAINER_SELECTOR,
    UPLOAD_MENU_ITEM_SELECTOR,
    UPLOAD_MENU_ITEM_TEXT_SELECTOR,
    OVERLAY_BACKDROP_SELECTOR,
    DIALOG_AGREE_BUTTONS,
    COPYRIGHT_ACK_BUTTON_SELECTOR,
)
from models import ClientDisconnectedError

from .base import BaseController


class InputController(BaseController):
    """Handles prompt input and submission."""

    @capture_error_snapshot
    async def submit_prompt(
        self,
        prompt: str,
        image_list: List[str],
        functions_json: Optional[str],
        check_client_disconnected: Callable,
    ) -> None:
        """提交提示到页面。"""
        # 1. 注入函数定义
        if functions_json:
            await self.inject_functions(functions_json)
            await self._check_disconnect(
                check_client_disconnected, "After Function Injection"
            )

        self.logger.info(f"[{self.req_id}] 填充并提交提示 ({len(prompt)} chars)...")

        # 2. 填充文本
        await self._fill_prompt_text(prompt, check_client_disconnected)

        # 3. 上传文件
        if image_list:
            await self._handle_file_uploads(image_list)

        # 4. 等待发送按钮启用
        submit_button = self.page.locator(SUBMIT_BUTTON_SELECTOR)
        await self._wait_for_submit_enabled(submit_button, check_client_disconnected)

        # 5. 执行提交
        await self._execute_submission(submit_button, check_client_disconnected)

    async def _fill_prompt_text(self, prompt: str, check_client_disconnected: Callable) -> None:
        """填充提示文本框。"""
        prompt_textarea = self.page.locator(PROMPT_TEXTAREA_SELECTOR)
        autosize_wrapper = self.page.locator(AUTOSIZE_WRAPPER_SELECTOR)

        await expect_async(prompt_textarea).to_be_visible(timeout=5000)
        await self._check_disconnect(check_client_disconnected, "After Input Visible")

        # 使用 JavaScript 填充文本以绕过可能的React限制
        await prompt_textarea.evaluate(
            """
            (element, text) => {
                element.value = text;
                element.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                element.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
            }
            """,
            prompt,
        )
        await autosize_wrapper.evaluate(
            '(element, text) => { element.setAttribute("data-value", text); }',
            prompt,
        )
        await self._check_disconnect(check_client_disconnected, "After Input Fill")

    async def _handle_file_uploads(self, image_list: List[str]) -> None:
        """处理文件上传。"""
        try:
            self.logger.info(f"[{self.req_id}] 待上传附件数量: {len(image_list)}")
            ok = await self._open_upload_menu_and_choose_file(image_list)
            if not ok:
                self.logger.error(f"[{self.req_id}] 在上传文件时发生错误: 通过菜单方式未能设置文件")
        except Exception as e:
            self.logger.error(f"[{self.req_id}] 文件上传过程异常: {e}")

    async def _wait_for_submit_enabled(
        self, submit_button, check_client_disconnected: Callable
    ) -> None:
        """等待提交按钮变为可用状态。"""
        wait_timeout_ms = 100000
        try:
            await self._check_disconnect(
                check_client_disconnected, "填充提示后等待发送按钮启用 - 前置检查"
            )
            await expect_async(submit_button).to_be_enabled(timeout=wait_timeout_ms)
            self.logger.info(f"[{self.req_id}] ✅ 发送按钮已启用。")
        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 等待发送按钮启用超时或错误: {e}")
            await save_error_snapshot(f"submit_button_enable_timeout_{self.req_id}")
            raise

        await self._check_disconnect(
            check_client_disconnected, "After Submit Button Enabled"
        )
        await asyncio.sleep(0.3)

    async def _execute_submission(
        self, submit_button, check_client_disconnected: Callable
    ) -> None:
        """执行提交操作：优先点击按钮，其次回车，最后组合键。"""
        button_clicked = False
        try:
            self.logger.info(f"[{self.req_id}] 尝试点击提交按钮...")
            # 提交前再处理一次潜在对话框
            await self._handle_post_upload_dialog()
            await submit_button.click(timeout=5000)
            self.logger.info(f"[{self.req_id}] ✅ 提交按钮点击完成。")
            button_clicked = True
        except Exception as click_err:
            self.logger.error(f"[{self.req_id}] ❌ 提交按钮点击失败: {click_err}")
            await save_error_snapshot(f"submit_button_click_fail_{self.req_id}")

        if not button_clicked:
            self.logger.info(f"[{self.req_id}] 按钮提交失败，尝试回车键提交...")
            prompt_textarea = self.page.locator(PROMPT_TEXTAREA_SELECTOR)

            # 尝试普通回车
            if await self._try_keyboard_submit(prompt_textarea, check_client_disconnected, combo=False):
                return

            self.logger.info(f"[{self.req_id}] 回车提交失败，尝试组合键提交...")
            # 尝试组合键
            if await self._try_keyboard_submit(prompt_textarea, check_client_disconnected, combo=True):
                return

            self.logger.error(f"[{self.req_id}] ❌ 组合键提交也失败。")
            raise Exception("Submit failed: Button, Enter, and Combo key all failed")

        await self._check_disconnect(check_client_disconnected, "After Submit")

    @capture_error_snapshot
    async def inject_functions(self, functions_json: str) -> None:
        """注入函数定义到 Google AI Studio UI (v3 Refined + v4 Tab Switch + v5 Optimized Waits)。"""
        self.logger.info(f"[{self.req_id}] 正在注入函数定义...")

        # 1. Click Edit Button
        edit_btn = self.page.locator(EDIT_FUNCTION_BUTTON_SELECTOR).first
        try:
            if await edit_btn.is_visible(timeout=2000):
                await edit_btn.click()
                self.logger.info(f"[{self.req_id}] 已点击 'Edit' 按钮。")

                # Smart Wait: Wait for drawer to appear.
                try:
                    code_tab = self.page.locator(CODE_EDITOR_TAB_SELECTOR).filter(has_text="Code Editor").first
                    await expect_async(code_tab).to_be_visible(timeout=3000)
                except Exception:
                    # Fallback: check for textarea if tab logic fails
                    try:
                        await expect_async(
                            self.page.locator(FUNCTION_EDITOR_TEXTAREA_SELECTOR).first
                        ).to_be_visible(timeout=1000)
                    except Exception:
                        self.logger.warning(f"[{self.req_id}] 等待函数编辑器面板出现超时，尝试继续...")
            else:
                self.logger.warning(f"[{self.req_id}] 'Edit' 按钮不可见。")
        except Exception as e:
            self.logger.error(f"[{self.req_id}] 点击 Edit 按钮出错: {e}")

        # 2. Switch to Code Editor Tab (v4)
        try:
            code_tab = (
                self.page.locator(CODE_EDITOR_TAB_SELECTOR)
                .filter(has_text="Code Editor")
                .first
            )

            if await code_tab.count() > 0:
                if await code_tab.is_visible():
                    is_selected = (
                        await code_tab.get_attribute("aria-selected") == "true"
                    )
                    if not is_selected:
                        self.logger.info(f"[{self.req_id}] 检测到代码编辑器未选中，正在切换...")
                        await code_tab.click()
                        # Smart wait for tab selection
                        await expect_async(code_tab).to_have_attribute(
                            "aria-selected", "true", timeout=3000
                        )
                    else:
                        self.logger.info(f"[{self.req_id}] 代码编辑器标签页已选中。")
                else:
                    self.logger.warning(f"[{self.req_id}] 'Code Editor' 标签页元素存在但不可见。")
            else:
                self.logger.warning(f"[{self.req_id}] 未找到 'Code Editor' 标签页。尝试继续...")

        except Exception as e:
            self.logger.warning(f"[{self.req_id}] 尝试切换标签页时出错 (非致命): {e}")

        # 3. Inject JSON
        editor_area = self.page.locator(FUNCTION_EDITOR_TEXTAREA_SELECTOR).first
        try:
            await expect_async(editor_area).to_be_visible(timeout=5000)

            # Clear and Fill
            await editor_area.fill("")  # Clear first
            await editor_area.fill(functions_json)

            # Dispatch events to ensure binding updates
            await editor_area.evaluate(
                """
                (element) => {
                    element.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true, cancelable: true }));
                }
                """
            )
            self.logger.info(f"[{self.req_id}] 已成功注入函数定义 JSON。")
            # No sleep needed here as fill awaits input

        except Exception as e:
            self.logger.error(f"[{self.req_id}] 注入 JSON 失败: {e}")
            await save_error_snapshot(f"function_injection_error_{self.req_id}")

        # 4. Save & Close (v5)
        try:
            save_btn = self.page.locator(SAVE_FUNCTION_BUTTON_SELECTOR)
            # Ensure visible and enabled
            await expect_async(save_btn).to_be_visible(timeout=3000)

            self.logger.info(f"[{self.req_id}] 正在点击保存按钮...")
            await save_btn.click()

            # Smart Wait: Wait for button to disappear (drawer closed)
            await expect_async(save_btn).to_be_hidden(timeout=3000)
            self.logger.info(f"[{self.req_id}] 函数定义已保存，编辑器已关闭。")

        except Exception as e:
            self.logger.error(f"[{self.req_id}] 点击保存按钮失败: {e}")
            await save_error_snapshot(f"save_function_error_{self.req_id}")

    async def _open_upload_menu_and_choose_file(self, files_list: List[str]) -> bool:
        """通过'Insert assets'菜单选择'上传/Upload'项并打开文件选择器设置文件。"""
        try:
            # 若上一次菜单/对话的透明遮罩仍在，先尝试关闭
            try:
                tb = self.page.locator(
                    "div.cdk-overlay-backdrop.cdk-overlay-transparent-backdrop.cdk-overlay-backdrop-showing"
                )
                if await tb.count() > 0 and await tb.first.is_visible(timeout=300):
                    await self.page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
            except Exception:
                pass

            trigger = self.page.locator(INSERT_ASSETS_BUTTON_SELECTOR)
            await trigger.click()
            menu_container = self.page.locator(UPLOAD_MENU_CONTAINER_SELECTOR)
            # 等待菜单显示
            try:
                await expect_async(
                    menu_container.locator("div[role='menu']").first
                ).to_be_visible(timeout=3000)
            except Exception:
                # 再尝试一次触发
                try:
                    await trigger.click()
                    await expect_async(
                        menu_container.locator("div[role='menu']").first
                    ).to_be_visible(timeout=3000)
                except Exception:
                    self.logger.warning(f"[{self.req_id}] 未能显示上传菜单面板。")
                    return False

            # 仅使用 aria-label='Upload File' 的菜单项
            try:
                upload_btn = menu_container.locator(UPLOAD_MENU_ITEM_SELECTOR)
                if await upload_btn.count() == 0:
                    # 退化到按文本匹配 Upload File
                    upload_btn = menu_container.locator(UPLOAD_MENU_ITEM_TEXT_SELECTOR)
                if await upload_btn.count() == 0:
                    self.logger.warning(f"[{self.req_id}] 未找到 'Upload File' 菜单项。")
                    return False
                btn = upload_btn.first
                await expect_async(btn).to_be_visible(timeout=2000)
                # 优先使用内部隐藏 input[type=file]
                input_loc = btn.locator('input[type="file"]')
                if await input_loc.count() > 0:
                    await input_loc.set_input_files(files_list)
                    self.logger.info(
                        f"[{self.req_id}] ✅ 通过菜单项(Upload File) 隐藏 input 设置文件成功: {len(files_list)} 个"
                    )
                else:
                    # 回退为原生文件选择器
                    async with self.page.expect_file_chooser() as fc_info:
                        await btn.click()
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(files_list)
                    self.logger.info(
                        f"[{self.req_id}] ✅ 通过文件选择器设置文件成功: {len(files_list)} 个"
                    )
            except Exception as e_set:
                self.logger.error(f"[{self.req_id}] 设置文件失败: {e_set}")
                return False
            # 关闭可能残留的菜单遮罩
            try:
                backdrop = self.page.locator(OVERLAY_BACKDROP_SELECTOR)
                if await backdrop.count() > 0:
                    await self.page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
            except Exception:
                pass
            # 处理可能的授权弹窗
            await self._handle_post_upload_dialog()
            return True
        except Exception as e:
            self.logger.error(f"[{self.req_id}] 通过上传菜单设置文件失败: {e}")
            return False

    @capture_error_snapshot
    async def submit_tool_outputs(
        self, tool_outputs: List[dict], check_client_disconnected: Callable
    ):
        """
        DEPRECATED: This method is no longer used.

        Tool results are now submitted as text via submit_prompt() instead of
        DOM interaction. This eliminates browser timeout errors and simplifies
        the architecture.

        See: api_utils/tool_formatter.py for the new approach.
        """
        self.logger.warning(
            f"[{self.req_id}] submit_tool_outputs() is deprecated. "
            "Tool results are now submitted as text."
        )
        raise NotImplementedError(
            "submit_tool_outputs() is deprecated. "
            "Use text-based tool result submission via submit_prompt()."
        )

    async def _handle_post_upload_dialog(self) -> None:
        """处理上传后可能出现的授权/版权确认对话框，优先点击同意类按钮，不主动关闭重要对话框。"""
        try:
            overlay_container = self.page.locator(UPLOAD_MENU_CONTAINER_SELECTOR)
            if await overlay_container.count() == 0:
                return

            # 统一在 overlay 容器内查找可见按钮
            for text in DIALOG_AGREE_BUTTONS:
                try:
                    btn = overlay_container.locator(f"button:has-text('{text}')")
                    if await btn.count() > 0 and await btn.first.is_visible(
                        timeout=300
                    ):
                        await btn.first.click()
                        self.logger.info(f"[{self.req_id}] 上传后对话框: 点击按钮 '{text}'。")
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    continue
            # 若存在带 aria-label 的版权按钮
            try:
                acknow_btn_locator = self.page.locator(COPYRIGHT_ACK_BUTTON_SELECTOR)
                if (
                    await acknow_btn_locator.count() > 0
                    and await acknow_btn_locator.first.is_visible(timeout=300)
                ):
                    await acknow_btn_locator.first.click()
                    self.logger.info(
                        f"[{self.req_id}] 上传后对话框: 点击版权确认按钮 (aria-label 匹配)。"
                    )
                    await asyncio.sleep(0.3)
            except Exception:
                pass

            # 等待遮罩层消失（尽量不强制 ESC，避免意外取消）
            try:
                overlay_backdrop = self.page.locator(OVERLAY_BACKDROP_SELECTOR)
                if await overlay_backdrop.count() > 0:
                    try:
                        await expect_async(overlay_backdrop).to_be_hidden(timeout=3000)
                        self.logger.info(f"[{self.req_id}] 上传后对话框遮罩层已隐藏。")
                    except Exception:
                        self.logger.warning(f"[{self.req_id}] 上传后对话框遮罩层仍存在，后续提交可能被拦截。")
            except Exception:
                pass
        except Exception:
            pass

    async def _ensure_files_attached(
        self, wrapper_locator, expected_min: int = 1, timeout_ms: int = 5000
    ) -> bool:
        """轮询检查输入区域内 file input 的 files 是否 >= 期望数量。"""
        end = asyncio.get_event_loop().time() + (timeout_ms / 1000)
        while asyncio.get_event_loop().time() < end:
            try:
                # NOTE: normalize JS eval string to avoid parser confusion
                counts = await wrapper_locator.evaluate(
                    """
                    (el) => {
                      const result = {inputs:0, chips:0, blobs:0};
                      try { el.querySelectorAll('input[type="file"]').forEach(i => { result.inputs += (i.files ? i.files.length : 0); }); } catch(e){}
                      try { result.chips = el.querySelectorAll('button[aria-label*="Remove" i], button[aria-label*="asset" i]').length; } catch(e){}
                      try { result.blobs = el.querySelectorAll('img[src^="blob:"], video[src^="blob:"]').length; } catch(e){}
                      return result;
                    }
                    """
                )

                total = 0
                if isinstance(counts, dict):
                    total = max(
                        int(counts.get("inputs") or 0),
                        int(counts.get("chips") or 0),
                        int(counts.get("blobs") or 0),
                    )
                if total >= expected_min:
                    self.logger.info(
                        f"[{self.req_id}] 已检测到已附加文件: inputs={counts.get('inputs')}, chips={counts.get('chips')}, blobs={counts.get('blobs')} (>= {expected_min})"
                    )
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
        self.logger.warning(f"[{self.req_id}] 未能在超时内检测到已附加文件 (期望 >= {expected_min})")
        return False

    async def _simulate_drag_drop_files(
        self, target_locator, files_list: List[str]
    ) -> None:
        """将本地文件以拖放事件的方式注入到目标元素。
        仅负责触发 dragenter/dragover/drop，不在此处做附加验证以节省时间。
        """
        payloads = []
        for path in files_list:
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                b64 = base64.b64encode(raw).decode("ascii")
                mime, _ = mimetypes.guess_type(path)
                payloads.append(
                    {
                        "name": path.split("/")[-1],
                        "mime": mime or "application/octet-stream",
                        "b64": b64,
                    }
                )
            except Exception as e:
                self.logger.warning(f"[{self.req_id}] 读取文件失败，跳过拖放: {path} - {e}")

        if not payloads:
            raise Exception("无可用文件用于拖放")

        candidates = [
            target_locator,
            self.page.locator("ms-prompt-input-wrapper ms-autosize-textarea textarea"),
            self.page.locator("ms-prompt-input-wrapper ms-autosize-textarea"),
            self.page.locator("ms-prompt-input-wrapper"),
        ]

        last_err = None
        for idx, cand in enumerate(candidates):
            try:
                await expect_async(cand).to_be_visible(timeout=3000)
                await cand.evaluate(
                    """
                    (el, files) => {
                      const dt = new DataTransfer();
                      for (const p of files) {
                        const bstr = atob(p.b64);
                        const len = bstr.length;
                        const u8 = new Uint8Array(len);
                        for (let i = 0; i < len; i++) u8[i] = bstr.charCodeAt(i);
                        const blob = new Blob([u8], { type: p.mime || 'application/octet-stream' });
                        const file = new File([blob], p.name, { type: p.mime || 'application/octet-stream' });
                        dt.items.add(file);
                      }
                      const evEnter = new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt });
                      el.dispatchEvent(evEnter);
                      const evOver = new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt });
                      el.dispatchEvent(evOver);
                      const evDrop = new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt });
                      el.dispatchEvent(evDrop);
                    }
                    """,
                    payloads,
                )
                await asyncio.sleep(0.5)
                self.logger.info(
                    f"[{self.req_id}] 拖放事件已在候选目标 {idx+1}/{len(candidates)} 上触发。"
                )
                return
            except Exception as e_try:
                last_err = e_try
                continue

        # 兜底：在 document.body 上尝试一次
        try:
            await self.page.evaluate(
                """
                (files) => {
                  const dt = new DataTransfer();
                  for (const p of files) {
                    const bstr = atob(p.b64);
                    const len = bstr.length;
                    const u8 = new Uint8Array(len);
                    for (let i = 0; i < len; i++) u8[i] = bstr.charCodeAt(i);
                    const blob = new Blob([u8], { type: p.mime || 'application/octet-stream' });
                    const file = new File([blob], p.name, { type: p.mime || 'application/octet-stream' });
                    dt.items.add(file);
                  }
                  const el = document.body;
                  const evEnter = new DragEvent('dragenter', { bubbles: true, cancelable: true, dataTransfer: dt });
                  el.dispatchEvent(evEnter);
                  const evOver = new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt });
                  el.dispatchEvent(evOver);
                  const evDrop = new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt });
                  el.dispatchEvent(evDrop);
                }
                """,
                payloads,
            )
            await asyncio.sleep(0.5)
            self.logger.info(f"[{self.req_id}] 拖放事件已在 document.body 上触发（兜底）。")
            return
        except Exception:
            pass

        raise last_err or Exception("拖放未能在任何候选目标上触发")

    async def _try_keyboard_submit(
        self, prompt_textarea_locator, check_client_disconnected: Callable, combo: bool = False
    ) -> bool:
        """尝试使用键盘提交 (Enter 或 Combo)。"""
        try:
            await prompt_textarea_locator.focus(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "After Input Focus")
            await asyncio.sleep(0.1)

            # 记录提交前的输入框内容，用于验证
            original_content = ""
            try:
                original_content = (
                    await prompt_textarea_locator.input_value(timeout=2000) or ""
                )
            except Exception:
                pass

            if combo:
                await self._perform_combo_press(prompt_textarea_locator)
            else:
                await self._perform_enter_press(prompt_textarea_locator)

            await self._check_disconnect(check_client_disconnected, "After Key Press")
            await asyncio.sleep(2.0)

            return await self._verify_submission(original_content, prompt_textarea_locator, combo)

        except Exception as e:
            self.logger.warning(f"[{self.req_id}] 键盘提交失败 (Combo={combo}): {e}")
            return False

    async def _perform_enter_press(self, locator) -> None:
        """执行回车按键。"""
        self.logger.info(f"[{self.req_id}] 尝试回车键提交")
        try:
            await self.page.keyboard.press("Enter")
        except Exception:
            await locator.press("Enter")

    async def _perform_combo_press(self, locator) -> None:
        """执行组合键 (Meta/Control + Enter) 按键。"""
        import os

        # 检测平台
        host_os = os.environ.get("HOST_OS_FOR_SHORTCUT")
        if host_os == "Darwin":
            is_mac = True
        elif host_os in ["Windows", "Linux"]:
            is_mac = False
        else:
            # Fallback user agent check
            try:
                ua = await self.page.evaluate("() => navigator.userAgent || ''")
                is_mac = "mac" in ua.lower()
            except Exception:
                is_mac = False

        modifier = "Meta" if is_mac else "Control"
        self.logger.info(f"[{self.req_id}] 尝试组合键提交: {modifier}+Enter")

        try:
            await self.page.keyboard.press(f"{modifier}+Enter")
        except Exception:
            # Fallback manual sequence
            await self.page.keyboard.down(modifier)
            await asyncio.sleep(0.05)
            await self.page.keyboard.press("Enter")
            await asyncio.sleep(0.05)
            await self.page.keyboard.up(modifier)

    async def _verify_submission(self, original_content, locator, is_combo) -> bool:
        """验证提交是否成功。"""
        desc = "组合键" if is_combo else "回车键"

        # 1. Check if input cleared
        try:
            current = await locator.input_value(timeout=2000) or ""
            if original_content and not current.strip():
                self.logger.info(f"[{self.req_id}] 验证方法1: 输入框已清空，{desc}提交成功")
                return True
        except Exception:
            pass

        # 2. Check if button disabled
        try:
            btn = self.page.locator(SUBMIT_BUTTON_SELECTOR)
            if await btn.is_disabled(timeout=2000):
                self.logger.info(f"[{self.req_id}] 验证方法2: 提交按钮已禁用，{desc}提交成功")
                return True
        except Exception:
            pass

        # 3. Check for response bubble
        try:
            bubbles = self.page.locator(RESPONSE_CONTAINER_SELECTOR)
            if await bubbles.count() > 0 and await bubbles.last.is_visible(timeout=1000):
                 self.logger.info(f"[{self.req_id}] 验证方法3: 检测到响应容器，{desc}提交成功")
                 return True
        except Exception:
            pass

        # Default fallback: assume failure unless exception raised during process?
        # Original code assumed success on verify error, but let's be strict if verification fails.
        # However, keeping original behavior of "if verification fails, just log warning but return False"
        self.logger.warning(f"[{self.req_id}] ⚠️ {desc}提交验证失败")
        return False

