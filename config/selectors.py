# AI Studio UI Selectors

# Login
EMAIL_INPUT_SELECTOR = 'input[type="email"]'
NEXT_BUTTON_SELECTOR = "#identifierNext"
PASSWORD_INPUT_SELECTOR = 'input[type="password"]'
PASSWORD_NEXT_BUTTON_SELECTOR = "#passwordNext"

# Chat Interface
PROMPT_TEXTAREA_SELECTOR = "ms-prompt-input-wrapper textarea"
# Aliases for backward compatibility
INPUT_SELECTOR = PROMPT_TEXTAREA_SELECTOR
INPUT_SELECTOR2 = PROMPT_TEXTAREA_SELECTOR

RESPONSE_CONTAINER_SELECTOR = "ms-chat-bubble"
RESPONSE_TEXT_SELECTOR = "ms-cmark-node.cmark-node"

SUBMIT_BUTTON_SELECTOR = "ms-prompt-input-wrapper button[aria-label='Run']"
# Fallback for submit button if aria-label changes
SUBMIT_BUTTON_SELECTOR_ALT = "ms-prompt-input-wrapper button.ms-button-primary"

CLEAR_CHAT_BUTTON_SELECTOR = 'button[data-test-clear="outside"][aria-label="New chat"], button[aria-label="New chat"]'
CLEAR_CHAT_CONFIRM_BUTTON_SELECTOR = (
    'button.ms-button-primary:has-text("Discard and continue")'
)

# Input Area
AUTOSIZE_WRAPPER_SELECTOR = "ms-prompt-input-wrapper ms-autosize-textarea"
INPUT_WRAPPER_SELECTOR = "ms-prompt-input-wrapper"

# Function Injection
EDIT_FUNCTION_BUTTON_SELECTOR = "button.edit-function-declarations-button"
FUNCTION_EDITOR_TEXTAREA_SELECTOR = "ms-text-editor textarea"
CODE_EDITOR_TAB_SELECTOR = "button[role='tab']"
SAVE_FUNCTION_BUTTON_SELECTOR = 'button.ms-button-primary[aria-label="Save the current function declarations"]'

# Uploads
INSERT_ASSETS_BUTTON_SELECTOR = 'button[aria-label="Insert assets such as images, videos, files, or audio"]'
UPLOAD_MENU_CONTAINER_SELECTOR = "div.cdk-overlay-container"
UPLOAD_MENU_ITEM_SELECTOR = "div[role='menu'] button[role='menuitem'][aria-label='Upload File']"
UPLOAD_MENU_ITEM_TEXT_SELECTOR = "div[role='menu'] button[role='menuitem']:has-text('Upload File')"
OVERLAY_BACKDROP_SELECTOR = "div.cdk-overlay-backdrop"
UPLOAD_BUTTON_SELECTOR = INSERT_ASSETS_BUTTON_SELECTOR # Alias

# Post-Upload Dialogs
DIALOG_AGREE_BUTTONS = [
    "Agree", "I agree", "Allow", "Continue", "OK",
    "确定", "同意", "继续", "允许"
]
COPYRIGHT_ACK_BUTTON_SELECTOR = 'button[aria-label*="copyright" i], button[aria-label*="acknowledge" i]'

# Loading & Status
LOADING_SPINNER_SELECTOR = 'button[aria-label="Run"].run-button svg .stoppable-spinner'
OVERLAY_SELECTOR = ".mat-mdc-dialog-inner-container"

# Error Handling
ERROR_TOAST_SELECTOR = "div.toast.warning, div.toast.error"

# Editing
EDIT_MESSAGE_BUTTON_SELECTOR = (
    "ms-chat-turn:last-child .actions-container button.toggle-edit-button"
)
MESSAGE_TEXTAREA_SELECTOR = "ms-chat-turn:last-child ms-text-chunk ms-autosize-textarea"
FINISH_EDIT_BUTTON_SELECTOR = 'ms-chat-turn:last-child .actions-container button.toggle-edit-button[aria-label="Stop editing"]'

# Menus & Copy
MORE_OPTIONS_BUTTON_SELECTOR = (
    "div.actions-container div ms-chat-turn-options div > button"
)
COPY_MARKDOWN_BUTTON_SELECTOR = "button.mat-mdc-menu-item:nth-child(4)"
COPY_MARKDOWN_BUTTON_SELECTOR_ALT = 'div[role="menu"] button:has-text("Copy Markdown")'

# Settings
MAX_OUTPUT_TOKENS_SELECTOR = 'input[aria-label="Maximum output tokens"]'
STOP_SEQUENCE_INPUT_SELECTOR = 'input[aria-label="Add stop token"]'
MAT_CHIP_REMOVE_BUTTON_SELECTOR = (
    'mat-chip-set mat-chip-row button[aria-label*="Remove"]'
)
TOP_P_INPUT_SELECTOR = 'ms-slider input[type="number"][max="1"]'
TEMPERATURE_INPUT_SELECTOR = 'ms-slider input[type="number"][max="2"]'
USE_URL_CONTEXT_SELECTOR = 'button[aria-label="Browse the url context"]'

# Thinking Mode
ENABLE_THINKING_MODE_TOGGLE_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="enable-thinking"] button[role="switch"].mdc-switch'
)
SET_THINKING_BUDGET_TOGGLE_SELECTOR = (
    'mat-slide-toggle[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch, '
    '[data-test-toggle="manual-budget"] button[role="switch"].mdc-switch'
)
THINKING_BUDGET_INPUT_SELECTOR = '[data-test-slider] input[type="number"]'

THINKING_LEVEL_SELECT_SELECTOR = '[role="combobox"][aria-label="Thinking Level"], mat-select[aria-label="Thinking Level"], [role="combobox"][aria-label="Thinking level"], mat-select[aria-label="Thinking level"]'
THINKING_LEVEL_OPTION_LOW_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("Low"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("Low")'
THINKING_LEVEL_OPTION_HIGH_SELECTOR = '[role="listbox"][aria-label="Thinking Level"] [role="option"]:has-text("High"), [role="listbox"][aria-label="Thinking level"] [role="option"]:has-text("High")'

# Grounding
GROUNDING_WITH_GOOGLE_SEARCH_TOGGLE_SELECTOR = (
    'div[data-test-id="searchAsAToolTooltip"] mat-slide-toggle button'
)

# Function Calling
FUNCTION_CALLING_TOGGLE_SELECTOR = 'div[data-test-id="functionCallingTooltip"] mat-slide-toggle button, mat-slide-toggle:has-text("Function calling") button'
