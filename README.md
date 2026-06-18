# PyApp CLI

跨平台 Python 应用打包工具，支持将 Python 应用打包为 Windows、Linux、Android 平台的可执行程序。

## 安装

```bash
pip install -e .
```

## 快速开始

```bash
# 1. 创建新项目
pyapp init my-app

# 2. 进入项目目录
cd my-app

# 3. 构建应用
pyapp build windows

# 4. 运行应用
pyapp run windows
```

## 命令列表

| 命令                         | 说明        |
| -------------------------- | --------- |
| `pyapp init <name>`        | 创建新项目     |
| `pyapp create <platform>`  | 创建平台项目结构  |
| `pyapp build <platform>`   | 构建应用      |
| `pyapp run <platform>`     | 运行应用      |
| `pyapp dev <platform>`     | 开发模式（热重载） |
| `pyapp package <platform>` | 打包发布版     |
| `pyapp deploy <platform>`  | 部署到设备     |
| `pyapp setup <platform>`   | 安装平台依赖    |
| `pyapp logs`               | 查看日志      |

### 命令详解

#### pyapp init

创建新项目，支持两种模板：

```bash
# FastAPI 模板（默认）
pyapp init my-app

# 基础模板
pyapp init my-app --template basic

# 指定输出目录
pyapp init my-app -o /path/to/project
```

#### pyapp build

构建应用：

```bash
# 构建 Windows 版
pyapp build windows

# 构建 Linux 版
pyapp build linux

# 构建 Android 版
pyapp build android

# 指定项目目录
pyapp build windows -d /path/to/project

# Android 平台指定 CPU 架构（支持多架构）
pyapp build android --arch arm64-v8a
pyapp build android --arch arm64-v8a --arch armeabi-v7a
pyapp build android --arch x86_64  # 模拟器
```

#### pyapp dev

开发模式，支持文件监听和热重载：

```bash
pyapp dev windows
```

#### pyapp run

运行已构建的应用：

```bash
pyapp run windows
```

## 平台支持

### Windows

- 使用 Embeddable Python 运行时
- 编译为原生 exe（需要 MinGW-w64）
- 输出 ZIP 包

**环境要求**：

- MinGW-w64（可选，用于编译 exe）

```bash
# 安装 MinGW-w64
pyapp setup windows
```

### Linux

- 使用 Python Build Standalone (PBS) 运行时
- 生成 systemd 服务文件
- 输出 tar.gz 包

### Android

- 使用 Chaquopy 打包 Python
- 需要 JDK 和 Android SDK
- 支持多种 CPU 架构

**支持的 CPU 架构（ABI）**：

- `arm64-v8a`：现代 64 位 ARM 设备（推荐）
- `armeabi-v7a`：旧款 32 位 ARM 设备
- `x86_64`：Android 模拟器

```bash
# 安装 Android 开发环境
pyapp setup android

# 构建指定架构
pyapp build android --arch arm64-v8a

# 构建多架构 APK（增大包体积但兼容性更好）
pyapp build android --arch arm64-v8a --arch armeabi-v7a
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
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "black>=23.0.0",
]
```

### PyApp 配置

```toml
[tool.pyapp]
# 通用配置
app_module = "my_app"        # Python 模块名（必需）
port = 18080                 # 应用端口（默认：18080）
python_version = "3.10.11"   # Python 版本（默认：3.12.1）
```

### Windows 平台配置

```toml
[tool.pyapp.windows]
# Windows 特定配置（可选）
# 目前支持基本的构建配置
```

### Linux 平台配置

```toml
[tool.pyapp.linux]
service_name = "my-app"      # systemd 服务名
service_description = "My Python Application Service"  # 服务描述
```

### Android 平台配置

```toml
[tool.pyapp.android]
# 基本配置
package_name = "com.example.myapp"  # Android 包名（必需）
min_sdk = 21                        # 最低 SDK 版本（默认：24）
target_sdk = 34                     # 目标 SDK 版本（默认：34）

# CPU 架构配置
abi_filters = ["arm64-v8a"]         # CPU 架构列表
# 支持的架构：
# - arm64-v8a: 现代 64 位 ARM 设备（推荐）
# - armeabi-v7a: 旧款 32 位 ARM 设备
# - x86_64: Android 模拟器

# 权限配置
permissions = ["INTERNET"]          # Android 权限列表
# 常用权限：
# - INTERNET: 网络访问
# - CAMERA: 相机
# - READ_EXTERNAL_STORAGE: 读取外部存储
# - WRITE_EXTERNAL_STORAGE: 写入外部存储

# 平台特定依赖（可选，会覆盖全局 dependencies）
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

# pip 配置（可选）
pip_index_url = ""                  # pip 主索引 URL
pip_extra_index_urls = [            # 额外索引 URL
    "https://chaquo.com/pypi-13.1", # Chaquopy 官方仓库
    "https://pypi.org/simple",      # PyPI 官方仓库
]
pip_timeout = 120                    # pip 超时时间（秒，默认：120）
pip_proxy = ""                      # pip 代理地址
```

### 完整配置示例

```toml
[project]
name = "my-app"
version = "0.1.0"
description = "My Python Application"
authors = [{name = "Your Name", email = "your.email@example.com"}]
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

[tool.pyapp]
app_module = "my_app"
port = 18080
python_version = "3.10.11"

[tool.pyapp.windows]
# Windows 特定配置

[tool.pyapp.linux]
service_name = "my-app"
service_description = "My Python Application Service"

[tool.pyapp.android]
package_name = "com.example.myapp"
min_sdk = 24
target_sdk = 34
abi_filters = ["arm64-v8a"]
permissions = ["INTERNET", "CAMERA"]

# 使用国内镜像加速依赖安装
pip_extra_index_urls = [
    "https://chaquo.com/pypi-13.1",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
]
pip_timeout = 180
```

## 项目结构

```
my-app/
├── src/
│   └── my_app/           # Python 源码
│       ├── __init__.py
│       ├── __main__.py
│       └── app.py
├── frontend/             # 前端项目（可选）
│   ├── package.json
│   └── dist/
├── bundles/              # 构建输出
│   ├── windows/
│   ├── linux/
│   └── android/
├── dist/                 # 发布包
└── pyproject.toml        # 项目配置
```

## 输出目录结构

### Windows

```
my-app-0.1.0-windows-x86_64/
├── my-app-0.1.0/
│   ├── app/              # Python 源码
│   │   └── my_app/
│   └── app_packages/     # 依赖包
├── runtime/              # Python 运行时
│   ├── python.exe
│   └── python310.dll
└── my-app.exe            # 启动程序
```

### Linux

```
my-app-0.1.0-linux-x86_64/
├── my-app-0.1.0/
│   ├── app/
│   └── app_packages/
├── runtime/
├── run.sh                # 启动脚本
├── install.sh            # 安装脚本
└── my-app.service        # systemd 服务
```

## 开发指南

### 启用详细日志

```bash
pyapp -v build windows
```

### 查看日志

```bash
# 查看最近日志
pyapp logs

# 查看指定行数
pyapp logs -n 100

# 清空日志
pyapp logs --clear
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

### Q: 如何更新 Stub 源码？

Stub 源码位于 `pyapp/templates/shells/windows/app_stub.c.j2`，修改后重新构建即可。

## License

MIT
