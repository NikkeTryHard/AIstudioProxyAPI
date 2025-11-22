import asyncio
from typing import Callable, Optional

from playwright.async_api import expect as expect_async
from playwright.async_api import TimeoutError

from config import (
    CLICK_TIMEOUT_MS,
    SYSTEM_INSTRUCTIONS_CARD_SELECTOR,
    SYSTEM_INSTRUCTIONS_TEXTAREA_SELECTOR,
    SYSTEM_INSTRUCTIONS_CLOSE_BUTTON_SELECTOR,
    SYSTEM_INSTRUCTIONS_PANEL_SELECTOR,
)
from models import ClientDisconnectedError
from browser_utils.operations import save_error_snapshot
from .base import BaseController


class SystemInstructionsController(BaseController):
    """Handles system instructions panel interaction and content management."""

    async def set_system_instructions(
        self,
        system_instruction: Optional[str],
        check_client_disconnected: Callable,
    ) -> None:
        """
        Sets system instructions via the dedicated UI panel.

        Workflow:
        1. Click system instructions card to open overlay
        2. Wait for textarea to be visible
        3. Fill textarea with content (or clear if None/empty)
        4. Close overlay panel

        Args:
            system_instruction: System instruction text to set, or None to clear
            check_client_disconnected: Callback to check if client has disconnected

        Raises:
            ClientDisconnectedError: If client disconnects during operation
        """
        panel_opened = False
        try:
            # Normalize: None or empty string means clear
            content_to_set = None if not system_instruction or not system_instruction.strip() else system_instruction.strip()

            if content_to_set:
                self.logger.info(f"[{self.req_id}] Setting system instructions ({len(content_to_set)} chars)")
            else:
                self.logger.info(f"[{self.req_id}] Clearing system instructions")

            # Step 1: Open panel
            await self._open_system_instructions_panel(check_client_disconnected)
            panel_opened = True

            # Step 2: Fill or clear textarea
            if content_to_set:
                await self._fill_system_instructions_textarea(content_to_set, check_client_disconnected)
            else:
                await self._clear_system_instructions(check_client_disconnected)

            # Step 3: Close panel
            await self._close_system_instructions_panel(check_client_disconnected)
            panel_opened = False

            self.logger.info(f"[{self.req_id}] ✅ System instructions operation completed successfully")

        except Exception as e:
            self.logger.error(f"[{self.req_id}] Failed to set system instructions: {e}")

            # CRITICAL: Try to close the panel if it was opened, to avoid blocking other operations
            if panel_opened:
                self.logger.warning(f"[{self.req_id}] Attempting emergency panel closure...")
                try:
                    await self._close_system_instructions_panel(check_client_disconnected)
                    self.logger.info(f"[{self.req_id}] ✅ Emergency panel closure succeeded")
                except Exception as close_error:
                    self.logger.error(f"[{self.req_id}] Emergency panel closure failed: {close_error}")
                    # Try Escape key as last resort
                    try:
                        await self.page.keyboard.press("Escape")
                        try:
                            # Wait for panel to hide after escape
                            panel = self.page.locator(SYSTEM_INSTRUCTIONS_PANEL_SELECTOR)
                            await expect_async(panel).to_be_hidden(timeout=2000)
                            self.logger.info(f"[{self.req_id}] Used Escape key for emergency closure")
                        except TimeoutError:
                            pass
                    except Exception:
                        pass

            await save_error_snapshot(f"system_instructions_error_{self.req_id}")
            if isinstance(e, ClientDisconnectedError):
                raise
            # Re-raise to allow caller to handle
            raise

    async def _open_system_instructions_panel(
        self,
        check_client_disconnected: Callable,
    ) -> None:
        """Opens the system instructions overlay panel.

        Args:
            check_client_disconnected: Callback to check if client has disconnected

        Raises:
            ClientDisconnectedError: If client disconnects during operation
            TimeoutError: If panel fails to open within timeout
        """
        self.logger.info(f"[{self.req_id}] Opening system instructions panel...")

        try:
            # Locate and click the card button
            card_button = self.page.locator(SYSTEM_INSTRUCTIONS_CARD_SELECTOR)
            await expect_async(card_button).to_be_visible(timeout=10000)

            try:
                await card_button.scroll_into_view_if_needed()
                # Wait for element to be stable
                await expect_async(card_button).to_be_enabled(timeout=2000)
            except Exception:
                pass

            await self._check_disconnect(check_client_disconnected, "System instructions - before opening panel")

            # Force click if normal click fails (sometimes covered by other elements)
            try:
                await card_button.click(timeout=CLICK_TIMEOUT_MS)
            except TimeoutError:
                self.logger.warning(f"[{self.req_id}] Normal click on system instruction card timed out, trying force click")
                await card_button.click(force=True, timeout=CLICK_TIMEOUT_MS)

            await self._check_disconnect(check_client_disconnected, "System instructions - after clicking card")

            # Instead of waiting for the panel container (which might report hidden),
            # wait directly for the textarea which is the interactive element we need.
            # This avoids issues where the container has weird display properties.
            textarea = self.page.locator(SYSTEM_INSTRUCTIONS_TEXTAREA_SELECTOR)
            try:
                await expect_async(textarea).to_be_visible(timeout=10000)
            except TimeoutError:
                # If textarea not found, maybe the click didn't register? Try clicking again if panel seems closed
                self.logger.warning(f"[{self.req_id}] Textarea not visible after click, checking if panel is actually open...")
                # Check if we can see the close button - if so, panel is open
                close_btn = self.page.locator(SYSTEM_INSTRUCTIONS_CLOSE_BUTTON_SELECTOR)
                if await close_btn.is_visible():
                    self.logger.info(f"[{self.req_id}] Panel seems open (close button visible), waiting for textarea...")
                    await expect_async(textarea).to_be_visible(timeout=5000)
                else:
                    self.logger.warning(f"[{self.req_id}] Panel seems closed, retrying click...")
                    await card_button.click(force=True, timeout=CLICK_TIMEOUT_MS)
                    await expect_async(textarea).to_be_visible(timeout=10000)

            # Wait for textarea to be enabled (editable)
            await expect_async(textarea).to_be_enabled(timeout=5000)

            self.logger.info(f"[{self.req_id}] ✅ System instructions panel opened successfully")

        except TimeoutError as e:
            self.logger.error(f"[{self.req_id}] Timeout opening system instructions panel: {e}")
            await save_error_snapshot(f"system_instructions_panel_open_timeout_{self.req_id}")
            raise
        except Exception as e:
            self.logger.error(f"[{self.req_id}] Error opening system instructions panel: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise
            raise

    async def _fill_system_instructions_textarea(
        self,
        content: str,
        check_client_disconnected: Callable,
    ) -> None:
        """Fills the system instructions textarea with content.

        Args:
            content: Text content to fill in the textarea
            check_client_disconnected: Callback to check if client has disconnected

        Raises:
            ClientDisconnectedError: If client disconnects during operation
        """
        self.logger.info(f"[{self.req_id}] Filling system instructions textarea...")

        try:
            textarea = self.page.locator(SYSTEM_INSTRUCTIONS_TEXTAREA_SELECTOR)
            await expect_async(textarea).to_be_visible(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "System instructions - before filling textarea")

            # Fill with new content - fill() automatically clears
            await textarea.fill(content, timeout=5000)
            await self._check_disconnect(check_client_disconnected, "System instructions - after filling textarea")

            # Verify content was set using active waiting
            try:
                await expect_async(textarea).to_have_value(content, timeout=3000)
                self.logger.info(f"[{self.req_id}] ✅ System instructions content verified")
            except Exception:
                # Fallback: Try getting value manually
                actual_value = await textarea.input_value(timeout=3000)
                if actual_value == content:
                    self.logger.info(f"[{self.req_id}] ✅ System instructions content verified (manual check)")
                else:
                    self.logger.warning(
                        f"[{self.req_id}] System instructions content mismatch. "
                        f"Expected length: {len(content)}, Actual length: {len(actual_value)}"
                    )

        except Exception as e:
            self.logger.error(f"[{self.req_id}] Error filling system instructions textarea: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise
            raise

    async def _close_system_instructions_panel(
        self,
        check_client_disconnected: Callable,
    ) -> None:
        """Closes the system instructions overlay panel using the Escape key.

        Args:
            check_client_disconnected: Callback to check if client has disconnected

        Raises:
            ClientDisconnectedError: If client disconnects during operation
        """
        self.logger.info(f"[{self.req_id}] Closing system instructions panel...")

        try:
            # Primary method: Press Escape key
            # This is more reliable than clicking the close button which might be obscured
            await self.page.keyboard.press("Escape")
            await self._check_disconnect(check_client_disconnected, "System instructions - after pressing Escape")

            # Wait for panel to be hidden
            panel = self.page.locator(SYSTEM_INSTRUCTIONS_PANEL_SELECTOR)
            try:
                await expect_async(panel).to_be_hidden(timeout=3000)
                self.logger.info(f"[{self.req_id}] ✅ System instructions panel closed successfully (via Escape)")
                return
            except TimeoutError:
                self.logger.warning(f"[{self.req_id}] Panel still visible after Escape, trying click fallback...")

            # Fallback: Try clicking the close button if Escape didn't work
            # Use specific selector for close button
            close_button = self.page.locator(SYSTEM_INSTRUCTIONS_CLOSE_BUTTON_SELECTOR)
            if await close_button.is_visible():
                await close_button.click(force=True, timeout=CLICK_TIMEOUT_MS)
                try:
                    await expect_async(panel).to_be_hidden(timeout=3000)
                    self.logger.info(f"[{self.req_id}] ✅ System instructions panel closed successfully (via Button)")
                except TimeoutError:
                    self.logger.warning(f"[{self.req_id}] Panel may still be visible after button click, but continuing...")
            else:
                self.logger.warning(f"[{self.req_id}] Close button not visible for fallback click")

        except Exception as e:
            self.logger.error(f"[{self.req_id}] Error closing system instructions panel: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise
            # Don't re-raise closure errors - panel closure is not critical for functionality

    async def _clear_system_instructions(
        self,
        check_client_disconnected: Callable,
    ) -> None:
        """Clears system instructions by emptying the textarea.

        Args:
            check_client_disconnected: Callback to check if client has disconnected

        Raises:
            ClientDisconnectedError: If client disconnects during operation
        """
        self.logger.info(f"[{self.req_id}] Clearing system instructions...")

        try:
            textarea = self.page.locator(SYSTEM_INSTRUCTIONS_TEXTAREA_SELECTOR)
            await expect_async(textarea).to_be_visible(timeout=5000)
            await self._check_disconnect(check_client_disconnected, "System instructions - before clearing")

            # Clear the textarea
            await textarea.fill("", timeout=5000)
            await self._check_disconnect(check_client_disconnected, "System instructions - after clearing")

            # Verify cleared using active waiting
            try:
                await expect_async(textarea).to_have_value("", timeout=3000)
                self.logger.info(f"[{self.req_id}] ✅ System instructions cleared successfully")
            except Exception:
                actual_value = await textarea.input_value(timeout=3000)
                if not actual_value or not actual_value.strip():
                    self.logger.info(f"[{self.req_id}] ✅ System instructions cleared (manual check)")
                else:
                    self.logger.warning(
                        f"[{self.req_id}] System instructions may not be fully cleared. "
                        f"Remaining content length: {len(actual_value)}"
                    )

        except Exception as e:
            self.logger.error(f"[{self.req_id}] Error clearing system instructions: {e}")
            if isinstance(e, ClientDisconnectedError):
                raise
            raise
