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
    """生成 GitHub Actions CI 脚本"""
    ci_template_dir = Path(__file__).parent.parent / "templates" / "ci"
    workflows_dir = project_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    
    jinja_env = Environment(loader=FileSystemLoader(str(ci_template_dir)))
    
    for template_name in ["build-windows.yml.j2", "build-linux.yml.j2", "build-android.yml.j2"]:
        jinja_template = jinja_env.get_template(template_name)
        content = jinja_template.render(
            name=name,
            module_name=module_name,
        )
        output_name = template_name.replace(".j2", "")
        (workflows_dir / output_name).write_text(content, encoding="utf-8")
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
        run: pyapp compile android --precompiled dist/{{ module_name }}.so
      
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

只负责编译源码，生成 `.so` 文件：

```bash
# scripts/termux_compile.sh

cd /src/src
APP_MODULE="{app_module}"

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

# 最终产物: dist/{app_module}.so
```

### 9.5 pyapp compile android 改进

compile 命令添加 `--precompiled` 参数，支持使用预编译的 `.so` 文件：

```python
# commands/compile.py

def compile_platform(platform: str, project_dir: Path = None, precompiled: Path = None):
    """
    编译 Python 源码为 pyd/so 文件
    
    Args:
        platform: 平台名称 (windows/linux/android)
        project_dir: 项目目录
        precompiled: 预编译的 .so 文件路径（Android 专用）
                     如果提供，跳过 Nuitka 编译，直接使用该文件替换源码
    """
    # ... 加载配置、检查 bundles 目录 ...
    
    if platform == "android":
        if precompiled:
            # Android 发布流程：使用 Termux 预编译的 .so
            if not precompiled.exists():
                raise click.ClickException(f"Precompiled .so not found: {precompiled}")
            logger.info(f"Using precompiled module: {precompiled}")
            for module_name in modules:
                install_precompiled_module(module_name, src_dir, precompiled)
        else:
            raise click.ClickException(
                "Android compile requires --precompiled option.\n"
                "Run Termux Docker first to generate .so file.\n"
                "See: scripts/termux_compile.sh"
            )
    else:
        # Windows/Linux: 本机 Nuitka 编译
        for module_name in modules:
            mod_file = compile_module(module_name, src_dir, extension)
            inject_stub(module_name, src_dir, mod_file)


def install_precompiled_module(module_name: str, src_dir: Path, so_file: Path):
    """
    使用预编译的 .so 文件替换源码，并注入桩文件
    
    Args:
        module_name: 模块名
        src_dir: bundles 目录中的源码目录
        so_file: Termux 预编译的 .so 文件路径
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
            shutil.rmtree(module_dir)
        
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
    
    # 复制 .so 文件到模块目录
    so_name = so_file.name
    shutil.copy2(str(so_file), str(module_dir / so_name))
    
    # 注入桩文件
    (module_dir / "__init__.py").write_text(
        INIT_PY_TEMPLATE.format(pkg_name=module_name, mod_file=so_name),
        encoding="utf-8"
    )
    (module_dir / "__main__.py").write_text(
        MAIN_PY_TEMPLATE.format(pkg_name=module_name),
        encoding="utf-8"
    )
    
    logger.success(f"Module {module_name} installed with precompiled .so")
```

### 9.6 GitHub Actions Android 流程示例

```yaml
# .github/workflows/build-android.yml

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
        run: pyapp compile android --precompiled dist/{app_module}.so
      
      - name: Package APK
        run: pyapp package android
      
      - uses: actions/upload-artifact@v4
        with:
          name: android-apk
          path: dist/*.apk
```

### 9.7 CLI 命令扩展

compile 命令添加 `--precompiled` 参数：

```python
# cli.py

@main.command()
@click.argument("platform", type=click.Choice(["windows", "linux", "android"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
@click.option("--precompiled", type=click.Path(exists=True), 
              help="预编译的 .so 文件路径（Android 专用，Termux 编译产物）")
def compile(platform, project_dir, precompiled):
    """编译 Python 源码为 pyd/so 文件（需要先 build）
    
    使用 Nuitka 将 Python 源码编译为原生二进制，保护源码并提升性能。
    
    注意：
    - Windows/Linux: 在本机执行 Nuitka 编译
    - Android: 需要先通过 Termux Docker 编译，再使用 --precompiled 指定 .so 文件
    
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
      pyapp compile android --precompiled dist/{app_module}.so
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

3. **向后兼容**：是否需要保留 `build` 的打包行为（通过参数控制）？

4. **`dev` 命令移除** ✅ 已确认：移除 `pyapp dev` 命令，改为 `run` 命令支持更新参数。

   - 移除 `pyapp dev` 命令
   - 增强 `pyapp run` 命令，添加 `-u/--update` 和 `-r/--rebuild` 参数（类似 Briefcase）
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
       
       示例:
         pyapp run windows              # 直接运行
         pyapp run windows -u          # 更新源码后运行
         pyapp run windows -ur         # 更新依赖和源码后运行
       """
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

1. 修改 `BasePlatform.build()` 抽象方法签名
2. 修改 `WindowsPlatform.build()` 和 `package()`
3. 修改 `LinuxPlatform.build()` 和 `package()`
4. 新增 `commands/compile.py`（含 `install_precompiled_module` 函数）
5. 移除 `pyapp dev` 命令（`cli.py` + `commands/dev.py` + 各平台 `dev()` 方法）
6. 增强 `pyapp run` 命令，添加 `-u/--update` 和 `-r/--rebuild` 参数
7. 更新 `cli.py` 命令注册
8. 更新文档和帮助信息
9. 添加 GitHub Actions workflow 示例