# 基于 Python 运行时的跨平台应用打包方案 (Specification v2.0)

## 一、目标

将 Python 应用打包为跨平台可分发产物，一次构建，三平台部署：

```
Linux    →  data-collector-1.2.0-linux-x86_64.tar.gz  →  解压即用
Windows  →  data-collector-1.2.0-windows-x86_64.zip    →  解压即用
Android  →  data-collector-1.2.0.apk                   →  安装即用
```

用户无需安装 Python，无需配置环境，应用内包含一切。

**v2.0 核心改进**：统一单应用 (standalone) 与多应用 (shared) 两种部署模式，按平台设定默认行为，保持机制统一、形态灵活。

***

## 二、核心设计原则

**原则 1：应用自包含**

应用 = Python 运行时 + 业务代码 + 依赖库 + 启动器，安装后零依赖，开箱即用。

**原则 2：运行时与应用代码分离**

- Python 运行时 (解释器+标准库) 很少变化 → 可共享，多应用复用，长期稳定
- 应用代码 (app+pip依赖) 经常变化 → 独立版本目录，支持热更新

**原则 3：100% 代码复用**

Python 业务代码 + 前端文件在三个平台完全相同，零 `#ifdef`。平台差异仅存在于启动器 (Shell) 层。

**原则 4：统一生命周期**

启动 → 就绪 → 服务 → 关闭，三平台协议一致。

**原则 5：VERSION 文件驱动版本切换**

通过根目录 VERSION 文件指定当前版本号，启动器读取后定位 `app-{ver}` 目录。
避免 symlink/Junction 的权限问题和 Windows 文件锁问题，实现运行中升级。

**原则 6：部署模式按平台默认，环境变量可覆盖**

- Windows / Android 默认 standalone（运行时在应用目录内）
- Linux 默认 shared（运行时在共享目录，多应用共用）
- 通过 `RUNTIME_DIR` 环境变量可覆盖默认行为

***

## 三、部署模式

### 3.1 两种部署模式

| 维度 | Standalone (单应用) | Shared (多应用共享) |
|------|:------------------:|:------------------:|
| 运行时位置 | `{app_dir}/runtime/` | 共享目录 (`/opt/runtime/` 或 `C:\Apps\runtime\`) |
| 运行时归属 | 应用私有 | 多应用共用 |
| 升级 Python | 只影响本应用 | 影响所有应用 |
| 磁盘占用 | 每应用含一份 runtime | runtime 仅一份 |
| 适用场景 | 单应用部署、移动端 | 工控机多应用部署 |

### 3.2 平台默认模式

| 平台 | 默认模式 | 理由 |
|------|---------|------|
| Windows | **standalone** | 单应用场景为主，自包含更简单可靠 |
| Android | **standalone** | 沙箱隔离，天然无法跨应用共享 |
| Linux | **shared** | 工控机多应用，节省空间和带宽 |

### 3.3 运行时解析策略

启动器统一使用两级回退定位 Python 运行时：

```
① 环境变量 RUNTIME_DIR (运维显式指定，最高优先)
② 平台默认路径
   Windows: {exe所在目录}/runtime/
   Linux:   /opt/runtime/
   Android: Chaquopy 内置 (无需发现)
③ 未找到 → 报错退出
```

> **为什么不用三级回退（本地→共享→报错）？**
> 按平台固定默认路径比"万能回退"更清晰。Windows standalone 模式下 `runtime/` 就在应用目录内，不存在"找不到共享目录再回退本地"的场景。如果运维需要切换模式，通过 `RUNTIME_DIR` 环境变量显式指定即可，避免隐式行为带来的不可预测性。

***

## 四、应用包结构

### 4.1 Windows 应用包 (Standalone)

```
data-collector-1.2.0-windows-x86_64.zip
└── data-collector-1.2.0\
    ├── install.bat                     ← 安装脚本
    ├── uninstall.bat                   ← 卸载脚本
    │
    ├── runtime\                        ← Python 运行时 (Embeddable Package)
    │   ├── python.exe
    │   ├── python3.dll                 ← 版本无关入口 (Stub Exe 加载此文件)
    │   ├── python312.dll               ← 实际 Python 实现
    │   ├── python312.zip               ← 标准库 (压缩字节码)
    │   ├── python312._pth              ← Stub 启动时动态重写
    │   ├── vcruntime140.dll
    │   ├── vcruntime140_1.dll
    │   └── VERSION                     ← Python 版本号，如 3.12.1
    │
    ├── app\                            ← 应用代码 (可热更新)
    │   ├── VERSION                     ← 版本号 1.2.0
    │   ├── data_collector\
    │   │   ├── __init__.py
    │   │   ├── __main__.py             ← 入口: python -m data_collector
    │   │   ├── app.py                  ← FastAPI 应用
    │   │   └── core.py                 ← 业务逻辑
    │   ├── app_packages\               ← pip 依赖
    │   │   ├── fastapi\
    │   │   ├── uvicorn\
    │   │   └── ...
    │   └── static\                     ← 前端文件
    │       ├── index.html
    │       └── app.js
    │
    └── data_collector.exe              ← Embed Stub 启动器 (~50 KB, 永不更新)
```

安装后布局 (Standalone)：

```
C:\Apps\data-collector\                 ← 或任意用户指定目录
├── runtime\                            ← 应用自带 Python 运行时
│   ├── python3.dll
│   ├── python312.dll
│   ├── python312.zip
│   ├── python312._pth
│   ├── python.exe
│   ├── vcruntime140.dll
│   ├── vcruntime140_1.dll
│   └── VERSION                         ← "3.12.1"
│
├── data_collector.exe                  ← Stub 代理入口 (永不更新)
├── VERSION                             ← 当前版本号 "1.2.0"
├── app-1.1.0\                          ← 旧版本
│   ├── VERSION
│   ├── app\...
│   └── app_packages\...
└── app-1.2.0\                          ← 当前版本
    ├── VERSION
    ├── app\...
    └── app_packages\...
```

### 4.2 Linux 应用包 (Shared)

```
data-collector-1.2.0-linux-x86_64.tar.gz
└── data-collector-1.2.0/
    ├── install.sh                      ← 安装脚本
    ├── uninstall.sh                    ← 卸载脚本
    │
    ├── runtime/                        ← Python 运行时 (PBS, 仅首次安装时使用)
    │   ├── bin/python3
    │   ├── lib/
    │   │   ├── python3.12/             ← 标准库
    │   │   └── libpython3.12.so        ← 共享库
    │   ├── share/
    │   └── VERSION                     ← Python 版本号，如 3.12.1
    │
    └── app/                            ← 应用代码 (可热更新)
        ├── VERSION                     ← 版本号 1.2.0
        ├── data_collector/
        │   ├── __init__.py
        │   ├── __main__.py
        │   ├── app.py
        │   └── core.py
        ├── app_packages/               ← pip 依赖
        │   ├── fastapi/
        │   ├── uvicorn/
        │   └── ...
        └── static/
            ├── index.html
            └── app.js
```

安装后布局 (Shared)：

```
/opt/
├── runtime/                            ← 共享 Python 运行时 (多应用共用)
│   ├── bin/python3
│   ├── lib/python3.12/
│   └── VERSION                         ← "3.12.1"
│
├── data-collector/                     ← 应用目录
│   ├── run.sh                          ← 启动入口 (永不更新)
│   ├── VERSION                         ← 当前版本号 "1.2.0"
│   ├── app-1.1.0/                      ← 旧版本 (旧进程退出后可删)
│   │   ├── VERSION
│   │   ├── app/
│   │   │   └── data_collector/
│   │   └── app_packages/
│   └── app-1.2.0/                      ← 当前版本
│       ├── VERSION
│       ├── app/
│       │   └── data_collector/
│       └── app_packages/
│
├── device-monitor/                     ← 应用2 (示例: 多应用共享 runtime)
│   ├── device_monitor.sh
│   ├── VERSION
│   └── app-2.0.1/...
│
└── versions                            ← 全局版本快照文件
```

### 4.3 Android 应用包 (Standalone)

```
data-collector-1.2.0.apk
└── (APK 内部)
    ├── lib/arm64-v8a/
    │   ├── libchaquopy_java.so         ← Chaquopy JNI
    │   └── libpython3.12.so            ← CPython 解释器
    │
    ├── assets/chaquopy/
    │   ├── bootstrap.zip
    │   └── python-3.12.zip             ← 标准库
    │
    ├── classes.dex                     ← Shell 代码
    │   ├── MainActivity                ← WebView Shell
    │   ├── PythonService               ← Foreground Service
    │   └── BootReceiver                ← 开机自启
    │
    └── assets/python-app/              ← 初始应用代码 (首次解压到内部存储)
        ├── VERSION                     ← "1.2.0"
        ├── app/
        │   └── data_collector/
        └── app_packages/
            ├── fastapi/
            └── uvicorn/
```

安装后布局：

```
APK 内:     Python 运行时 (Chaquopy 提供)
内部存储:   /data/data/com.myapp/files/
            ├── VERSION                ← 当前版本号 "1.2.0"
            ├── app-1.1.0/             ← 旧版本 (保留用于回滚)
            │   ├── app/
            │   │   └── data_collector/
            │   └── app_packages/
            └── app-1.2.0/             ← 当前版本
                ├── app/
                │   └── data_collector/
                └── app_packages/
```

### 4.4 关键观察：三平台结构的统一性

任何平台的应用包都包含且仅包含三样东西：

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Python 运行时 │  │   应用代码    │  │   启动器      │
│  (很少变化)    │  │  (经常变化)   │  │  (平台特定)   │
│              │  │              │  │              │
│  Linux: PBS  │  │  100% 相同   │  │  Linux: sh   │
│  Win:   EBD  │  │              │  │  Win:   exe  │
│  And:   Chaq │  │              │  │  And:   APK  │
└──────────────┘  └──────────────┘  └──────────────┘
```

三平台统一版本切换机制：

```
启动器读取根目录 VERSION 文件 → 定位 app-{ver} 目录 → 设置搜索路径
升级: 解压新版本到 app-{new_ver}/ + 写入 VERSION 文件 → 新进程自动使用新版本
回滚: 写入旧版本号到 VERSION 文件 → 新进程回退到旧版本
```

***

## 五、Python 运行时

### 5.1 运行时选型

| 平台      | 方案                            |    体积   | 来源                      |
| ------- | ----------------------------- | :-----: | ----------------------- |
| Linux   | PBS (Python Build Standalone) | \~40 MB | python-build-standalone |
| Windows | Windows Embeddable Package    | \~15 MB | python.org 官方           |
| Android | Chaquopy 内置                   | \~15 MB | chaquo.com              |

### 5.2 运行时获取方式

**Linux**：CI 中下载 PBS release

```bash
wget https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.12.1+20240107-x86_64-unknown-linux-gnu-install_only.tar.gz
# 解压后即为完整的 Python 运行时，无需编译
```

**Windows**：CI 中下载 Embeddable Package

```bash
wget https://www.python.org/ftp/python/3.12.1/python-3.12.1-embed-amd64.zip
# 解压后即为嵌入式 Python 运行时，无需安装
# 注意: 保留 ._pth 文件！由 Stub 启动时动态重写，删除后 Python 无法从 zip 加载标准库
```

**Android**：Chaquopy Gradle 插件自动下载

```kotlin
chaquopy { defaultConfig { python.version = "3.12" } }
// 构建时自动集成到 APK
```

### 5.3 运行时版本锁定

所有平台使用相同的 Python 大版本和小版本 (如 3.12.x)。版本号定义在项目根目录的 `PYTHON_VERSION` 文件中：

```
PYTHON_VERSION=3.12.1
```

CI 构建时读取此文件，确保三平台运行时版本一致。

### 5.4 运行时部署位置

| 平台 | 默认模式 | 运行时安装位置 | 说明 |
|------|---------|-------------|------|
| Windows | standalone | `{app_dir}/runtime/` | 应用私有，升级只影响本应用 |
| Linux | shared | `/opt/runtime/` | 多应用共用，升级影响所有应用 |
| Android | standalone | APK 内 (Chaquopy) | 沙箱隔离，无法共享 |

运维可通过 `RUNTIME_DIR` 环境变量覆盖默认位置。

### 5.5 Windows Embeddable Package 特殊处理

#### 5.5.1 .\_pth 文件动态重写

Embeddable Package 通过 `._pth` 文件控制 `sys.path`。当 `._pth` 存在时，Python **忽略所有环境变量**（包括 PYTHONHOME/PYTHONPATH），只使用 `._pth` 中列出的路径。

**不能删除 .\_pth**：删除后 Python 在 PYTHONHOME 模式下无法从 zip 文件加载标准库（报 `No module named 'encodings'`）。

**解决方案**：Stub Exe 在每次启动时动态重写 `._pth` 文件：

```
python312.zip                                              ← 标准库
.                                                          ← runtime 自身
C:\Apps\data-collector\app-1.2.0\app                       ← 应用代码
C:\Apps\data-collector\app-1.2.0\app_packages              ← pip 依赖
```

**并发保护**：多个应用共享同一个 runtime 时，使用 Named Mutex (`Global\PythonSharedRuntime_PthWrite`) 保护 `._pth` 文件的并发写入。Standalone 模式下只有一个应用写 `._pth`，不会触发并发，但保留此保护逻辑以备 `RUNTIME_DIR` 覆盖为共享路径的场景。

#### 5.5.2 环境变量可见性

`._pth` 模式下，Python 会**从 `os.environ` 中清除** `PYTHONHOME` 和 `PYTHONPATH`（不是忽略，是删除）。因此：

- 应用代码应使用 `APP_VERSION`、`PYTHON_EXECUTABLE` 等自定义环境变量
- 不要在 Python 代码中依赖 `os.environ["PYTHONHOME"]` 或 `os.environ["PYTHONPATH"]`

#### 5.5.3 Embeddable Package 限制

| 限制              | 影响        | 缓解                                        |
| --------------- | --------- | ----------------------------------------- |
| 无 pip           | 无法在运行时安装包 | CI 中使用完整 Python 执行 `pip install --target` |
| 无 tkinter       | 无法使用 GUI  | 本方案使用 WebView，不受影响                        |
| 无 venv          | 无法创建虚拟环境  | 不需要，依赖隔离通过 PYTHONPATH 实现                  |
| 标准库以 .pyc 压缩包提供 | 调试时看不到源码  | 运维时可替换为完整标准库                              |

***

## 六、应用代码

### 6.1 代码结构 (所有平台 100% 相同)

```
app/
├── VERSION                    ← 版本号 (如 1.2.0)
├── data_collector/
│   ├── __init__.py            ← 必须包含 __version__
│   ├── __main__.py            ← 统一入口
│   ├── app.py                 ← FastAPI 应用
│   └── core.py                ← 业务逻辑
├── app_packages/              ← pip install --target 的产物
│   ├── fastapi/
│   ├── uvicorn/
│   └── ...
└── static/                    ← 前端文件
    ├── index.html
    └── app.js
```

### 6.2 依赖管理

```
requirements.txt:
  fastapi==0.115.0
  uvicorn==0.30.0
  requests==2.31.0

构建时安装到 app_packages/:
  pip install -r requirements.txt --target app_packages/

注意: 三平台必须分别执行 pip install，因为含 C 扩展的包产出平台相关的编译文件。
  Linux 产出 .so 文件，Windows 产出 .pyd 文件，Android 由 Chaquopy 构建系统处理。
  requirements.txt 三平台相同，但 app_packages/ 内容不同。
```

### 6.3 统一入口 \_\_main\_\_.py

```python
import os
import sys
import signal

def main():
    port = int(os.environ.get("APP_PORT", "18080"))
    mode = os.environ.get("APP_MODE", "console")

    # 添加 DLL 搜索路径 (Windows, Python 3.8+)
    # 注意: ._pth 模式下 PYTHONHOME 被 Python 从 os.environ 清除，
    #       需通过 PYTHON_EXECUTABLE 推导 runtime 路径
    if sys.platform == "win32":
        python_exe = os.environ.get("PYTHON_EXECUTABLE", "")
        if python_exe:
            runtime_dir = os.path.dirname(python_exe)
            if os.path.isdir(runtime_dir):
                os.add_dll_directory(runtime_dir)

    import uvicorn
    from data_collector.app import create_app, set_server

    app = create_app()

    # Linux: 注册 SIGTERM
    if sys.platform != "win32":
        def handle_sigterm(signum, frame):
            server.should_exit = True
        signal.signal(signal.SIGTERM, handle_sigterm)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port,
        log_level="info",
        handle_signals=(sys.platform == "win32"),  # Android 设 False
    )
    server = uvicorn.Server(config)
    set_server(server)

    # Ready 信号
    ready_file = os.environ.get("APP_READY_FILE", "")
    if ready_file:
        with open(ready_file, "w") as f:
            f.write(str(port))

    # 控制台模式自动打开浏览器
    if mode == "console":
        import webbrowser
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    print(f"[data-collector] http://127.0.0.1:{port} (mode={mode})")
    server.run()

if __name__ == "__main__":
    main()
```

***

## 七、启动器 (Shell)

### 7.1 Linux 启动器: run.sh

```bash
#!/bin/bash
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
APP_HOME="$(dirname "$SELF")"

# 运行时解析: 环境变量 > 默认共享路径
RUNTIME="${RUNTIME_DIR:-/opt/runtime}"

VERSION="$(cat "$APP_HOME/VERSION" 2>/dev/null || echo unknown)"
APP="$APP_HOME/app-$VERSION"
export PYTHONHOME="$RUNTIME"
export PYTHONPATH="$APP/app:$APP/app_packages"
export LD_LIBRARY_PATH="$RUNTIME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$RUNTIME/bin:$PATH"
export APP_VERSION="$VERSION"
export APP_DATA_DIR="/var/lib/data-collector"
export APP_CONFIG_DIR="/etc/data-collector"
export APP_LOG_DIR="/var/log/data-collector"
exec -a "data_collector" "$RUNTIME/bin/python3" -s -m data_collector "$@"
```

### 7.2 Windows 启动器: data\_collector.exe (Embed Stub)

```
编译: windres app_stub.rc -O coff -o app_stub.res
      gcc -o data_collector.exe app_stub.c app_stub.res -municode -mconsole -O2 -s

逻辑:
  1. 获取 exe 所在目录 → APP_DIR (如 C:\Apps\data-collector\)
  2. 读取 APP_DIR\VERSION → 当前版本号 (如 1.2.0)
  3. 定位版本目录: APP_DIR\app-{VERSION}\
  4. 运行时解析 (resolve_runtime):
     ① 环境变量 RUNTIME_DIR → 使用指定路径
     ② APP_DIR\runtime\ → standalone 默认路径
     ③ 未找到 → 报错退出
  5. 解析 runtime\VERSION 获取 Python 版本标签 (如 312)
  6. 动态重写 ._pth 文件 (Named Mutex 保护并发):
       python312.zip
       .
       APP_DIR\app-{VERSION}\app
       APP_DIR\app-{VERSION}\app_packages
  7. 设置环境变量 (_wputenv，确保 os.environ 可见):
       PYTHONHOME   = {runtime_dir}
       PYTHONPATH   = APP_DIR\app-{VERSION}\app;APP_DIR\app-{VERSION}\app_packages
       PATH         = {runtime_dir};%PATH%  (前插，确保 DLL 优先加载)
       APP_VERSION  = {VERSION}
       PYTHON_EXECUTABLE = {runtime_dir}\python.exe
       APP_DATA_DIR     = C:\ProgramData\data-collector
       APP_CONFIG_DIR   = C:\ProgramData\data-collector\config
       APP_LOG_DIR      = C:\ProgramData\data-collector\logs
  8. LoadLibrary({runtime_dir}\python3.dll)
  9. Py_InitializeFromConfig + Py_RunMain 启动 Python 模块
  10. 单进程，Stub 与 Python 在同一进程
```

**Stub 运行时解析核心代码**：

```c
/* 统一运行时解析: 环境变量 > 本地 runtime/ */
wchar_t* resolve_runtime(const wchar_t* appDir) {
    /* ① 环境变量覆盖 (运维显式指定，最高优先) */
    const wchar_t* env = _wgetenv(L"RUNTIME_DIR");
    if (env && env[0] && dir_exists(env)) {
        return _wcsdup(env);
    }

    /* ② 本地 runtime/ (Windows standalone 默认) */
    wchar_t* local = join_path(appDir, L"runtime");
    if (dir_exists(local)) {
        return local;
    }

    /* ③ 未找到 */
    fwprintf(stderr, L"[STUB] ERROR: Python runtime not found\n");
    fwprintf(stderr, L"[STUB] Searched: RUNTIME_DIR env, %s\\runtime\\\n", appDir);
    return NULL;
}

/* Python 初始化与运行 (Python 3.11+ API) */
int run_python(const wchar_t* runtimeDir, const wchar_t* appDir, const wchar_t* version) {
    PyConfig config;
    PyConfig_InitPythonConfig(&config);

    /* 隔离模式: 不读取用户 site-packages */
    config.isolated = 1;
    /* 忽略环境变量 (._pth 模式已设置路径) */
    config.use_environment = 0;

    /* 设置程序名 */
    PyConfig_SetString(&config, &config.program_name, L"data_collector");

    /* 设置模块参数: -s -m data_collector */
    wchar_t* argv[] = {
        L"data_collector",
        L"-s",
        L"-m",
        L"data_collector"
    };
    PyConfig_SetArgv(&config, 4, argv);

    /* 初始化 Python 解释器 */
    PyStatus status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        fwprintf(stderr, L"[STUB] Python init failed: %s\n", status.err_msg);
        PyConfig_Clear(&config);
        return 1;
    }

    /* 运行 Python 模块 */
    int exit_code = Py_RunMain();
    PyConfig_Clear(&config);
    return exit_code;
}
```

### 7.3 Android 启动器: APK (MainActivity + PythonService)

```
MainActivity (WebView Shell):
  1. 读取内部存储 VERSION 文件 → 当前版本号
  2. 确保 PythonService 正在运行
  3. 轮询 GET /api/status 直到 200
  4. WebView 加载 http://127.0.0.1:18080
  5. 按 Back 键 → moveTaskToBack (Service 继续运行)

PythonService (Foreground Service):
  1. 读取 VERSION → 定位 app-{ver} 目录
  2. Chaquopy JNI → bridge.start_server(port)
  3. Python 在后台线程运行 uvicorn
  4. 通知栏常驻: "数据采集服务运行中 · 端口 18080"
  5. START_STICKY: 被杀后自动重启

BootReceiver:
  监听 BOOT_COMPLETED → 启动 PythonService
```

***

## 八、通信协议 (三平台统一)

### 8.1 启动协议

```
Shell                              Python
  │                                   │
  ├── 读取 VERSION 文件                │
  ├── 定位 app-{ver} 目录              │
  ├── 解析 runtime 路径                │
  ├── 设置环境变量                     │
  │   APP_PORT=18080                  │
  │   APP_MODE=console|webview        │
  │   APP_READY_FILE=...              │
  │   APP_VERSION=1.2.0               │
  │   APP_DATA_DIR=...                │
  │   APP_CONFIG_DIR=...              │
  │                                   │
  ├── 启动 Python ──────────────────► │
  │                                   ├── 初始化 FastAPI
  │                                   ├── 绑定 127.0.0.1:PORT
  │   轮询 GET /api/status            │
  │──────────────────────────────────►│
  │   ◄── 200 {"status":"running"} ──│
  │                                   │
  ├── 显示 UI                         │
  │   浏览器/WebView → http://...     │
  │                                   │
```

### 8.2 Shutdown 协议

```
触发方式                实现
─────────────────────────────────────────────────
Linux SIGTERM           signal handler → server.should_exit = True
Windows Ctrl+C          uvicorn handle_signals → should_exit = True
Windows Service Stop    NSSM 发送 Ctrl+C → should_exit = True
Shell POST /shutdown    api_shutdown() → should_exit = True
Android Service.destroy bridge.stop_server() → should_exit = True
所有方式最终汇聚到同一行: server.should_exit = True
→ uvicorn 停止接受新请求 → 等待当前请求完成 → 退出
```

***

## 九、构建流程

### 9.1 构建依赖

| 通用      | Python 3.12, pip           |
| ------- | -------------------------- |
| Linux   | tar                        |
| Windows | MinGW-w64 (仅 Stub), 7zip   |
| Android | Android SDK, NDK, Chaquopy |

### 9.2 构建类型矩阵

| 触发方式            | BUILD\_TYPE   | 产物含 Python | 产物含应用 | 部署场景         |
| --------------- | ------------- | :--------: | :---: | ------------ |
| `runtime/v*` 标签 | `python-only` |      ✅     |   ❌   | 仅升级底层 Python |
| `<app>/v*` 标签   | `app-only`    |      ❌     |   ✅   | 仅升级某个应用      |
| 无效标签            | `skip`        |      ❌     |   ❌   | 跳过           |
| 手动触发            | `full`        |      ✅     |   ✅   | 首次安装         |

### 9.3 构建步骤 (CI)

```
┌─────────────┐
│ 检出代码     │
└──────┬──────┘
       │
┌──────▼──────┐
│ 安装 pip 依赖│  pip install -r requirements.txt --target build/app/app_packages/
│              │  注意: 三平台分别构建，产出平台相关的 app_packages/
└──────┬──────┘
       │
       ├──────────────────────────────────────────────┐
       │                                              │
┌──────▼──────┐                              ┌───────▼───────┐
│ Linux 构建   │                              │ Windows 构建   │
│             │                              │               │
│ 1.下载 PBS  │                              │ 1.下载 EBD    │
│ 2.放入 runtime/│                            │ 2.放入 runtime/│
│ 3.复制 app/ │                              │ 3.复制 app/   │
│ 4.复制 run.sh│                              │ 4.编译 Stub   │
│ 5.写入 VERSION│                             │ 5.写入 VERSION│
│ 6.tar.gz    │                              │ 6.zip         │
└─────────────┘                              └───────────────┘
       │                                              │
       │                              ┌───────────────▼────────────┐
       │                              │ Android 构建                │
       │                              │                            │
       │                              │ 1.Gradle + Chaquopy 自动  │
       │                              │ 2.复制 python/ → assets    │
       │                              │ 3.编译 Kotlin Shell        │
       │                              │ 4.生成 .apk                │
       │                              └────────────────────────────┘
       │                                              │
┌──────▼──────────────────────────────────────────────▼──────┐
│                    产出物                                    │
│                                                            │
│  runtime-linux-x86_64.tar.gz                   (~40 MB)    │
│  runtime-win64.zip                             (~8 MB)     │
│  data-collector-1.2.0-linux-x86_64-app.tar.gz  (~3 MB)    │
│  data-collector-1.2.0-win64-app.zip             (~3 MB)    │
│  data_collector.exe                             (~50 KB)    │
│  data-collector-1.2.0.apk                       (~35 MB)   │
│                                                            │
│  Windows 全量包 = runtime + app + Stub (首次安装)           │
│  Linux 全量包 = runtime + app + run.sh (首次安装)           │
│  增量包 = app only (已安装 runtime 的设备)                   │
└────────────────────────────────────────────────────────────┘
```

### 9.4 增量包构建

只打包 app/ 目录 (不含 runtime/)：

```
data-collector-1.2.0-linux-x86_64-app.tar.gz     (~3 MB)
data-collector-1.2.0-win64-app.zip               (~3 MB)
data-collector-1.2.0-android-app.zip              (~3 MB)
适用于已安装运行时的设备，只更新应用代码。
```

### 9.5 Windows 全量包构建

Windows standalone 模式下，全量包将 runtime 和 app 打包在一起：

```powershell
# 全量包: runtime + app + Stub 合并
Compress-Archive -Path runtime\,app\,data_collector.exe -DestinationPath data-collector-1.2.0-windows-x86_64.zip
# 产物: ~20 MB (runtime ~15 MB + app ~3 MB + Stub ~50 KB)

# 增量包: 仅 app
Compress-Archive -Path app\ -DestinationPath data-collector-1.2.0-win64-app.zip
# 产物: ~3 MB
```

***

## 十、安装流程

### 10.1 Windows (Standalone)

```batch
REM 全量安装 (首次)
解压 data-collector-1.2.0-windows-x86_64.zip → C:\Apps\data-collector\
运行 data_collector.exe
REM 目录结构:
REM   C:\Apps\data-collector\
REM   ├── runtime\              ← 应用自带 Python
REM   ├── data_collector.exe    ← Stub
REM   ├── VERSION               ← 1.2.0
REM   └── app-1.2.0\            ← 应用代码

REM 增量更新 (两种方式)

REM 方式 A: HTTP Push (局域网推荐，三平台统一)
curl -X POST http://<device-ip>:18080/api/update ^
  -H "Authorization: Bearer <token>" ^
  -F "file=@data-collector-1.3.0-win64-app.zip"
REM 详见 10.4 局域网增量更新方案

REM 方式 B: 本地部署
REM   1. 解压 app/ → C:\Apps\data-collector\app-1.3.0\
REM   2. 写入 VERSION → 1.3.0
REM   3. 重启应用
REM   4. 回滚: 写入 VERSION → 1.2.0 → 重启应用

REM Python 运行时升级
REM   1. 解压 runtime/ → C:\Apps\data-collector\runtime\ (覆盖)
REM   2. 重启应用
REM   注意: standalone 模式下只影响本应用
```

### 10.2 Linux (Shared)

```bash
# 全量安装
tar xzf data-collector-1.2.0-linux-x86_64.tar.gz -C /tmp/
sudo /tmp/data-collector-1.2.0/install.sh
# install.sh 做了什么:
#   1. 解压 runtime/  → /opt/runtime/                    (首次, 多应用共享)
#   2. 解压 app/      → /opt/data-collector/app-1.2.0/
#   3. 写入 VERSION   → /opt/data-collector/VERSION (内容: 1.2.0)
#   4. 复制 run.sh    → /opt/data-collector/run.sh
#   5. 创建数据目录   → /var/lib/data-collector/
#   6. 创建配置目录   → /etc/data-collector/
#   7. 安装 systemd 服务
#   8. systemctl enable data-collector
#   9. 更新全局版本快照 → /opt/versions

# 增量更新 (两种方式)

# 方式 A: HTTP Push (局域网推荐，三平台统一)
curl -X POST http://<device-ip>:18080/api/update \
  -H "Authorization: Bearer <token>" \
  -F "file=@data-collector-1.3.0-linux-x86_64-app.tar.gz"
# 详见 10.4 局域网增量更新方案

# 方式 B: 本地脚本
tar xzf data-collector-1.3.0-linux-x86_64-app.tar.gz -C /tmp/
sudo /tmp/data-collector-1.3.0/update.sh
# update.sh 做了什么:
#   1. 解压 app/ → /opt/data-collector/app-1.3.0/
#   2. 写入 VERSION → /opt/data-collector/VERSION (内容: 1.3.0)
#   3. systemctl restart data-collector
#   4. 更新全局版本快照 → /opt/versions
#   5. 回滚: 写入 VERSION 文件内容为 1.2.0 → 重启服务

# Python 运行时升级 (shared 模式，影响所有应用)
#   1. 解压 runtime/ → /opt/runtime/ (覆盖)
#   2. 重启所有应用
#   3. 更新全局版本快照
```

### 10.3 Android (Standalone)

```
# 全量安装
安装 data-collector-1.2.0.apk
首次启动: 自动从 assets 解压初始代码到内部存储
  → /data/data/com.myapp/files/VERSION (内容: 1.2.0)
  → /data/data/com.myapp/files/app-1.2.0/
```

Android 增量更新支持三种方式：

#### 方式 1：HTTP Push 增量更新（局域网推荐）

三平台统一方案，详见 [10.4 局域网增量更新方案](#104-局域网增量更新方案)。

#### 方式 2：adb 推送（开发/调试）

```bash
# === 非 Root 设备 (使用 run-as 中转) ===

# 步骤 1: 推送更新包到 /sdcard/
adb push data-collector-1.3.0-android-app.zip /sdcard/

# 步骤 2: 通过 run-as 复制到应用内部存储
adb shell run-as com.myapp cp /sdcard/data-collector-1.3.0-android-app.zip /data/data/com.myapp/files/

# 步骤 3: 解压并更新 VERSION
adb shell run-as com.myapp sh -c "\
  cd /data/data/com.myapp/files/ && \
  unzip -o data-collector-1.3.0-android-app.zip -d app-1.3.0 && \
  echo 1.3.0 > VERSION"

# 步骤 4: 重启 PythonService
adb shell am force-stop com.myapp
adb shell am start -n com.myapp/.MainActivity

# 步骤 5: 清理临时文件
adb shell run-as com.myapp rm /data/data/com.myapp/files/data-collector-1.3.0-android-app.zip
adb shell rm /sdcard/data-collector-1.3.0-android-app.zip

# === Root 设备 (工控机/定制设备，可直接操作) ===

adb push data-collector-1.3.0-android-app.zip /data/data/com.myapp/files/
adb shell su -c "\
  cd /data/data/com.myapp/files/ && \
  unzip -o data-collector-1.3.0-android-app.zip -d app-1.3.0 && \
  echo 1.3.0 > VERSION && \
  chown -R $(stat -c '%U:%G' /data/data/com.myapp/files) app-1.3.0 VERSION"
adb shell am force-stop com.myapp
adb shell am start -n com.myapp/.MainActivity

# 回滚
adb shell run-as com.myapp sh -c "echo 1.2.0 > /data/data/com.myapp/files/VERSION"
adb shell am force-stop com.myapp
adb shell am start -n com.myapp/.MainActivity
```

#### 方式 3：adb install 全量重装

```bash
# 仅当无法增量更新时使用
adb install -r data-collector-1.3.0.apk
# -r: 替换已有应用，保留内部存储数据
```

### 10.4 局域网增量更新方案

#### 核心思路

设备已运行 FastAPI (端口 18080)，**复用现有 HTTP 服务接收增量包**，无需额外基础设施。

```
运维电脑 (局域网)                        目标设备 (局域网)
┌─────────────────┐                    ┌──────────────────────┐
│ curl / Web UI   │  POST /api/update  │ FastAPI :18080       │
│                 │ ──────────────────► │                      │
│ update.zip(3MB) │                    │ 1. 校验 + 解压       │
│                 │  ◄── 200 OK ────── │ 2. 写入 VERSION      │
│                 │                    │ 3. 重启 Python 进程   │
└─────────────────┘                    └──────────────────────┘
```

#### 三平台统一运维命令

```bash
# 查看当前版本
curl http://192.168.1.100:18080/api/version
# → {"app_version": "1.2.0", "python_version": "3.12.1"}

# 推送增量更新 (三平台命令完全相同)
curl -X POST http://192.168.1.100:18080/api/update \
  -H "Authorization: Bearer <token>" \
  -F "file=@data-collector-1.3.0-app.zip"

# → {"status": "ok", "old_version": "1.2.0", "new_version": "1.3.0"}

# 回滚到指定版本
curl -X POST http://192.168.1.100:18080/api/rollback \
  -H "Authorization: Bearer <token>" \
  -d "version=1.2.0"

# → {"status": "ok", "current_version": "1.2.0"}

# 查看可用版本列表
curl http://192.168.1.100:18080/api/versions
# → {"current": "1.3.0", "available": ["1.1.0", "1.2.0", "1.3.0"]}

# 批量更新多台设备
for ip in 192.168.1.{100..110}; do
  echo "Updating $ip..."
  curl -s -X POST "http://$ip:18080/api/update" \
    -H "Authorization: Bearer <token>" \
    -F "file=@data-collector-1.3.0-app.zip" | jq .
done
```

#### FastAPI 更新端点实现

```python
import os
import shutil
import zipfile
import tempfile
from fastapi import APIRouter, UploadFile, File, Header, HTTPException
from pathlib import Path

router = APIRouter()

# 配置
UPDATE_TOKEN = os.environ.get("UPDATE_TOKEN", "")  # 局域网安全 token
APP_BASE_DIR = Path(os.environ.get("APP_BASE_DIR", "."))

def verify_token(authorization: str = Header(None)):
    """局域网轻量认证，防止误操作"""
    if not UPDATE_TOKEN:
        return  # 未配置 token 则不校验
    if not authorization or authorization != f"Bearer {UPDATE_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/api/version")
async def get_version():
    """查看当前版本"""
    version_file = APP_BASE_DIR / "VERSION"
    app_version = version_file.read_text().strip() if version_file.exists() else "unknown"
    python_version = "unknown"
    # 尝试从多种路径获取 runtime VERSION
    runtime_version_file = Path(os.environ.get("RUNTIME_DIR", "")) / "VERSION"
    if not runtime_version_file.exists():
        python_exe = os.environ.get("PYTHON_EXECUTABLE", "")
        if python_exe:
            runtime_version_file = Path(python_exe).parent / "VERSION"
    if runtime_version_file.exists():
        python_version = runtime_version_file.read_text().strip()
    return {"app_version": app_version, "python_version": python_version}

@router.get("/api/versions")
async def get_versions():
    """查看所有可用版本"""
    current = (APP_BASE_DIR / "VERSION").read_text().strip()
    available = sorted([
        d.name.replace("app-", "")
        for d in APP_BASE_DIR.iterdir()
        if d.is_dir() and d.name.startswith("app-")
    ])
    return {"current": current, "available": available}

@router.post("/api/update")
async def push_update(
    file: UploadFile = File(...),
    authorization: str = Header(None),
):
    """接收增量更新包并应用"""
    verify_token(authorization)

    # 1. 保存上传的 zip 到临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "update.zip"
        with open(zip_path, "wb") as f:
            content = await file.read()
            f.write(content)

        # 2. 从 zip 中读取版本号
        with zipfile.ZipFile(zip_path) as zf:
            version = None
            for name in zf.namelist():
                if name.endswith("VERSION") and name.count("/") <= 2:
                    version = zf.read(name).decode().strip()
                    break
            if not version:
                raise HTTPException(400, "VERSION not found in zip")

        # 3. 检查目标版本目录是否已存在
        version_dir = APP_BASE_DIR / f"app-{version}"
        if version_dir.exists():
            if (APP_BASE_DIR / "VERSION").read_text().strip() == version:
                return {"status": "already_on_this_version", "version": version}

        # 4. 解压到 app-{version}/ (校验路径防止 Zip Slip)
        if version_dir.exists():
            shutil.rmtree(version_dir)
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                if member.startswith("/") or ".." in member:
                    raise HTTPException(400, f"Invalid path in zip: {member}")
            zf.extractall(version_dir)

    # 5. 写入 VERSION 文件 (旧进程不受影响)
    old_version = (APP_BASE_DIR / "VERSION").read_text().strip()
    (APP_BASE_DIR / "VERSION").write_text(version)

    # 6. 请求优雅重启
    from data_collector.app import request_restart
    request_restart()

    return {
        "status": "ok",
        "old_version": old_version,
        "new_version": version,
    }

@router.post("/api/rollback")
async def rollback(version: str, authorization: str = Header(None)):
    """回滚到指定版本"""
    verify_token(authorization)

    version_dir = APP_BASE_DIR / f"app-{version}"
    if not version_dir.exists():
        raise HTTPException(404, f"Version {version} not found")

    old_version = (APP_BASE_DIR / "VERSION").read_text().strip()
    (APP_BASE_DIR / "VERSION").write_text(version)

    from data_collector.app import request_restart
    request_restart()

    return {"status": "ok", "old_version": old_version, "current_version": version}
```

#### 优雅重启机制

更新后需要重启 Python 进程以加载新版本代码。三平台实现不同但协议统一：

```
API 调用 request_restart()
       │
       ├─ Linux:    server.should_exit = True → systemd 自动重启 (Restart=always)
       ├─ Windows:  server.should_exit = True → NSSM/WinSW 自动重启
       └─ Android:  server.should_exit = True → PythonService.stopSelf() + AlarmManager 延迟重启
```

```python
# data_collector/app.py 中添加
_server = None
_restart_requested = False

def request_restart():
    """请求优雅重启，三平台统一"""
    global _restart_requested
    _restart_requested = True
    if _server:
        _server.should_exit = True
```

`__main__.py` 中在 `server.run()` 之后检查：

```python
    print(f"[data-collector] http://127.0.0.1:{port} (mode={mode})")
    server.run()

    # server.run() 返回后检查是否需要重启
    if _restart_requested:
        sys.exit(42)  # 特殊退出码，表示需要重启
```

```ini
# Linux: systemd 自动重启
[Service]
Restart=always
RestartSec=2
# 退出码 42 也会重启

# Windows: NSSM 自动重启
nssm set data-collector AppExit Default Restart
nssm set data-collector AppRestartDelay 2000
```

```kotlin
// Android: PythonService 中的重启逻辑
fun restartSelf() {
    val restartIntent = Intent(this, PythonService::class.java)
    val pendingIntent = PendingIntent.getService(
        this, 0, restartIntent, PendingIntent.FLAG_IMMUTABLE
    )
    val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
    alarmManager.set(
        AlarmManager.ELAPSED_REALTIME,
        SystemClock.elapsedRealtime() + 2000,
        pendingIntent
    )
    stopSelf()
}

override fun onTaskRemoved(rootIntent: Intent?) {
    restartSelf()
    super.onTaskRemoved(rootIntent)
}

override fun onDestroy() {
    if (restartRequested) {
        restartSelf()
    }
    super.onDestroy()
}
```

#### 局域网安全考虑

| 措施 | 说明 |
|------|------|
| UPDATE_TOKEN | 环境变量配置认证 token，`curl` 请求时携带 |
| 绑定 127.0.0.1 | 如只允许本机更新，FastAPI 绑定 localhost (Android WebView 场景) |
| 绑定内网 IP | 如需远程更新，绑定 `0.0.0.0` 或指定内网网卡 IP |
| 签名验证 | zip 包内含 `SHA256SUMS` 签名文件，API 校验后再解压 |
| 更新包加密 | 敏感场景可对 zip 加密，API 解密后再解压 |

#### 三种更新方式对比

| 维度 | HTTP Push (局域网) | adb 推送 | adb install 全量 |
|------|-------------------|---------|-----------------|
| 需要 Root | 否 | 否 (run-as) / 是 (直接) | 否 |
| 需要物理接触 | 否 (网络可达即可) | 是 (USB) | 是 (USB) |
| 传输量 | ~3 MB (增量) | ~3 MB (增量) | ~35 MB (全量) |
| 批量更新 | 支持 (for 循环) | 不支持 | 不支持 |
| 回滚 | `curl /api/rollback` | 手动改 VERSION | 重新安装旧 APK |
| 适用场景 | **生产运维** | 开发调试 | 无法增量时的兜底 |

***

## 十一、版本管理与回滚

### 11.1 VERSION 文件版本切换机制

所有平台统一使用 **VERSION 文件 + app-{ver} 平铺目录** 进行版本管理：

```
应用目录/
├── VERSION             ← 当前版本号 "1.2.0" (启动器读取此文件)
├── app-1.1.0/          ← 旧版本 (保留用于回滚)
│   ├── VERSION         ← "1.1.0"
│   ├── app/
│   │   └── data_collector/
│   └── app_packages/
├── app-1.2.0/          ← 当前版本 (VERSION 文件指向此版本)
│   ├── VERSION
│   ├── app/
│   │   └── data_collector/
│   └── app_packages/
└── app-1.3.0/          ← 新版本 (刚部署)
    ├── VERSION
    ├── app/
    │   └── data_collector/
    └── app_packages/
```

**升级流程**：

```
1. 旧进程运行中，使用 app-1.2.0 目录 (被锁定，无法删除)
2. 部署脚本解压新版本到 app-1.3.0 目录
3. 写入 VERSION 文件: 1.3.0 (旧进程不受影响，仍使用已加载的路径)
4. 新启动的进程读取 VERSION 文件，自动使用 app-1.3.0
5. 旧进程退出后，app-1.2.0 目录可安全删除
```

**回滚流程**：

```
1. 写入 VERSION 文件: 1.2.0
2. 重启服务 → 新进程使用 app-1.2.0
3. 确认稳定后可删除 app-1.3.0
```

**相比 symlink/Junction 的优势**：

| 维度          | symlink/Junction               | VERSION 文件         |
| ----------- | ------------------------------ | ------------------ |
| 权限需求        | Linux 无，Windows 可能需要管理员        | 无特殊权限              |
| Windows 文件锁 | Junction 目标可能被锁                | VERSION 文件写入不受锁影响  |
| 原子性         | `ln -sfn` 原子，`mklink /J` 需先删后建 | 写入单行文本，接近原子        |
| 跨平台一致性      | 三平台实现不同                        | 三平台完全一致            |
| 可观测性        | 需 `readlink` 查看指向              | `cat VERSION` 直接可读 |

### 11.2 全局版本快照

**Linux (shared 模式)**：`/opt/versions` 文件记录所有组件版本：

```
runtime:3.12.1
data-collector:1.2.0
device-monitor:2.0.1
```

运维命令：`cat /opt/versions` 或 `deploy --show-versions`

**Windows (standalone 模式)**：无需全局版本快照，查看 `{app}/VERSION` 即可。

**Android (standalone 模式)**：无需全局版本快照，通过 API 查询版本。

### 11.3 旧版本自动清理

部署脚本内置清理逻辑：删除非当前版本的、超过 7 天的旧版本目录，保留最近 2-3 个版本。

### 11.4 版本信息流转

```
开发阶段: 开发者在 __init__.py 维护 __version__
    ↓
构建阶段: CI 从 Git 标签提取版本号，写入 VERSION 文件并打包
    ↓
部署阶段: 部署脚本将应用解压至 app-{ver} 目录，写入根目录 VERSION 文件
    ↓
运维阶段: deploy --show-versions 或 API 查看版本
```

### 11.5 Python 运行时升级

| 平台 | 模式 | 升级方式 | 影响范围 |
|------|------|---------|---------|
| Windows | standalone | 替换 `{app}/runtime/` 目录，重启本应用 | 仅本应用 |
| Linux | shared | 替换 `/opt/runtime/` 目录，重启所有应用 | 所有应用 |
| Android | standalone | 升级 APK (Chaquopy 随 APK 更新) | 仅本应用 |

**Linux shared 模式运行时升级注意事项**：

- 升级前需通知所有应用即将重启
- 升级后需重启所有依赖应用
- 建议在维护窗口期执行
- 必须更新全局版本快照 `/opt/versions`

***

## 十二、数据持久化路径

应用代码、配置文件、日志必须分离存储，升级时互不影响。

### 12.1 路径规划

| 路径类型 | Linux                            | Windows                                 | Android           |
| ---- | -------------------------------- | --------------------------------------- | ----------------- |
| 应用代码 | `/opt/data-collector/app-{ver}/` | `C:\Apps\data-collector\app-{ver}\`     | 内部存储 `app-{ver}/` |
| 配置文件 | `/etc/xdg/data-collector/`       | `C:\ProgramData\data-collector\`        | `.../shared_prefs/data-collector` |
| 数据文件 | `/var/lib/data-collector/`       | `C:\ProgramData\data-collector\`        | `.../files/data-collector` |
| 日志文件 | `/var/log/data-collector/`       | `C:\ProgramData\data-collector\Logs\`   | `.../cache/data-collector/log` |
| 缓存文件 | `/var/cache/data-collector/`     | `C:\ProgramData\data-collector\Cache\`  | `.../cache/data-collector` |
| 运行时文件 | `/run/data-collector/`          | `%TEMP%\data-collector\`                | `.../cache/data-collector/tmp` |

> Android 路径中的 `...` 为 `/data/user/<uid>/<packagename>`。

### 12.2 使用 platformdirs 统一管理

[`platformdirs`](https://github.com/tox-dev/platformdirs) 是跨平台目录路径库，支持 Linux / Windows / macOS / Android，
遵循各平台规范（XDG / FHS / AppData / Android 内部存储）。

**核心用法**：

```python
from platformdirs import PlatformDirs

# use_site_for_root=True: root (uid=0) 运行时，user_* 自动重定向到 site_*
# appauthor=False: Windows 不添加 author 层级目录
# roaming=True: Windows 使用 Roaming AppData (配置跟随用户漫游)
dirs = PlatformDirs(
    appname="data-collector",
    appauthor=False,
    roaming=True,
    use_site_for_root=True,   # systemd 以 root 运行时自动切换到 site_* 路径
    ensure_exists=False,       # 由启动器负责创建目录和设置权限
)

# 使用 user_* 属性 (use_site_for_root=True 会在 root 时自动切换)
config_dir  = dirs.user_config_dir    # 配置
data_dir    = dirs.user_state_dir     # 持久数据 (非 user_data_dir!)
log_dir     = dirs.user_log_dir       # 日志
cache_dir   = dirs.user_cache_dir     # 缓存 (可安全删除)
runtime_dir = dirs.user_runtime_dir   # 运行时 (PID 文件、Socket)
```

**为什么用 `user_state_dir` 而非 `user_data_dir`？**

| 属性 | Linux 路径 (非 root) | Linux 路径 (root) | 用途 |
|------|---------------------|-------------------|------|
| `user_data_dir` | `~/.local/share/` | `/usr/local/share/` | 只读共享数据 (图标、翻译) |
| `user_state_dir` | `~/.local/state/` | `/var/lib/` | **可变持久数据** (数据库、采集记录) |

FHS 规范中 `/var/lib/` 存放可变状态数据，`/usr/local/share/` 存放只读共享数据。采集数据属于可变状态，应使用 `user_state_dir`。

### 12.3 platformdirs 各平台完整路径映射

**root 运行时 (systemd 服务)**：

| 属性 | Linux | Windows | Android |
|------|-------|---------|---------|
| `user_config_dir` | `/etc/xdg/data-collector` | `C:\ProgramData\data-collector` | `.../shared_prefs/data-collector` |
| `user_state_dir` | `/var/lib/data-collector` | `C:\ProgramData\data-collector` | `.../files/data-collector` |
| `user_log_dir` | `/var/log/data-collector` | `C:\ProgramData\data-collector\Logs` | `.../cache/data-collector/log` |
| `user_cache_dir` | `/var/cache/data-collector` | `C:\ProgramData\data-collector\Cache` | `.../cache/data-collector` |
| `user_runtime_dir` | `/run/data-collector` | `%TEMP%\data-collector` | `.../cache/data-collector/tmp` |

**非 root 运行时 (开发/调试)**：

| 属性 | Linux | Windows |
|------|-------|---------|
| `user_config_dir` | `~/.config/data-collector` | `C:\Users\<User>\AppData\Roaming\data-collector` |
| `user_state_dir` | `~/.local/state/data-collector` | `C:\Users\<User>\AppData\Local\data-collector` |
| `user_log_dir` | `~/.local/state/data-collector/log` | `C:\Users\<User>\AppData\Local\data-collector\Logs` |
| `user_cache_dir` | `~/.cache/data-collector` | `C:\Users\<User>\AppData\Local\data-collector\Cache` |

### 12.4 运维覆盖机制

`platformdirs` 原生支持 XDG 环境变量覆盖，无需自定义 `APP_*_DIR` 变量：

```bash
# Linux: 通过 XDG 变量覆盖默认路径 (运维在 systemd Environment= 中设置)
XDG_CONFIG_HOME=/etc              # user_config_dir → /etc/data-collector
XDG_STATE_HOME=/data              # user_state_dir  → /data/data-collector
XDG_CACHE_HOME=/data/cache        # user_cache_dir  → /data/cache/data-collector

# XDG 规范未定义 log 的覆盖变量，需自定义变量
APP_LOG_DIR=/data/logs/data-collector  # 覆盖 /var/log/data-collector
```

应用代码中的完整路径解析逻辑：

```python
import os
from platformdirs import PlatformDirs

dirs = PlatformDirs(
    appname="data-collector",
    appauthor=False,
    roaming=True,
    use_site_for_root=True,
    ensure_exists=False,   # 启动器负责创建目录
)

# XDG 变量原生覆盖 config/state/cache (platformdirs 自动处理)
# 自定义变量覆盖 log (XDG 未定义 log 环境变量)
config_dir  = dirs.user_config_dir
data_dir    = dirs.user_state_dir
log_dir     = os.environ.get("APP_LOG_DIR", dirs.user_log_dir)
cache_dir   = dirs.user_cache_dir
runtime_dir = dirs.user_runtime_dir
```

启动器负责创建目录并设置权限（在 Python 启动前执行）：

```bash
# Linux (run.sh)
sudo mkdir -p /etc/xdg/data-collector /var/lib/data-collector \
              /var/log/data-collector /var/cache/data-collector /run/data-collector
sudo chown -R $APP_USER:$APP_GROUP /var/lib/data-collector \
                                    /var/log/data-collector \
                                    /var/cache/data-collector
```

### 12.5 platformdirs 关键特性

| 特性 | 说明 |
|------|------|
| `use_site_for_root=True` | root (uid=0) 运行时，`user_*` 自动重定向到 `site_*`，适配 systemd 场景 |
| `ensure_exists=False` | 由启动器创建目录并设置权限，避免应用层 PermissionError |
| `version="1.2.0"` | 自动追加版本子目录，支持多版本数据并存 |
| XDG 环境变量 | 原生支持 `XDG_CONFIG_HOME` / `XDG_STATE_HOME` / `XDG_CACHE_HOME` 等覆盖 |
| `roaming=True` | Windows `user_config_dir` 使用 Roaming AppData，配置跟随用户漫游 |
| `_path` 后缀 | `user_config_path` 返回 `Path` 对象，`user_config_dir` 返回 `str` |
| Android 支持 | 通过 `python4android` / `pyjnius` / `sys.path` 三层回退自动获取 |

> 注意: `platformdirs` 需添加到 `requirements.txt`，体积很小 (~15 KB)。

### 12.6 platformdirs Android 集成说明

Android 环境下 `platformdirs` 需要配合 Chaquopy 使用，确保正确获取应用内部存储路径：

```python
# Android 环境下 platformdirs 路径获取机制
# 1. 通过 pyjnius 获取 Android Context
# 2. 调用 Context.getFilesDir() / getCacheDir() 等方法
# 3. platformdirs 自动适配返回正确路径
```

**requirements.txt 配置**：

```
platformdirs>=4.0.0
pyjnius>=1.5.0  # Android JNI 桥接，Chaquopy 内置
```

**Chaquopy 配置 (build.gradle.kts)**：

```kotlin
chaquopy {
    defaultConfig {
        python {
            version = "3.12"
            // platformdirs 和 pyjnius 由 Chaquopy 自动处理
            pip {
                install("platformdirs>=4.0.0")
            }
        }
    }
}
```

**Android 端路径验证示例**：

```python
# 在 Android 上验证 platformdirs 路径
from platformdirs import PlatformDirs

dirs = PlatformDirs(appname="data-collector", appauthor=False)

# 预期输出 (Android):
# user_config_dir  -> /data/user/0/com.myapp/files/data-collector
# user_state_dir   -> /data/user/0/com.myapp/files/data-collector
# user_cache_dir   -> /data/user/0/com.myapp/cache/data-collector
# user_log_dir     -> /data/user/0/com.myapp/cache/data-collector/log
```

***

## 十三、项目目录结构

```
project/
│
├── PYTHON_VERSION                   ← Python 运行时版本 (3.12.1)
├── VERSION                          ← 应用版本 (1.2.0)
│
├── python/                          ← 共享 Python 代码 (三平台 100% 相同)
│   ├── requirements.txt             ← pip 依赖清单
│   ├── data_collector/
│   │   ├── __init__.py              ← 必须包含 __version__
│   │   ├── __main__.py              ← 统一入口
│   │   ├── app.py                   ← FastAPI 应用
│   │   └── core.py                  ← 业务逻辑
│   ├── bridge.py                    ← Android 调用接口
│   └── static/                      ← 前端文件
│       ├── index.html
│       └── app.js
│
├── shells/                          ← 平台启动器
│   ├── linux/
│   │   ├── run.sh                   ← Bash 启动脚本
│   │   ├── install.sh              ← 安装脚本
│   │   ├── update.sh               ← 增量更新脚本
│   │   └── data-collector.service  ← systemd 配置
│   │
│   ├── windows/
│   │   ├── app_stub.c              ← Embed Stub 源码
│   │   ├── app_stub.rc             ← 版本信息资源
│   │   ├── deploy.ps1              ← 智能部署脚本
│   │   └── install_service.ps1     ← NSSM 服务注册脚本
│   │
│   └── android/
│       ├── app/
│       │   ├── build.gradle.kts    ← Chaquopy 插件配置
│       │   └── src/main/
│       │       ├── AndroidManifest.xml
│       │       ├── java/com/myapp/
│       │       │   ├── MainActivity.kt
│       │       │   ├── PythonService.kt
│       │       │   └── BootReceiver.kt
│       │       └── assets/python-app/  ← 初始代码 (→ 内部存储)
│       ├── build.gradle.kts
│       └── settings.gradle.kts
│
├── build/                           ← 构建脚本
│   ├── build-linux.sh
│   ├── build-windows.sh
│   └── build-android.sh
│
└── .github/workflows/               ← CI/CD
    ├── build-all.yml
    └── release.yml
```

***

## 十四、完整对比表

### 14.1 跨平台对比

| 维度            | Linux                    | Windows                    | Android                |
| ------------- | ------------------------ | -------------------------- | ---------------------- |
| 应用包格式         | .tar.gz                  | .zip                       | .apk                   |
| 全量包体积         | \~40 MB                  | \~20 MB                    | \~35 MB                |
| 增量包体积         | \~3 MB                   | \~3 MB                     | \~3 MB                 |
| Python 运行时    | PBS                      | Embeddable Pkg             | Chaquopy               |
| **部署模式**      | **shared**               | **standalone**             | **standalone**         |
| 运行时位置         | /opt/runtime/            | {app}/runtime/             | APK 内                  |
| 运行时共享         | 多应用共用                    | 应用私有                      | 单应用内                   |
| 应用代码位置        | .../app-{ver}/           | ...\app-{ver}\             | 内部存储 app-{ver}/        |
| 版本切换          | VERSION 文件               | VERSION 文件                 | VERSION 文件             |
| 启动器           | run.sh                   | data\_collector.exe        | APK (Activity+Service) |
| 启动器语言         | Bash                     | C                          | Kotlin                 |
| 启动器体积         | \~1 KB                   | \~50 KB                    | 含在 APK 中               |
| UI 方式         | 浏览器                      | 浏览器/WebView2               | App 内 WebView          |
| 后台运行          | systemd                  | NSSM/WinSW Service         | Foreground Service     |
| 开机自启          | systemd enable           | Service AUTO\_START        | BootReceiver           |
| 崩溃重启          | Restart=always           | Service 恢复策略               | START\_STICKY          |
| 优雅关闭          | SIGTERM                  | Ctrl+C / POST              | bridge.stop\_server()  |
| Shutdown API  | POST /shutdown           | POST /shutdown             | POST /shutdown         |
| 配置文件          | /etc/data-collector/     | C:\ProgramData...\config\\ | 内部存储 config/           |
| 数据文件          | /var/lib/data-collector/ | C:\ProgramData...\data\\   | 内部存储 data/             |
| 日志文件          | /var/log/data-collector/ | C:\ProgramData...\logs\\   | 内部存储 logs/             |
| 全局版本快照        | /opt/versions            | 无 (单应用不需要)                 | 无                      |
| **Python 代码** | **100% 相同**              | **100% 相同**                | **100% 相同**            |
| **前端文件**      | **100% 相同**              | **100% 相同**                | **100% 相同**            |
| **通信协议**      | **HTTP :18080**          | **HTTP :18080**            | **HTTP :18080**        |
| **版本切换机制**    | **VERSION 文件**           | **VERSION 文件**             | **VERSION 文件**         |

### 14.2 部署模式对比

| 维度 | Standalone (Windows/Android) | Shared (Linux) |
|------|:---------------------------:|:--------------:|
| 运行时位置 | `{app}/runtime/` | `/opt/runtime/` |
| 运行时所有权 | 应用私有 | 全局共享 |
| Python 升级影响 | 仅本应用 | 所有应用 |
| 全局版本快照 | 不需要 | `/opt/versions` |
| ._pth 并发写入 | 不会发生 | 可能发生 (需 Mutex/flock) |
| 首次安装包体积 | \~20 MB (Win) / \~35 MB (APK) | \~40 MB |
| 增量升级包体积 | \~3 MB | \~3 MB |
| 多应用总占用 | N x (runtime + app) | 1 x runtime + N x app |

***

## 十五、Windows 特有风险与缓解

| #  | 风险                                                | 影响 | 缓解措施                                         |
| -- | ------------------------------------------------- | -- | -------------------------------------------- |
| W1 | Windows 文件锁：运行中 exe/dll 无法替换                      | 高  | VERSION 文件切换：Stub Exe 永不更新，版本目录可锁但无需替换       |
| W2 | .\_pth 未正确重写导致应用路径缺失                              | 高  | Stub 启动时强制重写 .\_pth；Named Mutex 保护并发写入       |
| W3 | .\_pth 模式下 PYTHONHOME/PYTHONPATH 从 os.environ 被清除 | 中  | 应用代码使用 APP\_VERSION 等自定义环境变量                 |
| W4 | PATH 后插导致系统 Python DLL 优先加载                       | 高  | PATH 前插 runtime                              |
| W5 | 杀软/SmartScreen 拦截                                 | 中  | 代码签名；内网加白名单；Windows Defender 排除目录            |
| W6 | subprocess 继承我们的环境变量                              | 中  | 开发规范禁止裸调用 subprocess                         |
| W7 | Embeddable Package 无 pip                          | 低  | CI 中使用完整 Python 执行 pip --target              |
| W8 | Py\_Main 自 Python 3.11 起已弃用                       | 中  | 已迁移到 Py\_InitializeFromConfig + Py\_RunMain (见第 7.2 节) |
| W9 | vcruntime140.dll 版本冲突                             | 低  | Embeddable Package 自带，PATH 前插确保优先加载          |

***

## 十六、Linux Shared 模式特有风险与缓解

| #  | 风险 | 影响 | 缓解措施 |
| -- | ---- | -- | ------ |
| L1 | runtime 升级影响所有应用 | 高 | 维护窗口期升级；升级前通知所有应用；升级后批量重启 |
| L2 | 应用间依赖版本冲突 (共享标准库) | 低 | 标准库 API 在小版本间高度稳定；pip 依赖通过 PYTHONPATH 隔离 |
| L3 | 全局版本快照 `/opt/versions` 写入冲突 | 低 | 部署脚本使用文件锁保护并发写入 |
| L4 | 多应用同时启动时 PYTHONPATH 环境变量竞争 | 低 | 各应用独立设置 PYTHONPATH，不共享环境变量；使用 systemd EnvironmentFile 隔离 |

> **注意**：`._pth` 文件是 Windows Embeddable Package 特有机制，Linux PBS 通过环境变量控制路径，不存在 `._pth` 并发写入问题。

***

## 十七、实施路线

| 阶段                     |              时间              | 产出                                               |
| ---------------------- | :--------------------------: | ------------------------------------------------ |
| **Phase 1** 基础设施       |            第 1-2 周           | Python 应用标准化，Linux/Windows 全量包构建，VERSION 文件版本切换  |
| **Phase 2** 生产部署       |             第 3 周            | systemd 服务，Embed Stub + .\_pth 重写，NSSM 服务注册，增量更新 |
| **Phase 3** Android 验证 | 第 1-4 周 (与 Phase 1-2 并行 PoC) | Chaquopy + PythonService + WebView 验证            |
| **Phase 4** 完善         |            第 5 周+            | OTA 热更新，CI/CD，业务迁移，旧版本自动清理                       |

***

## 结语

这个方案的本质是：
**一个 Python 应用 = Python 运行时 + 应用代码 + 启动器**

三样东西在三个平台上的形态不同，但组合方式完全相同。开发者只需维护一份 Python 代码，构建系统自动产出三平台安装包。用户安装后开箱即用，无需关心 Python。

v2.0 核心改进：

- **部署模式统一**：standalone 与 shared 不再是两套方案，而是同一套机制在不同平台的默认行为
- **运行时解析策略**：环境变量 `RUNTIME_DIR` 覆盖 + 平台默认路径，启动器逻辑统一
- **Windows standalone**：runtime 在应用目录内，升级只影响本应用，无需考虑多应用协调
- **Linux shared**：runtime 在共享目录，多应用共用，节省空间和带宽
- **Android standalone**：Chaquopy 内置，沙箱隔离，天然独立
- **统一的是机制，不是部署形态**：包格式、版本切换、热更新协议三平台一致，runtime 位置按场景灵活选择
