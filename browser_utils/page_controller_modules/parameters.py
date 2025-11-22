import asyncio
import re
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import expect as expect_async
from playwright.async_api import TimeoutError

from config import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_STOP_SEQUENCES,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
    MAX_OUTPUT_TOKENS_SELECTOR,
    STOP_SEQUENCE_INPUT_SELECTOR,
    TEMPERATURE_INPUT_SELECTOR,
    TOP_P_INPUT_SELECTOR,
    MAT_CHIP_REMOVE_BUTTON_SELECTOR,
    ENABLE_URL_CONTEXT,
    USE_URL_CONTEXT_SELECTOR,
    GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR,
    FUNCTION_CALLING_TOGGLE_SELECTOR,
    ENABLE_GOOGLE_SEARCH,
    CLICK_TIMEOUT_MS,
)
from models import ClientDisconnectedError
from browser_utils.operations import save_error_snapshot
from .base import BaseController

class ParameterController(BaseController):
    """Handles parameter adjustments (temperature, tokens, etc.)."""

    async def adjust_parameters(
        self,
        request_params: Dict[str, Any],
        page_params_cache: Dict[str, Any],
        params_cache_lock: asyncio.Lock,
        model_id_to_use: Optional[str],
        parsed_model_list: List[Dict[str, Any]],
        check_client_disconnected: Callable,
    ):
        """调整所有请求参数。"""
        self.logger.info(f"[{self.req_id}] 开始调整所有请求参数...")
        await self._check_disconnect(
            check_client_disconnected, "Start Parameter Adjustment"
        )

        # 调整温度
        temp_to_set = request_params.get("temperature", DEFAULT_TEMPERATURE)
        await self._adjust_temperature(
            temp_to_set, page_params_cache, params_cache_lock, check_client_disconnected
        )
        await self._check_disconnect(
            check_client_disconnected, "After Temperature Adjustment"
        )

        # 调整最大Token
        max_tokens_to_set = request_params.get(
            "max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS
        )
        await self._adjust_max_tokens(
            max_tokens_to_set,
            page_params_cache,
            params_cache_lock,
            model_id_to_use,
            parsed_model_list,
            check_client_disconnected,
        )
        await self._check_disconnect(
            check_client_disconnected, "After Max Tokens Adjustment"
        )

        # 调整停止序列
        stop_to_set = request_params.get("stop", DEFAULT_STOP_SEQUENCES)
        await self._adjust_stop_sequences(
            stop_to_set, page_params_cache, params_cache_lock, check_client_disconnected
        )
        await self._check_disconnect(
            check_client_disconnected, "After Stop Sequences Adjustment"
        )

        # 调整Top P
        top_p_to_set = request_params.get("top_p", DEFAULT_TOP_P)
        await self._adjust_top_p(top_p_to_set, check_client_disconnected)
        await self._check_disconnect(
            check_client_disconnected, "End Parameter Adjustment"
        )

        # 确保工具面板已展开，以便调整高级设置
        await self._ensure_tools_panel_expanded(check_client_disconnected)

        # 调整URL CONTEXT（允许按请求控制）
        if ENABLE_URL_CONTEXT:
            await self._open_url_content(check_client_disconnected)
        else:
            self.logger.info(f"[{self.req_id}] URL Context 功能已禁用，跳过调整。")

        # 调整“思考预算” - handled by ThinkingController but called here to maintain flow?
        # Ideally adjust_parameters should coordinate, but if we split, we need to ensure method availability.
        # We will assume the final class inherits from all mixins.
        if hasattr(self, '_handle_thinking_budget'):
             await self._handle_thinking_budget(request_params, model_id_to_use, check_client_disconnected)

        # 调整“思考预算” - handled by ThinkingController but called here to maintain flow?
        # Ideally adjust_parameters should coordinate, but if we split, we need to ensure method availability.
        # We will assume the final class inherits from all mixins.
        if hasattr(self, '_handle_thinking_budget'):
             await self._handle_thinking_budget(request_params, model_id_to_use, check_client_disconnected)

        # 综合调整 Function Calling 和 Google Search 开关
        # 优化逻辑：避免无效切换，优先处理冲突
        await self._adjust_tools_configuration(request_params, check_client_disconnected)

    async def _adjust_tools_configuration(
        self, request_params: Dict[str, Any], check_client_disconnected: Callable
    ):
        """
        综合调整 Function Calling 和 Google Search 开关。
        逻辑：
        1. 确定需求: need_fc (Function Calling), need_gs (Google Search)
        2. 如果需要 FC:
           a. 强制关闭 GS (如果开启)。(防止 FC 开启后 GS 变灰无法操作，且通常互斥)
           b. 开启 FC。
        3. 如果不需要 FC:
           a. 关闭 FC。(这将重新激活 GS 开关)
           b. 根据 need_gs 调整 GS (开启或关闭)。
        """
        need_fc = self._should_enable_function_calling(request_params)
        need_gs = self._should_enable_google_search(request_params)

        self.logger.info(f"[{self.req_id}] 工具配置调整 - 需求: FC={need_fc}, GS={need_gs}")

        if need_fc:
            # 场景 1: 需要 Function Calling
            # 步骤 A: 确保 Google Search 关闭
            await self._set_google_search_state(False, check_client_disconnected, force_action=True)

            # 步骤 B: 确保 Function Calling 开启
            await self._set_function_calling_state(True, check_client_disconnected)
        else:
            # 场景 2: 不需要 Function Calling
            # 步骤 A: 确保 Function Calling 关闭 (这也将解锁 Google Search 开关)
            await self._set_function_calling_state(False, check_client_disconnected)

            # 步骤 B: 根据需求调整 Google Search
            await self._set_google_search_state(need_gs, check_client_disconnected)

    async def _set_function_calling_state(self, should_enable: bool, check_client_disconnected: Callable):
        """设置 Function Calling 开关状态"""
        toggle_selector = FUNCTION_CALLING_TOGGLE_SELECTOR
        try:
            # 检查可见性
            try:
                toggle_locator = self.page.locator(toggle_selector).first
                if not await toggle_locator.is_visible(timeout=3000):
                    self.logger.info(f"[{self.req_id}] (FC) 未找到可见的 Function Calling 开关，跳过。")
                    return
            except Exception:
                return

            if not await toggle_locator.is_enabled():
                self.logger.warning(f"[{self.req_id}] (FC) 开关在 UI 中禁用，跳过。")
                return

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            is_currently_checked = is_checked_str == "true"

            need_change = should_enable != is_currently_checked
            self.logger.info(f"[{self.req_id}] (FC) 状态检查 - 当前: {is_currently_checked}, 期望: {should_enable}, 需要变更: {need_change}")

            if need_change:
                action = "打开" if should_enable else "关闭"
                self.logger.info(f"[{self.req_id}] (FC) 正在点击以{action}...")
                try:
                    await toggle_locator.scroll_into_view_if_needed()
                except Exception:
                    pass
                await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(check_client_disconnected, f"Function Calling - 点击{action}后")
                await asyncio.sleep(0.5)

                new_state = await toggle_locator.get_attribute("aria-checked")
                success = (new_state == "true") == should_enable
                if success:
                    self.logger.info(f"[{self.req_id}] (FC) ✅ 成功{action}。")
                else:
                    self.logger.warning(f"[{self.req_id}] (FC) ⚠️ {action}失败。当前状态: '{new_state}'")
            else:
                self.logger.info(f"[{self.req_id}] (FC) 状态已符合期望，无需操作。")

        except Exception as e:
            self.logger.error(f"[{self.req_id}] (FC) 操作出错: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _set_google_search_state(self, should_enable: bool, check_client_disconnected: Callable, force_action: bool = False):
        """设置 Google Search 开关状态"""
        toggle_selector = GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR
        try:
            toggle_locator = self.page.locator(toggle_selector)
            if not await toggle_locator.is_visible(timeout=5000):
                 self.logger.warning(f"[{self.req_id}] (GS) 开关未找到/不可见。")
                 return

            # 如果强制操作且被禁用，可能无法操作，但我们记录日志
            if not await toggle_locator.is_enabled():
                if force_action and not should_enable:
                     # 如果我们想关闭它，但它被禁用，检查它是否已经是关闭的
                     is_checked_str = await toggle_locator.get_attribute("aria-checked")
                     if is_checked_str == "false":
                         self.logger.info(f"[{self.req_id}] (GS) 开关禁用但已关闭，符合期望。")
                         return
                     else:
                         self.logger.warning(f"[{self.req_id}] (GS) 开关禁用且开启，无法强制关闭！")
                         return

                self.logger.warning(f"[{self.req_id}] (GS) 开关在 UI 中禁用，跳过。")
                return

            is_checked_str = await toggle_locator.get_attribute("aria-checked")
            is_currently_checked = is_checked_str == "true"

            need_change = should_enable != is_currently_checked

            # 如果只是为了"确保关闭"且本来就是关闭的，日志级别可以低一点
            if force_action and not should_enable and not is_currently_checked:
                 self.logger.info(f"[{self.req_id}] (GS) 已处于关闭状态 (Pre-check)。")
                 return

            self.logger.info(f"[{self.req_id}] (GS) 状态检查 - 当前: {is_currently_checked}, 期望: {should_enable}, 需要变更: {need_change}")

            if need_change:
                action = "打开" if should_enable else "关闭"
                self.logger.info(f"[{self.req_id}] (GS) 正在点击以{action}...")
                try:
                    await toggle_locator.scroll_into_view_if_needed()
                except Exception:
                    pass
                await toggle_locator.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(check_client_disconnected, f"Google Search - 点击{action}后")
                await asyncio.sleep(0.5)

                new_state = await toggle_locator.get_attribute("aria-checked")
                success = (new_state == "true") == should_enable
                if success:
                    self.logger.info(f"[{self.req_id}] (GS) ✅ 成功{action}。")
                else:
                    self.logger.warning(f"[{self.req_id}] (GS) ⚠️ {action}失败。当前状态: '{new_state}'")
            else:
                self.logger.info(f"[{self.req_id}] (GS) 状态已符合期望，无需操作。")

        except Exception as e:
            self.logger.error(f"[{self.req_id}] (GS) 操作出错: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _adjust_temperature(
        self,
        temperature: float,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        check_client_disconnected: Callable,
    ):
        """调整温度参数。"""
        async with params_cache_lock:
            self.logger.info(f"[{self.req_id}] 检查并调整温度设置...")
            clamped_temp = max(0.0, min(2.0, temperature))
            if clamped_temp != temperature:
                self.logger.warning(
                    f"[{self.req_id}] 请求的温度 {temperature} 超出范围 [0, 2]，已调整为 {clamped_temp}"
                )

            cached_temp = page_params_cache.get("temperature")
            if cached_temp is not None and abs(cached_temp - clamped_temp) < 0.001:
                self.logger.info(
                    f"[{self.req_id}] 温度 ({clamped_temp}) 与缓存值 ({cached_temp}) 一致。跳过页面交互。"
                )
                return

            self.logger.info(
                f"[{self.req_id}] 请求温度 ({clamped_temp}) 与缓存值 ({cached_temp}) 不一致或缓存中无值。需要与页面交互。"
            )
            temp_input_locator = self.page.locator(TEMPERATURE_INPUT_SELECTOR)

            try:
                await expect_async(temp_input_locator).to_be_visible(timeout=5000)
                await self._check_disconnect(check_client_disconnected, "温度调整 - 输入框可见后")

                current_temp_str = await temp_input_locator.input_value(timeout=3000)
                await self._check_disconnect(
                    check_client_disconnected, "温度调整 - 读取输入框值后"
                )

                current_temp_float = float(current_temp_str)
                self.logger.info(
                    f"[{self.req_id}] 页面当前温度: {current_temp_float}, 请求调整后温度: {clamped_temp}"
                )

                if abs(current_temp_float - clamped_temp) < 0.001:
                    self.logger.info(
                        f"[{self.req_id}] 页面当前温度 ({current_temp_float}) 与请求温度 ({clamped_temp}) 一致。更新缓存并跳过写入。"
                    )
                    page_params_cache["temperature"] = current_temp_float
                else:
                    self.logger.info(
                        f"[{self.req_id}] 页面温度 ({current_temp_float}) 与请求温度 ({clamped_temp}) 不同，正在更新..."
                    )
                    await temp_input_locator.fill(str(clamped_temp), timeout=5000)
                    await self._check_disconnect(
                        check_client_disconnected, "温度调整 - 填充输入框后"
                    )

                    await asyncio.sleep(0.1)
                    new_temp_str = await temp_input_locator.input_value(timeout=3000)
                    new_temp_float = float(new_temp_str)

                    if abs(new_temp_float - clamped_temp) < 0.001:
                        self.logger.info(
                            f"[{self.req_id}] ✅ 温度已成功更新为: {new_temp_float}。更新缓存。"
                        )
                        page_params_cache["temperature"] = new_temp_float
                    else:
                        self.logger.warning(
                            f"[{self.req_id}] ⚠️ 温度更新后验证失败。页面显示: {new_temp_float}, 期望: {clamped_temp}。清除缓存中的温度。"
                        )
                        page_params_cache.pop("temperature", None)
                        # We need to import save_error_snapshot or use a callback
                        # For now assuming it's available in the context or we import it.
                        # But save_error_snapshot is in browser_utils.operations.
                        # We should probably inject it or import it.
                        from browser_utils.operations import save_error_snapshot
                        await save_error_snapshot(
                            f"temperature_verify_fail_{self.req_id}"
                        )

            except ValueError as ve:
                self.logger.error(f"[{self.req_id}] 转换温度值为浮点数时出错. 错误: {ve}。清除缓存中的温度。")
                page_params_cache.pop("temperature", None)
                from browser_utils.operations import save_error_snapshot
                await save_error_snapshot(f"temperature_value_error_{self.req_id}")
            except Exception as pw_err:
                self.logger.error(f"[{self.req_id}] ❌ 操作温度输入框时发生错误: {pw_err}。清除缓存中的温度。")
                page_params_cache.pop("temperature", None)
                from browser_utils.operations import save_error_snapshot
                await save_error_snapshot(f"temperature_playwright_error_{self.req_id}")
                if isinstance(pw_err, ClientDisconnectedError):
                    raise

    async def _adjust_max_tokens(
        self,
        max_tokens: int,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        model_id_to_use: Optional[str],
        parsed_model_list: list,
        check_client_disconnected: Callable,
    ):
        """调整最大输出Token参数。"""
        async with params_cache_lock:
            self.logger.info(f"[{self.req_id}] 检查并调整最大输出 Token 设置...")
            min_val_for_tokens = 1
            max_val_for_tokens_from_model = 65536

            if model_id_to_use and parsed_model_list:
                current_model_data = next(
                    (m for m in parsed_model_list if m.get("id") == model_id_to_use),
                    None,
                )
                if (
                    current_model_data
                    and current_model_data.get("supported_max_output_tokens")
                    is not None
                ):
                    try:
                        supported_tokens = int(
                            current_model_data["supported_max_output_tokens"]
                        )
                        if supported_tokens > 0:
                            max_val_for_tokens_from_model = supported_tokens
                        else:
                            self.logger.warning(
                                f"[{self.req_id}] 模型 {model_id_to_use} supported_max_output_tokens 无效: {supported_tokens}"
                            )
                    except (ValueError, TypeError):
                        self.logger.warning(
                            f"[{self.req_id}] 模型 {model_id_to_use} supported_max_output_tokens 解析失败"
                        )

            clamped_max_tokens = max(
                min_val_for_tokens, min(max_val_for_tokens_from_model, max_tokens)
            )
            if clamped_max_tokens != max_tokens:
                self.logger.warning(
                    f"[{self.req_id}] 请求的最大输出 Tokens {max_tokens} 超出模型范围，已调整为 {clamped_max_tokens}"
                )

            cached_max_tokens = page_params_cache.get("max_output_tokens")
            if (
                cached_max_tokens is not None
                and cached_max_tokens == clamped_max_tokens
            ):
                self.logger.info(
                    f"[{self.req_id}] 最大输出 Tokens ({clamped_max_tokens}) 与缓存值一致。跳过页面交互。"
                )
                return

            max_tokens_input_locator = self.page.locator(MAX_OUTPUT_TOKENS_SELECTOR)

            try:
                await expect_async(max_tokens_input_locator).to_be_visible(timeout=5000)
                await self._check_disconnect(
                    check_client_disconnected, "最大输出Token调整 - 输入框可见后"
                )

                current_max_tokens_str = await max_tokens_input_locator.input_value(
                    timeout=3000
                )
                current_max_tokens_int = int(current_max_tokens_str)

                if current_max_tokens_int == clamped_max_tokens:
                    self.logger.info(
                        f"[{self.req_id}] 页面当前最大输出 Tokens ({current_max_tokens_int}) 与请求值 ({clamped_max_tokens}) 一致。更新缓存并跳过写入。"
                    )
                    page_params_cache["max_output_tokens"] = current_max_tokens_int
                else:
                    self.logger.info(
                        f"[{self.req_id}] 页面最大输出 Tokens ({current_max_tokens_int}) 与请求值 ({clamped_max_tokens}) 不同，正在更新..."
                    )
                    await max_tokens_input_locator.fill(
                        str(clamped_max_tokens), timeout=5000
                    )
                    await self._check_disconnect(
                        check_client_disconnected, "最大输出Token调整 - 填充输入框后"
                    )

                    await asyncio.sleep(0.1)
                    new_max_tokens_str = await max_tokens_input_locator.input_value(
                        timeout=3000
                    )
                    new_max_tokens_int = int(new_max_tokens_str)

                    if new_max_tokens_int == clamped_max_tokens:
                        self.logger.info(
                            f"[{self.req_id}] ✅ 最大输出 Tokens 已成功更新为: {new_max_tokens_int}"
                        )
                        page_params_cache["max_output_tokens"] = new_max_tokens_int
                    else:
                        self.logger.warning(
                            f"[{self.req_id}] ⚠️ 最大输出 Tokens 更新后验证失败。页面显示: {new_max_tokens_int}, 期望: {clamped_max_tokens}。清除缓存。"
                        )
                        page_params_cache.pop("max_output_tokens", None)
                        from browser_utils.operations import save_error_snapshot
                        await save_error_snapshot(
                            f"max_tokens_verify_fail_{self.req_id}"
                        )

            except (ValueError, TypeError) as ve:
                self.logger.error(f"[{self.req_id}] 转换最大输出 Tokens 值时出错: {ve}。清除缓存。")
                page_params_cache.pop("max_output_tokens", None)
                from browser_utils.operations import save_error_snapshot
                await save_error_snapshot(f"max_tokens_value_error_{self.req_id}")
            except Exception as e:
                self.logger.error(f"[{self.req_id}] ❌ 调整最大输出 Tokens 时出错: {e}。清除缓存。")
                page_params_cache.pop("max_output_tokens", None)
                from browser_utils.operations import save_error_snapshot
                await save_error_snapshot(f"max_tokens_error_{self.req_id}")
                if isinstance(e, ClientDisconnectedError):
                    raise

    async def _adjust_stop_sequences(
        self,
        stop_sequences,
        page_params_cache: dict,
        params_cache_lock: asyncio.Lock,
        check_client_disconnected: Callable,
    ):
        """调整停止序列参数。"""
        async with params_cache_lock:
            self.logger.info(f"[{self.req_id}] 检查并设置停止序列...")

            # 处理不同类型的stop_sequences输入
            normalized_requested_stops = set()
            if stop_sequences is not None:
                if isinstance(stop_sequences, str):
                    # 单个字符串
                    if stop_sequences.strip():
                        normalized_requested_stops.add(stop_sequences.strip())
                elif isinstance(stop_sequences, list):
                    # 字符串列表
                    for s in stop_sequences:
                        if isinstance(s, str) and s.strip():
                            normalized_requested_stops.add(s.strip())

            cached_stops_set = page_params_cache.get("stop_sequences")

            if (
                cached_stops_set is not None
                and cached_stops_set == normalized_requested_stops
            ):
                self.logger.info(f"[{self.req_id}] 请求的停止序列与缓存值一致。跳过页面交互。")
                return

            stop_input_locator = self.page.locator(STOP_SEQUENCE_INPUT_SELECTOR)
            remove_chip_buttons_locator = self.page.locator(
                MAT_CHIP_REMOVE_BUTTON_SELECTOR
            )

            try:
                # 清空已有的停止序列
                initial_chip_count = await remove_chip_buttons_locator.count()
                removed_count = 0
                max_removals = initial_chip_count + 5

                while (
                    await remove_chip_buttons_locator.count() > 0
                    and removed_count < max_removals
                ):
                    await self._check_disconnect(
                        check_client_disconnected, "停止序列清除 - 循环开始"
                    )
                    try:
                        await remove_chip_buttons_locator.first.click(timeout=2000)
                        removed_count += 1
                        await asyncio.sleep(0.15)
                    except Exception:
                        break

                # 添加新的停止序列
                if normalized_requested_stops:
                    await expect_async(stop_input_locator).to_be_visible(timeout=5000)
                    for seq in normalized_requested_stops:
                        await stop_input_locator.fill(seq, timeout=3000)
                        await stop_input_locator.press("Enter", timeout=3000)
                        await asyncio.sleep(0.2)

                page_params_cache["stop_sequences"] = normalized_requested_stops
                self.logger.info(f"[{self.req_id}] ✅ 停止序列已成功设置。缓存已更新。")

            except Exception as e:
                self.logger.error(f"[{self.req_id}] ❌ 设置停止序列时出错: {e}")
                page_params_cache.pop("stop_sequences", None)
                from browser_utils.operations import save_error_snapshot
                await save_error_snapshot(f"stop_sequence_error_{self.req_id}")
                if isinstance(e, ClientDisconnectedError):
                    raise

    async def _adjust_top_p(self, top_p: float, check_client_disconnected: Callable):
        """调整Top P参数。"""
        self.logger.info(f"[{self.req_id}] 检查并调整 Top P 设置...")
        clamped_top_p = max(0.0, min(1.0, top_p))

        if abs(clamped_top_p - top_p) > 1e-9:
            self.logger.warning(
                f"[{self.req_id}] 请求的 Top P {top_p} 超出范围 [0, 1]，已调整为 {clamped_top_p}"
            )

        top_p_input_locator = self.page.locator(TOP_P_INPUT_SELECTOR)
        try:
            await expect_async(top_p_input_locator).to_be_visible(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "Top P 调整 - 输入框可见后")

            current_top_p_str = await top_p_input_locator.input_value(timeout=3000)
            current_top_p_float = float(current_top_p_str)

            if abs(current_top_p_float - clamped_top_p) > 1e-9:
                self.logger.info(
                    f"[{self.req_id}] 页面 Top P ({current_top_p_float}) 与请求值 ({clamped_top_p}) 不同，正在更新..."
                )
                await top_p_input_locator.fill(str(clamped_top_p), timeout=5000)
                await self._check_disconnect(
                    check_client_disconnected, "Top P 调整 - 填充输入框后"
                )

                # 验证设置是否成功
                await asyncio.sleep(0.1)
                new_top_p_str = await top_p_input_locator.input_value(timeout=3000)
                new_top_p_float = float(new_top_p_str)

                if abs(new_top_p_float - clamped_top_p) <= 1e-9:
                    self.logger.info(
                        f"[{self.req_id}] ✅ Top P 已成功更新为: {new_top_p_float}"
                    )
                else:
                    self.logger.warning(
                        f"[{self.req_id}] ⚠️ Top P 更新后验证失败。页面显示: {new_top_p_float}, 期望: {clamped_top_p}"
                    )
                    from browser_utils.operations import save_error_snapshot
                    await save_error_snapshot(f"top_p_verify_fail_{self.req_id}")
            else:
                self.logger.info(
                    f"[{self.req_id}] 页面 Top P ({current_top_p_float}) 与请求值 ({clamped_top_p}) 一致，无需更改"
                )

        except (ValueError, TypeError) as ve:
            self.logger.error(f"[{self.req_id}] 转换 Top P 值时出错: {ve}")
            from browser_utils.operations import save_error_snapshot
            await save_error_snapshot(f"top_p_value_error_{self.req_id}")
        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 调整 Top P 时出错: {e}")
            from browser_utils.operations import save_error_snapshot
            await save_error_snapshot(f"top_p_error_{self.req_id}")
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _ensure_tools_panel_expanded(self, check_client_disconnected: Callable):
        """确保包含高级工具（URL上下文、思考预算等）的面板是展开的。"""
        self.logger.info(f"[{self.req_id}] 检查并确保工具面板已展开...")
        try:
            collapse_tools_locator = self.page.locator(
                'button[aria-label="Expand or collapse tools"]'
            )
            await expect_async(collapse_tools_locator).to_be_visible(timeout=5000)

            grandparent_locator = collapse_tools_locator.locator("xpath=../..")
            class_string = await grandparent_locator.get_attribute(
                "class", timeout=3000
            )

            if class_string and "expanded" not in class_string.split():
                self.logger.info(f"[{self.req_id}] 工具面板未展开，正在点击以展开...")
                await collapse_tools_locator.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(check_client_disconnected, "展开工具面板后")
                # 等待展开动画完成
                await expect_async(grandparent_locator).to_have_class(
                    re.compile(r".*expanded.*"), timeout=5000
                )
                self.logger.info(f"[{self.req_id}] ✅ 工具面板已成功展开。")
            else:
                self.logger.info(f"[{self.req_id}] 工具面板已处于展开状态。")
        except Exception as e:
            self.logger.error(f"[{self.req_id}] ❌ 展开工具面板时发生错误: {e}")
            # 即使出错，也继续尝试执行后续操作，但记录错误
            if isinstance(e, ClientDisconnectedError):
                raise

    async def _open_url_content(self, check_client_disconnected: Callable):
        """仅负责打开 URL Context 开关，前提是面板已展开。"""
        try:
            self.logger.info(f"[{self.req_id}] 检查并启用 URL Context 开关...")
            use_url_content_selector = self.page.locator(USE_URL_CONTEXT_SELECTOR)
            await expect_async(use_url_content_selector).to_be_visible(timeout=5000)

            is_checked = await use_url_content_selector.get_attribute("aria-checked")
            if "false" == is_checked:
                self.logger.info(f"[{self.req_id}] URL Context 开关未开启，正在点击以开启...")
                await use_url_content_selector.click(timeout=CLICK_TIMEOUT_MS)
                await self._check_disconnect(check_client_disconnected, "点击URLCONTEXT后")
                self.logger.info(f"[{self.req_id}] ✅ URL Context 开关已点击。")
            else:
                self.logger.info(f"[{self.req_id}] URL Context 开关已处于开启状态。")
        except Exception as e:
            self.logger.error(
                f"[{self.req_id}] ❌ 操作 USE_URL_CONTEXT_SELECTOR 时发生错误:{e}。"
            )
            if isinstance(e, ClientDisconnectedError):
                raise

    def _should_enable_google_search(self, request_params: Dict[str, Any]) -> bool:
        """根据请求参数或默认配置决定是否应启用 Google Search。"""
        if "tools" in request_params and request_params.get("tools") is not None:
            tools = request_params.get("tools")
            has_google_search_tool = False
            if isinstance(tools, list):
                for tool in tools:
                    if isinstance(tool, dict):
                        if tool.get("google_search_retrieval") is not None:
                            has_google_search_tool = True
                            break
                        if tool.get("function", {}).get("name") == "googleSearch":
                            has_google_search_tool = True
                            break
            self.logger.info(
                f"[{self.req_id}] 请求中包含 'tools' 参数。检测到 Google Search 工具: {has_google_search_tool}。"
            )
            return has_google_search_tool
        else:
            self.logger.info(
                f"[{self.req_id}] 请求中不包含 'tools' 参数。使用默认配置 ENABLE_GOOGLE_SEARCH: {ENABLE_GOOGLE_SEARCH}。"
            )
            return ENABLE_GOOGLE_SEARCH

    def _should_enable_function_calling(self, request_params: Dict[str, Any]) -> bool:
        """根据请求参数决定是否应启用 Function Calling。"""
        if "tools" in request_params and request_params.get("tools") is not None:
            tools = request_params.get("tools")
            has_function_tool = False
            if isinstance(tools, list):
                for tool in tools:
                    if isinstance(tool, dict):
                        # 1. 标准 OpenAI 格式: {"type": "function", "function": {...}}
                        if tool.get("type") == "function":
                            func_name = tool.get("function", {}).get("name")
                            if func_name != "googleSearch":
                                has_function_tool = True
                                break

                        # 2. 简化格式/其他格式: 直接包含 {"name":..., "parameters":...}
                        # 只要不是 Google Search，且看起来像函数，就认为是
                        # 注意: google_search_retrieval 是 Google Search 的一种标记
                        elif tool.get("google_search_retrieval") is None:
                            # 如果没有明确标记为 Google Search
                            # 且具有 name 属性 (可能是函数名)
                            possible_name = tool.get("name") or tool.get("function", {}).get("name")
                            if possible_name and possible_name != "googleSearch":
                                has_function_tool = True
                                break

            self.logger.info(
                f"[{self.req_id}] 请求中包含 'tools' 参数。检测到 Function Calling 工具: {has_function_tool}。"
            )
            return has_function_tool
        return False
