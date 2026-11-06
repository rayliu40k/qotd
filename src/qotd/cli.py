"""提供 ``qotd daily`` 和 ``qotd republish`` 命令。

此模块加载 Notion 配置和本地密钥，并用进程锁避免同一台电脑并发发布。
所有运行结果都经 Loguru 输出到控制台和日志文件。
"""

import argparse
import asyncio
import fcntl
import os
import tempfile
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv
from loguru import logger

from .logging_setup import configure_logging
from .models import PublicationError, canonical_id
from .notion import Notion
from .publisher import publish
from .republish import republish
from .settings import (
    DAILY_DATA_SOURCE_ID,
    HOME_PAGE_ID,
    MANAGED_BLOCK_ID,
    PENDING_STATUS,
    PUBLISHED_STATUS,
    QUOTES_DATA_SOURCE_ID,
    page_url,
)


@dataclass(frozen=True)
class Config:
    """组合固定的 Notion 对象、状态名和可调整的页面链接模板。"""

    page_url_template: str
    home_page_id: str = HOME_PAGE_ID
    managed_block_id: str = MANAGED_BLOCK_ID
    quotes_data_source_id: str = QUOTES_DATA_SOURCE_ID
    daily_data_source_id: str = DAILY_DATA_SOURCE_ID
    pending_status: str = PENDING_STATUS
    published_status: str = PUBLISHED_STATUS

    @classmethod
    def load(cls, path: Path):
        """只从 TOML 读取页面链接模板，校验固定 ID 与生成的链接。

        缺失或无效配置会抛出不含密钥的 ``PublicationError``。
        """
        try:
            data = tomllib.loads(path.read_text())
            publication = data["publication"]
            if set(data) != {"publication"} or set(publication) != {"page_url_template"}:
                raise ValueError("unexpected configuration keys")
            config = cls(page_url_template=publication["page_url_template"])
            for id_ in (
                config.home_page_id,
                config.managed_block_id,
                config.quotes_data_source_id,
                config.daily_data_source_id,
            ):
                canonical_id(id_)
            if not config.pending_status.strip() or not config.published_status.strip():
                raise ValueError("empty status")
            if config.pending_status == config.published_status:
                raise ValueError("statuses must differ")
            page_url(config.home_page_id, config.page_url_template)
            return config
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise PublicationError("无法读取配置，请检查 qotd.toml。") from error


@contextmanager
def publication_lock(home_id):
    """获取首页专用的本机进程锁，并在退出时释放。

    锁只防同机并发；每日记录在 Notion 中保存，锁文件不存业务状态。
    """
    path = Path(tempfile.gettempdir()) / f"qotd-{canonical_id(home_id)}.lock"

    def opener(name, flags):
        """以仅当前用户可读写的方式打开本机锁文件。"""
        return os.open(name, flags | os.O_NOFOLLOW, 0o600)

    with open(path, "a", opener=opener) as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PublicationError("已有发布进程运行，请稍后重试。") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


async def run_publication(token: str, config: Config, command: str = "daily"):
    """在同一事件循环中完成所选发布命令，并关闭异步 Notion 客户端。"""
    api = Notion(token)
    try:
        if command == "republish":
            return await republish(api, config)
        return await publish(api, config)
    finally:
        await api.aclose()


def main():
    """运行每日发布或当天原句重发，成功返回零状态码。"""
    parser = argparse.ArgumentParser(description="发布 Notion 每日金句")
    commands = parser.add_subparsers(dest="command", required=True)
    daily = commands.add_parser("daily", help="发布北京时间当天的金句")
    daily.add_argument("--config", type=Path, default=Path("qotd.toml"))
    retry = commands.add_parser("republish", help="重发北京时间当天已发布的同一条金句")
    retry.add_argument("--config", type=Path, default=Path("qotd.toml"))
    args = parser.parse_args()
    started_at = perf_counter()
    try:
        path = args.config.resolve()
        try:
            configure_logging(path.parent)
        except OSError as error:
            # 配置路径不可用时，先把文件日志落到当前目录，再报告配置错误。
            fallback = Path.cwd()
            if fallback == path.parent:
                raise
            configure_logging(fallback)
            logger.warning("配置目录无法写入日志：备用目录：{}，错误：{}", fallback / "logs", error)
        config = Config.load(path)
        load_dotenv(path.parent / ".env")
        token = os.environ.get("NOTION_TOKEN", "").strip()
        if not token:
            raise PublicationError("请在项目 .env 中配置 NOTION_TOKEN，并在 Notion 授权连接。")
        logger.info(
            "开始{}：首页：{}",
            "重发" if args.command == "republish" else "发布",
            config.home_page_id,
        )
        with publication_lock(config.home_page_id):
            if args.command == "republish":
                result = asyncio.run(run_publication(token, config, args.command))
            else:
                result = asyncio.run(run_publication(token, config))
        if args.command == "republish":
            if result["status"] == "unchanged":
                logger.info(
                    "重发无需操作：当天金句内容无变化，未写入 Notion；日期：{}，记录：{}",
                    result["date"],
                    result["record_id"],
                )
            else:
                logger.info(
                    "重发成功：日期：{}，记录：{}，金句 ID：{}，金句：{}，首页：{}",
                    result["date"],
                    result["record_id"],
                    result["quote_id"],
                    result["quote"],
                    result["home"],
                )
        else:
            logger.info(
                "发布成功：日期：{}，记录：{}，金句：{}，首页：{}",
                result["date"],
                result["record_id"],
                result["quote"],
                result["home"],
            )
        return 0
    except (PublicationError, OSError) as error:
        logger.error("{}失败：{}", "重发" if args.command == "republish" else "发布", str(error))
        return 1
    except Exception as error:
        # 意外异常只记录类型，避免 SDK 异常携带请求头或密钥进入日志。
        logger.error("发布遇到未预期异常：类型：{}", type(error).__name__)
        return 1
    finally:
        # 从参数解析完成到命令退出统一计时，成功或失败均记录总耗时。
        logger.info(
            "{}总耗时：{:.2f} ms",
            "重发" if args.command == "republish" else "发布",
            (perf_counter() - started_at) * 1000,
        )


if __name__ == "__main__":
    raise SystemExit(main())
