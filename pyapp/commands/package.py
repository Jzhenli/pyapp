"""pyapp package 命令 - 打包发布版"""

from pathlib import Path

import click

from ..core.config import load_config
from ..core.logger import get_logger
from ..platforms import get_platform, PLATFORMS


def package_platform(platform: str, project_dir: Path = None):
    """
    打包发布版（签名、优化）

    Args:
        platform: 平台名称 (android/windows/linux/all)
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

    # 确定要打包的平台
    if platform == "all":
        platforms = list(PLATFORMS.keys())
    else:
        platforms = [platform]

    results = []
    for plat in platforms:
        logger.info(f"Packaging {plat}...")
        try:
            platform_instance = get_platform(plat)
            result = platform_instance.package(project_dir, config_dict)
            results.append((plat, result))

            if result.success:
                logger.success(f"{plat} package succeeded: {result.output_path}")
            else:
                logger.error(f"{plat} package failed: {result.error_message}")

        except ValueError as e:
            raise click.ClickException(str(e))
        except Exception as e:
            logger.error(f"{plat} package failed: {e}")
            from ..platforms.base import BuildResult
            results.append((plat, BuildResult(success=False, error_message=str(e))))

    # 汇总结果
    logger.info("")
    logger.info("Package Summary:")
    for plat, result in results:
        if result.success:
            logger.success(f"  {plat}: {result.output_path}")
        else:
            logger.error(f"  {plat}: {result.error_message}")

    failed = [plat for plat, result in results if not result.success]
    if failed:
        raise click.ClickException(f"Package failed for: {', '.join(failed)}")
