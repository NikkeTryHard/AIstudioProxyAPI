# AI Studio Proxy API

这是一个基于 Python 的代理服务器，用于将 Google AI Studio 的网页界面转换为 OpenAI 兼容的 API。通过 Camoufox (反指纹检测的 Firefox) 和 Playwright 自动化，提供稳定的 API 访问。

[![Star History Chart](https://api.star-history.com/svg?repos=CJackHwang/AIstudioProxyAPI&type=Date)](https://www.star-history.com/#CJackHwang/AIstudioProxyAPI&Date)

This project is generously sponsored by ZMTO. Visit their website: [https://zmto.com/](https://zmto.com/)

本项目由 ZMTO 慷慨赞助服务器支持。访问他们的网站：[https://zmto.com/](https://zmto.com/)

---

## 致谢 (Acknowledgements)

本项目的诞生与发展，离不开以下个人、组织和社区的慷慨支持与智慧贡献：

- **项目发起与主要开发**: @CJackHwang ([https://github.com/CJackHwang](https://github.com/CJackHwang))
- **功能完善、页面操作优化思路贡献**: @ayuayue ([https://github.com/ayuayue](https://github.com/ayuayue))
- **实时流式功能优化与完善**: @luispater ([https://github.com/luispater](https://github.com/luispater))
- **3400+行主文件项目重构伟大贡献**: @yattin (Holt) ([https://github.com/yattin](https://github.com/yattin))
- **项目后期高质量维护**: @Louie （[https://github.com/NikkeTryHard](https://github.com/NikkeTryHard)）
- **社区支持与灵感碰撞**: 特别感谢 [Linux.do 社区](https://linux.do/) 成员们的热烈讨论、宝贵建议和问题反馈，你们的参与是项目前进的重要动力。

同时，我们衷心感谢所有通过提交 Issue、提供建议、分享使用体验、贡献代码修复等方式为本项目默默奉献的每一位朋友。是你们共同的努力，让这个项目变得更好！

---

**这是当前维护的 Python 版本。不再维护的 Javascript 版本请参见 [`deprecated_javascript_version/README.md`](deprecated_javascript_version/README.md)。**

## 系统要求

- **Python**: >=3.9, <4.0 (推荐 3.10+ 以获得最佳性能，Docker 环境使用 3.10)
- **依赖管理**: [Poetry](https://python-poetry.org/) (现代化 Python 依赖管理工具，替代传统 requirements.txt)
- **类型检查**: [Pyright](https://github.com/microsoft/pyright) (可选，用于开发时类型检查和 IDE 支持)
- **操作系统**: Windows, macOS, Linux (完全跨平台支持，Docker 部署支持 x86_64 和 ARM64)
- **内存**: 建议 2GB+ 可用内存 (浏览器自动化需要)
- **网络**: 稳定的互联网连接访问 Google AI Studio (支持代理配置)

## 主要特性

- **OpenAI 兼容 API**: 支持 `/v1/chat/completions` 端点，完全兼容 OpenAI 客户端和第三方工具
- **三层流式响应机制**: 集成流式代理 → 外部 Helper 服务 → Playwright 页面交互的多重保障
- **智能模型切换**: 通过 API 请求中的 `model` 字段动态切换 AI Studio 中的模型
- **完整参数控制**: 支持 `temperature`、`max_output_tokens`、`top_p`、`stop`、`reasoning_effort` 等所有主要参数
- **反指纹检测**: 使用 Camoufox 浏览器降低被检测为自动化脚本的风险
- **脚本注入功能 v3.0**: 使用 Playwright 原生网络拦截，支持油猴脚本动态挂载，100%可靠 🆕
- **现代化 Web UI**: 内置测试界面，支持实时聊天、状态监控、分级 API 密钥管理
- **图形界面启动器**: 提供功能丰富的 GUI 启动器，简化配置和进程管理
- **灵活认证系统**: 支持可选的 API 密钥认证，完全兼容 OpenAI 标准的 Bearer token 格式
- **模块化架构**: 清晰的模块分离设计，api_utils/、browser_utils/、config/ 等独立模块
- **统一配置管理**: 基于 `.env` 文件的统一配置方式，支持环境变量覆盖，Docker 兼容
- **现代化开发工具**: Poetry 依赖管理 + Pyright 类型检查，提供优秀的开发体验

## 系统架构

```mermaid
graph TD
    subgraph "用户端 (User End)"
        User["用户 (User)"]
        WebUI["Web UI (Browser)"]
        API_Client["API 客户端 (API Client)"]
    end

    subgraph "启动与配置 (Launch & Config)"
        GUI_Launch["gui_launcher.py (图形启动器)"]
        CLI_Launch["launch_camoufox.py (命令行启动)"]
        EnvConfig[".env (统一配置)"]
        KeyFile["auth_profiles/key.txt (API Keys)"]
        ConfigDir["config/ (配置模块)"]
    end

    subgraph "核心应用 (Core Application)"
        FastAPI_App["api_utils/app.py (FastAPI 应用)"]
        Routes["api_utils/routes.py (路由处理)"]
        RequestProcessor["api_utils/request_processor.py (请求处理)"]
        AuthUtils["api_utils/auth_utils.py (认证管理)"]
        PageController["browser_utils/page_controller.py (页面控制)"]
        ScriptManager["browser_utils/script_manager.py (脚本注入)"]
        ModelManager["browser_utils/model_management.py (模型管理)"]
        StreamProxy["stream/ (流式代理服务器)"]
    end

    subgraph "外部依赖 (External Dependencies)"
        CamoufoxInstance["Camoufox 浏览器 (反指纹)"]
        AI_Studio["Google AI Studio"]
        UserScript["油猴脚本 (可选)"]
    end

    User -- "运行 (Run)" --> GUI_Launch
    User -- "运行 (Run)" --> CLI_Launch
    User -- "访问 (Access)" --> WebUI

    GUI_Launch -- "启动 (Starts)" --> CLI_Launch
    CLI_Launch -- "启动 (Starts)" --> FastAPI_App
    CLI_Launch -- "配置 (Configures)" --> StreamProxy

    API_Client -- "API 请求 (Request)" --> FastAPI_App
    WebUI -- "聊天请求 (Chat Request)" --> FastAPI_App

    FastAPI_App -- "读取配置 (Reads Config)" --> EnvConfig
    FastAPI_App -- "使用路由 (Uses Routes)" --> Routes
    AuthUtils -- "验证密钥 (Validates Key)" --> KeyFile
    ConfigDir -- "提供设置 (Provides Settings)" --> EnvConfig

    Routes -- "处理请求 (Processes Request)" --> RequestProcessor
    Routes -- "认证管理 (Auth Management)" --> AuthUtils
    RequestProcessor -- "控制浏览器 (Controls Browser)" --> PageController
    RequestProcessor -- "通过代理 (Uses Proxy)" --> StreamProxy

    PageController -- "模型管理 (Model Management)" --> ModelManager
    PageController -- "脚本注入 (Script Injection)" --> ScriptManager
    ScriptManager -- "加载脚本 (Loads Script)" --> UserScript
    ScriptManager -- "增强功能 (Enhances)" --> CamoufoxInstance
    PageController -- "自动化 (Automates)" --> CamoufoxInstance
    CamoufoxInstance -- "访问 (Accesses)" --> AI_Studio
    StreamProxy -- "转发请求 (Forwards Request)" --> AI_Studio

    AI_Studio -- "响应 (Response)" --> CamoufoxInstance
    AI_Studio -- "响应 (Response)" --> StreamProxy

    CamoufoxInstance -- "返回数据 (Returns Data)" --> PageController
    StreamProxy -- "返回数据 (Returns Data)" --> RequestProcessor

    FastAPI_App -- "API 响应 (Response)" --> API_Client
    FastAPI_App -- "UI 响应 (Response)" --> WebUI
```

## 配置管理 ⭐

**新功能**: 项目现在支持通过 `.env` 文件进行配置管理，避免硬编码参数！

### 快速配置

```bash
# 1. 复制配置模板
cp .env.example .env

# 2. 编辑配置文件
nano .env  # 或使用其他编辑器

# 3. 启动服务（自动读取配置）
python gui_launcher.py
# 或直接命令行启动
python launch_camoufox.py --headless
```

### 主要优势

- ✅ **版本更新无忧**: 一个 `git pull` 就完成更新，无需重新配置
- ✅ **配置集中管理**: 所有配置项统一在 `.env` 文件中
- ✅ **启动命令简化**: 无需复杂的命令行参数，一键启动
- ✅ **安全性**: `.env` 文件已被 `.gitignore` 忽略，不会泄露配置
- ✅ **灵活性**: 支持不同环境的配置管理
- ✅ **Docker 兼容**: Docker 和本地环境使用相同的配置方式

详细配置说明请参见 [环境变量配置指南](docs/environment-configuration.md)。

## 使用教程

推荐使用 [`gui_launcher.py`](gui_launcher.py) (图形界面) 或直接使用 [`launch_camoufox.py`](launch_camoufox.py) (命令行) 进行日常运行。仅在首次设置或认证过期时才需要使用调试模式。

### 快速开始

本项目采用现代化的 Python 开发工具链，使用 [Poetry](https://python-poetry.org/) 进行依赖管理，[Pyright](https://github.com/microsoft/pyright) 进行类型检查。

#### 🚀 一键安装脚本 (推荐)

```bash
# macOS/Linux 用户
curl -sSL https://raw.githubusercontent.com/CJackHwang/AIstudioProxyAPI/main/scripts/install.sh | bash

# Windows 用户 (PowerShell)
iwr -useb https://raw.githubusercontent.com/CJackHwang/AIstudioProxyAPI/main/scripts/install.ps1 | iex
```

#### 📋 手动安装步骤

1.  **安装 Poetry** (如果尚未安装):

    ```bash
    # macOS/Linux
    curl -sSL https://install.python-poetry.org | python3 -

    # Windows (PowerShell)
    (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -

    # 或使用包管理器
    # macOS: brew install poetry
    # Ubuntu/Debian: apt install python3-poetry
    ```

2.  **克隆项目**:

    ```bash
    git clone https://github.com/CJackHwang/AIstudioProxyAPI.git
    cd AIstudioProxyAPI
    ```

3.  **安装依赖**:
    Poetry 会自动创建虚拟环境并安装所有依赖：

    ```bash
    poetry install
    ```

4.  **激活虚拟环境**:

    ```bash
    # 方式1: 激活 shell (推荐日常开发)
    poetry env activate

    # 方式2: 直接运行命令 (推荐自动化脚本)
    poetry run python gui_launcher.py
    ```

#### 🔧 后续配置步骤

5.  **环境配置**: 参见 [环境变量配置指南](docs/environment-configuration.md) - **推荐先配置**
6.  **首次认证**: 参见 [认证设置指南](docs/authentication-setup.md)
7.  **日常运行**: 参见 [日常运行指南](docs/daily-usage.md)
8.  **API 使用**: 参见 [API 使用指南](docs/api-usage.md)
9.  **Web 界面**: 参见 [Web UI 使用指南](docs/webui-guide.md)

#### 🛠️ 开发者选项

如果您是开发者，还可以：

```bash
# 安装开发依赖 (包含类型检查、测试工具等)
poetry install --with dev

# 启用类型检查 (需要安装 pyright)
npm install -g pyright
pyright

# 查看项目依赖树
poetry show --tree

# 更新依赖
poetry update
```

### 📚 详细文档

#### 🚀 快速上手

- [安装指南](docs/installation-guide.md) - 详细的安装步骤和环境配置
- [环境变量配置指南](docs/environment-configuration.md) - **.env 文件配置管理** ⭐
- [认证设置指南](docs/authentication-setup.md) - 首次运行与认证文件设置
- [日常运行指南](docs/daily-usage.md) - 日常使用和配置选项

#### 🔧 功能使用

- [API 使用指南](docs/api-usage.md) - API 端点和客户端配置
- [Web UI 使用指南](docs/webui-guide.md) - Web 界面功能说明
- [脚本注入指南](docs/script_injection_guide.md) - 油猴脚本动态挂载功能使用指南 (v3.0) 🆕

#### ⚙️ 高级配置

- [流式处理模式详解](docs/streaming-modes.md) - 三层响应获取机制详细说明 🆕
- [高级配置指南](docs/advanced-configuration.md) - 高级功能和配置选项
- [日志控制指南](docs/logging-control.md) - 日志系统配置和调试
- [故障排除指南](docs/troubleshooting.md) - 常见问题解决方案

#### 🛠️ 开发相关

- [项目架构指南](docs/architecture-guide.md) - 模块化架构设计和组件详解 🆕
- [开发者指南](docs/development-guide.md) - Poetry、Pyright 和开发工作流程
- [依赖版本说明](docs/dependency-versions.md) - Poetry 依赖管理和版本控制详解

## 客户端配置示例

以 Open WebUI 为例：

1. 打开 Open WebUI
2. 进入 "设置" -> "连接"
3. 在 "模型" 部分，点击 "添加模型"
4. **模型名称**: 输入你想要的名字，例如 `aistudio-gemini-py`
5. **API 基础 URL**: 输入 `http://127.0.0.1:2048/v1`
6. **API 密钥**: 留空或输入任意字符
7. 保存设置并开始聊天

---

## 🐳 Docker 部署

本项目支持通过 Docker 进行部署，使用 **Poetry** 进行依赖管理，**完全支持 `.env` 配置文件**！

> 📁 **注意**: 所有 Docker 相关文件已移至 `docker/` 目录，保持项目根目录整洁。

### 🚀 快速 Docker 部署

```bash
# 1. 准备配置文件
cd docker
cp .env.docker .env
nano .env  # 编辑配置

# 2. 使用 Docker Compose 启动
docker compose up -d

# 3. 查看日志
docker compose logs -f

# 4. 版本更新 (在 docker 目录下)
bash update.sh
```

### 📚 详细文档

- [Docker 部署指南 (docker/README-Docker.md)](docker/README-Docker.md) - 包含完整的 Poetry + `.env` 配置说明
- [Docker 快速指南 (docker/README.md)](docker/README.md) - 快速开始指南

### ✨ Docker 特性

- ✅ **Poetry 依赖管理**: 使用现代化的 Python 依赖管理工具
- ✅ **多阶段构建**: 优化镜像大小和构建速度
- ✅ **配置统一**: 使用 `.env` 文件管理所有配置
- ✅ **版本更新**: `bash update.sh` 即可完成更新
- ✅ **目录整洁**: Docker 文件已移至 `docker/` 目录
- ✅ **跨平台支持**: 支持 x86_64 和 ARM64 架构
- ⚠️ **认证文件**: 首次运行需要在主机上获取认证文件，然后挂载到容器中

---

## 关于 Camoufox

本项目使用 [Camoufox](https://camoufox.com/) 来提供具有增强反指纹检测能力的浏览器实例。

- **核心目标**: 模拟真实用户流量，避免被网站识别为自动化脚本或机器人
- **实现方式**: Camoufox 基于 Firefox，通过修改浏览器底层 C++ 实现来伪装设备指纹（如屏幕、操作系统、WebGL、字体等），而不是通过容易被检测到的 JavaScript 注入
- **Playwright 兼容**: Camoufox 提供了与 Playwright 兼容的接口
- **Python 接口**: Camoufox 提供了 Python 包，可以通过 `camoufox.server.launch_server()` 启动其服务，并通过 WebSocket 连接进行控制

使用 Camoufox 的主要目的是提高与 AI Studio 网页交互时的隐蔽性，减少被检测或限制的可能性。但请注意，没有任何反指纹技术是绝对完美的。

## 重要提示

### 三层响应获取机制与参数控制

- **响应获取优先级**: 项目采用三层响应获取机制，确保高可用性：

  1. **集成流式代理服务 (Stream Proxy)**: 默认启用，端口 3120，提供最佳性能和稳定性
  2. **外部 Helper 服务**: 可选配置，需要有效认证文件，作为备用方案
  3. **Playwright 页面交互**: 最终后备方案，通过浏览器自动化获取响应

- **参数控制机制**:

  - **流式代理模式**: 支持基础参数传递，性能最优
  - **Helper 服务模式**: 参数支持取决于外部服务实现
  - **Playwright 模式**: 完整支持所有参数（`temperature`, `max_output_tokens`, `top_p`, `stop`, `reasoning_effort`等）

- **脚本注入增强**: v3.0 版本使用 Playwright 原生网络拦截，确保注入模型与原生模型 100%一致

### 客户端管理历史

**客户端管理历史，代理不支持 UI 内编辑**: 客户端负责维护完整的聊天记录并将其发送给代理。代理服务器本身不支持在 AI Studio 界面中对历史消息进行编辑或分叉操作。

## 未来计划

以下是一些计划中的改进方向：

- **云服务器部署指南**: 提供更详细的在主流云平台上部署和管理服务的指南
- **认证更新流程优化**: 探索更便捷的认证文件更新机制，减少手动操作
- **流程健壮性优化**: 减少错误几率和接近原生体验

## 贡献

欢迎提交 Issue 和 Pull Request！

## License

[AGPLv3](LICENSE)

## 开发不易，支持作者

如果您觉得本项目对您有帮助，并且希望支持作者的持续开发，欢迎通过以下方式进行捐赠。您的支持是对我们最大的鼓励！

![开发不易，支持作者](./支持作者.jpg)
