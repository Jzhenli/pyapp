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

| 命令 | 说明 |
|------|------|
| `pyapp init <name>` | 创建新项目 |
| `pyapp create <platform>` | 创建平台项目结构 |
| `pyapp build <platform>` | 构建应用 |
| `pyapp run <platform>` | 运行应用 |
| `pyapp dev <platform>` | 开发模式（热重载） |
| `pyapp package <platform>` | 打包发布版 |
| `pyapp deploy <platform>` | 部署到设备 |
| `pyapp setup <platform>` | 安装平台依赖 |
| `pyapp logs` | 查看日志 |

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

```bash
# 安装 Android 开发环境
pyapp setup android
```

## 配置说明

项目配置文件：`pyproject.toml`

```toml
[project]
name = "my-app"
version = "0.1.0"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.0",
]

[tool.pyapp]
app_module = "my_app"        # Python 模块名
port = 18080                 # 应用端口
python_version = "3.10.11"   # Python 版本

[tool.pyapp.windows]
# Windows 特定配置

[tool.pyapp.linux]
service_name = "my-app"      # systemd 服务名

[tool.pyapp.android]
package_name = "com.example.myapp"  # Android 包名
min_sdk = 21                        # 最低 SDK 版本
target_sdk = 34                     # 目标 SDK 版本
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
