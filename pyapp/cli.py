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
    """构建平台安装包

    示例:
      pyapp build linux                         # 构建 Linux x86_64
      pyapp build linux --arch aarch64          # 构建 Linux ARM64
      pyapp build android                       # 构建 Android (使用 pyproject.toml 配置)
      pyapp build android --arch arm64-v8a      # 构建 Android arm64-v8a
      pyapp build android --arch arm64-v8a,armeabi-v7a  # 构建多架构
    """
    from .commands.build import build_platform
    build_platform(platform, build_type, Path(project_dir) if project_dir else None, no_create, arch)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
def run(platform, project_dir):
    """安装并运行应用"""
    from .commands.run import run_platform
    run_platform(platform, Path(project_dir) if project_dir else None)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
def dev(platform, project_dir):
    """开发模式（文件监听 + 热重载）"""
    from .commands.dev import dev_platform
    dev_platform(platform, Path(project_dir) if project_dir else None)


@main.command()
@click.argument("platform", type=click.Choice(["android", "windows", "linux", "all"]))
@click.option("-d", "--project-dir", type=click.Path(exists=True), help="项目目录")
def package(platform, project_dir):
    """打包发布版"""
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
