# PyApp CLI

跨平台 Python 应用打包工具，支持将 Python 应用打包为 Windows、Linux、Android 平台的可执行程序。

> 一份 Python 代码，一行命令，三平台安装包

## 安装

```bash
pip install -e .
```

如需使用 Nuitka 源码编译功能：

```bash
pip install -e ".[compile]"
```

## 快速开始

```bash
# 1. 创建新项目
pyapp init my-app

# 2. 进入项目目录
cd my-app

# 3. 构建并运行（开发）
pyapp build windows
pyapp run windows

# 发布流程：build → (可选 compile) → package
pyapp build windows
pyapp compile windows    # 可选，使用 Nuitka 编译源码
pyapp package windows
```

## 命令列表

| 命令 | 说明 |
| --- | --- |
| `pyapp init <name>` | 创建新项目 |
| `pyapp create <platform>` | 创建平台项目结构 |
| `pyapp build <platform>` | 准备平台构建目录（运行时、源码、依赖） |
| `pyapp compile <platform>` | 使用 Nuitka 编译 Python 源码为 pyd/so |
| `pyapp run <platform>` | 运行应用（支持源码/依赖更新） |
| `pyapp package <platform>` | 打包分发文件（ZIP / tar.gz / APK） |
| `pyapp deploy <platform> <target>` | 部署到目标设备 |
| `pyapp setup <platform>` | 安装平台依赖环境 |
| `pyapp logs` | 查看或管理日志 |

> `build`、`create`、`package` 支持 `all` 平台，会依次处理 windows、linux、android。
> `compile`、`run`、`deploy`、`setup` 不支持 `all`，需指定单个平台。

### 命令详解

#### pyapp init

创建新项目，支持两种模板：

```bash
# FastAPI 模板（默认，含前端 Vue 模板和 CI 脚本）
pyapp init my-app

# 基础模板（仅 Python 入口）
pyapp init my-app --template basic

# 指定输出目录
pyapp init my-app -o /path/to/project
```

#### pyapp create

创建平台项目结构（生成 Gradle、systemd、app.ini 等平台文件）：

```bash
pyapp create windows
pyapp create linux
pyapp create android
pyapp create all                      # 创建所有平台结构

# Android 指定 CPU 架构（多个用逗号分隔）
pyapp create android --arch arm64-v8a,armeabi-v7a
```

#### pyapp build

准备平台构建目录（`bundles/<platform>/`），包括 Python 运行时、应用源码、pip 依赖、启动脚本。**不会生成分发包**，需后续执行 `package`。

```bash
# 构建 Windows 版
pyapp build windows

# 构建 Linux 版
pyapp build linux

# 构建 Linux ARM64 / ARM32 版
pyapp build linux --arch aarch64
pyapp build linux --arch armv7l

# 构建 Android 版
pyapp build android

# Android 指定 CPU 架构（支持多架构，逗号分隔）
pyapp build android --arch arm64-v8a
pyapp build android --arch arm64-v8a,armeabi-v7a
pyapp build android --arch x86_64        # 模拟器

# 构建所有平台
pyapp build all

# 指定项目目录
pyapp build windows -d /path/to/project

# 构建类型（debug/release，影响 Android Gradle 任务）
pyapp build android -t release

# 不自动创建平台项目结构
pyapp build windows --no-create
```

**支持的 CPU 架构**：

| 平台 | 架构 | 说明 |
| --- | --- | --- |
| Linux | `x86_64` | 64 位 x86（默认） |
| Linux | `aarch64` | 64 位 ARM（如 Raspberry Pi 4） |
| Linux | `armv7l` | 32 位 ARM（如 Raspberry Pi 3） |
| Android | `arm64-v8a` | 现代 64 位 ARM（推荐） |
| Android | `armeabi-v7a` | 旧款 32 位 ARM |
| Android | `x86_64` | Android 模拟器 |

> Windows 固定输出 x86_64，`--arch` 参数被忽略。

#### pyapp compile

使用 Nuitka 将 Python 源码编译为原生二进制（`.pyd`/`.so`），保护源码并提升性能。需要先执行 `build`。

```bash
# Windows / Linux（本机 Nuitka 编译）
pyapp build windows
pyapp compile windows
pyapp package windows

# Android（需先通过 Termux Docker 编译生成 .so，再指定预编译产物）
pyapp build android
pyapp compile android --precompiled dist/app.so
pyapp package android
```

**前置条件**：

- Windows/Linux：安装 Nuitka（推荐固定版本，已验证）
  ```bash
  pip install nuitka==2.7.12 ordered-set zstandard
  ```
- Android：必须提供 `--precompiled` 指向 Termux 编译出的 `.so` 文件
- 所有平台：先执行 `pyapp build <platform>`

> `compile` 不支持 `all` 平台，因为编译需要平台特定环境。

#### pyapp run

运行应用。如果 `bundles` 目录不存在会自动先 `build`。会自动同步 `frontend/.env.development` 的 `VITE_API_PORT`。

```bash
pyapp run windows                      # 直接运行
pyapp run windows -u                   # 仅更新应用源码后运行（不重装依赖）
pyapp run windows -r                   # 重新安装依赖并运行（含源码更新）
pyapp run windows -ur                  # 同上（-u 与 -r 组合）
```

| 选项 | 说明 |
| --- | --- |
| `-u, --update` | 仅更新应用源码和前端产物（不重装依赖） |
| `-r, --rebuild` | 重新执行完整 build（含依赖安装） |

#### pyapp package

将 `bundles` 目录打包为分发文件，需要先执行 `build`（可选 `compile`）。

```bash
pyapp build windows
pyapp package windows                  # 产出 dist/<app>-<ver>-windows-x86_64.zip

pyapp build linux --arch aarch64
pyapp package linux                    # 产出 dist/<app>-<ver>-linux-aarch64.tar.gz

pyapp build android
pyapp package android                  # 产出 dist/<app>-<ver>-android-<abis>.apk
pyapp package all                      # 打包所有平台
```

分发文件输出到项目根目录的 `dist/`。Android 打包会运行 Gradle（`assembleDebug`/`assembleRelease`），若设置了 `ANDROID_KEYSTORE_PATH` 等环境变量会自动签名。

#### pyapp deploy

部署到目标设备（需先 `package`）：

```bash
# Android：通过 adb 安装 APK
pyapp deploy android 192.168.1.100:5555

# Linux：完整部署（scp + 解压 + install.sh + 重启服务）
pyapp deploy linux user@192.168.1.100

# Linux：仅推送增量更新（打包 src/ 触发 /api/update）
pyapp deploy linux user@192.168.1.100 --update-only

# Linux：回滚到指定版本（调用 /api/rollback）
pyapp deploy linux user@192.168.1.100 --rollback 0.1.0

# Windows：scp 推送 ZIP 到目标机
pyapp deploy windows user@192.168.1.100
```

| 选项 | 说明 |
| --- | --- |
| `--update-only` | 仅推送增量更新（Linux） |
| `--rollback <version>` | 回滚到指定版本（Linux） |

#### pyapp setup

安装/检查平台开发环境：

```bash
pyapp setup android    # 安装 JDK 17、Android SDK、预下载 Gradle
pyapp setup windows    # 检查 MinGW-w64（仅自定义编译 Stub 时需要）
pyapp setup linux      # 检查 python3/pip/tar/systemctl
```

`pyapp setup android` 会将 JDK 安装到 `~/.android-jdk`，SDK 安装到 `~/.android-sdk`，并在 `~/.gradle/pyapp-cache` 预下载 Gradle 发行版（规避 Java SSL 证书问题）。结束后会提示需要设置的环境变量：

```
JAVA_HOME = "~/.android-jdk"
ANDROID_HOME = "~/.android-sdk"
```

#### pyapp logs

```bash
pyapp logs                 # 查看最近 50 行日志
pyapp logs -n 100          # 查看指定行数
pyapp logs --clear         # 清空日志文件
```

## 平台支持

### Windows

- 使用 Embeddable Python 运行时
- 预编译 Stub + rcedit 修改 VERSIONINFO 和图标
- 自动下载 WebView2Loader.dll（UI 模式运行时依赖）
- 通过 `app.ini` 配置启动模式（ui/console/headless）、窗口、托盘等
- 输出 ZIP 包

**环境要求**：

- 无需编译器（使用预编译 Stub 模式）
- 如需自定义 Stub，可本地编译（见下方说明）

#### 本地编译 Windows Stub

Stub 源码位于 [stub-src/windows/app_stub.cpp](file:///d:/code/pyapp/stub-src/windows/app_stub.cpp)。如需修改并本地编译：

**前置条件**：MinGW-w64 (g++)

```powershell
cd stub-src/windows

g++ -o ..\..\pyapp\stubs\windows\pyapp-stub-x64.exe app_stub.cpp `
    -mwindows -O2 -s `
    -static-libgcc -static-libstdc++ `
    -lwinhttp -lole32 -loleaut32 -lshell32 -lws2_32
```

| 参数 | 说明 |
|------|------|
| `-mwindows` | 生成 Windows GUI 程序（无控制台窗口） |
| `-O2` | 优化级别 |
| `-s` | 剥离调试符号，减小体积 |
| `-static-libgcc -static-libstdc++` | 静态链接 GCC 运行时，避免依赖 DLL |
| `-lwinhttp -lole32 ...` | 链接 Windows API 库（源码中 `#pragma comment(lib)` 是 MSVC 专用，MinGW 需手动指定） |

编译产物直接输出到 `pyapp/stubs/windows/pyapp-stub-x64.exe`，无需额外拷贝。

### Linux

- 使用 Python Build Standalone (PBS) 运行时
- 生成 systemd 服务文件和 install.sh 安装脚本
- 输出 tar.gz 包
- 支持多种 CPU 架构（x86_64 / aarch64 / armv7l）

```bash
pyapp build linux                      # x86_64（默认）
pyapp build linux --arch aarch64       # ARM64
pyapp build linux --arch armv7l        # ARM32
```

### Android

- 使用 Chaquopy 打包 Python，Gradle 构建 APK
- 前端产物通过 WebView 加载，Python 跑在前台服务中
- 支持 JDK 17、Android SDK 34
- 支持多种 CPU 架构（ABI）

```bash
pyapp setup android                    # 安装开发环境
pyapp build android --arch arm64-v8a   # 构建指定架构
pyapp build android --arch arm64-v8a,armeabi-v7a  # 多架构 APK
```

## 配置说明

项目配置文件：`pyproject.toml`

### 基本配置

```toml
[project]
name = "my-app"
version = "0.1.0"
description = "My Python Application"
authors = [{name = "Your Name", email = "your.email@example.com"}]
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "httpx>=0.24.0",
]
```

### PyApp 通用配置

```toml
[tool.pyapp]
app_module = "my_app"        # Python 模块名（必需，未配置时自动检测 src/ 下唯一包）
port = 18080                 # 应用端口（默认：18080）
python_version = "3.10"      # Python 版本（默认：3.10，支持 X.Y 或 X.Y.Z）
```

> `python_version` 支持 3.8 ~ 3.12；Android 平台额外受 Chaquopy 支持版本约束（3.8 ~ 3.12）。

### Windows 平台配置

```toml
[tool.pyapp.windows]
deployment = "standalone"    # 部署模式：standalone（独立运行）/ shared（共享运行时）
create_service = true        # 是否创建系统服务
service_name = "MyApp"       # 服务名称
icon = "app_icon.ico"        # 应用图标路径（项目根目录下，可选）
```

### Linux 平台配置

```toml
[tool.pyapp.linux]
deployment = "shared"        # 部署模式：standalone / shared
install_systemd = true       # 是否安装 systemd 服务
service_name = "my-app"      # systemd 服务名（默认：app_name 将下划线转为连字符）
```

### Android 平台配置

```toml
[tool.pyapp.android]
# 基本配置
package_name = "com.example.myapp"  # Android 包名（必需）
min_sdk = 24                        # 最低 SDK 版本（默认：24）
target_sdk = 34                     # 目标 SDK 版本（默认：34）
icon = "icons/android/xplay"        # 自定义图标基础名（可选，Briefcase 命名约定）

# CPU 架构配置（命令行 --arch 优先于此配置）
abi_filters = ["arm64-v8a"]         # 默认 ["arm64-v8a"]
# 支持的架构：arm64-v8a / armeabi-v7a / x86_64

# 权限配置
permissions = ["INTERNET", "FOREGROUND_SERVICE"]  # Android 权限列表

# 平台特定依赖（可选，会覆盖全局 dependencies 的同名包）
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

# pip 配置（可选）
pip_index_url = ""                  # pip 主索引 URL
pip_extra_index_urls = [            # 额外索引 URL（默认含 Chaquopy 官方仓库与 PyPI）
    "https://chaquo.com/pypi-13.1",
    "https://pypi.org/simple",
]
pip_timeout = 120                   # pip 超时时间（秒，默认：120）
pip_proxy = ""                      # pip 代理地址
```

### 完整配置示例

```toml
[project]
name = "my-app"
version = "0.1.0"
description = "My Python Application"
authors = [{name = "Your Name", email = "your.email@example.com"}]
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

[tool.pyapp]
app_module = "my_app"
port = 18080
python_version = "3.10"

[tool.pyapp.windows]
deployment = "standalone"
create_service = true
service_name = "MyApp"
icon = "app_icon.ico"

[tool.pyapp.linux]
deployment = "shared"
install_systemd = true
service_name = "my-app"

[tool.pyapp.android]
package_name = "com.example.myapp"
min_sdk = 24
target_sdk = 34
abi_filters = ["arm64-v8a"]
permissions = ["INTERNET", "FOREGROUND_SERVICE"]

# 使用国内镜像加速依赖安装
pip_extra_index_urls = [
    "https://chaquo.com/pypi-13.1",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
]
pip_timeout = 180
```

## 项目结构

`pyapp init` 生成的项目结构：

```
my-app/
├── src/
│   └── my_app/                # Python 源码
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py             # FastAPI 应用（fastapi 模板）
│       └── resources/         # 静态资源
│           ├── config/
│           └── static/        # 前端构建产物同步到此
├── frontend/                  # 前端项目（fastapi 模板，可选）
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
├── .github/workflows/         # CI 脚本（自动生成）
├── bundles/                   # 构建输出（build 产物）
│   ├── windows/
│   ├── linux/
│   └── android/
├── dist/                      # 发布包（package 产物）
└── pyproject.toml             # 项目配置
```

## 输出目录结构

### Windows

`bundles/windows/` 结构：

```
windows/
├── my-app-0.1.0/
│   └── app/                   # 应用源码 + app_packages/（依赖）
├── runtime/                   # Embeddable Python 运行时
│   ├── python.exe
│   ├── my-app-runtime.exe     # 带 VERSIONINFO 的运行时（任务管理器显示应用名）
│   └── python310.dll
├── my-app.exe                 # 启动程序（预编译 Stub + rcedit 改图标/版本）
├── WebView2Loader.dll         # UI 模式运行时依赖（自动下载）
├── app.ini                    # 启动配置（ui/console/headless、窗口、端口等）
└── build.meta.json            # 构建元数据（arch、build_type，package 阶段读取）
```

打包产物：`dist/my-app-0.1.0-windows-x86_64.zip`

### Linux

`bundles/linux/` 结构：

```
linux/
├── my-app-0.1.0/
│   └── app/                   # 应用源码 + app_packages/
├── runtime/                   # PBS (Python Build Standalone) 运行时
├── run.sh                     # 启动脚本
├── install.sh                 # 安装脚本（拷贝到 /opt/<service_name>/ 并注册 systemd）
├── my-app.service             # systemd 服务单元（文件名为 service_name）
└── build.meta.json            # 构建元数据
```

打包产物：`dist/my-app-0.1.0-linux-<arch>.tar.gz`

### Android

`bundles/android/` 为标准 Gradle 项目结构：

```
android/
├── settings.gradle.kts
├── build.gradle.kts
├── gradle/wrapper/...
├── gradlew / gradlew.bat
├── local.properties           # 指向 ANDROID_HOME
└── app/
    ├── build.gradle.kts       # 含 Chaquopy pip 配置
    └── src/main/
        ├── AndroidManifest.xml
        ├── java/<package>/    # MainActivity.kt、PythonService.kt
        ├── python/            # Python 源码（Chaquopy 默认查找位置）
        │   └── my_app/
        └── res/               # 图标、strings、themes
```

打包产物：`dist/my-app-0.1.0-android-<abis>.apk`（如 `arm64_v8a.apk`）

## 开发指南

### 启用详细日志

```bash
pyapp -v build windows
pyapp -v --log-file /path/to.log run windows
```

### 验证工具

```bash
python verify.py
```

## 常见问题

### Q: Windows 构建后运行闪退？

检查以下几点：

1. 确认 `pyproject.toml` 中 `app_module` 配置正确
2. 使用 `pyapp -v build windows` 查看详细日志
3. 手动运行 `runtime\python.exe -m <app_module>` 测试

### Q: 依赖安装失败？

```bash
# 手动安装依赖到指定目录
pip install <package> --target bundles/windows/my-app-0.1.0/app_packages
```

跨架构构建（如在本机为 Linux ARM64/aarch64 安装依赖）会自动使用 `--only-binary=:all:` 与对应的 `--platform` 标识；ARM32 还会回退到 piwheels 源。

### Q: 如何更新 Stub 源码？

Stub 源码位于 `stub-src/windows/app_stub.cpp`。修改后本地编译：

```powershell
cd stub-src/windows
g++ -o ..\..\pyapp\stubs\windows\pyapp-stub-x64.exe app_stub.cpp -mwindows -O2 -s -static-libgcc -static-libstdc++ -lwinhttp -lole32 -loleaut32 -lshell32 -lws2_32
```

编译产物直接输出到内置 Stub 目录。

### Q: Android Gradle 构建因 SSL 证书失败？

先执行 `pyapp setup android`，它会用 Python 预下载 Gradle 发行版到 `~/.gradle/pyapp-cache`，构建时会自动改用本地缓存，规避 JDK SSL 证书问题。

## License

MIT
