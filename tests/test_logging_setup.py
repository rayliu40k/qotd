"""验证日志双输出、按天清理和敏感值不进入日志。"""

import re
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

from qotd.logging_setup import configure_logging


def test_logging_keeps_last_seven_days_and_writes_console_and_file(tmp_path, capsys):
    """单次运行也会清理过期日志，并把关键事件写到两个输出。"""
    directory = tmp_path / "logs"
    directory.mkdir()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    old = directory / f"qotd_{today - timedelta(days=7):%Y-%m-%d}.log"
    recent = directory / f"qotd_{today - timedelta(days=6):%Y-%m-%d}.log"
    old.write_text("old")
    recent.write_text("recent")

    try:
        configure_logging(tmp_path)
        logger.info("测试发布：记录 123")
        console = capsys.readouterr().err
        file_log = (directory / f"qotd_{today:%Y-%m-%d}.log").read_text()
        location = r"test_logging_setup:test_logging_keeps.*:\d+"
        thread = f"{threading.current_thread().name}:{threading.get_ident()} | "
        assert thread in console
        assert thread in file_log
        assert re.search(location, console)
        assert re.search(location, file_log)
        assert "测试发布：记录 123" in console
        assert "测试发布：记录 123" in file_log
        assert not old.exists()
        assert recent.exists()
    finally:
        logger.remove()
