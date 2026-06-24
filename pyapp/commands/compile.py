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
# 基于 hello 项目已验证的 INIT_PY_TEMPLATE (Nuitka 2.7.12 已验证)
# 关键设计：利用 sys.modules 中已存在的部分初始化模块，避免循环导入
# 重要：前后两次设置 _RESOURCE_DIR，确保不被 update 覆盖
INIT_PY_TEMPLATE = '''\
import sys, importlib.util as u, os
d = os.path.dirname(os.path.abspath(__file__))
m, s, m._RESOURCE_DIR = sys.modules["{pkg_name}"], sys.modules["{pkg_name}"].__spec__, d
sp = u.spec_from_file_location("{pkg_name}", os.path.join(d, "{mod_file}"))
lib = u.module_from_spec(sp); sp.loader.exec_module(lib)
sys.meta_path.sort(key=lambda f: type(f).__name__ == "nuitka_module_loader")
m.__dict__.update({{k: v for k, v in vars(lib).items() if k in {{ "__version__", "__all__" }} or k[:2] != "__"}})
m.__spec__, m.__file__, m._RESOURCE_DIR = s, __file__, d
lib._RESOURCE_DIR = d
sys.modules["{pkg_name}"] = m
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
