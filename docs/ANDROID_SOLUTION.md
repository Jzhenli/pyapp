# Android 打包方案总结

## 概述

本文档总结了基于 **Chaquopy + FastAPI + WebView** 的 Android 应用打包方案，验证了在 Android 平台上运行 Python Web 服务的可行性。

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      Android Application                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐         ┌─────────────────────────┐   │
│  │  MainActivity   │         │     PythonService       │   │
│  │   (Activity)    │         │   (Foreground Service)  │   │
│  ├─────────────────┤         ├─────────────────────────┤   │
│  │  - 动态创建     │         │  - Chaquopy Python 运行时│   │
│  │    WebView      │────────▶│  - FastAPI + Uvicorn    │   │
│  │  - 加载本地     │  HTTP   │  - 端口: 18080          │   │
│  │    HTTP 服务    │  请求   │  - 后台持续运行          │   │
│  └─────────────────┘         └─────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 技术栈

| 组件 | 技术选型 | 版本 |
|------|---------|------|
| Android 构建工具 | Gradle | 8.5 |
| Android SDK | minSdk | 24 (Android 7.0) |
| Python 运行时 | Chaquopy | 15.0.1 |
| Python 版本 | Python | 3.10 |
| Web 框架 | FastAPI | 0.136.1 |
| ASGI 服务器 | Uvicorn | 0.27.0+ |
| UI 渲染 | WebView | 动态创建 |

---

## 项目结构

```
android-demo/
├── settings.gradle.kts              # Gradle 设置
├── build.gradle.kts                 # 项目级配置
├── gradle.properties
├── README.md
│
├── scripts/                         # 构建脚本
│   ├── install_android_sdk.py       # 自动安装 JDK + Android SDK
│   └── build_android.py             # 构建 APK
│
├── briefcase/                       # Briefcase 配置（可选）
│   └── pyproject.toml
│
└── app/                             # Android 应用模块
    ├── build.gradle.kts             # Chaquopy 配置
    ├── proguard-rules.pro
    │
    └── src/main/
        ├── AndroidManifest.xml      # 清单文件
        │
        ├── java/com/demo/datacollector/
        │   ├── MainActivity.kt      # 主界面（WebView Shell）
        │   ├── PythonService.kt     # Python 前台服务
        │   └── BootReceiver.kt      # 开机自启
        │
        ├── python/                  # Python 源码（Chaquopy 默认路径）
        │   ├── bridge.py            # Python 桥接模块
        │   └── data_collector/
        │       ├── __init__.py
        │       └── app.py           # FastAPI 应用
        │
        └── res/                     # Android 资源
            ├── layout/
            ├── values/
            └── drawable/
```

---

## 关键配置

### 1. build.gradle.kts (Chaquopy 配置)

```kotlin
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python") version "15.0.1"
}

android {
    defaultConfig {
        // Python 版本
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }
}

chaquopy {
    productFlavors {
        getByName("default") {
            python.version = "3.10"
            
            pip {
                // 自定义 PyPI 仓库
                options("--extra-index-url", "https://jzhenli.github.io/my-pypi/simple")
                
                // 依赖
                install("uvicorn>=0.27.0")
                install("fastapi==0.136.1")
                install("platformdirs>=4.0.0")
                // ... 其他依赖
            }
        }
    }
}
```

### 2. AndroidManifest.xml

```xml
<manifest>
    <!-- 权限 -->
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
    
    <application>
        <!-- 主 Activity -->
        <activity android:name=".MainActivity" />
        
        <!-- Python 前台服务 -->
        <service
            android:name=".PythonService"
            android:foregroundServiceType="dataSync" />
        
        <!-- 开机自启 -->
        <receiver android:name=".BootReceiver">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
            </intent-filter>
        </receiver>
    </application>
</manifest>
```

### 3. Python 依赖优先级

Chaquopy 默认从以下源下载包（按优先级）：

1. `https://jzhenli.github.io/my-pypi/simple`（自定义仓库）
2. `https://chaquo.com/pypi-13.1`（Chaquopy 官方，Android 兼容包）
3. `https://pypi.org/simple`（标准 PyPI）

---

## 核心实现

### 1. 动态创建 WebView（关键！）

**问题**：XML 布局中定义的 WebView 会导致 `tile memory limits exceeded` 错误，页面无法渲染。

**解决方案**：参考 Toga 框架，在代码中动态创建 WebView。

```kotlin
class MainActivity : AppCompatActivity() {
    private var webView: WebView? = null
    
    private fun loadWebView() {
        // 动态创建 WebView
        webView = WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                setSupportZoom(true)
                builtInZoomControls = true
                displayZoomControls = false
            }
            webViewClient = object : WebViewClient() { ... }
        }
        rootLayout.addView(webView)
        webView?.loadUrl("http://127.0.0.1:18080")
    }
    
    override fun onDestroy() {
        webView?.apply {
            stopLoading()
            destroy()
        }
        webView = null
        super.onDestroy()
    }
}
```

### 2. Python 前台服务

```kotlin
class PythonService : Service() {
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 创建通知渠道
        createNotificationChannel()
        
        // 启动前台服务
        startForeground(NOTIFICATION_ID, notification)
        
        // 启动 Python 服务
        startPythonServer()
        
        // 服务被杀死后自动重启
        return START_STICKY
    }
    
    private fun startPythonServer() {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val python = Python.getInstance()
                val module = python.getModule("bridge")
                module.callAttr("start_server", 18080)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to start Python server", e)
            }
        }
    }
}
```

### 3. Python 桥接模块

```python
# bridge.py
import data_collector.app as app_module

_server = None

def start_server(port: int = 18080) -> bool:
    """启动 FastAPI 服务器"""
    global _server
    try:
        _server = app_module.run_server(port)
        return True
    except Exception as e:
        print(f"Failed to start server: {e}")
        return False

def stop_server() -> bool:
    """停止服务器"""
    global _server
    if _server:
        _server.should_exit = True
        return True
    return False
```

### 4. FastAPI 应用

```python
# data_collector/app.py
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
async def index():
    return HTMLResponse(content=get_index_html())

@app.get("/api/data")
async def get_data():
    import random
    return {
        "temperature": round(random.uniform(20, 30), 1),
        "humidity": round(random.uniform(40, 60), 1),
        "cpu": round(random.uniform(10, 60), 1),
        "memory": round(random.uniform(30, 80), 1),
    }

def run_server(port: int = 18080):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    server.run()
    return server
```

---

## 构建流程

### 方式一：自动安装脚本（推荐）

```powershell
# 1. 安装 JDK + Android SDK
python scripts/install_android_sdk.py

# 2. 构建 APK
python scripts/build_android.py
```

### 方式二：手动构建

```powershell
# 前提：已安装 JDK 17 和 Android SDK

# 设置环境变量
$env:JAVA_HOME = "C:\Users\{user}\.android-jdk\jdk-17.0.17+10"
$env:ANDROID_HOME = "C:\Users\{user}\.android-sdk"

# 构建
cd android-demo
.\gradlew.bat assembleDebug
```

### 方式三：使用 Briefcase

```powershell
pip install briefcase
cd briefcase
briefcase create android
briefcase build android
briefcase run android
```

---

## 遇到的问题与解决方案

### 问题 1：WebView 空白页面

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| `tile memory limits exceeded` | XML 布局中 WebView 与 Python 进程资源竞争 | 动态创建 WebView，延迟初始化 |

### 问题 2：Python 模块找不到

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| `ModuleNotFoundError: No module named 'bridge'` | Python 源码路径错误 | 放到 `src/main/python/` 目录 |

### 问题 3：依赖下载超时

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| `ReadTimeoutError` | 网络问题 | 添加 `--timeout` 选项，配置代理 |

### 问题 4：Gradle 构建失败

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| `Unable to delete file` | Java 进程锁定文件 | 构建前停止 Java 进程 |
| `ClassNotFoundException: GradleWrapperMain` | Gradle Wrapper 不完整 | 重新生成 Wrapper |

### 问题 5：Python 版本不兼容

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| `buildPython version incompatible` | 系统 Python 与 Chaquopy Python 版本不一致 | 使用相同版本（如 3.10） |

---

## 服务生命周期

```
┌─────────────────────────────────────────────────────────────┐
│                    用户操作                                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  打开 App                                                    │
│      ↓                                                       │
│  MainActivity.onCreate()                                     │
│      ↓                                                       │
│  startForegroundService(PythonService)                       │
│      ↓                                                       │
│  PythonService.onCreate() → startForeground()                │
│      ↓                                                       │
│  Python 启动 FastAPI (127.0.0.1:18080)                       │
│      ↓                                                       │
│  WebView 加载 http://127.0.0.1:18080                         │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  按 Home 键 / 划掉最近任务                                   │
│      ↓                                                       │
│  Activity 销毁，WebView 销毁                                 │
│      ↓                                                       │
│  Python 服务继续运行（前台服务）                             │
│                                                              │
├─────────────────────────────────────────────────────────────┤
│  卸载应用                                                    │
│      ↓                                                       │
│  整个应用进程被杀死                                          │
│      ↓                                                       │
│  Python 服务停止                                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 与 Briefcase/Toga 对比

| 特性 | 本方案 | Briefcase + Toga |
|------|--------|------------------|
| Python 运行时 | Chaquopy | Chaquopy |
| UI 框架 | WebView + FastAPI | Toga (原生组件) |
| WebView 创建 | 动态创建 | 动态创建 |
| 构建工具 | Gradle / Python 脚本 | Briefcase CLI |
| 灵活性 | 高（完全自定义） | 中（受 Toga 限制） |
| 学习曲线 | 较陡 | 平缓 |
| 适用场景 | 复杂 Web UI | 简单原生 UI |

---

## 最佳实践

### 1. WebView 创建

- ✅ **推荐**：动态创建 WebView，延迟初始化
- ❌ **避免**：在 XML 布局中定义 WebView

### 2. Python 服务

- ✅ **推荐**：使用前台服务 + 通知
- ✅ **推荐**：返回 `START_STICKY` 确保服务重启
- ❌ **避免**：在 Activity 中直接运行 Python

### 3. 依赖管理

- ✅ **推荐**：优先使用 Chaquopy 官方仓库
- ✅ **推荐**：指定具体版本号
- ❌ **避免**：使用不兼容 Android 的包

### 4. 资源清理

```kotlin
override fun onDestroy() {
    webView?.apply {
        stopLoading()
        settings.javaScriptEnabled = false
        clearCache(true)
        clearHistory()
        removeAllViews()
        destroy()
    }
    webView = null
    super.onDestroy()
}
```

---

## 参考资料

- [Chaquopy 官方文档](https://chaquo.com/chaquopy/doc/current/)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Toga WebView 实现](https://github.com/beeware/toga/blob/main/android/src/toga_android/widgets/webview.py)
- [Briefcase 项目](https://github.com/beeware/briefcase)

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2024-01-15 | 初始版本，验证方案可行性 |
