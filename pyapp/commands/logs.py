"""pyapp logs 命令 - 查看或管理日志"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from ..core.logger import get_logger


def show_logs(lines: int = 50):
    """
    显示最近的日志

    Args:
        lines: 显示的行数
    """
    logger = get_logger()
    log_file = logger.log_dir / f"pyapp_{datetime.now().strftime('%Y%m%d')}.log"

    if not log_file.exists():
        # 尝试查找最新的日志文件
        log_files = sorted(logger.log_dir.glob("pyapp_*.log"), reverse=True)
        if log_files:
            log_file = log_files[0]
        else:
            click.echo("No log files found")
            return

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            display_lines = all_lines[-lines:]
            for line in display_lines:
                click.echo(line.rstrip())
    except Exception as e:
        click.echo(f"Failed to read log file: {e}")


def clear_logs():
    """清空日志文件"""
    logger = get_logger()

    log_files = list(logger.log_dir.glob("pyapp_*.log"))
    if not log_files:
        click.echo("No log files to clear")
        return

    for log_file in log_files:
        log_file.unlink()

    click.echo(f"Cleared {len(log_files)} log file(s)")
