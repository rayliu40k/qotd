"""配置 Loguru 的控制台与文件日志输出。

日志按北京时间逐日命名，运行时清理七天前的文件，并限制单文件大小。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from .settings import LOG_MAX_BYTES, LOG_RETENTION_DAYS, SHANGHAI


def configure_logging(project_dir: Path) -> None:
    """在项目 ``logs`` 目录建立双输出并清理过期日志。

    每日命令通常只启动一次，不能仅依赖 Loguru 轮转时触发的保留策略；
    因此每次启动先按北京时间清理旧日期文件，再注册两个输出端。
    """
    directory = project_dir / "logs"
    directory.mkdir(exist_ok=True)
    today = datetime.now(SHANGHAI).date()
    cutoff = today - timedelta(days=LOG_RETENTION_DAYS - 1)
    for path in directory.glob("qotd_*.log*"):
        try:
            day = datetime.strptime(path.name[5:15], "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < cutoff and path.is_file():
            path.unlink()

    logger.remove()
    fmt = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | "
        "{thread.name}:{thread.id} | {name}:{function}:{line} - {message}"
    )
    logger.add(sys.stderr, level="INFO", format=fmt, backtrace=False, diagnose=False)
    logger.add(
        directory / f"qotd_{today:%Y-%m-%d}.log",
        level="INFO",
        format=fmt,
        rotation=LOG_MAX_BYTES,
        retention=timedelta(days=LOG_RETENTION_DAYS),
        backtrace=False,
        diagnose=False,
    )
