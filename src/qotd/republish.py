"""将北京时间当天已发布的同一条金句从 Notion 金句库重新发布。"""

from datetime import datetime
from time import perf_counter

from loguru import logger

from .models import PublicationError, Quote, canonical_id, prop_text, relation_id, rich_text
from .publisher import only_record, record_quote
from .render import render
from .settings import (
    DAILY_DATE,
    DAILY_QUOTE,
    DAILY_ROUND,
    DAILY_STATUS,
    DAILY_TITLE,
    QUOTE_BOOK,
    SHANGHAI,
    page_url,
)


def _style_runs(items):
    """把 Notion 富文本按显示样式合并，容忍服务端改变分段和默认注解。"""
    runs = []
    for item in items:
        content = item.get("text", {}).get("content", item.get("plain_text", ""))
        link = item.get("text", {}).get("link") or {}
        annotations = item.get("annotations") or {}
        style = (
            link.get("url"),
            annotations.get("bold", False),
            annotations.get("color", "default"),
        )
        if runs and runs[-1][1] == style:
            runs[-1] = (runs[-1][0] + content, style)
        else:
            runs.append((content, style))
    return runs


def verify_slots(rows, blocks, label):
    """读回核对六区块的类型、文字、链接、粗体、高亮和区块颜色。"""
    if len(rows) != len(blocks):
        raise PublicationError(f"{label}读回区块数量不一致，重发未确认成功。")
    for index, (row, target) in enumerate(zip(rows, blocks, strict=True)):
        kind = target["type"]
        actual = row.get(kind, {})
        expected = target[kind]
        if (
            row.get("type") != kind
            or actual.get("color", "default") != expected.get("color", "default")
            or _style_runs(actual.get("rich_text", [])) != _style_runs(expected["rich_text"])
        ):
            raise PublicationError(f"{label}区块 {index} 读回不一致，重发未确认成功。")


def _checked_record(rows, day, config):
    """要求当天唯一记录已发布，并核对其关联、快照和保留字段。"""
    record = only_record(rows)
    if record is None:
        raise PublicationError("当天没有已发布记录，无法重发。")
    props = record.get("properties", {})
    if props.get(DAILY_DATE, {}).get("date", {}).get("start") != day.isoformat():
        raise PublicationError("当天记录日期不一致，已停止重发。")
    if props.get(DAILY_STATUS, {}).get("select", {}).get("name") != config.published_status:
        raise PublicationError("当天记录尚未发布，已停止重发。")
    round_ = props.get(DAILY_ROUND, {}).get("number")
    if isinstance(round_, bool) or not isinstance(round_, int) or round_ < 1:
        raise PublicationError("当天记录轮次无效，已停止重发。")
    if prop_text(record, DAILY_TITLE) != day.isoformat():
        raise PublicationError("当天记录标题无效，已停止重发。")
    return record, record_quote(record)


async def republish(api, config, *, clock=None):
    """重发当天记录所关联的金句；不抽句、不新建记录或更改轮次。"""
    clock = clock or (lambda: datetime.now(SHANGHAI))
    local = clock()
    if local.tzinfo is None:
        raise PublicationError("重发时间缺少时区。")
    day = local.astimezone(SHANGHAI).date()
    day_filter = {"property": DAILY_DATE, "date": {"equals": day.isoformat()}}
    logger.info("开始重发：日期：{}", day)
    start = perf_counter()
    await api.preflight(config)
    record, _ = _checked_record(
        await api.query(config.daily_data_source_id, day_filter), day, config
    )
    record_id = canonical_id(record["id"])
    quote_id = relation_id(record, DAILY_QUOTE)
    round_ = record["properties"][DAILY_ROUND]["number"]
    logger.info(
        "重发目标已核验：记录：{}，金句：{}，读取耗时：{:.2f} ms",
        record_id,
        quote_id,
        (perf_counter() - start) * 1000,
    )

    quote_page = await api.page(quote_id)
    if (
        canonical_id(quote_page.get("id")) != quote_id
        or quote_page.get("archived")
        or quote_page.get("in_trash")
    ):
        raise PublicationError("当天金句页面不可用，已停止重发。")
    book_id = relation_id(quote_page, QUOTE_BOOK)
    book_page = await api.page(book_id)
    if canonical_id(book_page.get("id")) != book_id:
        raise PublicationError("关联书籍页面不一致，已停止重发。")
    quote = Quote.from_page(quote_page, book_page, config.page_url_template)
    blocks = render(quote, day)

    # 读取来源期间若另一进程换句，绝不把旧关联覆盖为这次读取的金句。
    latest, _ = _checked_record(
        await api.query(config.daily_data_source_id, day_filter), day, config
    )
    if (
        canonical_id(latest["id"]) != record_id
        or relation_id(latest, DAILY_QUOTE) != quote_id
        or latest["properties"][DAILY_ROUND]["number"] != round_
    ):
        raise PublicationError("当天记录已变更，未写入；请重新运行。")
    if clock().astimezone(SHANGHAI).date() != day:
        raise PublicationError("北京时间日期已变化，未写入；请重新运行。")

    start = perf_counter()
    await api.refresh_record(record_id, rich_text(quote.snapshot()), blocks)
    logger.info("重发刷新每日记录耗时：{:.2f} ms", (perf_counter() - start) * 1000)
    saved, saved_quote = _checked_record(
        await api.query(config.daily_data_source_id, day_filter), day, config
    )
    if (
        canonical_id(saved["id"]) != record_id
        or saved_quote != quote
        or saved["properties"][DAILY_ROUND]["number"] != round_
    ):
        raise PublicationError("重发记录快照读回不一致，未更新首页。")
    verify_slots(await api.slots(record_id, "每日记录"), blocks, "每日记录")

    start = perf_counter()
    await api.update_home(config.managed_block_id, blocks)
    verify_slots(await api.slots(config.managed_block_id), blocks, "首页")
    final, final_quote = _checked_record(
        await api.query(config.daily_data_source_id, day_filter), day, config
    )
    if (
        canonical_id(final["id"]) != record_id
        or final_quote != quote
        or final["properties"][DAILY_ROUND]["number"] != round_
    ):
        raise PublicationError("首页更新后每日记录已变更，重发未确认成功。")
    logger.info("重发更新并核对首页耗时：{:.2f} ms", (perf_counter() - start) * 1000)
    logger.info("当天金句重发成功：日期：{}，记录：{}，金句：{}", day, record_id, quote_id)
    return {
        "date": day.isoformat(),
        "record_id": record_id,
        "quote_id": quote_id,
        "quote": quote.text,
        "home": page_url(config.home_page_id, config.page_url_template),
    }
