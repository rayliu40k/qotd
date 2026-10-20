from pathlib import Path
from uuid import UUID

import pytest

from qotd import cli
from qotd.cli import Config, publication_lock
from qotd.models import PublicationError
from qotd.settings import (
    DAILY_DATA_SOURCE_ID,
    HOME_PAGE_ID,
    MANAGED_BLOCK_ID,
    PENDING_STATUS,
    PUBLISHED_STATUS,
    QUOTES_DATA_SOURCE_ID,
)


def test_real_config_has_valid_unique_ids():
    config = Config.load(Path("qotd.toml"))
    ids = [
        config.home_page_id,
        config.managed_block_id,
        config.quotes_data_source_id,
        config.daily_data_source_id,
    ]
    assert len(set(ids)) == 4
    assert all(str(UUID(v)) == v for v in ids)
    assert ids == [HOME_PAGE_ID, MANAGED_BLOCK_ID, QUOTES_DATA_SOURCE_ID, DAILY_DATA_SOURCE_ID]
    assert (config.pending_status, config.published_status) == (PENDING_STATUS, PUBLISHED_STATUS)


def test_missing_config_has_actionable_error(tmp_path):
    with pytest.raises(PublicationError, match="配置"):
        Config.load(tmp_path / "missing.toml")


def test_page_url_template_can_be_changed_in_toml(tmp_path):
    original = Path("qotd.toml").read_text()
    custom = original.replace("https://www.notion.so/{page_id}", "https://notion.so/{page_id}")
    path = tmp_path / "qotd.toml"
    path.write_text(custom)
    config = Config.load(path)
    assert (config.pending_status, config.published_status) == (PENDING_STATUS, PUBLISHED_STATUS)
    assert config.page_url_template == "https://notion.so/{page_id}"


@pytest.mark.parametrize("extra", ['[notion]\nhome_page_id = "old"\n', 'pending_status = "旧"\n'])
def test_obsolete_config_keys_are_rejected(tmp_path, extra):
    original = Path("qotd.toml").read_text()
    path = tmp_path / "qotd.toml"
    path.write_text(original + extra)
    with pytest.raises(PublicationError, match="配置"):
        Config.load(path)


@pytest.mark.parametrize("template", ["http://notion.so/{page_id}", "https://notion.so/id"])
def test_invalid_page_url_template_fails_before_publish(tmp_path, template):
    path = tmp_path / "qotd.toml"
    path.write_text(
        Path("qotd.toml").read_text().replace("https://www.notion.so/{page_id}", template)
    )
    with pytest.raises(PublicationError, match="配置"):
        Config.load(path)


def test_cli_reports_success_through_logger_without_print(monkeypatch, capsys):
    events = []
    from loguru import logger

    sink = logger.add(lambda message: events.append(str(message)))
    monkeypatch.setattr(cli, "configure_logging", lambda _: None)
    monkeypatch.setattr(cli, "load_dotenv", lambda _: None)
    monkeypatch.setenv("NOTION_TOKEN", "test-token")

    class Api:
        async def aclose(self):
            pass

    async def fake_publish(_api, _config):
        return {
            "date": "2026-10-17",
            "record_id": "id",
            "quote": "测试金句",
            "home": "https://notion.so/id",
        }

    monkeypatch.setattr(cli, "Notion", lambda _: Api())
    monkeypatch.setattr(
        cli,
        "publish",
        fake_publish,
    )
    monkeypatch.setattr("sys.argv", ["qotd", "daily"])
    try:
        assert cli.main() == 0
        assert capsys.readouterr().out == ""
        assert any("发布成功" in event and "测试金句" in event for event in events)
    finally:
        logger.remove(sink)


def test_missing_config_directory_logs_error_to_current_project(monkeypatch, tmp_path, capsys):
    """配置目录不存在时，仍将最终错误写到当前项目的日志文件。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from loguru import logger

    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "missing" / "qotd.toml"
    monkeypatch.setattr("sys.argv", ["qotd", "daily", "--config", str(missing)])
    try:
        assert cli.main() == 1
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        log_file = tmp_path / "logs" / f"qotd_{day:%Y-%m-%d}.log"
        content = log_file.read_text()
        assert "配置目录无法写入日志" in content
        assert "ERROR" in content and "无法读取配置" in content
        assert "无法读取配置" in capsys.readouterr().err
    finally:
        logger.remove()


def test_process_lock_prevents_concurrent_publish_and_is_reusable():
    home = str(UUID(int=999))
    with publication_lock(home):
        with pytest.raises(PublicationError, match="发布进程"):
            with publication_lock(home):
                pytest.fail("lock should prevent concurrent publication")
    with publication_lock(home):
        pass
