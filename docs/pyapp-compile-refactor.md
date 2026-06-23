# PyApp 命令重构方案

## 1. 问题分析

### 当前命令职责

| 命令 | 当前实现 | 问题 |
|------|---------|------|
| `pyapp build` | 下载运行时 + 同步源码 + 安装依赖 + **打包** | 已包含打包步骤 |
| `pyapp package` | 调用 `build(release)` + 签名 | 重复执行所有步骤，功能重叠 |

### 问题场景

如果中间插入 `compile` 步骤：

```
build (已生成 ZIP) → compile (编译源码) → package (重新 build，覆盖修改)
```

导致：
1. `build` 已经生成 ZIP 包
2. `compile` 修改 `bundles/` 下的源码
3. `package` 重新执行 `build`，覆盖 `compile` 的修改

---

## 2. 重构目标

将命令职责分离，支持中间插入可选步骤：

```
build (准备) → compile (可选，编译) → package (打包)
```

---

## 3. 新命令职责划分

### 3.1 `pyapp build` - 准备构建目录

**职责**：准备 `bundles/` 目录结构，**不打包**。build 阶段写入 `build.meta.json` 记录构建元数据（arch、build_type 等），供 package 阶段读取。

| 步骤 | 操作 |
|------|------|
| 1 | 下载 Python 运行时 |
| 2 | 同步 Python 源码 (`src/` → `bundles/{platform}/{app_name}-{version}/app/`) |
| 3 | 同步前端资源 (`frontend/dist/` → `app/{module}/resources/static/`) |
| 4 | 安装 pip 依赖 (`bundles/{platform}/{app_name}-{version}/app_packages/`) |
| 5 | 生成启动脚本/配置文件 |
| 6 | 写入 `bundles/{platform}/build.meta.json`（记录 arch、build_type、app_name、version） |

**输出**：`bundles/{platform}/` 目录

**返回**：`BuildResult(success=True, output_path=bundle_dir)`（目录路径，而非 ZIP）

> **注意**：Android 平台的源码路径不同，为 `bundles/android/app/src/main/python/{app_module}/`（Chaquopy 默认位置）。Android 的 build 阶段**不运行 Gradle**，Gradle 构建移至 package 阶段执行。

### 3.2 `pyapp compile` - 编译源码（可选）

**职责**：使用 Nuitka 将 Python 源码编译为原生二进制

| 步骤 | 操作 |
|------|------|
| 1 | 检查 Nuitka 环境 |
| 2 | 扫描可编译模块 |
| 3 | 编译 `.py` → `.pyd` (Windows) / `.so` (Linux) |
| 4 | 注入桩文件 (`__init__.py`, `__main__.py`) |
| 5 | 保留非 `.py` 资源文件 |

**输入**：`bundles/{platform}/{app_name}-{version}/app/`（Windows/Linux）或 `bundles/android/app/src/main/python/`（Android）

**输出**：编译后的源码目录（原地替换）

**前置条件**：必须先执行 `pyapp build`

**平台限制**：
- Windows 编译必须在 Windows 上运行
- Linux 编译必须在 Linux 上运行

### 3.3 `pyapp package` - 打包分发

**职责**：将 `bundles/` 目录打包为分发文件

| 步骤 | 操作 |
|------|------|
| 1 | 检查 `bundles/` 目录是否存在 |
| 2 | 创建 ZIP (Windows) / tar.gz (Linux) |
| 3 | 签名（可选） |

**输入**：`bundles/{platform}/`（含 `build.meta.json`）

**输出**：`dist/{app}-{version}-{platform}-{arch}.zip`（Windows）/ `.tar.gz`（Linux）/ `.apk`（Android）

**前置条件**：必须先执行 `pyapp build`，可选执行 `pyapp compile`

> **arch 来源**：package 从 `bundles/{platform}/build.meta.json` 读取 arch，构造分发文件名。Android 的 package 阶段执行 Gradle 构建（`assembleDebug`/`assembleRelease` 由 `build.meta.json` 中的 `build_type` 决定）+ 签名。

---

## 4. 流程图

### 4.1 开发调试流程

```
pyapp build windows
        ↓
pyapp run windows              # 直接运行
pyapp run windows -u           # 更新源码后运行
pyapp run windows -ur          # 更新依赖和源码后运行
```

### 4.2 发布流程（无编译）

```
pyapp build windows
        ↓
pyapp package windows
        ↓
   dist/app-1.0.0-windows-x86_64.zip
```

### 4.3 发布流程（有编译）

```
pyapp build windows
        ↓
pyapp compile windows
        ↓
pyapp package windows
        ↓
   dist/app-1.0.0-windows-x86_64.zip
```

### 4.4 GitHub Actions 流程

```
┌─────────────────────────────────────────────────────────────┐
│  Windows Runner                                             │
│                                                             │
│  pyapp build windows                                        │
│           ↓                                                 │
│  pip install nuitka ordered-set zstandard                   │
│           ↓                                                 │
│  pyapp compile windows                                      │
│           ↓                                                 │
│  pyapp package windows                                      │
│           ↓                                                 │
│  Upload artifact: dist/*.zip                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Linux Runner (QEMU/ARM)                                    │
│                                                             │
│  pyapp build linux --arch aarch64                           │
│           ↓                                                 │
│  pip install nuitka ordered-set zstandard                   │
│           ↓                                                 │
│  pyapp compile linux                                        │
│           ↓                                                 │
│  pyapp package linux                                        │
│           ↓                                                 │
│  Upload artifact: dist/*.tar.gz                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 代码修改方案

### 5.1 `BasePlatform` 修改

**修改点**：统一 `build()` 签名（含 `arch` 参数），新增 `build.meta.json` 读写工具方法，`package()` 不再调用 `build()`。

```python
# pyapp/platforms/base.py

@abstractmethod
def build(self, project_dir: Path, config: Dict[str, Any], 
          build_type: str = "debug", arch=None) -> BuildResult:
    """
    准备平台构建目录（不打包）
    
    Args:
        arch: Windows 忽略；Linux 为 str (x86_64/aarch64/armv7l)；Android 为 list (["arm64-v8a"])
    
    Returns:
        BuildResult.output_path: bundles/{platform}/ 目录路径
    """
    pass

@abstractmethod
def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
    """
    打包分发文件（不再调用 build()）
    
    从 bundles/{platform}/build.meta.json 读取 arch 和 build_type。
    """
    pass

# ---- 新增工具方法 ----

def _write_build_meta(self, bundle_dir: Path, platform: str, config: Dict[str, Any],
                      arch, build_type: str) -> None:
    """写入构建元数据，供 package 阶段读取"""
    import json
    meta = {
        "platform": platform,
        "arch": arch if isinstance(arch, str) else (arch or []),
        "build_type": build_type,
        "app_name": self.get_app_name(config),
        "version": self.get_app_version(config),
    }
    (bundle_dir / "build.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

def _read_build_meta(self, bundle_dir: Path) -> dict:
    """读取构建元数据"""
    import json
    meta_path = bundle_dir / "build.meta.json"
    if not meta_path.exists():
        raise BuildError(
            f"Build metadata not found: {meta_path}",
            "Run 'pyapp build' first"
        )
    return json.loads(meta_path.read_text(encoding="utf-8"))
```

### 5.2 `WindowsPlatform.build()` 修改

```python
# pyapp/platforms/windows.py

def build(self, project_dir: Path, config: Dict[str, Any], 
          build_type: str = "debug", arch=None) -> BuildResult:
    """准备 Windows 构建目录（不打包）"""
    try:
        bundle_dir = project_dir / "bundles" / "windows"
        
        # ... 步骤 1-5 保持不变 ...
        
        # 1. 下载 Embeddable Python
        # 2. 创建 runtime exe
        # 3. 同步 Python 源码
        # 4. 同步前端资源
        # 5. 安装依赖
        
        # 6. 创建 Stub exe
        self._create_stub_exe(bundle_dir, app_name, version, icon_path)
        
        # 7. 下载 WebView2Loader.dll
        self._download_webview2_loader(bundle_dir)
        
        # 8. 渲染 app.ini
        self._render_all_templates(project_dir, config)
        
        # 9. 写入构建元数据
        self._write_build_meta(bundle_dir, "windows", config, arch="x86_64", build_type=build_type)
        
        # 移除打包步骤！不再调用 _create_zip()
        
        self.logger.success(f"Build prepared at {bundle_dir}")
        
        return BuildResult(success=True, output_path=bundle_dir)
        
    except Exception as e:
        return BuildResult(success=False, error_message=str(e))
```

### 5.3 `WindowsPlatform.package()` 修改

```python
# pyapp/platforms/windows.py

def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
    """打包 Windows 分发文件（不再调用 build）"""
    try:
        bundle_dir = project_dir / "bundles" / "windows"
        
        # 检查前置条件
        if not bundle_dir.exists():
            raise BuildError(
                f"Bundle directory not found: {bundle_dir}",
                "Run 'pyapp build windows' first"
            )
        
        # 从 build.meta.json 读取 arch 和元数据
        meta = self._read_build_meta(bundle_dir)
        app_name = meta["app_name"]
        version = meta["version"]
        arch = meta["arch"]  # "x86_64"
        
        # 打包 ZIP
        dist_dir = self.ensure_dist_dir(project_dir)
        zip_filename = f"{app_name}-{version}-windows-{arch}.zip"
        zip_path = dist_dir / zip_filename
        
        self._create_zip(bundle_dir, zip_path, zip_filename.replace(".zip", ""))
        
        self.logger.success(f"Package created: {zip_path}")
        
        # 签名（可选，后续实现）
        # if sign_config:
        #     self._sign_exe(bundle_dir / f"{app_name}.exe")
        
        return BuildResult(success=True, output_path=zip_path)
        
    except Exception as e:
        return BuildResult(success=False, error_message=str(e))
```

### 5.4 `LinuxPlatform` 同样修改

```python
# pyapp/platforms/linux.py

def build(self, project_dir, config, build_type="debug", arch=None):
    """准备 Linux 构建目录（不打包）"""
    # ... 步骤 1-5 保持不变 ...
    
    # 写入构建元数据
    self._write_build_meta(bundle_dir, "linux", config, arch=arch or "x86_64", build_type=build_type)
    
    # 移除打包步骤！不再调用 _create_tarball()
    
    return BuildResult(success=True, output_path=bundle_dir)


def package(self, project_dir, config):
    """打包 Linux 分发文件（不再调用 build）"""
    bundle_dir = project_dir / "bundles" / "linux"
    
    if not bundle_dir.exists():
        raise BuildError("Bundle directory not found", "Run 'pyapp build linux' first")
    
    # 从 build.meta.json 读取 arch 和元数据
    meta = self._read_build_meta(bundle_dir)
    app_name = meta["app_name"]
    version = meta["version"]
    arch = meta["arch"]  # "x86_64" / "aarch64" / "armv7l"
    
    # 打包 tar.gz
    dist_dir = self.ensure_dist_dir(project_dir)
    tar_path = dist_dir / f"{app_name}-{version}-linux-{arch}.tar.gz"
    self._create_tarball(bundle_dir, tar_path)
    
    return BuildResult(success=True, output_path=tar_path)
```

### 5.5 `AndroidPlatform` 修改

**关键改动**：Android 的 Gradle 构建从 `build()` 移至 `package()`，使 build 只负责准备目录，与 Windows/Linux 职责一致。

```python
# pyapp/platforms/android.py

def build(self, project_dir, config, build_type="debug", arch=None):
    """准备 Android 构建目录（不运行 Gradle，不生成 APK）"""
    try:
        # 1. 检查环境
        ok, missing = self.check_environment()
        if not ok:
            raise PyAppEnvironmentError(...)

        # 获取架构配置
        android_config = config.get("tool", {}).get("pyapp", {}).get("android", {})
        abi_filters = arch if arch is not None else android_config.get("abi_filters", ["arm64-v8a"])

        # 2. 创建项目结构（如果不存在）
        bundle_dir = project_dir / "bundles" / "android"
        app_dir = bundle_dir / "app"
        if not app_dir.exists() or not (app_dir / "build.gradle.kts").exists():
            self.create(project_dir, config, arch=abi_filters)

        # 3. 同步 Python 源码
        self.logger.step(1, 4, "Syncing Python source code")
        self._sync_python_source(project_dir, bundle_dir, config)

        # 4. 同步前端资源
        self.logger.step(2, 4, "Syncing frontend resources")
        self._sync_frontend_dist(project_dir, bundle_dir, config)

        # 5. 更新 Chaquopy 依赖配置
        self.logger.step(3, 4, "Configuring Chaquopy dependencies")
        self._update_chaquopy_dependencies(bundle_dir, config)

        # 6. 写入构建元数据（含 build_type，供 package 阶段决定 Gradle 任务）
        self.logger.step(4, 4, "Writing build metadata")
        self._write_build_meta(bundle_dir, "android", config, arch=abi_filters, build_type=build_type)

        # 移除 Gradle 构建步骤！不再调用 gradlew assembleDebug/Release
        # APK 生成移至 package() 阶段

        self.logger.success(f"Build prepared at {bundle_dir}")
        return BuildResult(success=True, output_path=bundle_dir)

    except (BuildError, PyAppEnvironmentError) as e:
        self.logger.error(str(e))
        return BuildResult(success=False, error_message=str(e))


def package(self, project_dir, config):
    """打包 Android APK（运行 Gradle + 签名，不再调用 build）"""
    try:
        bundle_dir = project_dir / "bundles" / "android"
        
        if not bundle_dir.exists():
            raise BuildError("Bundle directory not found", "Run 'pyapp build android' first")
        
        # 从 build.meta.json 读取 arch 和 build_type
        meta = self._read_build_meta(bundle_dir)
        app_name = meta["app_name"]
        version = meta["version"]
        abi_filters = meta["arch"]  # ["arm64-v8a"]
        build_type = meta["build_type"]  # "debug" / "release"
        
        # 运行 Gradle 构建
        build_task = "assembleDebug" if build_type == "debug" else "assembleRelease"
        gradle_cmd = "gradlew.bat" if os.name == "nt" else "gradlew"
        gradle_path = bundle_dir / gradle_cmd
        
        env = os.environ.copy()
        self._preload_gradle_distribution(bundle_dir, env)
        
        result = subprocess.run(
            [str(gradle_path), "--console", "plain", build_task],
            cwd=str(bundle_dir), capture_output=True, text=True, env=env,
        )
        
        if result.returncode != 0:
            raise BuildError("Gradle build failed", "Check the Gradle output for details")
        
        # 复制 APK 到 dist/
        dist_dir = self.ensure_dist_dir(project_dir)
        apk_pattern = "*debug*.apk" if build_type == "debug" else "*release*.apk"
        apk_files = list((bundle_dir / "app" / "build" / "outputs" / "apk").rglob(apk_pattern))
        
        if not apk_files:
            raise BuildError("APK not found after build")
        
        arch_suffix = "_".join(a.replace("-", "_") for a in abi_filters)
        dest_apk = dist_dir / f"{app_name}-{version}-android-{arch_suffix}.apk"
        shutil.copy2(apk_files[0], dest_apk)
        
        self.logger.success(f"APK: {dest_apk}")
        
        # 签名（可选）
        keystore_path = os.environ.get("ANDROID_KEYSTORE_PATH")
        if not keystore_path:
            self.logger.warning("ANDROID_KEYSTORE_PATH not set, APK is unsigned.")
            return BuildResult(success=True, output_path=dest_apk)
        
        # jarsigner 签名...
        # (保持原有签名逻辑)
        
        return BuildResult(success=True, output_path=dest_apk)
        
    except Exception as e:
        return BuildResult(success=False, error_message=str(e))
```

> **设计要点**：Android 的 `build_type` 在 `build` 阶段通过 `-t release` 决定并写入 `build.meta.json`，`package` 阶段读取后选择对应的 Gradle 任务。`package` 不再调用 `build()`，避免重复同步源码和覆盖 compile 结果。

### 5.6 新增 `compile` 命令

```python
# pyapp/commands/compile.py

"""pyapp compile 命令 - 使用 Nuitka 编译源码"""

import sys
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..core.errors import BuildError


COMPILED_EXTENSIONS = {
    "windows": ".pyd",
    "linux": ".so",
    "android": ".so",
}

# 桩文件模板
# 基于 hello 项目已验证的 INIT_PY_TEMPLATE 改进（Nuitka 2.7.12 已验证）
# 改进点：
# 1. 白名单保留必要 dunder（__version__/__all__/__doc__ 等），避免子模块导入异常
# 2. 对 sys.modules 查找加 fallback，避免 KeyError
# 3. 移除脆弱的 meta_path 排序 hack，改用显式 spec_from_file_location 加载
# 注意：如遇兼容性问题，可回退到 hello 项目原始版本（见 scripts/nuitka_compile.py）
INIT_PY_TEMPLATE = '''\
import sys, importlib.util as u, os
_PKG = "{pkg_name}"
_MOD_FILE = "{mod_file}"
_d = os.path.dirname(os.path.abspath(__file__))

# 显式加载编译产物，不依赖 meta_path 排序
_sp = u.spec_from_file_location(_PKG, os.path.join(_d, _MOD_FILE))
_lib = u.module_from_spec(_sp)
_sp.loader.exec_module(_lib)

# 白名单保留必要 dunder，避免过滤 __version__/__all__/__doc__
_KEEP_DUNDER = {{"__version__", "__all__", "__doc__", "__author__", "__email__"}}

# 获取或创建当前包模块（加 fallback 避免 KeyError）
_m = sys.modules.get(_PKG)
if _m is None:
    import importlib.machinery as mach
    _spec = mach.ModuleSpec(_PKG, loader=None, is_package=True)
    _m = type(sys)(_PKG)
    _m.__spec__ = _spec
    sys.modules[_PKG] = _m

# 合并编译模块的属性（保留白名单 dunder + 普通属性）
for _k, _v in vars(_lib).items():
    if _k in _KEEP_DUNDER or not _k.startswith("__"):
        setattr(_m, _k, _v)

_m.__file__ = __file__
_m._RESOURCE_DIR = _d
_lib._RESOURCE_DIR = _d
'''

MAIN_PY_TEMPLATE = '''\
import {pkg_name}
{pkg_name}.main()
'''


def _get_src_dir(platform: str, bundle_dir: Path, version_dir: str) -> Path:
    """
    根据平台计算源码目录

    Windows/Linux: bundles/{platform}/{app_name}-{version}/app/
    Android:       bundles/android/app/src/main/python/
    """
    if platform == "android":
        return bundle_dir / "app" / "src" / "main" / "python"
    return bundle_dir / version_dir / "app"


def _swap_module_with_compiled(module_dir: Path, compiled_file: Path, move: bool = False) -> None:
    """
    用编译产物替换模块目录，保留非 .py 资源文件

    公共逻辑：被 compile_module 和 Android precompiled 路径共用，
    消除两处重复的"备份资源 → 删除目录 → 重建目录 → 恢复资源"代码。

    Args:
        module_dir: 模块目录路径（如 .../app/myapp/）
        compiled_file: 编译产物文件路径（.pyd/.so）
        move: True 时移动 compiled_file（compile_module 路径，避免 src_dir 残留）；
              False 时复制 compiled_file（precompiled 路径，保留原文件）
    """
    logger = get_logger()
    _tmpdir = Path(tempfile.mkdtemp())
    try:
        # 1. 备份非 .py 资源文件
        if module_dir.exists():
            for f in module_dir.rglob("*"):
                if f.is_file() and not f.name.endswith(".py"):
                    rel_path = f.relative_to(module_dir)
                    dest = _tmpdir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(f), str(dest))

            res_count = sum(1 for _ in _tmpdir.rglob("*") if _.is_file())
            if res_count > 0:
                logger.info(f"Preserving {res_count} resource files")

            # 2. 删除原模块目录
            shutil.rmtree(module_dir)

        # 3. 重新创建模块目录
        module_dir.mkdir(parents=True, exist_ok=True)

        # 4. 恢复资源文件
        for f in _tmpdir.rglob("*"):
            if f.is_file():
                rel_path = f.relative_to(_tmpdir)
                dest = module_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dest))
    finally:
        shutil.rmtree(str(_tmpdir), ignore_errors=True)

    # 5. 移动或复制编译产物到模块目录
    dest_file = module_dir / compiled_file.name
    if move:
        shutil.move(str(compiled_file), str(dest_file))
    else:
        shutil.copy2(str(compiled_file), str(dest_file))


def _inject_stub(module_name: str, module_dir: Path, mod_file: str) -> None:
    """写入桩文件"""
    (module_dir / "__init__.py").write_text(
        INIT_PY_TEMPLATE.format(pkg_name=module_name, mod_file=mod_file),
        encoding="utf-8"
    )
    (module_dir / "__main__.py").write_text(
        MAIN_PY_TEMPLATE.format(pkg_name=module_name),
        encoding="utf-8"
    )
    get_logger().info(f"Stub injected: {module_name}/__init__.py, __main__.py")


def compile_platform(platform: str, project_dir: Path = None, precompiled: Path = None):
    """
    编译 Python 源码为 pyd/so 文件

    Args:
        platform: 平台名称 (windows/linux/android)
        project_dir: 项目目录
        precompiled: 预编译的 .so 文件路径（Android 专用）
                     如果提供，跳过 Nuitka 编译，直接使用该文件替换源码
    """
    logger = get_logger()

    if project_dir is None:
        project_dir = Path.cwd()

    # 加载配置
    try:
        config = load_config(project_dir)
        config_dict = config.to_dict()
    except FileNotFoundError:
        raise click.ClickException(
            "pyproject.toml not found. Run 'pyapp init' first."
        )

    app_name = config_dict.get("project", {}).get("name", "app")
    app_module = config_dict.get("tool", {}).get("pyapp", {}).get("app_module", "app")
    version = config_dict.get("project", {}).get("version", "0.1.0")
    version_dir = f"{app_name}-{version}"

    # 检查 bundles 目录
    bundle_dir = project_dir / "bundles" / platform

    # 按平台计算源码目录（修复 Android 路径问题）
    src_dir = _get_src_dir(platform, bundle_dir, version_dir)

    if not src_dir.exists():
        raise click.ClickException(
            f"Source directory not found: {src_dir}\n"
            f"Run 'pyapp build {platform}' first"
        )

    extension = COMPILED_EXTENSIONS.get(platform, ".so")

    if platform == "android":
        # Android 必须使用 Termux 预编译的 .so
        if precompiled is None:
            raise click.ClickException(
                "Android compile requires --precompiled option.\n"
                "Run Termux Docker first to generate .so file.\n"
                "See: scripts/termux_compile.sh"
            )
        if not precompiled.exists():
            raise click.ClickException(f"Precompiled .so not found: {precompiled}")

        logger.info(f"Using precompiled module: {precompiled}")
        modules = scan_compilable_modules(src_dir, [app_module])
        if not modules:
            logger.warning("No compilable modules found")
            return

        for module_name in modules:
            module_dir = src_dir / module_name
            _swap_module_with_compiled(module_dir, precompiled)
            _inject_stub(module_name, module_dir, precompiled.name)
            logger.success(f"Module {module_name} installed with precompiled .so")
    else:
        # Windows/Linux: 本机 Nuitka 编译
        nuitka_version = check_nuitka()
        logger.info(f"Nuitka version: {nuitka_version}")

        modules = scan_compilable_modules(src_dir, [app_module])
        if not modules:
            logger.warning("No compilable modules found")
            return

        logger.info(f"Compiling modules: {', '.join(modules)}")
        logger.info(f"Target extension: {extension}")

        for module_name in modules:
            try:
                logger.info(f"Compiling {module_name}...")
                mod_file = compile_module(module_name, src_dir, extension)
                module_dir = src_dir / module_name
                compiled_file = src_dir / mod_file
                # move=True：移动编译产物，避免 src_dir 残留
                _swap_module_with_compiled(module_dir, compiled_file, move=True)
                _inject_stub(module_name, module_dir, mod_file)
                logger.success(f"Module {module_name} compiled successfully")
            except Exception as e:
                logger.error(f"Failed to compile {module_name}: {e}")
                raise click.ClickException(str(e))


def check_nuitka() -> str:
    """检查 Nuitka 是否安装"""
    result = subprocess.run(
        [sys.executable, "-m", "nuitka", "--version"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise click.ClickException(
            "Nuitka not installed.\n"
            "Run: pip install nuitka==2.7.12 ordered-set zstandard\n"
            "(2.7.12 is the verified version, tested in hello project)"
        )
    return result.stdout.strip().split("\n")[0]


def scan_compilable_modules(src_dir: Path, module_filter: Optional[List[str]] = None) -> List[str]:
    """扫描可编译的模块（有 __init__.py 的目录）"""
    skip_dirs = {"__pycache__", "app_packages"}
    modules = []

    for item in sorted(src_dir.iterdir()):
        if not item.is_dir():
            continue
        if item.name in skip_dirs or item.name.startswith("."):
            continue
        if (item / "__init__.py").exists():
            if module_filter and item.name not in module_filter:
                continue
            modules.append(item.name)

    return modules


def compile_module(module_name: str, src_dir: Path, extension: str) -> str:
    """
    编译单个模块（使用系统临时目录，避免污染源码目录）

    Args:
        module_name: 模块名
        src_dir: 源码目录
        extension: 编译产物扩展名 (.pyd/.so)

    Returns:
        编译产物文件名
    """
    logger = get_logger()

    # 使用系统临时目录，避免在 src_dir 下创建 compiled/ 残留
    with tempfile.TemporaryDirectory(prefix="nuitka_") as tmpdir:
        compiled_dir = Path(tmpdir)

        # 构建 Nuitka 命令
        # 注意：--module 模式下 --include-package 可能导致重复编译，
        # 实施前需用最小示例验证 Nuitka 版本行为，必要时改用 --include-module
        cmd = [
            sys.executable, "-m", "nuitka",
            "--module", module_name,
            f"--output-dir={compiled_dir}",
            "--remove-output",
            "--assume-yes-for-downloads",
            f"--include-package={module_name}",
            "--no-progressbar",
        ]

        logger.debug(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=str(src_dir))

        if result.returncode != 0:
            raise RuntimeError(f"Nuitka compilation failed: {module_name}")

        # 查找编译产物
        pattern = f"{module_name}*{extension}"
        matches = list(compiled_dir.glob(pattern))

        if not matches:
            raise FileNotFoundError(
                f"Compiled product not found: {pattern}\n"
                f"Directory contents: {[f.name for f in compiled_dir.iterdir()]}"
            )

        compiled_file = matches[0]

        # 复制到源码目录
        dest = src_dir / compiled_file.name
        shutil.copy2(str(compiled_file), str(dest))

        logger.info(f"Compiled: {compiled_file.name}")

        return compiled_file.name
```

> **改进说明**：
> 1. **`_get_src_dir()`**：按平台分支计算源码目录，修复 Android 路径错误
> 2. **`_swap_module_with_compiled()`**：提取公共逻辑，消除 `compile_module` 和 `install_precompiled_module` 的代码重复
> 3. **`INIT_PY_TEMPLATE`**：白名单保留必要 dunder，加 fallback 避免 KeyError，移除脆弱的 meta_path 排序 hack
> 4. **`compile_module`**：改用 `tempfile.TemporaryDirectory`，避免在 src_dir 下创建 `compiled/` 残留；`scan_compilable_modules` 的 `skip_dirs` 相应移除 `"compiled"`

---

## 6. CLI 命令设计

```python
# pyapp/cli.py

@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux", "all"]))
@click.option("-t", "--type", "build_type", type=click.Choice(["debug", "release"]), 
              default="debug", help="构建类型")
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
@click.option("--arch", type=str, default=None,
              help="目标架构。Linux: x86_64, aarch64, armv7l")
def build(platform, build_type, project_dir, arch):
    """准备平台构建目录（不打包）
    
    此命令准备 bundles 目录结构，包括：
    - Python 运行时
    - 应用源码
    - pip 依赖
    - 启动脚本
    
    后续可执行 compile（可选）和 package 完成打包。
    
    示例:
      pyapp build windows
      pyapp build linux --arch aarch64
    """
    from .commands.build import build_platform
    build_platform(platform, build_type, Path(project_dir) if project_dir else None, arch=arch)


@main.command("compile")
@click.argument("platform", type=click.Choice(["windows", "linux", "android"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
@click.option("--precompiled", type=click.Path(exists=True), 
              help="预编译的 .so 文件路径（Android 专用，Termux 编译产物）")
def compile_cmd(platform, project_dir, precompiled):
    """编译 Python 源码为 pyd/so 文件（需要先 build）
    
    使用 Nuitka 将 Python 源码编译为原生二进制，保护源码并提升性能。
    
    注意：
    - Windows/Linux: 在本机执行 Nuitka 编译
    - Android: 需要先通过 Termux Docker 编译，再使用 --precompiled 指定 .so 文件
    - compile 不支持 "all" 平台（编译需平台特定环境）
    
    前置条件：
    - Windows/Linux: 安装 Nuitka: pip install nuitka ordered-set zstandard
    - Android: 先执行 Termux Docker 编译生成 .so 文件
    - 所有平台: 先执行 pyapp build
    
    示例:
      pyapp build windows
      pyapp compile windows
      pyapp package windows
    """
    from .commands.compile import compile_platform
    compile_platform(platform, Path(project_dir) if project_dir else None,
                     Path(precompiled) if precompiled else None)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux", "all"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
def package(platform, project_dir):
    """打包分发文件（需要先 build，可选 compile）
    
    将 bundles 目录打包为分发文件：
    - Windows: ZIP
    - Linux: tar.gz
    
    前置条件：先执行 pyapp build
    
    示例:
      pyapp build windows
      pyapp package windows
      
      # 或带编译
      pyapp build windows
      pyapp compile windows
      pyapp package windows
    """
    from .commands.package import package_platform
    package_platform(platform, Path(project_dir) if project_dir else None)
```

---

## 7. GitHub Actions CI 模板

### 7.1 设计目标

`pyapp init` 时自动生成三个平台的 CI 脚本到 `.github/workflows/` 目录，用户无需手动编写。

### 7.2 模板文件结构

```
pyapp/templates/
├── project/
│   └── pyproject.toml.j2
└── ci/
    ├── build-windows.yml.j2
    ├── build-linux.yml.j2
    └── build-android.yml.j2
```

### 7.3 init 命令生成 CI 脚本

在 `commands/init.py` 的 `_create_project_structure()` 中添加 CI 脚本生成：

```python
def _create_project_structure(project_dir: Path, name: str, module_name: str, template: str):
    # ... 现有代码 ...
    
    # 生成 CI 脚本
    _generate_ci_workflows(project_dir, name, module_name)


def _generate_ci_workflows(project_dir: Path, name: str, module_name: str):
    """生成 GitHub Actions CI 脚本和 Termux 编译脚本"""
    ci_template_dir = Path(__file__).parent.parent / "templates" / "ci"
    jinja_env = Environment(loader=FileSystemLoader(str(ci_template_dir)))
    
    # 渲染上下文：app_module 对应模板中的 {{ app_module }}
    render_ctx = {
        "name": name,
        "module_name": module_name,
        "app_module": module_name,  # 模板中使用 {{ app_module }}
        "python_version": "3.11",   # Termux Python 版本
        "nuitka_version": "2.7.12", # 已验证的 Nuitka 版本
    }
    
    # 1. 生成 CI workflow 脚本
    workflows_dir = project_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    for template_name in ["build-windows.yml.j2", "build-linux.yml.j2", "build-android.yml.j2"]:
        jinja_template = jinja_env.get_template(template_name)
        content = jinja_template.render(**render_ctx)
        output_name = template_name.replace(".j2", "")
        (workflows_dir / output_name).write_text(content, encoding="utf-8")
    
    # 2. 生成 Termux 编译脚本
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    termux_template = jinja_env.get_template("termux_compile.sh.j2")
    termux_content = termux_template.render(**render_ctx)
    (scripts_dir / "termux_compile.sh").write_text(termux_content, encoding="utf-8")
```

### 7.4 CI 模板内容

#### build-windows.yml.j2

```yaml
name: Build Windows

on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install pyapp
        run: pip install -e .
      
      - name: Build
        run: pyapp build windows
      
      - name: Install Nuitka
        run: pip install nuitka==2.7.12 ordered-set zstandard
      
      - name: Setup MSVC
        uses: ilammy/msvc-dev-cmd@v1
      
      - name: Compile
        run: pyapp compile windows
      
      - name: Package
        run: pyapp package windows
      
      - uses: actions/upload-artifact@v4
        with:
          name: windows-package
          path: dist/*.zip
```

#### build-linux.yml.j2

```yaml
name: Build Linux

on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  build-aarch64:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build on ARM
        uses: uraimo/run-on-arch-action@v3
        with:
          arch: aarch64
          distro: bullseye
          install: |
            apt-get update -qq
            apt-get install -y -qq python3 build-essential libffi-dev libssl-dev \
              libbz2-dev libreadline-dev libsqlite3-dev zlib1g-dev \
              wget git file ca-certificates tar gzip gcc g++ make patchelf
          run: |
            pip3 install -e .
            pip3 install nuitka==2.7.12 ordered-set zstandard
            
            pyapp build linux --arch aarch64
            pyapp compile linux
            pyapp package linux
      
      - uses: actions/upload-artifact@v4
        with:
          name: linux-aarch64-package
          path: dist/*.tar.gz
```

#### build-android.yml.j2

```yaml
name: Build Android

on:
  push:
    tags: ['v*']
  workflow_dispatch:

jobs:
  termux-compile:
    runs-on: ubuntu-24.04-arm
    steps:
      - uses: actions/checkout@v4
      
      - name: Compile in Termux Docker
        run: |
          docker run --rm -v $PWD:/src termux/termux-docker:aarch64 \
            bash /src/scripts/termux_compile.sh
      
      - uses: actions/upload-artifact@v4
        with:
          name: compiled-so
          path: dist/*.so

  build-compile-package:
    needs: termux-compile
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/download-artifact@v4
        with:
          name: compiled-so
          path: dist
      
      - name: Install pyapp
        run: pip install -e .
      
      - name: Build
        run: pyapp build android
      
      - name: Compile with precompiled .so
        run: pyapp compile android --precompiled dist/{{ app_module }}.so
      
      - name: Package APK
        run: pyapp package android
      
      - uses: actions/upload-artifact@v4
        with:
          name: android-apk
          path: dist/*.apk
```

### 7.5 生成的项目结构

`pyapp init myapp` 生成的目录结构：

```
myapp/
├── .github/
│   └── workflows/
│       ├── build-windows.yml    # Windows CI 脚本
│       ├── build-linux.yml     # Linux CI 脚本
│       └── build-android.yml   # Android CI 脚本
├── scripts/
│   └── termux_compile.sh       # Termux 编译脚本
├── src/
│   └── myapp/
├── frontend/
├── pyproject.toml
└── .gitignore
```

### 7.6 用户使用方式

```bash
# 1. 初始化项目（自动生成 CI 脚本）
pyapp init myapp

# 2. 本地开发
cd myapp
pyapp build windows
pyapp run windows

# 3. 发布（打 tag 自动触发 CI）
git tag v1.0.0
git push origin v1.0.0
# → 自动执行 build → compile → package
# → 生成 dist/*.zip, dist/*.tar.gz, dist/*.apk
```

---

## 8. 命令对比总结

### 重构前

| 命令 | 职责 | 输出 |
|------|------|------|
| `build` | 准备 + 打包 | `dist/*.zip` |
| `package` | build + 签名 | `dist/*.zip` |

### 重构后

| 命令 | 职责 | 输出 | 前置条件 |
|------|------|------|---------|
| `build` | 准备目录 | `bundles/` | 无 |
| `compile` | 编译源码 | `bundles/` (修改) | `build` |
| `package` | 打包分发 | `dist/*.zip` | `build` |

---

## 9. Android 平台特殊处理

Android 平台的 Nuitka 编译需要 Termux 环境支持，但流程与其他平台保持一致。

### 9.1 为什么需要特殊处理

| 问题 | 说明 |
|------|------|
| **目标平台限制** | Nuitka 需要在目标平台编译，Android 编译必须在 Termux (ARM) 环境中执行 |
| **跨平台执行** | Termux 编译在 ARM 平台，build/compile/package 在 Linux 平台 |
| **ELF 处理** | 编译产物需要 `termux-elf-cleaner` 和 `patchelf` 处理 |

### 9.2 Android 流程：区分开发与发布

Android 平台有两种流程：

#### 开发流程（本地调试）

```
pyapp build android → pyapp package android
```

- 不需要编译，直接使用源码
- 用于本地开发和调试

#### 发布流程（GitHub Actions）

流程与其他平台一致：`build → compile → package`，只是 compile 使用 Termux 预编译的 `.so` 文件：

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Termux Docker 编译（ARM 平台）                      │
│                                                             │
│  输入: src/{app_module}/                                    │
│  输出: dist/{app_module}.so                                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: pyapp build android（Linux 平台）                   │
│                                                             │
│  输入: 源码                                                  │
│  输出: bundles/android/app/src/main/python/{app_module}/    │
│        (Python 源码)                                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 3: pyapp compile android --precompiled（Linux 平台）   │
│                                                             │
│  输入: bundles/ 目录 + dist/{app_module}.so                 │
│  操作: 用 .so 替换源码，注入桩文件                            │
│  输出: bundles/android/app/src/main/python/{app_module}/    │
│        (含 .so + 桩文件)                                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 4: pyapp package android（Linux 平台）                 │
│                                                             │
│  输入: bundles/android/                                     │
│  输出: dist/{app}-android-{arch}.apk                        │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 与 Windows/Linux 的流程对比

| 平台 | 开发流程 | 发布流程（带编译） | compile 执行方式 |
|------|---------|------------------|-----------------|
| Windows | build → package | build → compile → package | 本机 Nuitka 编译 |
| Linux | build → package | build → compile → package | 本机 Nuitka 编译 |
| **Android** | build → package | build → compile → package | 使用 Termux 预编译的 .so |

**统一性**：所有平台的发布流程都是 `build → compile → package`，只是 Android 的 compile 使用 Termux 预编译的 `.so` 文件。

### 9.4 Termux 编译脚本

只负责编译源码，生成 `.so` 文件。此脚本作为 Jinja 模板 `termux_compile.sh.j2`，变量用 `{{ }}` 语法。

**参考 hello 项目已验证的实现**，需包含以下关键步骤：

```bash
# scripts/termux_compile.sh.j2

#!/data/data/com.termux/files/usr/bin/bash
set -e

export PREFIX=/data/data/com.termux/files/usr
export PATH=$PREFIX/bin:$PATH
export HOME=/data/data/com.termux/files/home
export TMPDIR=$PREFIX/tmp
export LANG=en_US.UTF-8

# DNS 配置
echo "nameserver 8.8.8.8" > $PREFIX/etc/resolv.conf
echo "nameserver 8.8.4.4" >> $PREFIX/etc/resolv.conf

# 镜像源加速（国内）
if [ -f "$PREFIX/etc/apt/sources.list" ]; then
  sed -i 's|https://packages.termux.dev/apt/termux-main|https://mirrors.ustc.edu.cn/termux/apt/termux-main|g' "$PREFIX/etc/apt/sources.list"
  sed -i 's|https://packages-cf.termux.dev/apt/termux-main|https://mirrors.ustc.edu.cn/termux/apt/termux-main|g' "$PREFIX/etc/apt/sources.list"
fi

# 安装 Python 和编译工具
apt update -yq && apt upgrade -yq
apt install -yq tur-repo && apt update -yq
apt install -yq python{{ python_version }}  # 如 python3.11

PY_BIN=$(ls $PREFIX/bin/python3.* 2>/dev/null | grep -v config | head -1)
[ -z "$PY_BIN" ] && { echo "error: python3 not found"; exit 1; }
PY_SFX=$(basename "$PY_BIN" | sed 's/python//')
ln -sf "$PY_BIN" $PREFIX/bin/python
[ -f "$PREFIX/bin/pip${PY_SFX}" ] && ln -sf "$PREFIX/bin/pip${PY_SFX}" $PREFIX/bin/pip
python --version

# 安装编译工具链
apt install -yq ninja clang git patchelf ccache termux-elf-cleaner findutils
pip install --upgrade pip
pip install MarkupSafe==2.1.3 ordered-set==4.1.0 zstandard==0.23.0 nuitka=={{ nuitka_version }}

# 编译
cd /src/src
APP_MODULE="{{ app_module }}"

python -m nuitka --module $APP_MODULE --include-package=$APP_MODULE \
  --output-dir=/src/dist --remove-output \
  --assume-yes-for-downloads --no-progressbar

# 处理 ELF
cd /src/dist
SO_FILE=$(ls $APP_MODULE.*.so 2>/dev/null | head -1)
[ -z "$SO_FILE" ] && { echo "error: No .so produced"; exit 1; }
mv "$SO_FILE" $APP_MODULE.so
termux-elf-cleaner $APP_MODULE.so || true
patchelf --set-rpath '' $APP_MODULE.so || true

# 关键步骤：修正 Python 共享库依赖名
# Nuitka 产出依赖 libpython3.11.so.1.0，但 Android 端提供 libpython3.11.so
patchelf --replace-needed libpython${PY_SFX}.so.1.0 libpython${PY_SFX}.so $APP_MODULE.so || true

# 最终产物: dist/{{ app_module }}.so
```

> **关键改进点（对比 hello 项目已验证版本）**：
> 1. `patchelf --replace-needed`：修正 `libpython{ver}.so.1.0` → `libpython{ver}.so`，适配 Android 的 Python 共享库命名
> 2. Python 版本和 Nuitka 版本通过 Jinja 变量注入（`{{ python_version }}`、`{{ nuitka_version }}`），而非 hello 项目的 sed 替换
> 3. 安装 `ninja`、`clang`、`ccache` 等编译工具（Nuitka 在 Termux 中需要）

### 9.5 pyapp compile android 改进

Android 的 compile 逻辑已整合到 5.6 节的 `compile_platform` 函数中（通过 `platform == "android"` 分支处理）。核心调用公共函数 `_swap_module_with_compiled` + `_inject_stub`，无需单独的 `install_precompiled_module` 函数。

```python
# commands/compile.py（节选自 5.6 节 compile_platform 的 Android 分支）

if platform == "android":
    # Android 必须使用 Termux 预编译的 .so
    if precompiled is None:
        raise click.ClickException(
            "Android compile requires --precompiled option.\n"
            "Run Termux Docker first to generate .so file.\n"
            "See: scripts/termux_compile.sh"
        )
    if not precompiled.exists():
        raise click.ClickException(f"Precompiled .so not found: {precompiled}")

    logger.info(f"Using precompiled module: {precompiled}")
    modules = scan_compilable_modules(src_dir, [app_module])
    if not modules:
        logger.warning("No compilable modules found")
        return

    for module_name in modules:
        module_dir = src_dir / module_name
        # 复用公共函数，消除与 compile_module 的代码重复
        _swap_module_with_compiled(module_dir, precompiled)
        _inject_stub(module_name, module_dir, precompiled.name)
        logger.success(f"Module {module_name} installed with precompiled .so")
```

> **改进**：原方案的 `install_precompiled_module` 函数已删除，其逻辑由公共函数 `_swap_module_with_compiled` + `_inject_stub` 替代，与 Windows/Linux 的 `compile_module` 路径共用同一套"备份资源 → 替换 → 注入桩"逻辑。

### 9.6 GitHub Actions Android 流程示例

此模板作为 `build-android.yml.j2`，`{{ app_module }}` 由 Jinja 渲染：

```yaml
# .github/workflows/build-android.yml.j2

jobs:
  # Step 1: Termux 编译（ARM 平台）
  termux-compile:
    runs-on: ubuntu-24.04-arm
    steps:
      - uses: actions/checkout@v4
      
      - name: Compile in Termux Docker
        run: |
          docker run --rm -v $PWD:/src termux/termux-docker:aarch64 \
            bash /src/scripts/termux_compile.sh
      
      - uses: actions/upload-artifact@v4
        with:
          name: compiled-so
          path: dist/*.so

  # Step 2-4: build → compile → package（Linux 平台）
  build-compile-package:
    needs: termux-compile
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/download-artifact@v4
        with:
          name: compiled-so
          path: dist
      
      - name: Build
        run: pyapp build android
      
      - name: Compile with precompiled .so
        run: pyapp compile android --precompiled dist/{{ app_module }}.so
      
      - name: Package APK
        run: pyapp package android
      
      - uses: actions/upload-artifact@v4
        with:
          name: android-apk
          path: dist/*.apk
```

### 9.7 CLI 命令扩展

compile 命令的完整定义（与 6 节统一，函数名用 `compile_cmd` 避免遮蔽内置 `compile`）：

```python
# cli.py

@main.command("compile")
@click.argument("platform", type=click.Choice(["windows", "linux", "android"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
@click.option("--precompiled", type=click.Path(exists=True), 
              help="预编译的 .so 文件路径（Android 专用，Termux 编译产物）")
def compile_cmd(platform, project_dir, precompiled):
    """编译 Python 源码为 pyd/so 文件（需要先 build）
    
    使用 Nuitka 将 Python 源码编译为原生二进制，保护源码并提升性能。
    
    注意：
    - Windows/Linux: 在本机执行 Nuitka 编译
    - Android: 需要先通过 Termux Docker 编译，再使用 --precompiled 指定 .so 文件
    - compile 不支持 "all" 平台（编译需平台特定环境）
    
    前置条件：
    - Windows/Linux: 安装 Nuitka: pip install nuitka ordered-set zstandard
    - Android: 先执行 Termux Docker 编译生成 .so 文件
    - 所有平台: 先执行 pyapp build
    
    示例:
      # Windows/Linux
      pyapp build windows
      pyapp compile windows
      pyapp package windows
      
      # Android（在 GitHub Actions 中）
      pyapp build android
      pyapp compile android --precompiled dist/{{ app_module }}.so
      pyapp package android
    """
    from .commands.compile import compile_platform
    compile_platform(platform, Path(project_dir) if project_dir else None, 
                     Path(precompiled) if precompiled else None)
```

### 9.8 总结

#### 开发流程（所有平台）

| 命令 | 说明 |
|------|------|
| `pyapp build android` | 准备 bundles 目录（使用源码） |
| `pyapp package android` | 打包 APK |

#### 发布流程（所有平台统一）

| 步骤 | Windows/Linux | Android |
|------|--------------|---------|
| 1 | `pyapp build` | `pyapp build` |
| 2 | `pyapp compile`（本机 Nuitka） | Termux 编译 → `pyapp compile --precompiled` |
| 3 | `pyapp package` | `pyapp package` |

**关键点**：
- 所有平台的发布流程都是 `build → compile → package`
- Android 的 compile 使用 Termux 预编译的 `.so` 文件，跳过本机 Nuitka 编译
- compile 命令在所有平台都存在，只是 Android 需要额外的 `--precompiled` 参数

---

## 10. 待确认事项

1. **Android 平台** ✅ 已确认：实现 `pyapp compile android --precompiled` 命令，使用 Termux Docker 预编译的 .so 文件。流程与其他平台统一为 `build → compile → package`。

2. **签名功能**：`package` 命令是否需要集成签名功能（Windows signtool / Android jarsigner）？

3. **向后兼容** ✅ 已确认：开发阶段不考虑兼容性，`build` 不再打包，直接移除打包行为。

4. **`dev` 命令移除** ✅ 已确认：移除 `pyapp dev` 命令，改为 `run` 命令支持更新参数。

   - 移除 `pyapp dev` 命令（`cli.py` + `commands/dev.py` + 各平台 `dev()` 方法）
   - 增强 `pyapp run` 命令，添加 `-u/--update` 和 `-r/--rebuild` 参数（类似 Briefcase）
   - **迁移 `_sync_frontend_env` 功能**：将 `dev.py` 中的前端环境同步逻辑迁移到 `run` 命令，确保 `frontend/.env.development` 的 `VITE_API_PORT` 仍能从 `pyproject.toml` 自动同步
   - 开发流程：`build` → `run` 或 `run -ur`（更新依赖和源码再运行）

   **`run` 命令参数设计**：

   ```python
   @main.command()
   @click.argument("platform", type=click.Choice(["android", "windows", "linux"]))
   @click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
   @click.option("-u", "--update", is_flag=True, 
                 help="更新应用源码（不更新依赖）")
   @click.option("-r", "--rebuild", is_flag=True, 
                 help="重新安装依赖（包含源码更新）")
   def run(platform, project_dir, update, rebuild):
       """运行应用
       
       如果 bundles 目录不存在，会先自动执行 build。
       自动同步 frontend/.env.development 的 VITE_API_PORT。
       
       示例:
         pyapp run windows              # 直接运行
         pyapp run windows -u          # 更新源码后运行
         pyapp run windows -ur         # 更新依赖和源码后运行
       """
       from .commands.run import run_platform
       run_platform(platform, Path(project_dir) if project_dir else None, 
                    update=update, rebuild=rebuild)
   ```

   **`run_platform` 实现要点**（迁移 `dev.py` 的 `_sync_frontend_env`）：

   ```python
   # pyapp/commands/run.py

   import re
   from pathlib import Path

   def _sync_frontend_env(project_dir: Path, port: int) -> None:
       """同步 frontend/.env.development 的 VITE_API_PORT（从 dev.py 迁移）"""
       env_file = project_dir / "frontend" / ".env.development"
       
       if not env_file.exists():
           env_file.parent.mkdir(parents=True, exist_ok=True)
           env_content = (
               "# Backend API port for development\n"
               "# Auto-synced from pyproject.toml\n"
               f"VITE_API_PORT={port}\n"
           )
           env_file.write_text(env_content, encoding="utf-8")
           return
       
       content = env_file.read_text(encoding="utf-8")
       new_content = re.sub(
           r"(VITE_API_PORT\s*=\s*)['\"]?\d+['\"]?",
           f"\\g<1>{port}",
           content,
       )
       if new_content != content:
           env_file.write_text(new_content, encoding="utf-8")

   def run_platform(platform: str, project_dir: Path = None, 
                    update: bool = False, rebuild: bool = False):
       """运行应用（支持 -u/-r 参数）"""
       # ... 加载配置 ...
       
       # 同步前端环境（从 dev.py 迁移）
       _sync_frontend_env(project_dir, port)
       
       # 如果 bundles 不存在或 -r/-u，先执行 build
       bundle_dir = project_dir / "bundles" / platform
       if not bundle_dir.exists() or rebuild:
           from .commands.build import build_platform
           build_platform(platform, build_type="debug", project_dir=project_dir)
       elif update:
           # 仅更新源码，不重新安装依赖
           # ... 调用 platform.sync_source_code() ...
           pass
       
       # 运行
       platform_instance = get_platform(platform)
       platform_instance.run(project_dir, config_dict)
   ```

   **开发流程**：

   | 场景 | 命令 | 说明 |
   |------|------|------|
   | 首次运行 | `pyapp build` → `pyapp run` | 完整构建后运行 |
   | 修改源码后 | `pyapp run -u` | 更新源码后运行 |
   | 修改依赖后 | `pyapp run -ur` | 更新依赖和源码后运行 |

   **发布流程**：

   ```
   pyapp build → pyapp compile → pyapp package
   ```

   `run` 命令仅用于开发调试，不参与发布流程。

---

## 11. 实施步骤

1. 修改 `BasePlatform`：统一 `build()` 签名（含 `arch`），新增 `_write_build_meta()` / `_read_build_meta()` 工具方法，`package()` 不再调用 `build()`
2. 修改 `WindowsPlatform.build()` 和 `package()`（build 写入 `build.meta.json`，package 读取 arch）
3. 修改 `LinuxPlatform.build()` 和 `package()`（同上）
4. 修改 `AndroidPlatform.build()` 和 `package()`（Gradle 构建从 build 移至 package，build 写入 `build.meta.json` 含 `build_type`）
5. 新增 `commands/compile.py`（含 `_get_src_dir`、`_swap_module_with_compiled`、`_inject_stub`、`compile_platform`、`compile_module`）
6. 移除 `pyapp dev` 命令（`cli.py` + `commands/dev.py` + 各平台 `dev()` 方法）
7. 增强 `pyapp run` 命令：添加 `-u/--update` 和 `-r/--rebuild` 参数，迁移 `_sync_frontend_env` 到 `commands/run.py`
8. 更新 `cli.py` 命令注册（`compile_cmd` 函数名，Click choice 含 android，`--precompiled` 选项）
9. 新增 CI 模板文件 `templates/ci/*.yml.j2`（Jinja 变量用 `{{ app_module }}`）
10. 新增 Termux 编译脚本模板 `templates/ci/termux_compile.sh.j2`
11. 修改 `commands/init.py`，在项目初始化时生成 CI 脚本和 Termux 脚本
12. 更新文档和帮助信息