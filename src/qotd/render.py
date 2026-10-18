"""把每日快照渲染为阅读首页的六个 Notion 原生区块。

原文完整保留；直接命中或 Codex 预先标注的范围使用粗体和灰色背景。
"""

from datetime import date

from .highlights import matching_ranges, validate_ranges
from .models import PublicationError, Quote, rich_text
from .settings import (
    BLOCK_DEFAULT_COLOR,
    HIGHLIGHT_BACKGROUND_COLOR,
    LINK_COLOR,
    MISSING_CONTEXT,
    MISSING_SOURCE_LABEL,
    NOTION_RICH_TEXT_LIMIT,
)

SLOT_TYPES = ("heading_1", "quote", "paragraph", "paragraph", "paragraph", "paragraph")
# 最后更新日期，避免首页短暂出现新日期配旧内容。
SLOT_WRITE_ORDER = (1, 2, 3, 4, 5, 0)


def block(kind: str, text: str = "", *, color: str = BLOCK_DEFAULT_COLOR) -> dict:
    """构造一个原生 Notion 区块。"""
    return {
        "object": "block",
        "type": kind,
        kind: {"rich_text": rich_text(text), "color": color},
    }


def linked_text(text: str, url: str) -> list[dict]:
    """构造使用配置颜色和粗体的书籍或原稿链接富文本。"""
    items = rich_text(text)
    for item in items:
        if url:
            item["text"]["link"] = {"url": url}
            item["annotations"] = {"color": LINK_COLOR, "bold": True}
    return items


def context_text(quote: Quote) -> list[dict]:
    """返回完整原文的富文本，并突出显示可信命中范围。

    优先采用快照中的人工定位范围；没有人工标注时尝试直接匹配。
    两种方式都没有结果时只展示原文，不猜测或改写内容。
    """
    text = quote.context or MISSING_CONTEXT
    ranges = validate_ranges(
        quote.context_highlights or matching_ranges(quote.context, quote.text), len(text)
    )
    items = []
    cursor = 0
    for start, end in ranges:
        # 只给命中片段加注解，不改动原文字符或整段背景。
        items.extend(rich_text(text[cursor:start]))
        marked = rich_text(text[start:end])
        for item in marked:
            item["annotations"] = {"bold": True, "color": HIGHLIGHT_BACKGROUND_COLOR}
        items.extend(marked)
        cursor = end
    items.extend(rich_text(text[cursor:]))
    if len(items) > NOTION_RICH_TEXT_LIMIT:
        raise PublicationError("原文高亮超过 Notion 写入限制，请让 Codex 核查。")
    return items


def render(quote: Quote, day: date) -> list[dict]:
    """按约定顺序生成首页的六个区块。

    两个空白段落为阅读留白；书名和原文位置各保留一个可点击链接。
    """
    weekday = "一二三四五六日"[day.weekday()]
    blocks = [
        block("heading_1", f"{day.year}年{day.month}月{day.day}日 星期{weekday}"),
        block("quote", quote.text + "　——"),
        block("paragraph"),
        block("paragraph", quote.context or MISSING_CONTEXT),
        block("paragraph"),
        block("paragraph"),
    ]
    for item in blocks[1]["quote"]["rich_text"]:
        item["annotations"] = {"bold": True}
    blocks[1]["quote"]["rich_text"] += linked_text(quote.book, quote.book_url)
    blocks[3]["paragraph"]["rich_text"] = context_text(quote)
    blocks[5]["paragraph"]["rich_text"] = linked_text(
        quote.source_label or MISSING_SOURCE_LABEL, quote.source_url
    )
    return blocks
