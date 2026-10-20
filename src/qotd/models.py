"""解析 Codex 已整理的 Notion 数据，并维护金句快照与轮换规则。

此模块不解析原稿或推断语义，只验证来源数据及每日快照结构。
"""

import json
import random
from dataclasses import asdict, dataclass
from time import perf_counter
from uuid import UUID

from loguru import logger

from .highlights import ranges_from_rich_text, validate_ranges
from .settings import (
    NOTION_RICH_TEXT_LIMIT,
    NOTION_TEXT_LIMIT,
    QUOTE_CONTEXT,
    QUOTE_SOURCE_LABEL,
    QUOTE_SOURCE_URL,
    QUOTE_TITLE,
    page_url,
)


class PublicationError(RuntimeError):
    """仅包含安全提示的发布错误，避免带出凭据或响应正文。"""


def canonical_id(value: str) -> str:
    """规范化 Notion UUID。"""
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise PublicationError("Notion ID 格式无效，请检查配置或数据关联。") from error


def plain(items: list[dict]) -> str:
    """拼接 Notion 富文本中的原始文字。"""
    return "".join(x.get("plain_text", x.get("text", {}).get("content", "")) for x in items)


def prop_text(page: dict, name: str) -> str:
    """读取页面标题或文本属性。"""
    value = page.get("properties", {}).get(name)
    if value is None:
        raise PublicationError(f"缺少字段“{name}”，请让 Codex 检查数据库。")
    return plain(value.get("title", value.get("rich_text", [])))


def rich_text(value: str) -> list[dict]:
    """把字符串拆成符合 Notion 单项长度限制的富文本列表。

    文本总量超过单个属性允许的富文本项数量时抛出 ``PublicationError``。
    """
    if len(value) > NOTION_TEXT_LIMIT * NOTION_RICH_TEXT_LIMIT:
        raise PublicationError("文本超过 Notion 写入限制，请让 Codex 核查原文。")
    return [
        {"type": "text", "text": {"content": value[i : i + NOTION_TEXT_LIMIT]}}
        for i in range(0, len(value), NOTION_TEXT_LIMIT)
    ]


def relation_id(page: dict, name: str) -> str:
    """读取恰好一个页面关联。"""
    relations = page.get("properties", {}).get(name, {}).get("relation", [])
    if len(relations) != 1:
        raise PublicationError(f"“{name}”必须有且仅有一个关联，请让 Codex 核查。")
    return canonical_id(relations[0].get("id"))


def book_title(page: dict) -> str:
    """从书籍页标题属性读取书名。"""
    if page.get("archived") or page.get("in_trash"):
        raise PublicationError("关联的书籍已删除，请让 Codex 核查。")
    for value in page.get("properties", {}).values():
        if "title" in value:
            title = plain(value["title"])
            if title.strip():
                return title
    raise PublicationError("关联的书籍缺少书名，请让 Codex 补齐。")


@dataclass(frozen=True)
class Quote:
    """保存一条可发布金句及已核对的原稿上下文。

    ``context_highlights`` 记录原文中的字符偏移范围；语义定位由 Codex
    在初始化时提供，直接文本匹配可在页面渲染时计算。
    """

    id: str
    text: str
    book: str
    book_url: str
    context: str = ""
    source_label: str = ""
    source_url: str = ""
    context_highlights: tuple[tuple[int, int], ...] = ()

    @classmethod
    def from_page(cls, page: dict, book: dict, page_url_template: str) -> "Quote":
        """从金句页和关联书籍页读取展示数据。

        书籍没有返回 URL 时，使用配置的模板生成链接；原文标黄范围
        会转成字符偏移保存于 ``context_highlights``。
        """
        text = prop_text(page, QUOTE_TITLE)
        if not text.strip():
            raise PublicationError("金句为空，请让 Codex 补齐。")
        return cls(
            id=canonical_id(page["id"]),
            text=text,
            book=book_title(book),
            book_url=book.get("url") or page_url(book["id"], page_url_template),
            context=prop_text(page, QUOTE_CONTEXT),
            source_label=prop_text(page, QUOTE_SOURCE_LABEL),
            source_url=page.get("properties", {}).get(QUOTE_SOURCE_URL, {}).get("url") or "",
            context_highlights=ranges_from_rich_text(
                page.get("properties", {}).get(QUOTE_CONTEXT, {}).get("rich_text", [])
            ),
        )

    def snapshot(self) -> str:
        """序列化本次展示内容，供写入核验和每日记录保存。"""
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_snapshot(cls, value: str) -> "Quote":
        """校验并恢复每日快照，拒绝无效结构及定位范围。

        旧快照允许缺少 ``context_highlights``；渲染器会对原文尝试
        直接文本匹配，覆盖前仍需确认旧快照与关联一致。
        """
        try:
            data = json.loads(value)
            if not isinstance(data, dict) or not isinstance(data.get("context", ""), str):
                raise ValueError("invalid snapshot shape")
            data["context_highlights"] = validate_ranges(
                data.get("context_highlights", []), len(data.get("context", ""))
            )
            quote = cls(**data)
            if not all(
                isinstance(x, str)
                for name, x in asdict(quote).items()
                if name != "context_highlights"
            ):
                raise ValueError("non-string field")
            canonical_id(quote.id)
            if not all(x.strip() for x in (quote.text, quote.book, quote.book_url)):
                raise ValueError("empty required field")
            return quote
        except (TypeError, ValueError, PublicationError) as error:
            raise PublicationError("当天展示快照无效，已停止本次发布，不会覆盖旧记录。") from error


def choose_quote(
    quotes: list[Quote], history: list[tuple[str, int]], rng: random.Random | None = None
) -> tuple[Quote, int]:
    """从当前轮尚未使用的金句中随机选择并返回轮次。

    当前轮全部展示后才进入下一轮；新增金句可加入当前轮。``rng``
    允许测试注入确定性的随机源。
    """
    if not quotes:
        raise PublicationError("没有可参与轮换的金句，请先让 Codex 初始化。")
    filter_start = perf_counter()
    round_ = max((r for _, r in history), default=1)
    seen = {canonical_id(id_) for id_, r in history if r == round_}
    candidates = [q for q in quotes if canonical_id(q.id) not in seen]
    if not candidates:
        round_ += 1
        candidates = quotes
    filter_ms = (perf_counter() - filter_start) * 1000

    sort_start = perf_counter()
    ordered = sorted(candidates, key=lambda q: q.id)
    sort_ms = (perf_counter() - sort_start) * 1000

    random_start = perf_counter()
    selected = (rng or random.SystemRandom()).choice(ordered)
    random_ms = (perf_counter() - random_start) * 1000
    logger.info(
        "抽选耗时：筛选：{:.2f} ms，排序：{:.2f} ms，随机选择：{:.2f} ms，候选：{} 条",
        filter_ms,
        sort_ms,
        random_ms,
        len(candidates),
    )
    return selected, round_
