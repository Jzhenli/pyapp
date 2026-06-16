"""pyapp run 命令 - 安装并运行应用"""

from pathlib import Path

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..platforms import get_platform, PLATFORMS


def run_platform(platform: str, project_dir: Path = None):
    """
    安装并运行应用

    Args:
        platform: 平台名称 (android/windows/linux)
        project_dir: 项目目录，默认为当前目录
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
            "pyproject.toml not found. Run 'pyapp init' to create a new project."
        )
    except ValueError as e:
        raise click.ClickException(f"Configuration error: {e}")

    if platform == "all":
        raise click.ClickException("'run' command does not support 'all' platform. Specify a single platform.")

    try:
        platform_instance = get_platform(platform)
        platform_instance.run(project_dir, config_dict)
    except ValueError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        logger.error(f"Failed to run {platform} app: {e}")
        raise click.ClickException(f"Failed to run {platform} app: {e}")
