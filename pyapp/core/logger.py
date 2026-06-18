"""PyApp 日志系统"""

import logging
import sys
import os
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime


class SafeStreamHandler(logging.StreamHandler):
    """安全的流处理器，避免管道关闭时的错误"""

    def flush(self):
        """安全刷新，忽略 Bad file descriptor 错误"""
        try:
            if self.stream and hasattr(self.stream, "flush"):
                self.stream.flush()
        except OSError:
            # 忽略管道关闭错误
            pass

    def emit(self, record):
        """安全输出日志"""
        try:
            super().emit(record)
        except OSError:
            # 忽略管道关闭错误
            pass


class PyAppLogger:
    """PyApp 日志管理器"""

    def __init__(self, name: str = "pyapp", log_dir: Optional[Path] = None):
        """
        初始化日志管理器

        Args:
            name: 日志器名称
            log_dir: 日志文件目录，默认为 ~/.pyapp/logs/
        """
        self.name = name
        self.log_dir = log_dir or Path.home() / ".pyapp" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 创建日志器
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # 避免重复添加 handler
        if not self.logger.handlers:
            self._setup_handlers()

    def _setup_handlers(self):
        """设置日志处理器"""
        # 控制台处理器（使用安全处理器避免管道错误）
        console_handler = SafeStreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            '%(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)

        # 文件处理器
        log_file = self.log_dir / f"{self.name}_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        self.logger.addHandler(file_handler)

    def set_level(self, level: str):
        """
        设置日志级别

        Args:
            level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        """
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        self.logger.setLevel(level_map.get(level.upper(), logging.INFO))

    def debug(self, message: str):
        """记录调试信息"""
        self.logger.debug(message)

    def info(self, message: str):
        """记录一般信息"""
        self.logger.info(message)

    def warning(self, message: str):
        """记录警告信息"""
        self.logger.warning(message)

    def error(self, message: str, exc_info: bool = False):
        """
        记录错误信息

        Args:
            message: 错误消息
            exc_info: 是否包含异常堆栈信息
        """
        self.logger.error(message, exc_info=exc_info)

    def success(self, message: str):
        """记录成功信息"""
        self.logger.info(f"✓ {message}")

    def step(self, step_num: int, total_steps: int, message: str):
        """
        记录构建步骤

        Args:
            step_num: 当前步骤号
            total_steps: 总步骤数
            message: 步骤描述
        """
        self.logger.info(f"[{step_num}/{total_steps}] {message}")


# 全局日志实例（按名称缓存）
_loggers: Dict[str, "PyAppLogger"] = {}


def get_logger(name: str = "pyapp", log_dir: Optional[Path] = None) -> PyAppLogger:
    """
    获取日志实例

    Args:
        name: 日志器名称
        log_dir: 日志文件目录

    Returns:
        日志管理器实例
    """
    if name not in _loggers:
        _loggers[name] = PyAppLogger(name, log_dir)
    return _loggers[name]


def setup_logging(verbose: bool = False, log_file: Optional[Path] = None):
    """
    配置日志系统

    Args:
        verbose: 是否启用详细日志
        log_file: 自定义日志文件路径
    """
    logger = get_logger()

    if verbose:
        logger.set_level("DEBUG")

    if log_file:
        # 添加自定义文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_format)
        logger.logger.addHandler(file_handler)
