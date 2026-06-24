"""PyApp CLI - 跨平台打包工具命令行入口"""

from pathlib import Path

import click

from . import __version__
from .core.logger import get_logger, setup_logging


@click.group()
@click.version_option(version=__version__, prog_name="pyapp")
@click.option("-v", "--verbose", is_flag=True, help="启用详细日志输出")
@click.option("--log-file", type=click.Path(), help="自定义日志文件路径")
def main(verbose, log_file):
    """PyApp CLI - 跨平台打包工具

    一份 Python 代码，一行命令，三平台安装包
    """
    setup_logging(verbose=verbose, log_file=Path(log_file) if log_file else None)


@main.command()
@click.argument("name")
@click.option("-t", "--template", type=click.Choice(["basic", "fastapi"]), default="fastapi", help="项目模板")
@click.option("-o", "--output-dir", type=click.Path(), help="输出目录")
def init(name, template, output_dir):
    """初始化新项目"""
    from .commands.init import init_project
    init_project(name, template, output_dir)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux", "all"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
@click.option("--arch", type=str, default=None,
              help="目标架构。Android: arm64-v8a, armeabi-v7a, x86_64 (多个用逗号分隔)")
def create(platform, project_dir, arch):
    """创建平台项目结构"""
    from .commands.create import create_platform
    create_platform(platform, Path(project_dir) if project_dir else None, arch)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux", "all"]))
@click.option("-t", "--type", "build_type", type=click.Choice(["debug", "release"]), default="debug", help="构建类型")
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
@click.option("--no-create", is_flag=True, help="不自动创建平台项目结构")
@click.option("--arch", type=str, default=None,
              help="目标架构。Linux: x86_64, aarch64, armv7l。Android: arm64-v8a, armeabi-v7a, x86_64 (多个用逗号分隔)")
def build(platform, build_type, project_dir, no_create, arch):
    """准备平台构建目录（不打包）

    此命令准备 bundles 目录结构，包括：
    - Python 运行时
    - 应用源码
    - pip 依赖
    - 启动脚本

    后续可执行 compile（可选）和 package 完成打包。

    示例:
      pyapp build linux                         # 构建 Linux x86_64
      pyapp build linux --arch aarch64          # 构建 Linux ARM64
      pyapp build android                       # 构建 Android (使用 pyproject.toml 配置)
      pyapp build android --arch arm64-v8a      # 构建 Android arm64-v8a
      pyapp build android --arch arm64-v8a,armeabi-v7a  # 构建多架构
    """
    from .commands.build import build_platform
    build_platform(platform, build_type, Path(project_dir) if project_dir else None, no_create, arch)


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
      pyapp compile android --precompiled dist/app.so
      pyapp package android
    """
    from .commands.compile import compile_platform
    compile_platform(platform, Path(project_dir) if project_dir else None,
                     Path(precompiled) if precompiled else None)


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
      pyapp run windows -u           # 更新源码后运行
      pyapp run windows -ur          # 更新依赖和源码后运行
    """
    from .commands.run import run_platform
    run_platform(platform, Path(project_dir) if project_dir else None,
                 update=update, rebuild=rebuild)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux", "all"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
def package(platform, project_dir):
    """打包分发文件（需要先 build，可选 compile）

    将 bundles 目录打包为分发文件：
    - Windows: ZIP
    - Linux: tar.gz
    - Android: APK

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


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux"]))
@click.argument("target")  # 目标设备地址
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
@click.option("--update-only", is_flag=True, help="仅推送增量更新")
@click.option("--rollback", type=str, help="回滚到指定版本")
def deploy(platform, target, project_dir, update_only, rollback):
    """部署到目标设备"""
    from .commands.deploy import deploy_platform
    deploy_platform(platform, target, Path(project_dir) if project_dir else None,
                   update_only, rollback)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux"]))
def setup(platform):
    """安装平台依赖环境"""
    from .commands.setup import setup_platform
    setup_platform(platform)


@main.command()
@click.option("--lines", "-n", default=50, help="显示的行数")
@click.option("--clear", is_flag=True, help="清空日志文件")
def logs(lines, clear):
    """查看或管理日志"""
    from .commands.logs import show_logs, clear_logs
    if clear:
        clear_logs()
    else:
        show_logs(lines)


if __name__ == "__main__":
    main()
