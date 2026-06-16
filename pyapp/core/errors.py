"""PyApp 错误类型定义"""


class PyAppError(Exception):
    """基础错误类"""
    def __init__(self, message: str, hint: str = ""):
        self.message = message
        self.hint = hint
        super().__init__(message)

    def __str__(self):
        if self.hint:
            return f"{self.message}\n  Hint: {self.hint}"
        return self.message


class ConfigError(PyAppError):
    """配置错误"""
    pass


class PyAppEnvironmentError(PyAppError):
    """环境错误"""
    pass


class BuildError(PyAppError):
    """构建错误"""
    pass


class DownloadError(PyAppError):
    """下载错误"""
    pass


class VerificationError(PyAppError):
    """验证错误"""
    pass
