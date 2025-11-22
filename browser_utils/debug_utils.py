"""
Debug utilities for comprehensive error snapshots and logging.

This module provides enhanced debugging capabilities with:
- Date-based directory structure (errors_py/YYYY-MM-DD/)
- Multiple artifact types (screenshot, DOM dump, console logs, network state)
- Human-readable Texas timestamps
- Complete metadata capture

Created: 2025-11-21
Purpose: Fix headless mode debugging and client disconnect issues
"""

import asyncio
import json
import logging
import os
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import Page as AsyncPage, Locator

logger = logging.getLogger("AIStudioProxyServer")


def get_texas_timestamp() -> Tuple[str, str]:
    """
    Get current timestamp in both ISO format and human-readable Texas time.

    Texas is in Central Time Zone (UTC-6 in standard time, UTC-5 in daylight time).

    Returns:
        Tuple[str, str]: (iso_format, human_readable_format)
        Example: ("2025-11-21T18:37:32.440", "2025-11-21 18:37:32.440 CST")
    """
    # Get current UTC time
    utc_now = datetime.now(timezone.utc)

    # Convert to Central Time (approximation using fixed offset)
    # Note: For production, use pytz for accurate DST handling
    central_offset = timedelta(hours=-6)  # CST (standard time)
    # TODO: Add DST detection if needed
    central_time = utc_now + central_offset

    # ISO format
    iso_format = central_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    # Human-readable format
    human_format = central_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " CST"

    return iso_format, human_format


async def capture_dom_structure(page: AsyncPage) -> str:
    """
    Capture human-readable DOM tree structure.

    Unlike raw HTML, this provides a clean, indented tree view showing:
    - Element hierarchy
    - IDs and classes
    - Important attributes (disabled, value, etc.)

    Args:
        page: Playwright page instance

    Returns:
        str: Human-readable DOM tree structure
    """
    try:
        dom_tree = await page.evaluate("""() => {
            function getTreeStructure(element, indent = '', depth = 0, maxDepth = 15) {
                // Prevent infinite recursion
                if (depth > maxDepth) {
                    return indent + '... (max depth reached)\\n';
                }

                let result = indent + element.tagName;

                // Add ID
                if (element.id) {
                    result += `#${element.id}`;
                }

                // Add classes
                if (element.className && typeof element.className === 'string') {
                    const classes = element.className.trim().split(/\\s+/).filter(c => c);
                    if (classes.length > 0) {
                        result += '.' + classes.join('.');
                    }
                }

                // Add important attributes
                const importantAttrs = ['aria-label', 'type', 'role', 'data-test-id'];
                for (const attr of importantAttrs) {
                    const val = element.getAttribute(attr);
                    if (val) {
                        result += ` [${attr}="${val}"]`;
                    }
                }

                // Add state attributes
                if (element.disabled !== undefined) {
                    result += ` [disabled=${element.disabled}]`;
                }
                if (element.hasAttribute('aria-disabled')) {
                    result += ` [aria-disabled=${element.getAttribute('aria-disabled')}]`;
                }

                // Add value for input elements (truncated)
                if (element.value && typeof element.value === 'string') {
                    const truncated = element.value.substring(0, 50);
                    const suffix = element.value.length > 50 ? '...' : '';
                    result += ` value="${truncated}${suffix}"`;
                }

                result += '\\n';

                // Recurse for children
                for (let child of element.children) {
                    result += getTreeStructure(child, indent + '  ', depth + 1, maxDepth);
                }

                return result;
            }

            return getTreeStructure(document.body);
        }()""")

        return dom_tree
    except Exception as e:
        logger.error(f"Failed to capture DOM structure: {e}")
        return f"Error capturing DOM structure: {str(e)}\n"


async def capture_playwright_state(
    page: AsyncPage, locators: Optional[Dict[str, Locator]] = None
) -> Dict[str, Any]:
    """
    Capture current Playwright page and element states.

    Args:
        page: Playwright page instance
        locators: Optional dict of named locators to inspect
                 Example: {"submit_button": loc, "input_field": loc}

    Returns:
        Dict containing page state and locator states
    """
    state = {
        "page": {
            "url": page.url,
            "title": "",
            "viewport": page.viewport_size,
        },
        "locators": {},
        "storage": {
            "cookies_count": 0,
            "localStorage_keys": [],
        },
    }

    try:
        state["page"]["title"] = await page.title()
    except Exception as e:
        logger.warning(f"Failed to get page title: {e}")
        state["page"]["title"] = f"Error: {e}"

    # Capture locator states
    if locators:
        for name, locator in locators.items():
            loc_state = {
                "exists": False,
                "count": 0,
                "visible": False,
                "enabled": False,
                "value": None,
            }

            try:
                loc_state["count"] = await locator.count()
                loc_state["exists"] = loc_state["count"] > 0

                if loc_state["exists"]:
                    # Check visibility with short timeout
                    try:
                        loc_state["visible"] = await locator.is_visible(timeout=1000)
                    except Exception:
                        loc_state["visible"] = False

                    # Check enabled state
                    try:
                        loc_state["enabled"] = await locator.is_enabled(timeout=1000)
                    except Exception:
                        loc_state["enabled"] = False

                    # Try to get value (for input elements)
                    try:
                        value = await locator.input_value(timeout=1000)
                        if value:
                            # Truncate long values
                            loc_state["value"] = (
                                value[:100] + "..." if len(value) > 100 else value
                            )
                    except Exception:
                        pass  # Not an input element or error

            except Exception as e:
                logger.warning(f"Failed to capture state for locator '{name}': {e}")
                loc_state["error"] = str(e)

            state["locators"][name] = loc_state

    # Capture storage info
    try:
        cookies = await page.context.cookies()
        state["storage"]["cookies_count"] = len(cookies)
    except Exception as e:
        logger.warning(f"Failed to get cookies: {e}")

    try:
        localStorage_keys = await page.evaluate("() => Object.keys(localStorage)")
        state["storage"]["localStorage_keys"] = localStorage_keys
    except Exception as e:
        logger.warning(f"Failed to get localStorage keys: {e}")

    return state


async def save_comprehensive_snapshot(
    page: AsyncPage,
    error_name: str,
    req_id: str,
    error_stage: str = "",
    additional_context: Optional[Dict[str, Any]] = None,
    locators: Optional[Dict[str, Locator]] = None,
    error_exception: Optional[Exception] = None,
) -> str:
    """
    Save comprehensive error snapshot with all debugging artifacts.

    Directory structure:
        errors_py/YYYY-MM-DD/HH-MM-SS_reqid_errorname/
            ├── screenshot.png
            ├── dom_dump.html
            ├── dom_structure.txt
            ├── console_logs.txt
            ├── network_requests.json
            ├── playwright_state.json
            └── metadata.json

    Args:
        page: Playwright page instance
        error_name: Base error name (e.g., "stream_post_button_check_disconnect")
        req_id: Request ID
        error_stage: Description of error stage (e.g., "流式响应后按钮状态检查")
        additional_context: Extra context to include in metadata
        locators: Dict of named locators to capture states for
        error_exception: Exception object (if available)

    Returns:
        str: Path to snapshot directory
    """
    log_prefix = f"[{req_id}]" if req_id else "[DEBUG]"

    # Check page availability
    if not page or page.is_closed():
        logger.warning(
            f"{log_prefix} Cannot save snapshot ({error_name}), page is unavailable."
        )
        return ""

    logger.info(f"{log_prefix} 💾 Saving comprehensive error snapshot ({error_name})...")

    # Get timestamps
    iso_timestamp, human_timestamp = get_texas_timestamp()
    time_component = iso_timestamp.split("T")[1].replace(":", "-").replace(".", "-")

    # Create date-based directory structure
    date_str = iso_timestamp.split("T")[0]  # YYYY-MM-DD
    base_error_dir = Path(__file__).parent.parent / "errors_py"
    date_dir = base_error_dir / date_str
    snapshot_dir_name = f"{time_component}_{req_id}_{error_name}"
    snapshot_dir = date_dir / snapshot_dir_name

    try:
        # Create directory structure
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"{log_prefix}   📁 Created snapshot directory: {snapshot_dir}")

        # === 1. Screenshot ===
        screenshot_path = snapshot_dir / "screenshot.png"
        try:
            await page.screenshot(path=str(screenshot_path), full_page=True, timeout=15000)
            logger.info(f"{log_prefix}   ✅ Screenshot saved")
        except Exception as ss_err:
            logger.error(f"{log_prefix}   ❌ Screenshot failed: {ss_err}")

        # === 2. HTML Dump ===
        html_path = snapshot_dir / "dom_dump.html"
        try:
            content = await page.content()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"{log_prefix}   ✅ HTML dump saved")
        except Exception as html_err:
            logger.error(f"{log_prefix}   ❌ HTML dump failed: {html_err}")

        # === 3. DOM Structure (Human-Readable) ===
        dom_structure_path = snapshot_dir / "dom_structure.txt"
        try:
            dom_tree = await capture_dom_structure(page)
            with open(dom_structure_path, "w", encoding="utf-8") as f:
                f.write(dom_tree)
            logger.info(f"{log_prefix}   ✅ DOM structure saved")
        except Exception as dom_err:
            logger.error(f"{log_prefix}   ❌ DOM structure failed: {dom_err}")

        # === 4. Console Logs ===
        console_logs_path = snapshot_dir / "console_logs.txt"
        try:
            # Get console logs from global state
            from server import console_logs

            if console_logs:
                with open(console_logs_path, "w", encoding="utf-8") as f:
                    f.write("=== Browser Console Logs ===\n\n")
                    for log_entry in console_logs:
                        timestamp = log_entry.get("timestamp", "N/A")
                        log_type = log_entry.get("type", "log")
                        text = log_entry.get("text", "")
                        location = log_entry.get("location", "")

                        f.write(f"[{timestamp}] [{log_type.upper()}] {text}\n")
                        if location:
                            f.write(f"  Location: {location}\n")
                        f.write("\n")

                logger.info(
                    f"{log_prefix}   ✅ Console logs saved ({len(console_logs)} entries)"
                )
            else:
                with open(console_logs_path, "w", encoding="utf-8") as f:
                    f.write("No console logs captured.\n")
                logger.info(f"{log_prefix}   ℹ️ No console logs available")
        except Exception as console_err:
            logger.error(f"{log_prefix}   ❌ Console logs failed: {console_err}")

        # === 5. Network Requests ===
        network_path = snapshot_dir / "network_requests.json"
        try:
            from server import network_log

            with open(network_path, "w", encoding="utf-8") as f:
                json.dump(network_log, f, indent=2, ensure_ascii=False)

            req_count = len(network_log.get("requests", []))
            resp_count = len(network_log.get("responses", []))
            logger.info(
                f"{log_prefix}   ✅ Network log saved ({req_count} reqs, {resp_count} resps)"
            )
        except Exception as net_err:
            logger.error(f"{log_prefix}   ❌ Network log failed: {net_err}")

        # === 6. Playwright State ===
        playwright_state_path = snapshot_dir / "playwright_state.json"
        try:
            pw_state = await capture_playwright_state(page, locators)
            with open(playwright_state_path, "w", encoding="utf-8") as f:
                json.dump(pw_state, f, indent=2, ensure_ascii=False)
            logger.info(f"{log_prefix}   ✅ Playwright state saved")
        except Exception as pw_err:
            logger.error(f"{log_prefix}   ❌ Playwright state failed: {pw_err}")

        # === 7. Metadata ===
        metadata_path = snapshot_dir / "metadata.json"
        try:
            # Build metadata
            metadata = {
                "req_id": req_id,
                "error_name": error_name,
                "error_stage": error_stage,
                "timestamp": {
                    "iso": iso_timestamp,
                    "human": human_timestamp,
                },
                "headless_mode": os.environ.get("HEADLESS", "true").lower() == "true",
                "launch_mode": os.environ.get("LAUNCH_MODE", "unknown"),
                "environment": {
                    "RESPONSE_COMPLETION_TIMEOUT": os.environ.get(
                        "RESPONSE_COMPLETION_TIMEOUT", "300000"
                    ),
                    "DEBUG_LOGS_ENABLED": os.environ.get(
                        "DEBUG_LOGS_ENABLED", "false"
                    ).lower()
                    == "true",
                    "DEFAULT_MODEL": os.environ.get("DEFAULT_MODEL", "unknown"),
                },
            }

            # Add exception info if available
            if error_exception:
                metadata["exception"] = {
                    "type": type(error_exception).__name__,
                    "message": str(error_exception),
                    "traceback": traceback.format_exc(),
                }

            # Add additional context
            if additional_context:
                metadata["additional_context"] = additional_context

            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.info(f"{log_prefix}   ✅ Metadata saved")
        except Exception as meta_err:
            logger.error(f"{log_prefix}   ❌ Metadata failed: {meta_err}")

        logger.info(
            f"{log_prefix} 🎉 Comprehensive snapshot complete: {snapshot_dir.name}"
        )
        return str(snapshot_dir)

    except Exception as e:
        logger.error(
            f"{log_prefix} ❌ Failed to create snapshot directory: {e}", exc_info=True
        )
        return ""


async def save_error_snapshot_legacy(error_name: str = "error") -> None:
    """
    Legacy error snapshot function for backward compatibility.

    This function maintains the old interface but uses the new comprehensive
    snapshot system internally.

    DEPRECATED: Use save_comprehensive_snapshot() instead for full features.

    Args:
        error_name: Error name with optional req_id suffix (e.g., "error_hbfu521")
    """
    import server

    # Parse req_id from error_name if present
    name_parts = error_name.split("_")
    req_id = (
        name_parts[-1]
        if len(name_parts) > 1 and len(name_parts[-1]) == 7
        else "unknown"
    )
    base_error_name = error_name if req_id == "unknown" else "_".join(name_parts[:-1])

    page_to_snapshot = server.page_instance

    if (
        not server.browser_instance
        or not server.browser_instance.is_connected()
        or not page_to_snapshot
        or page_to_snapshot.is_closed()
    ):
        logger.warning(
            f"[{req_id}] Cannot save legacy snapshot ({base_error_name}), browser/page unavailable."
        )
        return

    # Call new comprehensive snapshot
    await save_comprehensive_snapshot(
        page=page_to_snapshot,
        error_name=base_error_name,
        req_id=req_id,
        error_stage="Legacy snapshot call",
        additional_context={"legacy_call": True},
    )
