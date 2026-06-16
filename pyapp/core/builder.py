"""构建器模块 - 前端资源同步和版本管理"""

import json
import shutil
from pathlib import Path
from typing import Optional
from .logger import get_logger


def sync_frontend_dist(project_dir: Path, platform: str, app_module: str, version_dir: str = "app") -> Optional[Path]:
    """
    将前端编译产物同步到打包目录

    源: frontend/dist/
    目标: bundles/{platform}/{version_dir}/app/{app_module}/resources/static/

    Args:
        project_dir: 项目根目录
        platform: 平台名称
        app_module: Python 模块名
        version_dir: 版本号目录名 (如 "my-app-0.1.0")

    Returns:
        目标目录路径，如果源不存在则返回 None
    """
    logger = get_logger()
    frontend_dist = project_dir / "frontend" / "dist"

    target_static = (
        project_dir / "bundles" / platform / version_dir / "app" /
        app_module / "resources" / "static"
    )

    if not frontend_dist.exists():
        logger.warning("frontend/dist/ not found, skipping frontend sync")
        return None

    # 同步前端资源
    if target_static.exists():
        shutil.rmtree(target_static)
    shutil.copytree(frontend_dist, target_static)

    logger.success(f"Synced frontend/dist/ → {target_static}")
    return target_static


def validate_frontend_version(frontend_dist: Path, backend_version: str) -> bool:
    """
    验证前端版本与后端 API 版本的兼容性

    Args:
        frontend_dist: 前端编译产物目录
        backend_version: 后端版本号

    Returns:
        是否兼容
    """
    logger = get_logger()
    version_file = frontend_dist / "version.json"
    if not version_file.exists():
        logger.debug("Frontend version.json not found, skipping version check")
        return True

    try:
        with open(version_file, "r", encoding="utf-8") as f:
            frontend_version = json.load(f)

        # 比较主版本号
        frontend_major = frontend_version.get("version", "0.0.0").split(".")[0]
        backend_major = backend_version.split(".")[0]

        if frontend_major != backend_major:
            logger.warning(
                f"Major version mismatch - Frontend: {frontend_major}, Backend: {backend_major}"
            )
            return False

        return True

    except Exception as e:
        logger.warning(f"Failed to validate frontend version: {e}")
        return True  # 验证失败时允许继续，但给出警告


def generate_frontend_version_file(
    frontend_dir: Path, version: str, api_version: str = "1.0"
) -> None:
    """
    生成前端版本信息文件

    Args:
        frontend_dir: 前端项目目录
        version: 前端版本号
        api_version: API 版本号
    """
    import datetime

    version_info = {
        "version": version,
        "api_version": api_version,
        "build_time": datetime.datetime.now().isoformat(),
        "git_commit": get_git_commit_hash(frontend_dir),
    }

    dist_dir = frontend_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    version_file = dist_dir / "version.json"
    with open(version_file, "w", encoding="utf-8") as f:
        json.dump(version_info, f, indent=2)

    print(f"Generated frontend version file: {version_file}")


def get_git_commit_hash(project_dir: Path) -> Optional[str]:
    """获取 Git 提交哈希"""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()[:8]
    except Exception:
        return None
