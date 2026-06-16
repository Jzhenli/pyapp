"""pyapp dev 命令 - 开发模式（文件监听 + 热重载）"""

from pathlib import Path

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..platforms import get_platform


def dev_platform(platform: str, project_dir: Path = None):
    """
    开发模式（文件监听 + 热重载）

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
        raise click.ClickException("'dev' command does not support 'all' platform. Specify a single platform.")

    try:
        platform_instance = get_platform(platform)
        platform_instance.dev(project_dir, config_dict)
    except ValueError as e:
        raise click.ClickException(str(e))
    except KeyboardInterrupt:
        logger.info("Development mode stopped")
    except Exception as e:
        logger.error(f"Development mode failed: {e}")
        raise click.ClickException(f"Development mode failed: {e}")
