"""
PageController模块
封装了所有与Playwright页面直接交互的复杂逻辑。
"""
from playwright.async_api import Page as AsyncPage

from browser_utils.page_controller_modules import (
    ParameterController,
    ThinkingController,
    InputController,
    ChatController,
    ResponseController,
    BaseController
)

class PageController(
    ParameterController,
    ThinkingController,
    InputController,
    ChatController,
    ResponseController,
    BaseController
):
    """封装了与AI Studio页面交互的所有操作。"""

    def __init__(self, page: AsyncPage, logger, req_id: str):
        super().__init__(page, logger, req_id)
