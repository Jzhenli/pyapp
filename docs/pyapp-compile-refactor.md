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

**职责**：准备 `bundles/` 目录结构，**不打包**

| 步骤 | 操作 |
|------|------|
| 1 | 下载 Python 运行时 |
| 2 | 同步 Python 源码 (`src/` → `bundles/{platform}/{version}/app/`) |
| 3 | 同步前端资源 (`frontend/dist/` → `app/{module}/resources/static/`) |
| 4 | 安装 pip 依赖 (`bundles/{platform}/{version}/app_packages/`) |
| 5 | 生成启动脚本/配置文件 |

**输出**：`bundles/{platform}/{version}/` 目录

**返回**：`BuildResult(success=True, output_path=bundle_dir)`（目录路径，而非 ZIP）

### 3.2 `pyapp compile` - 编译源码（可选）

**职责**：使用 Nuitka 将 Python 源码编译为原生二进制

| 步骤 | 操作 |
|------|------|
| 1 | 检查 Nuitka 环境 |
| 2 | 扫描可编译模块 |
| 3 | 编译 `.py` → `.pyd` (Windows) / `.so` (Linux) |
| 4 | 注入桩文件 (`__init__.py`, `__main__.py`) |
| 5 | 保留非 `.py` 资源文件 |

**输入**：`bundles/{platform}/{version}/app/`

**输出**：编译后的 `bundles/{platform}/{version}/app/`

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

**输入**：`bundles/{platform}/`

**输出**：`dist/{app}-{version}-{platform}-{arch}.zip`

**前置条件**：必须先执行 `pyapp build`，可选执行 `pyapp compile`

---

## 4. 流程图

### 4.1 开发调试流程

```
pyapp build windows
        ↓
pyapp run windows
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

### 5.1 `BasePlatform.build()` 修改

**修改点**：移除打包步骤，只返回目录路径

```python
# pyapp/platforms/base.py

@abstractmethod
def build(self, project_dir: Path, config: Dict[str, Any], 
          build_type: str = "debug", arch: str = None) -> BuildResult:
    """
    准备平台构建目录（不打包）
    
    Returns:
        BuildResult.output_path: bundles/{platform}/ 目录路径
    """
    pass
```

### 5.2 `WindowsPlatform.build()` 修改

```python
# pyapp/platforms/windows.py

def build(self, project_dir: Path, config: Dict[str, Any], 
          build_type: str = "debug") -> BuildResult:
    """准备 Windows 构建目录"""
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
        
        # 移除打包步骤！
        # 不再调用 _create_zip()
        
        self.logger.success(f"Build prepared at {bundle_dir}")
        
        return BuildResult(success=True, output_path=bundle_dir)
        
    except Exception as e:
        return BuildResult(success=False, error_message=str(e))
```

### 5.3 `WindowsPlatform.package()` 修改

```python
# pyapp/platforms/windows.py

def package(self, project_dir: Path, config: Dict[str, Any]) -> BuildResult:
    """打包 Windows 分发文件"""
    try:
        bundle_dir = project_dir / "bundles" / "windows"
        
        # 检查前置条件
        if not bundle_dir.exists():
            raise BuildError(
                f"Bundle directory not found: {bundle_dir}\n"
                f"Run 'pyapp build windows' first"
            )
        
        app_name = self.get_app_name(config)
        version = self.get_app_version(config)
        
        # 打包 ZIP
        dist_dir = self.ensure_dist_dir(project_dir)
        zip_filename = f"{app_name}-{version}-windows-x86_64.zip"
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
    """准备 Linux 构建目录"""
    # ... 步骤 1-5 保持不变 ...
    
    # 移除打包步骤！
    # 不再调用 _create_tarball()
    
    return BuildResult(success=True, output_path=bundle_dir)


def package(self, project_dir, config):
    """打包 Linux 分发文件"""
    bundle_dir = project_dir / "bundles" / "linux"
    
    if not bundle_dir.exists():
        raise BuildError("Run 'pyapp build linux' first")
    
    # 打包 tar.gz
    dist_dir = self.ensure_dist_dir(project_dir)
    tar_path = dist_dir / f"{app_name}-{version}-linux-{arch}.tar.gz"
    self._create_tarball(bundle_dir, tar_path)
    
    return BuildResult(success=True, output_path=tar_path)
```

### 5.5 新增 `compile` 命令

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
}

# 桩文件模板
INIT_PY_TEMPLATE = '''\
import sys, importlib.util as u, os
d = os.path.dirname(os.path.abspath(__file__))
m, s = sys.modules["{pkg_name}"], sys.modules["{pkg_name}"].__spec__
sp = u.spec_from_file_location("{pkg_name}", os.path.join(d, "{mod_file}"))
lib = u.module_from_spec(sp); sp.loader.exec_module(lib)
sys.meta_path.sort(key=lambda f: type(f).__name__ == "nuitka_module_loader")
m.__dict__.update({{k: v for k, v in vars(lib).items() if k[:2] != "__"}})
m.__spec__, m.__file__, m._RESOURCE_DIR = s, __file__, d
lib._RESOURCE_DIR = d
sys.modules["{pkg_name}"] = m
'''

MAIN_PY_TEMPLATE = '''\
import {pkg_name}
{pkg_name}.main()
'''


def compile_platform(platform: str, project_dir: Path = None):
    """
    编译 Python 源码为 pyd/so 文件
    
    Args:
        platform: 平台名称 (windows/linux)
        project_dir: 项目目录
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
    src_dir = bundle_dir / version_dir / "app"
    
    if not src_dir.exists():
        raise click.ClickException(
            f"Source directory not found: {src_dir}\n"
            f"Run 'pyapp build {platform}' first"
        )
    
    # 检查 Nuitka
    nuitka_version = check_nuitka()
    logger.info(f"Nuitka version: {nuitka_version}")
    
    # 扫描可编译模块
    modules = scan_compilable_modules(src_dir, [app_module])
    if not modules:
        logger.warning("No compilable modules found")
        return
    
    extension = COMPILED_EXTENSIONS.get(platform, ".so")
    
    logger.info(f"Compiling modules: {', '.join(modules)}")
    logger.info(f"Target extension: {extension}")
    
    for module_name in modules:
        try:
            logger.info(f"Compiling {module_name}...")
            mod_file = compile_module(module_name, src_dir, extension)
            inject_stub(module_name, src_dir, mod_file)
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
            "Run: pip install nuitka ordered-set zstandard"
        )
    return result.stdout.strip().split("\n")[0]


def scan_compilable_modules(src_dir: Path, module_filter: Optional[List[str]] = None) -> List[str]:
    """扫描可编译的模块（有 __init__.py 的目录）"""
    skip_dirs = {"__pycache__", "compiled", "app_packages"}
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
    编译单个模块
    
    Args:
        module_name: 模块名
        src_dir: 源码目录
        extension: 编译产物扩展名 (.pyd/.so)
    
    Returns:
        编译产物文件名
    """
    logger = get_logger()
    
    # 创建临时编译目录
    compiled_dir = src_dir / "compiled"
    if compiled_dir.exists():
        shutil.rmtree(compiled_dir)
    compiled_dir.mkdir()
    
    # 构建 Nuitka 命令
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
    
    # 清理临时目录
    shutil.rmtree(compiled_dir, ignore_errors=True)
    
    logger.info(f"Compiled: {compiled_file.name}")
    
    return compiled_file.name


def inject_stub(module_name: str, src_dir: Path, mod_file: str) -> None:
    """
    注入桩文件，使编译模块可通过 python -m 运行
    
    Args:
        module_name: 模块名
        src_dir: 源码目录
        mod_file: 编译产物文件名
    """
    module_dir = src_dir / module_name
    
    # 备份非 .py 资源文件
    _tmpdir = Path(tempfile.mkdtemp())
    try:
        if module_dir.exists():
            for f in module_dir.rglob("*"):
                if f.is_file() and not f.name.endswith(".py"):
                    rel_path = f.relative_to(module_dir)
                    dest = _tmpdir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(f), str(dest))
            
            # 计算资源文件数量
            res_count = sum(1 for _ in _tmpdir.rglob("*") if _.is_file())
            if res_count > 0:
                get_logger().info(f"Preserving {res_count} resource files")
            
            # 删除原模块目录
            shutil.rmtree(module_dir)
        
        # 重新创建模块目录
        module_dir.mkdir()
        
        # 恢复资源文件
        for f in _tmpdir.rglob("*"):
            if f.is_file():
                rel_path = f.relative_to(_tmpdir)
                dest = module_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dest))
    
    finally:
        shutil.rmtree(str(_tmpdir), ignore_errors=True)
    
    # 移动编译产物到模块目录
    src_file = src_dir / mod_file
    if src_file.exists():
        shutil.move(str(src_file), str(module_dir / mod_file))
    
    # 写入桩文件
    (module_dir / "__init__.py").write_text(
        INIT_PY_TEMPLATE.format(pkg_name=module_name, mod_file=mod_file),
        encoding="utf-8"
    )
    (module_dir / "__main__.py").write_text(
        MAIN_PY_TEMPLATE.format(pkg_name=module_name),
        encoding="utf-8"
    )
    
    get_logger().info(f"Stub injected: {module_name}/__init__.py, __main__.py")
```

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


@main.command()
@click.argument("platform", type=click.Choice(["windows", "linux"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
def compile(platform, project_dir):
    """编译 Python 源码为 pyd/so 文件（需要先 build）
    
    使用 Nuitka 将 Python 源码编译为原生二进制，保护源码并提升性能。
    
    注意：需要在对应平台上运行
    - Windows 编译必须在 Windows 上执行
    - Linux 编译必须在 Linux 上执行
    
    前置条件：
    - 安装 Nuitka: pip install nuitka ordered-set zstandard
    - 先执行 pyapp build
    
    示例:
      pyapp build windows
      pyapp compile windows
      pyapp package windows
    """
    from .commands.compile import compile_platform
    compile_platform(platform, Path(project_dir) if project_dir else None)


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

## 7. GitHub Actions 使用示例

### 8.1 Windows 构建

```yaml
# .github/workflows/build-windows.yml

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
        run: pip install nuitka ordered-set zstandard
      
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

### 7.2 Linux 构建（多架构）

```yaml
# .github/workflows/build-linux.yml

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Build on ARM
        uses: uraimo/run-on-arch-action@v3
        with:
          arch: aarch64
          distro: bullseye
          install: |
            apt-get update
            apt-get install -y python3 build-essential
          run: |
            pip3 install -e .
            pip3 install nuitka ordered-set zstandard
            
            pyapp build linux --arch aarch64
            pyapp compile linux
            pyapp package linux
      
      - uses: actions/upload-artifact@v4
        with:
          name: linux-aarch64-package
          path: dist/*.tar.gz
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

Android 平台的 Nuitka 编译需要特殊处理，流程顺序与其他平台不同。

### 9.1 为什么需要特殊处理

| 问题 | 说明 |
|------|------|
| **目标平台限制** | Nuitka 需要在目标平台编译，Android 编译必须在 Termux (ARM) 环境中执行 |
| **跨平台执行** | compile 在 Termux Docker，build/package 在 Linux Runner |
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

由于 compile 和 build/package 在不同平台执行，顺序调整为：

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Termux Docker 编译（ARM 平台）                      │
│                                                             │
│  输入: src/{app_module}/                                    │
│  输出: dist/{app_module}/ (含 .so + 桩文件)                  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: pyapp build android --precompiled（Linux 平台）     │
│                                                             │
│  输入: 编译产物目录                                          │
│  输出: bundles/android/app/src/main/python/{app_module}/    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 3: pyapp package android（Linux 平台）                 │
│                                                             │
│  输入: bundles/android/                                     │
│  输出: dist/{app}-android-{arch}.apk                        │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 与 Windows/Linux 的流程对比

| 平台 | 流程顺序 | compile 执行位置 |
|------|---------|-----------------|
| Windows | build → compile → package | 本机 Windows |
| Linux | build → compile → package | 本机 Linux / QEMU |
| **Android** | **compile → build → package** | Termux Docker (ARM) / Linux |

### 9.4 Termux 编译脚本

只编译源码，生成 `.so` 文件：

```bash
# scripts/termux_compile.sh

cd /src/src/{app_module}

python -m nuitka --module {app_module} --include-package={app_module} \
  --output-dir=/src/dist --remove-output \
  --assume-yes-for-downloads --no-progressbar

# 处理 ELF
cd /src/dist
SO_FILE=$(ls {app_module}.*.so 2>/dev/null | head -1)
mv "$SO_FILE" {app_module}.so
termux-elf-cleaner {app_module}.so || true
patchelf --set-rpath '' {app_module}.so || true
```

### 9.5 pyapp build android 改进

build 步骤需要支持接收预编译的 `.so` 文件：

```python
# platforms/android.py

def build(self, project_dir, config, build_type="debug", arch=None, 
          precompiled_so=None):
    """
    构建 Android 项目
    
    Args:
        precompiled_so: 预编译的 .so 文件路径（可选）
                        如果提供，则直接放入 python 目录，不同步源码
    """
    # ...
    
    if precompiled_so:
        # 使用预编译产物
        self._install_precompiled_module(bundle_dir, precompiled_so, config)
    else:
        # 同步源码（未编译）
        self._sync_python_source(project_dir, bundle_dir, config)
```

### 9.6 GitHub Actions Android 流程示例

```yaml
# .github/workflows/build-android.yml

jobs:
  # Step 1: Termux 编译（ARM 平台）
  compile:
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

  # Step 2 + 3: build + package（Linux 平台）
  build-package:
    needs: compile
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - uses: actions/download-artifact@v4
        with:
          name: compiled-so
          path: dist
      
      - name: Build with precompiled module
        run: pyapp build android --precompiled dist/{app_module}.so
      
      - name: Package APK
        run: pyapp package android
      
      - uses: actions/upload-artifact@v4
        with:
          name: android-apk
          path: dist/*.apk
```

### 9.7 CLI 命令扩展

```python
# cli.py

@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux", "all"]))
@click.option("--precompiled", type=click.Path(exists=True), 
              help="预编译的 .so/.pyd 文件路径（Android 专用）")
def build(platform, precompiled, ...):
    """准备平台构建目录"""
    if platform == "android" and precompiled:
        # 使用预编译产物
        ...
```

### 9.8 总结

| 步骤 | 命令/操作 | 执行平台 | 输入 | 输出 |
|------|----------|---------|------|------|
| 1 | Termux Docker 编译 | ARM | `src/{module}/` | `dist/{module}.so` |
| 2 | `pyapp build android --precompiled` | Linux | `.so` 文件 | `bundles/android/` |
| 3 | `pyapp package android` | Linux | `bundles/android/` | `dist/*.apk` |

**关键点**：
- compile 在 Termux Docker (ARM) 执行，只需要源码
- build 在 Linux 执行，接收预编译产物
- 减少跨平台文件传输（只传输 `.so` 文件）

---

## 10. 待确认事项

1. **Android 平台** ✅ 已确认：不实现 `pyapp compile android` 命令，Android 编译在 GitHub Actions 中通过 Termux Docker 完成。

2. **签名功能**：`package` 命令是否需要集成签名功能（Windows signtool / Android jarsigner）？

3. **向后兼容**：是否需要保留 `build` 的打包行为（通过参数控制）？

4. **`dev` 命令**：`dev` 命令目前调用 `build`，重构后是否需要调整？

---

## 11. 实施步骤

1. 修改 `BasePlatform.build()` 抽象方法签名
2. 修改 `WindowsPlatform.build()` 和 `package()`
3. 修改 `LinuxPlatform.build()` 和 `package()`
4. 新增 `commands/compile.py`
5. 更新 `cli.py` 命令注册
6. 更新文档和帮助信息
7. 添加 GitHub Actions workflow 示例