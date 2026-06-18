"""pyapp dev 命令 - 开发模式（文件监听 + 热重载）"""

from pathlib import Path
import re

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..platforms import get_platform


def _sync_frontend_env(project_dir: Path, port: int) -> None:
    """
    Sync frontend .env.development with backend port configuration.
    
    Args:
        project_dir: Project directory
        port: Backend port from pyproject.toml
    """
    env_file = project_dir / "frontend" / ".env.development"
    
    if not env_file.exists():
        # Create .env.development if not exists
        env_content = f"# Backend API port for development\n# Auto-synced from pyproject.toml\nVITE_API_PORT={port}\n"
        env_file.write_text(env_content, encoding="utf-8")
        return
    
    # Update existing .env.development
    content = env_file.read_text(encoding="utf-8")

    # Update VITE_API_PORT value (support various formats: with quotes, spaces, etc.)
    new_content = re.sub(
        r'VITE_API_PORT\s*=\s*[\'"]?\d+[\'"]?',
        f'VITE_API_PORT={port}',
        content
    )

    if new_content != content:
        try:
            env_file.write_text(new_content, encoding="utf-8")
            logger = get_logger()
            logger.info(f"Synced frontend port to {port}")
        except (PermissionError, OSError, IOError) as e:
            logger = get_logger()
            logger.warning(f"Failed to sync frontend .env.development: {e}")


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

    # Sync frontend .env.development with backend port
    port = config_dict.get("tool", {}).get("pyapp", {}).get("port", 18080)
    _sync_frontend_env(project_dir, port)

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
