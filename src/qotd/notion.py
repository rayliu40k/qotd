"""通过 ``notion-client`` SDK 访问每日金句使用的 Notion 对象。

此模块只提供发布流程需要的读写操作。写入前验证首页管理块结构，
并把创建结果不确定的情况交给上层按日期查询恢复。
"""

import time

import httpx
from loguru import logger
from notion_client import APIResponseError, Client, RequestTimeoutError, UnknownHTTPResponseError
from notion_client.helpers import collect_paginated_api

from .models import PublicationError, canonical_id
from .render import SLOT_TYPES, SLOT_WRITE_ORDER
from .settings import (
    DAILY_STATUS,
    NOTION_MAX_ATTEMPTS,
    NOTION_PAGE_SIZE,
    NOTION_TIMEOUT_MS,
)


class UncertainCreate(PublicationError):
    """表示每日记录可能已创建，需要先查询而不能直接重发。"""


class Notion:
    """封装 SDK 端点、有限重试和首页结构保护。"""

    def __init__(self, token: str, *, client=None, sleep=time.sleep):
        """创建 SDK 客户端并关闭 SDK 自带的创建请求重试。

        ``client`` 和 ``sleep`` 允许测试注入模拟 HTTP 客户端及等待函数。
        SDK 不自动重试创建操作，避免超时后生成重复的每日记录。
        """
        self.client = Client(auth=token, client=client, retry=False, timeout_ms=NOTION_TIMEOUT_MS)
        self.sleep = sleep

    def close(self):
        """释放 SDK 的 HTTP 连接。"""
        self.client.close()

    def _call(self, operation, label: str, *, create: bool = False):
        """执行 SDK 请求并有限重试，返回其响应数据。

        ``create`` 指示写入是否会新增每日记录。创建请求遇到超时或
        服务端错误时抛出 ``UncertainCreate``；其他请求最多重试配置次数。
        异常日志只记录状态码和异常类型，避免暴露密钥或响应正文。
        """
        for attempt in range(NOTION_MAX_ATTEMPTS):
            try:
                return operation()
            except (APIResponseError, UnknownHTTPResponseError) as error:
                status = error.status
                logger.warning(
                    "Notion 请求失败：操作：{}，HTTP 状态：{}，尝试次数：{}",
                    label,
                    status,
                    attempt + 1,
                )
                if status == 429 and attempt < NOTION_MAX_ATTEMPTS - 1:
                    # 尊重 Notion 的限流等待时间，避免立即重试再次触发限流。
                    retry_after = error.headers.get("Retry-After", "")
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = 2**attempt
                    self.sleep(min(60, max(0, delay)))
                    continue
                if create and status >= 500:
                    # 服务端可能已经写入；上层只能按日期查询，不能重发创建请求。
                    raise UncertainCreate("创建结果不确定，正在核对 Notion。") from error
                if not create and status >= 500 and attempt < NOTION_MAX_ATTEMPTS - 1:
                    self.sleep(2**attempt)
                    continue
                raise PublicationError(
                    f"Notion {label}失败（HTTP {status}）。请检查连接权限。"
                ) from error
            except (RequestTimeoutError, httpx.TransportError, ValueError) as error:
                logger.warning(
                    "Notion 请求中断：操作：{}，异常类型：{}，尝试次数：{}",
                    label,
                    type(error).__name__,
                    attempt + 1,
                )
                if create:
                    raise UncertainCreate("创建结果不确定，正在核对 Notion。") from error
                if attempt == NOTION_MAX_ATTEMPTS - 1:
                    raise PublicationError(f"Notion {label}失败，请稍后重试。") from error
                self.sleep(2**attempt)
        raise PublicationError(f"Notion {label}重试已用尽。")

    def query(self, source, filter_=None):
        """分页查询一个数据源，并返回全部页面记录。

        每一页都使用相同的 ``filter_``，直到 SDK 报告没有后续游标。
        """
        params = {"data_source_id": source, "page_size": NOTION_PAGE_SIZE}
        if filter_:
            params["filter"] = filter_
        rows = []
        cursor = None
        while True:
            page_params = dict(params)
            if cursor:
                page_params["start_cursor"] = cursor
            data = self._call(lambda: self.client.data_sources.query(**page_params), "查询数据源")
            rows.extend(data["results"])
            if not data.get("has_more"):
                return rows
            cursor = data["next_cursor"]

    def children(self, parent):
        """使用 SDK 辅助函数读取全部子块。"""
        return self._call(
            lambda: collect_paginated_api(self.client.blocks.children.list, block_id=parent),
            "读取区块",
        )

    def page(self, id_):
        """读取书籍或首页页面。"""
        return self._call(lambda: self.client.pages.retrieve(page_id=id_), "读取页面")

    def slots(self, parent, label="首页"):
        """读取并验证首页或每日记录内的六个固定区块。

        区块类型、子内容或两个空白区发生变化时抛出 ``PublicationError``，
        使调用方在写入前停止。
        """
        rows = self.children(parent)
        if tuple(row["type"] for row in rows) != SLOT_TYPES or any(
            row.get("has_children") or row.get("archived") for row in rows
        ):
            raise PublicationError(f"{label}区块结构已改变，已停止更新；请让 Codex 核查。")
        if any(rows[i]["paragraph"].get("rich_text") for i in (2, 4)):
            raise PublicationError(f"{label}空白间隔中有用户内容，已停止更新；请让 Codex 核查。")
        return rows

    def preflight(self, config):
        """核验数据源、首页及管理块归属，失败时阻止发布。"""
        for source in (config.quotes_data_source_id, config.daily_data_source_id):
            self._call(
                lambda source=source: self.client.data_sources.retrieve(data_source_id=source),
                "读取数据源",
            )
        home = self.page(config.home_page_id)
        if home.get("archived") or home.get("in_trash"):
            raise PublicationError("首页已删除，请让 Codex 核查配置。")
        block = self._call(
            lambda: self.client.blocks.retrieve(block_id=config.managed_block_id), "读取管理块"
        )
        if (
            block.get("type") != "synced_block"
            or block.get("synced_block", {}).get("synced_from") is not None
            or block.get("archived")
            or canonical_id(block.get("parent", {}).get("page_id"))
            != canonical_id(config.home_page_id)
        ):
            raise PublicationError("首页发布区域不是指定页面的原始同步块，请让 Codex 核查。")
        self.slots(config.managed_block_id)

    def create_record(self, source, properties, blocks):
        """创建包含快照的每日记录，返回 SDK 响应。

        不确定是否写入成功时抛出 ``UncertainCreate``，调用方负责查询。
        """
        return self._call(
            lambda: self.client.pages.create(
                parent={"type": "data_source_id", "data_source_id": source},
                properties=properties,
                children=blocks,
            ),
            "创建每日记录",
            create=True,
        )

    def update_record(self, id_, properties, blocks):
        """原地覆盖当天记录的属性和六个正文块，保留页面 ID。

        先确认旧正文没有被用户改成其他结构，再保存新快照和待发布状态；
        正文按日期最后的顺序更新，中途失败由下次运行重新抽取并覆盖。
        """
        rows = self.slots(id_, "每日记录")
        self._call(
            lambda: self.client.pages.update(page_id=id_, properties=properties),
            "覆盖每日记录属性",
        )
        self._write_slots(rows, blocks, "每日记录")

    def _write_slots(self, rows, blocks, label):
        """逐块更新已核验的六个阅读区块，并在最后更新日期。"""
        for i in SLOT_WRITE_ORDER:
            kind = blocks[i]["type"]
            self._call(
                lambda i=i, kind=kind: self.client.blocks.update(
                    block_id=rows[i]["id"], **{kind: blocks[i][kind]}
                ),
                f"更新{label}区块 {i}",
            )

    def update_home(self, parent, blocks):
        """只更新受管理的六个区块，并在最后写入日期。

        日期放在最后，可降低读取者看到新日期配旧金句的时间窗口。
        该操作不是事务；中途失败后下次运行重新抽取并覆盖。
        """
        rows = self.slots(parent)
        self._write_slots(rows, blocks, "首页")

    def mark_published(self, id_, status):
        """在首页全部写入成功后，把每日记录更新为配置的完成状态。"""
        self._call(
            lambda: self.client.pages.update(
                page_id=id_, properties={DAILY_STATUS: {"select": {"name": status}}}
            ),
            "标记发布",
        )
