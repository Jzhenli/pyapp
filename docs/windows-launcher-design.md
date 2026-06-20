# Windows 启动器双模式方案设计

> 版本: v1.0 | 日期: 2026-06-17

## 1. 概述

### 1.1 目标

将 Windows 平台启动器从当前的**父子进程方案**升级为**Python 嵌入式方案**，并支持两种运行模式：

| 模式 | 入口 | 窗口 | 用途 |
|------|------|------|------|
| UI 模式 | WebView2 | 原生窗口 + WebView2 | 普通用户，桌面应用体验 |
| 控制台模式 | 控制台 | 终端窗口 | 开发调试、服务部署 |

### 1.2 核心变更

| 项目 | 当前方案 | 新方案 |
|------|----------|--------|
| 进程架构 | 父子进程 (app.exe + python.exe) | 单进程 (嵌入式 Python) |
| 任务管理器 | 显示 2 个进程 | 显示 1 个进程 |
| Python 启动 | CreateProcess python.exe | Py_Initialize() 嵌入 |
| UI 支持 | 无 | WebView2 |
| 模式切换 | 无 | 配置文件 + 命令行参数 |

---

## 2. 架构设计

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│  app.exe (单进程)                                            │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 1. 解析配置 (app.ini + 命令行参数)                       │ │
│  │ 2. 单实例检查 (Mutex)                                    │ │
│  │ 3. 初始化 Python (Py_Initialize)                        │ │
│  │ 4. 启动 FastAPI 服务 (子线程)                            │ │
│  │ 5. 根据模式进入主循环:                                   │ │
│  │    ├─ UI 模式: WebView2 窗口消息循环                     │ │
│  │    └─ 控制台模式: 等待 Python 主线程结束                  │ │
│  │ 6. 清理 (Py_Finalize)                                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 模式切换流程

```
app.exe 启动
    │
    ├─ 读取 app.ini → launch.mode
    │
    ├─ 解析命令行参数 → 覆盖 mode
    │   ├─ --console  → console
    │   ├─ --headless → headless
    │   └─ --ui       → ui (默认)
    │
    └─ 按 mode 执行
        ├─ ui:      WebView2 窗口 + Python 服务
        ├─ console: 控制台窗口 + Python 服务
        └─ headless: 无窗口 + Python 服务
```

### 2.3 UI 模式详细流程

```
app.exe --ui (或默认)
    │
    ├─ 1. Py_Initialize()
    ├─ 2. 在子线程中启动 FastAPI (PyGILState_Ensure/Release)
    ├─ 3. 轮询 http://localhost:{port}/health (等待服务就绪)
    ├─ 4. 创建主窗口 (CreateWindow)
    ├─ 5. 创建 WebView2 控件
    ├─ 6. 导航到 http://localhost:{port}{start_path}
    ├─ 7. 消息循环 (GetMessage/DispatchMessage)
    ├─ 8. 窗口关闭时:
    │      ├─ 通知 Python 服务停止
    │      ├─ Py_Finalize()
    │      └─ 退出
    └─ 9. 系统托盘 (可选):
           ├─ 最小化到托盘
           ├─ 右键菜单: 显示窗口 / 退出
           └─ 关闭窗口 = 最小化到托盘
```

### 2.4 控制台模式详细流程

```
app.exe --console
    │
    ├─ 1. AttachConsole / AllocConsole (确保有控制台)
    ├─ 2. Py_Initialize()
    ├─ 3. 运行 Python 应用 (主线程, 阻塞)
    │      PyRun_SimpleString("import myapp; myapp.main()")
    ├─ 4. Py_Finalize()
    └─ 5. 退出
```

---

## 3. 配置设计

### 3.1 配置文件 (app.ini)

位置: exe 同目录 / `app.ini`

```ini
[launch]
# 启动模式: ui / console / headless
mode = ui

[ui]
# 窗口标题
title = {{ app_name }}
# 窗口宽度
width = 1280
# 窗口高度
height = 800
# 是否允许调整大小
resizable = true
# 启动时 URL 路径
start_path = /
# 关闭按钮行为: exit (退出) / minimize (最小化到托盘)
close_action = minimize
# 是否显示系统托盘图标
show_tray = true

[console]
# 是否在退出前暂停 (按任意键继续)
pause_on_exit = true
```

### 3.2 命令行参数

```
app.exe [选项]

选项:
  --ui          UI 模式 (WebView2 窗口，默认)
  --console     控制台模式 (终端窗口)
  --headless    后台模式 (无窗口)
  --port=PORT   指定服务端口 (覆盖配置)
  --help        显示帮助信息
```

### 3.3 优先级

```
命令行参数 > app.ini > 内置默认值
```

### 3.4 pyproject.toml 扩展

```toml
[tool.pyapp.windows]
deployment = "standalone"
# 默认启动模式
launch_mode = "ui"
# WebView2 窗口配置
ui_width = 1280
ui_height = 800
ui_resizable = true
ui_start_path = "/"
ui_close_action = "minimize"
ui_show_tray = true
```

---

## 4. 编译方案

### 4.1 PBS 编译 + EBD 打包

```
编译时: PBS (python-build-standalone) → 提供 include/ + libs/
运行时: EBD (Embeddable Distribution)  → 打包分发 (~8MB)
```

两者均由 MSVC 编译，`python3xx.dll` ABI 兼容。

### 4.2 编译依赖

| 依赖 | 用途 | 来源 |
|------|------|------|
| PBS install_only | Python.h + python3xx.lib | GitHub astral-sh |
| WebView2 SDK | WebView2 头文件 + 导入库 | NuGet / GitHub |
| MinGW-w64 / MSVC | C 编译器 | 本地安装 |

### 4.3 编译命令

```bash
# 方案 A: MinGW gcc (需生成 .def + .a 导入库)
# 1. 从 PBS 的 python311.dll 生成导入库
dlltool --dllname python311.dll --def python311.def --output-lib libpython311.a

# 2. 编译
gcc -o app.exe app_stub.c ^
    -I"{pbs_dir}/include" ^
    -L"{pbs_dir}/libs" -lpython311 ^
    -mwindows -O2 -s

# 方案 B: MSVC cl (推荐，与 Python 构建工具链一致)
cl app_stub.c /I"{pbs_dir}/include" ^
   /link python311.lib /OUT:app.exe /SUBSYSTEM:WINDOWS
```

### 4.4 WebView2 链接

WebView2 使用 COM 接口，**无需额外链接库**。Windows 10/11 已预装 WebView2 Runtime。

```c
// 头文件方式: 使用 WebView2 API 声明
// 不需要链接 WebView2.lib，通过 CoCreateInstance 动态加载
#include "WebView2.h"
```

---

## 5. 目录结构

### 5.1 模板文件

```
pyapp/templates/shells/windows/
├── app_stub.c.j2          # 主启动器 (嵌入式 Python + 双模式)
├── app_stub.rc.j2         # 资源文件 (不变)
├── build.bat.j2           # 编译脚本 (更新)
├── app.ini.j2             # 默认配置模板 (新增)
└── WebView2.h              # WebView2 API 声明 (新增, 单头文件)
```

### 5.2 最终分发结构

```
dist/myapp-0.1.0-windows-x86_64/
├── myapp.exe               # 嵌入式启动器 (单进程)
├── app.ini                 # 启动配置
├── runtime/                # EBD 运行时
│   ├── python311.dll       # Python DLL
│   ├── python311.zip       # 标准库
│   └── python311._pth      # 模块搜索路径
├── myapp-0.1.0/
│   ├── app/                # 应用代码
│   │   └── myapp/
│   │       ├── __init__.py
│   │       ├── __main__.py
│   │       └── app.py
│   └── app_packages/       # 第三方依赖
└── (无 python.exe)         # 不再需要
```

---

## 6. 核心代码设计

### 6.1 app_stub.c.j2 结构

```c
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <Python.h>

/* ========== 配置结构体 ========== */
typedef struct {
    char mode[16];         // ui, console, headless
    char title[64];
    int  width;
    int  height;
    int  resizable;
    char start_path[256];
    char close_action[16]; // exit, minimize
    int  show_tray;
    int  pause_on_exit;
    int  port;
} AppConfig;

/* ========== 配置解析 ========== */
static void config_set_defaults(AppConfig *cfg);
static void config_parse_ini(const char *exe_dir, AppConfig *cfg);
static void config_parse_args(LPSTR lpCmdLine, AppConfig *cfg);

/* ========== Python 嵌入 ========== */
static int  python_init(const char *exe_dir, const char *version_dir);
static int  python_start_server(int port);
static void python_finalize(void);

/* ========== UI 模式 ========== */
static int  run_ui_mode(HINSTANCE hInstance, AppConfig *cfg);
static LRESULT CALLBACK WndProc(HWND, UINT, WPARAM, LPARAM);
static void create_webview(HWND hwnd, AppConfig *cfg);
static void create_tray_icon(HWND hwnd, AppConfig *cfg);

/* ========== 控制台模式 ========== */
static int run_console_mode(AppConfig *cfg);

/* ========== 后台模式 ========== */
static int run_headless_mode(AppConfig *cfg);

/* ========== 主入口 ========== */
int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance,
                   LPSTR lpCmdLine, int nCmdShow) {
    AppConfig cfg;
    char exe_dir[MAX_PATH], version_dir[MAX_PATH];

    // 1. 获取路径
    get_exe_dir(exe_dir);
    get_version_dir(exe_dir, version_dir);

    // 2. 单实例检查
    if (!check_single_instance("{{ app_name }}-SingleInstance"))
        return 0;

    // 3. 解析配置
    config_set_defaults(&cfg);
    config_parse_ini(exe_dir, &cfg);
    config_parse_args(lpCmdLine, &cfg);

    // 4. 初始化 Python
    if (!python_init(exe_dir, version_dir))
        return 1;

    // 5. 按模式运行
    int result;
    if (strcmp(cfg.mode, "console") == 0) {
        result = run_console_mode(&cfg);
    } else if (strcmp(cfg.mode, "headless") == 0) {
        result = run_headless_mode(&cfg);
    } else {
        result = run_ui_mode(hInstance, &cfg);
    }

    // 6. 清理
    python_finalize();
    return result;
}
```

### 6.2 Python 嵌入核心

```c
static int python_init(const char *exe_dir, const char *version_dir) {
    // 构建 Python 路径
    wchar_t python_home[MAX_PATH];
    wchar_t python_path[MAX_PATH * 4];

    swprintf(python_home, MAX_PATH, L"%hs\\runtime", exe_dir);
    swprintf(python_path, MAX_PATH * 4,
        L"%hs\\runtime\\python{{ ver_tag }}.zip;"
        L"%hs\\runtime;"
        L"%hs\\%hs\\app;"
        L"%hs\\%hs\\app_packages",
        exe_dir, exe_dir, exe_dir, version_dir, exe_dir, version_dir);

    Py_SetPythonHome(python_home);
    Py_SetPath(python_path);

    // 设置环境变量
    SetEnvironmentVariableA("APP_MODE", "production");

    return Py_Initialize() == 0;
}

static int python_start_server(int port) {
    // 在子线程中启动 FastAPI
    // 使用 PyGILState_Ensure/Release 管理 GIL
    PyObject *main_module = PyImport_ImportModule("{{ app_module }}");
    if (!main_module) {
        PyErr_Print();
        return -1;
    }

    PyObject *start_func = PyObject_GetAttrString(main_module, "main");
    if (!start_func) {
        Py_DECREF(main_module);
        return -1;
    }

    PyObject *result = PyObject_CallObject(start_func, NULL);
    Py_DECREF(start_func);
    Py_DECREF(main_module);

    if (!result) {
        PyErr_Print();
        return -1;
    }
    Py_DECREF(result);
    return 0;
}
```

### 6.3 UI 模式核心

```c
static int run_ui_mode(HINSTANCE hInstance, AppConfig *cfg) {
    // 1. 注册窗口类
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInstance;
    wc.hIcon = LoadIcon(hInstance, MAKEINTRESOURCE(1));
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.lpszClassName = "{{ app_name }}WndClass";
    RegisterClassA(&wc);

    // 2. 创建主窗口
    HWND hwnd = CreateWindowA(
        wc.lpszClassName, cfg->title,
        WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT, CW_USEDEFAULT,
        cfg->width, cfg->height,
        NULL, NULL, hInstance, NULL);

    // 3. 启动 Python 服务 (子线程)
    HANDLE hThread = CreateThread(NULL, 0,
        (LPTHREAD_START_ROUTINE)python_server_thread,
        cfg, 0, NULL);

    // 4. 等待服务就绪
    wait_for_server(cfg->port);

    // 5. 创建 WebView2
    create_webview(hwnd, cfg);

    // 6. 显示窗口
    ShowWindow(hwnd, SW_SHOW);

    // 7. 托盘图标
    if (cfg->show_tray)
        create_tray_icon(hwnd, cfg);

    // 8. 消息循环
    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    // 9. 等待 Python 线程结束
    WaitForSingleObject(hThread, 5000);
    CloseHandle(hThread);

    return (int)msg.wParam;
}
```

### 6.4 控制台模式核心

```c
static int run_console_mode(AppConfig *cfg) {
    // 控制台模式: 直接在主线程运行 Python
    int ret = python_start_server(cfg->port);

    if (cfg->pause_on_exit) {
        printf("\nPress Enter to exit...");
        getchar();
    }
    return ret;
}
```

---

## 7. Python 应用侧适配

### 7.1 应用入口修改

当前 `__main__.py` 需要支持嵌入式调用：

```python
# myapp/__main__.py
import sys
import uvicorn
from .app import app

def main():
    """嵌入式入口 (由 C 启动器调用)"""
    port = int(os.environ.get("APP_PORT", "18080"))
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
```

### 7.2 健康检查端点

FastAPI 应用需提供健康检查端点，供启动器轮询：

```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## 8. 构建流程变更

### 8.1 当前流程 (6 步)

```
Step 1: 下载 EBD 运行时
Step 2: 同步 Python 源码
Step 3: 同步前端资源
Step 4: 安装依赖
Step 5: 编译 Stub (gcc -mwindows)
Step 6: 打包 ZIP
```

### 8.2 新流程 (7 步)

```
Step 1: 下载 EBD 运行时 (运行时打包)
Step 2: 下载 PBS 运行时 (编译依赖, 可缓存) ← 新增
Step 3: 同步 Python 源码
Step 4: 同步前端资源
Step 5: 安装依赖
Step 6: 编译 Stub (gcc/cl + Python 头文件 + WebView2) ← 变更
Step 7: 打包 ZIP (排除 PBS, 只包含 EBD)
```

### 8.3 runtime.py 变更

新增 PBS Windows 下载源：

```python
RUNTIME_SOURCES = {
    # EBD: 运行时分发
    "windows": RuntimeSource(
        url_template="https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
    ),
    # PBS: 编译时依赖
    "windows-dev": RuntimeSource(
        url_template=(
            "https://github.com/astral-sh/python-build-standalone/releases/download/"
            "{build}/cpython-{version}+{build}-x86_64-pc-windows-msvc-install_only.tar.gz"
        ),
        strip_components=1,
    ),
}

PYTHON_VERSIONS = {
    "3.10": {
        "windows": "3.10.11",
        "windows-dev": ("3.10.20", "20260610"),  # 新增
        "linux": ("3.10.20", "20260610"),
    },
    # ...
}
```

### 8.4 windows.py 变更

```python
def _compile_stub(self, bundle_dir, app_name, python_version):
    # 1. 获取 PBS 开发运行时 (缓存)
    dev_dir = self._get_dev_runtime(python_version)

    # 2. 提取版本标签
    ver_tag = python_version.replace(".", "")[:2] + \
              python_version.split(".")[1]  # "311"

    # 3. 编译
    cmd = [
        "gcc", "-o", str(exe_path), str(stub_c),
        f"-I{dev_dir}/include",
        f"-L{dev_dir}/libs", f"-lpython{ver_tag}",
        "-mwindows", "-O2", "-s",
    ]
```

---

## 9. 回退方案

### 9.1 编译失败回退

当嵌入式 Stub 编译失败时，回退到当前方案：

| 情况 | 回退方案 |
|------|----------|
| gcc 不可用 | 生成 .bat 启动脚本 |
| PBS 下载失败 | 使用系统 Python 编译 |
| WebView2 不可用 | 降级为控制台模式 |

### 9.2 WebView2 不可用回退

```c
// UI 模式启动时检查 WebView2
if (FAILED(CreateCoreWebView2EnvironmentWithOptions(...))) {
    MessageBoxA(NULL,
        "WebView2 Runtime is not available.\n"
        "Switching to console mode.",
        "{{ app_name }}", MB_ICONWARNING);
    strcpy(cfg.mode, "console");
    return run_console_mode(cfg);
}
```

---

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| MinGW 链接 MSVC python3xx.lib 不兼容 | 编译失败 | 方案 A: 生成 .def/.a 导入库; 方案 B: 改用 MSVC 编译 |
| PBS 与 EBD 版本不完全一致 | 运行时崩溃 | 确保主版本号一致 (3.11.x)，定期同步版本映射 |
| WebView2 在旧 Windows 不可用 | UI 模式无法使用 | 自动降级为控制台模式 |
| Python GIL 与 UI 线程冲突 | 死锁 | Python 服务运行在子线程，UI 线程不调用 Python API |
| 嵌入式方案调试困难 | 开发效率低 | 保留控制台模式用于调试 |

---

## 11. 实施计划

### Phase 1: 嵌入式基础 (控制台模式)

- [ ] 修改 `app_stub.c.j2`: CreateProcess → Py_Initialize
- [ ] 修改 `runtime.py`: 新增 PBS windows-dev 源
- [ ] 修改 `windows.py`: 编译流程适配
- [ ] 修改 `build.bat.j2`: 编译参数更新
- [ ] 新增 `app.ini.j2`: 配置模板
- [ ] 测试: 控制台模式单进程运行

### Phase 2: 双模式支持

- [ ] 实现配置解析 (INI + 命令行参数)
- [ ] 实现控制台模式入口
- [ ] 实现后台模式入口
- [ ] 测试: 三种模式切换

### Phase 3: WebView2 UI 模式

- [ ] 集成 WebView2 SDK
- [ ] 实现主窗口 + WebView2 控件
- [ ] 实现服务就绪等待 (health check 轮询)
- [ ] 实现系统托盘
- [ ] 测试: UI 模式完整流程

### Phase 4: 打包与发布

- [ ] 更新 ZIP 打包逻辑 (排除 PBS, 包含 EBD)
- [ ] 更新 pyproject.toml 配置项
- [ ] 端到端测试
- [ ] 文档更新

---

## 12. 附录

### A. PBS 版本选择

| Python 版本 | EBD 版本 | PBS 版本 | PBS Build Tag |
|-------------|----------|----------|---------------|
| 3.10 | 3.10.11 | 3.10.20 | 20260610 |
| 3.11 | 3.11.9 | 3.11.15 | 20260610 |
| 3.12 | 3.12.10 | 3.12.13 | 20260610 |

PBS Windows 文件名格式 (注意: 无 `-shared` 后缀):

```
cpython-{version}+{build}-x86_64-pc-windows-msvc-install_only.tar.gz
```

示例:
```
cpython-3.11.15+20260610-x86_64-pc-windows-msvc-install_only.tar.gz
```

PBS install_only 包含编译所需的头文件和导入库:
```
python/
├── include/              # Python.h 等头文件
├── libs/                 # python311.lib 导入库
├── python.exe
├── python311.dll
├── python311.zip
└── ...
```

### B. WebView2 最低系统要求

| 要求 | 版本 |
|------|------|
| Windows | 10 (1803+) |
| WebView2 Runtime | 已预装于 Windows 11, Windows 10 需自动安装 |

### C. 编译器选择建议

| 编译器 | 优点 | 缺点 | 推荐度 |
|--------|------|------|--------|
| MinGW gcc | 当前已使用, 无需额外安装 | 链接 MSVC .lib 可能有问题 | 中 |
| MSVC cl | 与 Python 构建一致, ABI 兼容 | 需安装 Visual Studio | 高 |
| Clang-cl | 兼容 MSVC, 跨平台 | 需额外安装 | 中 |

### D. 与 Briefcase 方案对比

| 特性 | Briefcase | 本方案 |
|------|-----------|--------|
| 进程架构 | 嵌入式 (单进程) | 嵌入式 (单进程) |
| UI 框架 | Toga (自研) | WebView2 (系统原生) |
| 编译工具 | Visual Studio | MinGW / MSVC |
| 配置方式 | pyproject.toml | app.ini + 命令行参数 |
| 模式切换 | 不支持 | 支持 (ui/console/headless) |
| 运行时来源 | 完整 Python 安装 | EBD (更小体积) |
