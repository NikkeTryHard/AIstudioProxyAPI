# --- browser_utils/__init__.py ---
# 浏览器操作工具模块
from .debug_utils import (
    capture_dom_structure,
    capture_playwright_state,
    get_texas_timestamp,
    save_comprehensive_snapshot,
    save_error_snapshot_legacy,
)
from .initialization import (
    _close_page_logic,
    _initialize_page_logic,
    enable_temporary_chat_mode,
    signal_camoufox_shutdown,
)
from .model_management import (
    _force_ui_state_settings,
    _force_ui_state_with_retry,
    _handle_initial_model_state_and_storage,
    _set_model_from_page_display,
    _verify_and_apply_ui_state,
    _verify_ui_state_settings,
    load_excluded_models,
    switch_ai_studio_model,
)
from .operations import (
    _get_final_response_content,
    _handle_model_list_response,
    _wait_for_response_completion,
    detect_and_extract_page_error,
    get_raw_text_content,
    get_response_via_copy_button,
    get_response_via_edit_button,
    save_error_snapshot,
)
from .page_controller import PageController
from .script_manager import ScriptManager, script_manager

__all__ = [
    # 初始化相关
    "_initialize_page_logic",
    "_close_page_logic",
    "signal_camoufox_shutdown",
    "enable_temporary_chat_mode",
    # 页面操作相关
    "_handle_model_list_response",
    "detect_and_extract_page_error",
    "save_error_snapshot",
    "get_response_via_edit_button",
    "get_response_via_copy_button",
    "_wait_for_response_completion",
    "_get_final_response_content",
    "get_raw_text_content",
    # 模型管理相关
    "switch_ai_studio_model",
    "load_excluded_models",
    "_handle_initial_model_state_and_storage",
    "_set_model_from_page_display",
    "_verify_ui_state_settings",
    "_force_ui_state_settings",
    "_force_ui_state_with_retry",
    "_verify_and_apply_ui_state",
    # 脚本管理相关
    "ScriptManager",
    "script_manager",
    # Page Controller
    "PageController",
    # Debug utilities (comprehensive error snapshots)
    "save_comprehensive_snapshot",
    "save_error_snapshot_legacy",
    "get_texas_timestamp",
    "capture_dom_structure",
    "capture_playwright_state",
]
