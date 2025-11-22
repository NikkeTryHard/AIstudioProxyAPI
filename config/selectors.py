"""
CSS Selectors Configuration Module
Contains all CSS selectors used for page element location.
"""

# --- Input Related Selectors ---
PROMPT_TEXTAREA_SELECTOR = "ms-prompt-input-wrapper ms-autosize-textarea textarea"
INPUT_SELECTOR = PROMPT_TEXTAREA_SELECTOR
INPUT_SELECTOR2 = PROMPT_TEXTAREA_SELECTOR

# --- Button Selectors ---
# Send button: prioritize button with aria-label="Run"; fallback to submit button within container if page structure changes.
SUBMIT_BUTTON_SELECTOR = 'button[aria-label="Run"].run-button, ms-run-button button[type="submit"].run-button'
CLEAR_CHAT_BUTTON_SELECTOR = 'button[data-test-clear="outside"][aria-label="New chat"], button[aria-label="New chat"]'
CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR = (
    'button.ms-button-primary:has-text("Discard and continue")'
)
UPLOAD_BUTTON_SELECTOR = 'button[aria-label^="Insert assets"]'

# --- Response Related Selectors ---
RESPONSE_CONTAINER_SELECTOR = "ms-chat-turn .chat-turn-container.model"
RESPONSE_TEXT_SELECTOR = "ms-cmark-node.cmark-node"

# --- Loading and Status Selectors ---
LOADING_SPINNER_SELECTOR = 'button[aria-label="Run"].run-button svg .stoppable-spinner'
OVERLAY_SELECTOR = ".mat-mdc-dialog-inner-container"

# --- Error Notification Selectors ---
ERROR_TOAST_SELECTOR = "div.toast.warning, div.toast.error"

# --- Edit Related Selectors ---
EDIT_MESSAGE_BUTTON_SELECTOR = (
    "ms-chat-turn:last-child .actions-container button.toggle-edit-button"
)
MESSAGE_TEXTAREA_SELECTOR = "ms-chat-turn:last-child ms-text-chunk ms-autosize-textarea"
FINISH_EDIT_BUTTON_SELECTOR = 'ms-chat-turn:last-child .actions-container button.toggle-edit-button[aria-label="Stop editing"]'

# --- Menu and Copy Related Selectors ---
MORE_OPTIONS_BUTTON_SELECTOR = (
    "div.actions-container div ms-chat-turn-options div > button"
)
COPY_MARKDOWN_BUTTON_SELECTOR = "button.mat-mdc-menu-item:nth-child(4)"
COPY_MARKDOWN_BUTTON_SELECTOR_ALT = 'div[role="menu"] button:has-text("Copy Markdown")'

# --- Settings Related Selectors ---
MAX_OUTPUT_TOKENS_SELECTOR = 'input[aria-label="Maximum output tokens"]'
STOP_SEQUENCE_INPUT_SELECTOR = 'input[aria-label="Add stop token"]'
MAT_CHIP_REMOVE_BUTTON_SELECTOR = (
    'mat-chip-set mat-chip-row button[aria-label*="Remove"]'
)
TOP_P_INPUT_SELECTOR = 'ms-slider input[type="number"][max="1"]'
TEMPERATURE_INPUT_SELECTOR = 'ms-slider input[type="number"][max="2"]'
USE_URL_CONTEXT_SELECTOR = 'button[aria-label="Browse the url context"]'

# --- Thinking Mode Related Selectors ---
# Main thinking toggle: controls whether to enable thinking mode (master switch)
ENABLE_THINKING_MODE_TOGGLE_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch'
)
# Manual budget toggle: controls whether to manually limit thinking budget
SET_THINKING_BUDGET_TOGGLE_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch'
)
# Thinking budget input field
THINKING_BUDGET_INPUT_SELECTOR = '[data-test-slider] input[type="number"]'

# Thinking level dropdown
THINKING_LEVEL_SELECT_SELECTOR = '[role="combobox"][aria-label="Thinking Level"], mat-select[aria-label="Thinking Level"], [role="combobox"][aria-label="Thinking level"], mat-select[aria-label="Thinking level"]'
THINKING_LEVEL_OPTION_LOW_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("Low"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("Low")'
THINKING_LEVEL_OPTION_HIGH_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("High"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("High")'

# --- Google Search Grounding ---
GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR = (
    'div[data-test-id="searchAsAToolTooltip"] mat-slide-toggle button'
)

# --- Function Calling ---
FUNCTION_CALLING_TOGGLE_SELECTOR = (
    'div[data-test-id="functionCallingTooltip"] mat-slide-toggle button, mat-slide-toggle:has-text("Function calling") button'
)

# --- System Instructions ---
SYSTEM_INSTRUCTIONS_CARD_SELECTOR = 'button[data-test-system-instructions-card]'
SYSTEM_INSTRUCTIONS_TEXTAREA_SELECTOR = 'textarea[aria-label="System instructions"]'
SYSTEM_INSTRUCTIONS_CLOSE_BUTTON_SELECTOR = 'ms-system-instructions-panel button[data-test-close-button][aria-label="Close panel"]'
SYSTEM_INSTRUCTIONS_PANEL_SELECTOR = 'ms-system-instructions-panel ms-sliding-right-panel'
