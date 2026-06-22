# Windows Stub 预编译方案

## 一、背景与问题

### 1.1 当前实现

pyapp 在 Windows 平台打包时，`app_stub.exe`（应用启动器）需要从 C++ 源码实时编译：

```
打包流程：
1. 渲染 app_stub.cpp.j2（Jinja2 模板，注入 app_name、port 等）
2. 渲染 app_stub.rc.j2（资源文件模板，注入图标、版本信息）
3. 使用 MinGW-w64 编译：
   - windres app_stub.rc -O coff -o app_stub.res
   - g++ -o app_name.exe app_stub.cpp app_stub.res -mwindows -O2 -s ...
```

### 1.2 存在的问题

| 问题 | 影响 |
|------|------|
| **需要用户安装 MinGW-w64** | 增加了环境配置门槛，用户体验差 |
| **每次打包都要编译** | 编译耗时（约 5-10 秒），且可能失败 |
| **编译失败降级为 .bat** | 降级方案功能受限（无 UI 模式、无单实例检查） |
| **两套资源修改机制** | stub 用 .rc 编译，runtime 用 rcedit，逻辑不一致 |

### 1.3 briefcase 的做法

beeware/briefcase 项目采用了更合理的方案：

1. **预编译 stub exe**：托管在 AWS S3，按 Python 版本分发
2. **打包时用 rcedit 修改**：复制 stub → 重命名 → rcedit 设置图标和版本信息
3. **零编译依赖**：用户无需安装任何编译工具

参考代码：
- `briefcase/commands/create.py`：stub 下载逻辑
- `briefcase/platforms/windows/app.py`：rcedit 调用逻辑
- stub URL 格式：`https://briefcase-support.s3.amazonaws.com/python/3.12/windows/GUI-Stub-3.12-b12.zip`

---

## 二、方案概述

### 2.1 核心思路

将 `app_stub.cpp` 从 **Jinja2 模板** 改为 **通用 C++ 源码**，所有项目特定信息从 `app.ini` 运行时读取。预编译一次 `pyapp-stub-x64.exe`，打包时只需复制 + rcedit 修改。

### 2.2 改动前后对比

| 方面 | 改动前 | 改动后 |
|------|--------|--------|
| stub 来源 | 每次从 C++ 源码编译 | 预编译 exe，复制使用 |
| 环境依赖 | MinGW-w64 (g++, windres) | 无编译依赖 |
| 资源修改 | .rc 文件编译嵌入 | rcedit 修改（与 runtime 一致） |
| 打包耗时 | 编译约 5-10 秒 | 复制 + rcedit 约 1 秒 |
| 失败降级 | .bat 启动脚本 | 无降级（stub 必须可用） |

### 2.3 stub exe 托管方式

**方案 B（推荐）**：随 pyapp 包内置

```
pyapp/
└── stubs/
    └── windows/
        └── pyapp-stub-x64.exe   # 约 200-300KB
```

优点：
- 零网络依赖，即装即用
- stub exe 很小，对包体积影响可忽略
- 版本管理简单，随 pyapp 发布

备选方案 A：GitHub Release 托管（可作为 fallback）

---

## 三、详细改动

### 3.1 通用化 `app_stub.cpp`

**当前**：24 处 Jinja2 模板变量硬编码

```cpp
// 示例：硬编码的模板变量
g_hMutex = CreateMutexA(NULL, TRUE, "{{ app_name }}-SingleInstance");
wc.lpszClassName = "{{ app_name }}WndClass";
snprintf(cmdLine, ..., "\"%s\\runtime\\{{ app_name }}-runtime.exe\" -m %s", ...);
```

**改为**：全部从 `app.ini` 运行时读取

```cpp
// 新增 AppConfig 字段
struct AppConfig {
    // ... 原有字段 ...
    char app_name[128];     // 应用名
    char app_module[128];   // Python 模块名
    char version_dir[256];  // 版本目录名
};

// 动态拼接
char mutexName[256];
snprintf(mutexName, sizeof(mutexName), "%s-SingleInstance", g_cfg.app_name);
g_hMutex = CreateMutexA(NULL, TRUE, mutexName);

char wndClassName[256];
snprintf(wndClassName, sizeof(wndClassName), "%sWndClass", g_cfg.app_name);
wc.lpszClassName = wndClassName;
```

**24 处模板变量替换对照表**：

| 位置 | 当前模板变量 | 改为动态读取 |
|------|-------------|-------------|
| Mutex 名 | `{{ app_name }}-SingleInstance` | `g_cfg.app_name` 拼接 |
| 窗口类名 | `{{ app_name }}WndClass` | `g_cfg.app_name` 拼接 |
| 窗口标题默认值 | `{{ app_name }}` | `g_cfg.app_name` |
| 托盘提示 | `{{ app_name }}` | `g_cfg.app_name` |
| 所有 MessageBox 标题 | `{{ app_name }}` | `g_cfg.app_name` |
| 命令行 runtime exe | `{{ app_name }}-runtime.exe` | `g_cfg.app_name` 拼接 |
| 帮助文本 | `{{ app_name }}.exe` | `g_cfg.app_name` 拼接 |
| 默认 port | `{{ port }}` | 从 ini 读取 |
| 默认 app_module | `{{ app_module }}` | 从 ini 读取 |
| 默认 version_dir | `{{ app_name }}-{{ version }}` | 从 ini 读取 |

### 3.2 修改 `app.ini.j2` 模板

新增 `[app]` section：

```ini
[app]
; 应用名称（用于 Mutex、窗口类名、消息框标题等）
name = {{ app_name }}
; Python 模块名
module = {{ app_module }}
; 版本目录名
version_dir = {{ app_name }}-{{ version }}

[launch]
mode = ui

[ui]
title = {{ app_name }}
width = 1280
height = 800
...

[server]
port = {{ port }}
```

### 3.3 新增 `_get_stub_exe` 方法

参考 `_get_rcedit` 的模式：

```python
class WindowsPlatform(BasePlatform):
    STUB_VERSION = "1.0.0"

    def _get_stub_exe(self) -> Optional[Path]:
        """获取预编译 stub exe"""
        from ..core.cache import CacheManager

        cache_manager = CacheManager()
        tools_dir = cache_manager.cache_dir / "tools"
        stub_dir = tools_dir / f"pyapp-stub-v{self.STUB_VERSION}"
        stub_exe = stub_dir / "pyapp-stub.exe"

        # 优先从内置目录查找
        builtin_stub = Path(__file__).parent.parent / "stubs" / "windows" / "pyapp-stub-x64.exe"
        if builtin_stub.exists():
            return builtin_stub

        # 从缓存查找
        if stub_exe.exists():
            return stub_exe

        # 从 GitHub Release 下载（fallback）
        url = f"https://github.com/{user}/pyapp/releases/download/stub-v{self.STUB_VERSION}/pyapp-stub-x64.exe"
        # ... 下载逻辑 ...

        return stub_exe
```

### 3.4 新增 `_create_stub_exe` 方法

```python
def _create_stub_exe(self, bundle_dir: Path, app_name: str, version: str,
                     icon_path: Optional[Path] = None) -> Optional[Path]:
    """复制预编译 stub 并用 rcedit 修改图标和版本信息"""
    stub_src = self._get_stub_exe()
    if not stub_src:
        self.logger.error("Pre-built stub not available")
        return None

    exe_path = bundle_dir / f"{app_name}.exe"
    shutil.copy2(stub_src, exe_path)
    self.logger.info(f"Copied stub: {stub_src.name} -> {exe_path.name}")

    # 用 rcedit 修改 VERSIONINFO 和图标
    rcedit_path = self._get_rcedit()
    if rcedit_path:
        try:
            cmd = [
                str(rcedit_path), str(exe_path),
                "--set-version-string", "FileDescription", app_name,
                "--set-version-string", "ProductName", app_name,
                "--set-version-string", "OriginalFilename", f"{app_name}.exe",
                "--set-version-string", "InternalName", app_name,
                "--set-file-version", version,
                "--set-product-version", version,
            ]
            if icon_path and icon_path.exists():
                cmd.extend(["--set-icon", str(icon_path)])
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.logger.success(f"Stub resources updated: {exe_path.name}")
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"rcedit failed on stub: {e}")

    return exe_path
```

### 3.5 修改 `build()` 流程

```python
def build(self, project_dir: Path, config: Dict[str, Any], build_type: str = "debug") -> BuildResult:
    """构建 Windows 安装包"""
    # 改动后的流程（8 步）：
    # 1. 下载 Python runtime
    # 2. 创建 runtime exe（复制 + rcedit）
    # 3. 同步 Python 源码
    # 4. 同步前端资源
    # 5. 安装依赖
    # 6. 创建 Stub exe（复制预编译 + rcedit）  ← 新逻辑
    # 7. 下载 WebView2Loader.dll
    # 8. 渲染 app.ini + 打包 ZIP

    # ... 具体实现 ...
```

### 3.6 删除的代码

| 删除项 | 文件位置 | 原因 |
|--------|----------|------|
| `_compile_stub()` | `windows.py` 第 267-283 行 | 不再需要 MinGW 编译 |
| `_compile_stub_mingw()` | `windows.py` 第 285-331 行 | 同上 |
| `_create_launch_script()` | `windows.py` 第 333-349 行 | 不再有编译失败降级 |
| `_update_stub_sources()` | `windows.py` 第 602-604 行 | 不再需要渲染 stub 源码 |
| `_check_mingw()` | `windows.py` 第 38-48 行 | 不再需要 MinGW 检查 |
| `check_environment()` MinGW 检查 | `windows.py` 第 30-36 行 | 同上 |
| stub 模板渲染 | `_render_all_templates()` 第 651-653 行 | 只保留 app.ini 渲染 |
| `app_stub.rc.j2` | templates 目录 | 不再需要 .rc 资源文件 |
| `build.bat.j2` | templates 目录 | 不再需要手动构建脚本 |
| `_create_zip()` exclude_files | `windows.py` 第 584-589 行 | 不再生成编译中间文件 |

---

## 四、stub 编译与发布

### 4.1 编译命令

通用化后的 `app_stub.cpp` 需要编译一次：

```bash
# Windows (MinGW-w64)
g++ -o pyapp-stub-x64.exe app_stub.cpp \
    -mwindows -O2 -s \
    -static-libgcc -static-libstdc++ \
    -lwinhttp -lole32 -loleaut32 -lshell32 -lgdi32 -lws2_32
```

编译产物约 200-300KB（静态链接 + strip 后）。

### 4.2 发布流程

1. 将编译好的 `pyapp-stub-x64.exe` 放入 `pyapp/stubs/windows/` 目录
2. 随 pyapp 版本发布（在 `pyproject.toml` 中配置包包含该文件）
3. 如需更新 stub，修改 `STUB_VERSION` 并重新编译发布

### 4.3 stub 版本管理

```python
class WindowsPlatform(BasePlatform):
    STUB_VERSION = "1.0.0"  # stub 版本号，与 pyapp 版本独立
```

当 stub 功能更新时（如新增配置项、修复 bug），更新此版本号，pyapp 会自动检查并使用新版本。

---

## 五、pyapp 构建与分发

### 5.1 当前状态

pyapp 当前是纯 Python 包，使用 setuptools 构建：

```
pyapp/
├── pyproject.toml      # setuptools 构建
├── pyapp/              # 纯 Python 代码
│   ├── cli.py
│   ├── platforms/
│   └── templates/
└── myapp/              # 示例项目（不应打包）
```

**现状问题**：
- 没有 CI/CD，手动发布
- 如果内置 stub exe，需要处理二进制文件分发

### 5.2 目录结构调整

为支持 stub 源码与分发分离，目录结构调整为：

```
pyapp/
├── pyproject.toml
├── stub-src/                         # 新增：stub 源码目录（不随 pyapp 分发）
│   └── windows/
│       ├── app_stub.cpp              # 通用化 stub 源码
│       └── WebView2.h                # 编译时头文件
├── pyapp/
│   ├── cli.py
│   ├── platforms/
│   │   └── windows.py
│   ├── templates/
│   │   └── shells/
│   │       └── windows/
│   │           └── app.ini.j2        # 只保留配置模板
│   └── stubs/                        # 新增：预编译 stub 目录（随 pyapp 分发）
│       └── windows/
│           └── pyapp-stub-x64.exe    # 预编译 stub（约 300KB）
└── .github/
    └── workflows/
        ├── build-stub.yml            # stub 构建 CI
        └── release.yml               # pyapp 发布 CI
```

**关键设计**：
- `stub-src/` 目录不随 pyapp 包分发，只用于 CI 编译
- `pyapp/stubs/` 目录随 pyapp 包分发，包含预编译的 stub exe
- `templates/shells/windows/` 只保留 `app.ini.j2` 配置模板，删除其他模板文件

### 5.3 pyproject.toml 配置

确保 stub exe 被包含在 Python 包中：

```toml
[project]
name = "pyapp-cli"
version = "0.1.0"
...

[tool.setuptools.packages.find]
where = ["."]
include = ["pyapp*"]

[tool.setuptools.package-data]
pyapp = [
    "templates/**/*",
    "stubs/**/*",        # 包含 stub exe
]
```

或使用 MANIFEST.in：

```
include pyapp/templates/**/*
include pyapp/stubs/**/*
```

### 5.4 stub 构建 CI

`.github/workflows/build-stub.yml`：

```yaml
name: Build Windows Stub

on:
  push:
    tags:
      - 'stub-v*'          # stub 版本标签触发
  workflow_dispatch:       # 手动触发

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup MinGW
        uses: msys2/setup-msys2@v2
        with:
          install: mingw-w64-x86_64-gcc

      - name: Build stub
        shell: msys2 {0}
        run: |
          cd stub-src/windows
          g++ -o pyapp-stub-x64.exe app_stub.cpp \
              -mwindows -O2 -s \
              -static-libgcc -static-libstdc++ \
              -lwinhttp -lole32 -loleaut32 -lshell32 -lgdi32 -lws2_32

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: pyapp-stub
          path: stub-src/windows/pyapp-stub-x64.exe

      - name: Upload to Release
        if: startsWith(github.ref, 'refs/tags/stub-v')
        uses: softprops/action-gh-release@v1
        with:
          files: stub-src/windows/pyapp-stub-x64.exe

      # 自动提交到仓库（更新内置 stub）
      - name: Commit to repo
        run: |
          mkdir -p pyapp/stubs/windows
          cp stub-src/windows/pyapp-stub-x64.exe pyapp/stubs/windows/
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add pyapp/stubs/windows/pyapp-stub-x64.exe
          git commit -m "Update pre-built stub to v${{ github.ref_name }}"
          git push
```

### 5.5 pyapp 发布 CI

`.github/workflows/release.yml`：

```yaml
name: Release pyapp

on:
  push:
    tags:
      - 'v*'          # pyapp 版本标签（如 v0.1.0）
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install build tools
        run: pip install build

      - name: Build package
        run: python -m build

      - name: Create GitHub Release
        if: startsWith(github.ref, 'refs/tags/v')
        uses: softprops/action-gh-release@v1
        with:
          files: dist/*
          generate_release_notes: true
```

### 5.6 stub 版本与 pyapp 版本的关系

采用独立版本管理（推荐）：

```
pyapp-cli v0.1.0  包含 stub v1.0.0
pyapp-cli v0.2.0  包含 stub v1.0.0  (stub 无变化)
pyapp-cli v0.3.0  包含 stub v1.1.0  (stub 有新功能)
```

- stub 有独立版本号 `STUB_VERSION`
- stub 更新时发布 `stub-v1.x.x` tag，触发 CI 构建
- pyapp 发布时检查是否需要更新内置 stub

### 5.7 发布流程

#### stub 更新流程

```
1. 修改 stub-src/windows/app_stub.cpp 源码
2. 更新 windows.py 中的 STUB_VERSION（如 "1.0.0" -> "1.1.0"）
3. 如有不兼容变更，更新 STUB_COMPATIBLE_VERSIONS（移除不兼容的旧版本）
4. 提交代码：git add . && git commit -m "Update stub to v1.1.0"
5. Push：git push
6. 创建 Git tag：git tag stub-v1.1.0
7. Push tag：git push origin stub-v1.1.0
8. CI 自动构建 stub，上传到 GitHub Release，并自动提交到 pyapp/stubs/windows/
```

**注意**：CI 会自动将编译后的 stub 提交到仓库，无需手动复制。

#### pyapp 发布流程

```
1. 更新 pyproject.toml 版本号
2. 确保 stub 版本正确（检查 STUB_VERSION）
3. 创建 Git tag：git tag v0.2.0
4. Push tag：git push origin v0.2.0
5. CI 自动构建 pyapp 包，发布到 GitHub Release
```

### 5.8 Console stub 说明

当前方案只提供一个 stub exe，通过 `--console` 参数切换运行模式。这与 briefcase 的做法不同（briefcase 区分 GUI stub 和 Console stub）。

**当前设计**：
- 一个 stub 支持 ui/console/headless 三种模式
- 通过命令行参数或 app.ini 配置切换
- Console 模式下使用 `AllocConsole()` 创建控制台窗口

**后续扩展**（可选）：
如果需要更好的控制台体验（如彩色输出、进度条），可以考虑：
- 编译时使用 `-mconsole` 替代 `-mwindows` 创建单独的 Console stub
- Console stub 直接输出到控制台，无需 `AllocConsole()`
- 当前方案暂不实现，后续可按需扩展

### 5.9 用户安装和使用

```bash
# 从 GitHub Release 下载并安装 pyapp
pip install https://github.com/{owner}/pyapp/releases/download/v0.1.0/pyapp_cli-0.1.0-py3-none-any.whl

# 或者从源码安装
git clone https://github.com/{owner}/pyapp.git
cd pyapp
pip install .

# 打包项目（stub 已内置，无需下载）
pyapp build windows

# 如果内置 stub 不存在或版本过旧，自动从 GitHub Release 下载
```

### 5.10 `_get_stub_exe` 完整实现

```python
class WindowsPlatform(BasePlatform):
    # stub 版本配置
    STUB_VERSION = "1.0.0"
    STUB_COMPATIBLE_VERSIONS = ["1.0.0"]  # 兼容的旧版本列表（用于回滚）
    
    # GitHub 配置（可通过环境变量覆盖）
    GITHUB_OWNER = os.environ.get("PYAPP_GITHUB_OWNER", "your-github-user")
    STUB_DOWNLOAD_URL = (
        f"https://github.com/{GITHUB_OWNER}/pyapp/releases/download/"
        f"stub-v{STUB_VERSION}/pyapp-stub-x64.exe"
    )

def _get_stub_exe(self) -> Optional[Path]:
    """获取预编译 stub exe（内置优先，远程 fallback，支持回滚）"""
    from ..core.cache import CacheManager
    import urllib.request

    cache_manager = CacheManager()
    tools_dir = cache_manager.cache_dir / "tools"

    # 优先级 1：内置 stub（零网络依赖）
    builtin_stub = Path(__file__).parent.parent / "stubs" / "windows" / "pyapp-stub-x64.exe"
    if builtin_stub.exists() and builtin_stub.stat().st_size > 0:
        # 内置 stub 版本由 pyapp 版本决定，直接返回
        self.logger.info(f"Using builtin stub: {builtin_stub}")
        return builtin_stub

    # 优先级 2：缓存 stub（当前版本）
    stub_dir = tools_dir / f"pyapp-stub-v{self.STUB_VERSION}"
    stub_exe = stub_dir / "pyapp-stub.exe"
    if stub_exe.exists() and stub_exe.stat().st_size > 0:
        self.logger.info(f"Using cached stub v{self.STUB_VERSION}: {stub_exe}")
        return stub_exe

    # 优先级 3：从 GitHub Release 下载
    self.logger.info(f"Downloading stub v{self.STUB_VERSION}...")
    try:
        stub_dir.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(self.STUB_DOWNLOAD_URL, str(stub_exe))

        if stub_exe.exists() and stub_exe.stat().st_size > 0:
            self.logger.success(f"Stub downloaded: {stub_exe}")
            return stub_exe
        else:
            stub_exe.unlink(missing_ok=True)
            self.logger.error("Stub download failed or file is empty")
    except Exception as e:
        self.logger.error(f"Failed to download stub: {e}")

    # 优先级 4：回滚到兼容的旧版本
    for old_version in self.STUB_COMPATIBLE_VERSIONS:
        if old_version == self.STUB_VERSION:
            continue  # 跳过当前版本（已尝试）
        old_stub_dir = tools_dir / f"pyapp-stub-v{old_version}"
        old_stub_exe = old_stub_dir / "pyapp-stub.exe"
        if old_stub_exe.exists() and old_stub_exe.stat().st_size > 0:
            self.logger.warning(f"Using fallback stub v{old_version}: {old_stub_exe}")
            return old_stub_exe

    self.logger.error("No stub available")
    return None
```

---

## 六、风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| rcedit 不能修改已签名的 exe | 签名会损坏 | 签名必须在 rcedit 之后执行（当前已如此） |
| Mutex 名动态拼接字符集问题 | 非ASCII 字符可能异常 | 限制 `app_name` 为 ASCII 字母数字和连字符 |
| app.ini 缺失或损坏 | stub 无法读取配置 | `config_set_defaults` 提供合理默认值 |
| 预编译 stub 被杀毒软件误报 | 用户安装受阻 | 使用 strip 和静态链接减少误报；必要时提交白名单 |
| stub 功能更新需重新编译 | 旧版 pyapp 可能不兼容 | `STUB_VERSION` 管理版本，不兼容时提示升级 |
| stub 与 app.ini 配置格式不兼容 | 旧版 stub 无法读取新版 app.ini | 在 app.ini 中添加 `stub_version` 字段，stub 启动时检查版本兼容性 |
| GitHub Release 下载失败 | 无法获取 stub | 支持回滚到兼容的旧版本（`STUB_COMPATIBLE_VERSIONS`） |

### 6.1 签名流程说明（可选）

如果需要对打包后的 exe 进行代码签名：

```
签名流程：
1. 打包完成后，先执行 rcedit 修改资源
2. 再使用 signtool 签名（签名必须在 rcedit 之后）
3. 签名命令：signtool sign /f cert.pfx /p password /t timestamp_url app.exe

注意事项：
- rcedit 会损坏已签名的 exe，因此签名必须在最后一步
- stub exe 本身不需要签名（用户打包时才签名）
- 如需对 stub exe 本身签名，需要在 CI 编译后、rcedit 之前完成
```

---

## 七、文件变更总览

| 文件 | 操作 | 说明 |
|------|------|------|
| `stub-src/windows/app_stub.cpp` | **新增** | 通用化 stub 源码（从 app_stub.cpp.j2 迁移并去掉 Jinja2 变量） |
| `stub-src/windows/WebView2.h` | **移动** | 从 templates 移到 stub-src（编译时头文件，不随 pyapp 分发） |
| `pyapp/templates/shells/windows/app_stub.cpp.j2` | **删除** | 不再需要模板文件 |
| `pyapp/templates/shells/windows/app_stub.rc.j2` | **删除** | 不再需要资源文件模板 |
| `pyapp/templates/shells/windows/build.bat.j2` | **删除** | 不再需要手动构建脚本 |
| `pyapp/templates/shells/windows/WebView2.h` | **删除** | 移到 stub-src 目录 |
| `pyapp/templates/shells/windows/app.ini.j2` | **修改** | 新增 `[app]` section 和 `stub_version` 字段 |
| `pyapp/platforms/windows.py` | **重构** | 删除编译相关方法，新增 `_get_stub_exe` / `_create_stub_exe`，添加版本配置 |
| `pyapp/stubs/windows/pyapp-stub-x64.exe` | **新增** | 预编译 stub 二进制（约 200-300KB） |
| `.github/workflows/build-stub.yml` | **新增** | stub 构建 CI |
| `.github/workflows/release.yml` | **新增** | pyapp 发布 CI |

---

## 八、工作量评估

| 任务 | 复杂度 | 预估工作量 |
|------|--------|-----------|
| 通用化 `app_stub.cpp`（24 处模板变量 → ini 读取） | 中等 | 主要工作，需仔细处理字符串拼接 |
| 新增 `_get_stub_exe` / `_create_stub_exe` | 简单 | 参考现有 `_get_rcedit` 模式 |
| 修改 `build()` 流程 | 简单 | 删除编译步骤，替换为复制+rcedit |
| 修改 `app.ini.j2` | 简单 | 加 3 行配置 |
| 删除废弃代码 | 简单 | 直接删除 |
| 编译并发布 `pyapp-stub-x64.exe` | 简单 | 一次性操作 |
| 测试验证 | 中等 | 验证 UI/console/headless 三种模式 |

---

## 九、附录：briefcase 参考代码

### 9.1 stub 下载 URL 构造

```python
# briefcase/commands/create.py
def stub_binary_url(self, support_revision: str, is_console_app: bool) -> str:
    stub_type = "Console" if is_console_app else "GUI"
    return (
        "https://briefcase-support.s3.amazonaws.com/python/"
        f"{self.python_version_tag}/"
        f"{self.platform}/"
        f"{self.stub_binary_filename(support_revision, is_console_app)}"
    )
```

### 9.2 rcedit 调用参数

```python
# briefcase/platforms/windows/app.py
self.tools.subprocess.run(
    [
        self.tools.rcedit.rcedit_path,
        exe_path,
        "--set-version-string", "CompanyName", app.author,
        "--set-version-string", "FileDescription", app.formal_name,
        "--set-version-string", "FileVersion", app.version,
        "--set-version-string", "InternalName", app.module_name,
        "--set-version-string", "OriginalFilename", exe_name,
        "--set-version-string", "ProductName", app.formal_name,
        "--set-version-string", "ProductVersion", app.version,
        "--set-icon", "icon.ico",
    ],
    check=True,
    cwd=self.bundle_path(app),
)
```

### 9.3 rcedit 工具管理

```python
# briefcase/integrations/rcedit.py
class RCEdit(ManagedTool):
    name = "rcedit"
    download_url = "https://github.com/electron/rcedit/releases/download/v2.0.0/rcedit-x64.exe"
```