"""从 Notion 金句库选句并发布到阅读首页。

每次运行都重新抽取；同一天复用并覆盖唯一的每日记录，最后更新首页。
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from loguru import logger

from .models import PublicationError, Quote, choose_quote, prop_text, relation_id, rich_text
from .notion import UncertainCreate
from .render import render
from .settings import (
    BOOK_READ_WORKERS,
    CREATE_RECOVERY_DELAYS,
    DAILY_DATE,
    DAILY_QUOTE,
    DAILY_ROUND,
    DAILY_SNAPSHOT,
    DAILY_STATUS,
    DAILY_TITLE,
    PENDING_STATUS,
    QUOTE_BOOK,
    QUOTE_ENABLED,
    RESULT_STATUS_PUBLISHED,
    SHANGHAI,
    page_url,
)


def only_record(rows):
    """返回唯一一条每日记录；有重复项时阻止发布。"""
    if len(rows) > 1:
        raise PublicationError("当天有多条记录，已停止发布；请让 Codex 核查。")
    return rows[0] if rows else None


def record_quote(record):
    """从每日快照恢复金句，并核对其关联 ID 是否一致。"""
    quote = Quote.from_snapshot(prop_text(record, DAILY_SNAPSHOT))
    if relation_id(record, DAILY_QUOTE) != quote.id:
        raise PublicationError("当天快照和金句关联不一致，已停止发布。")
    return quote


def record_properties(day, quote, round_, pending_status=PENDING_STATUS):
    """构造创建或覆盖每日记录所需的 Notion 属性。

    快照保存本次金句、书名、原文和定位范围，供写入核验与展示。
    """
    return {
        DAILY_TITLE: {"title": rich_text(day.isoformat())},
        DAILY_DATE: {"date": {"start": day.isoformat()}},
        DAILY_QUOTE: {"relation": [{"id": quote.id}]},
        DAILY_ROUND: {"number": round_},
        DAILY_STATUS: {"select": {"name": pending_status}},
        DAILY_SNAPSHOT: {"rich_text": rich_text(quote.snapshot())},
    }


def read_quotes(api, rows, page_url_template):
    """校验候选金句关联，并发读取不同书籍后组装完整候选项。

    已归档或进入垃圾箱的金句不会参加轮换；同一本书仅查询一次。
    保留全部候选项的原有校验，避免选中有效金句时掩盖其他错误数据。
    """
    active_rows = [row for row in rows if not row.get("archived") and not row.get("in_trash")]
    book_ids = list(dict.fromkeys(relation_id(row, QUOTE_BOOK) for row in active_rows))
    if not book_ids:
        return []
    # 关联 ID 已全部核验，下面只并发读取不同书籍；共享 API 客户端用于连接复用。
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(BOOK_READ_WORKERS, len(book_ids))) as executor:
        futures = {id_: executor.submit(api.page, id_) for id_ in book_ids}
        books = {id_: future.result() for id_, future in futures.items()}
    logger.info(
        "Notion 查询关联书籍耗时：{:.2f} ms，书籍：{} 本",
        (time.perf_counter() - start) * 1000,
        len(books),
    )
    return [
        Quote.from_page(row, books[relation_id(row, QUOTE_BOOK)], page_url_template)
        for row in active_rows
    ]


def publish(api, config, *, now=None, sleep=time.sleep):
    """发布北京时间当天的金句并返回发布摘要。

    ``now`` 和 ``sleep`` 用于模拟时间及恢复等待。每次运行重新选择，
    当天已有记录则原地覆盖；单次请求重试仍沿用本次选句。
    无效记录或未来日期记录会在写入前中止。
    """
    local = now or datetime.now(SHANGHAI)
    if local.tzinfo is None:
        raise PublicationError("发布时间缺少时区。")
    day = local.astimezone(SHANGHAI).date()
    logger.info("核验日期：{}", day.isoformat())
    # 先确认管理区仍属于指定首页，避免把内容写进其他页面或用户编辑区。
    start = time.perf_counter()
    api.preflight(config)
    logger.info("Notion 发布前核验耗时：{:.2f} ms", (time.perf_counter() - start) * 1000)
    if api.query(
        config.daily_data_source_id, {"property": DAILY_DATE, "date": {"after": day.isoformat()}}
    ):
        raise PublicationError("存在未来日期记录，已停止发布；请让 Codex 核查。")
    day_filter = {"property": DAILY_DATE, "date": {"equals": day.isoformat()}}

    def existing():
        """查询当天唯一记录，供覆盖和不确定创建后的核对使用。"""
        return only_record(api.query(config.daily_data_source_id, day_filter))

    record = existing()
    if record is not None:
        # 旧快照与关联不一致时停止，避免以覆盖掩盖已有数据损坏。
        record_quote(record)
    start = time.perf_counter()
    quote_rows = api.query(
        config.quotes_data_source_id,
        {"property": QUOTE_ENABLED, "checkbox": {"equals": True}},
    )
    logger.info(
        "Notion 查询可轮换金句耗时：{:.2f} ms，返回：{} 条",
        (time.perf_counter() - start) * 1000,
        len(quote_rows),
    )
    start = time.perf_counter()
    quotes = read_quotes(api, quote_rows, config.page_url_template)
    logger.info(
        "整理金句和关联书籍耗时：{:.2f} ms，可用：{} 条",
        (time.perf_counter() - start) * 1000,
        len(quotes),
    )
    history = []
    # 同日旧选句不进入历史；只有当天以前最终保留的记录影响轮次。
    start = time.perf_counter()
    rows = api.query(
        config.daily_data_source_id,
        {"property": DAILY_DATE, "date": {"before": day.isoformat()}},
    )
    logger.info(
        "Notion 查询历史每日记录耗时：{:.2f} ms，返回：{} 条",
        (time.perf_counter() - start) * 1000,
        len(rows),
    )
    start = time.perf_counter()
    dates = set()
    for row in rows:
        round_ = row["properties"][DAILY_ROUND].get("number")
        if isinstance(round_, bool) or not isinstance(round_, (int, float)) or round_ < 1:
            raise PublicationError("历史轮次无效，请让 Codex 核查。")
        if int(round_) != round_:
            raise PublicationError("历史轮次不是整数，请让 Codex 核查。")
        old_day = row["properties"][DAILY_DATE]["date"]["start"]
        if old_day in dates:
            raise PublicationError("历史日期有重复记录，请让 Codex 核查。")
        dates.add(old_day)
        history.append((relation_id(row, DAILY_QUOTE), int(round_)))
    logger.info(
        "核对轮换历史耗时：{:.2f} ms，记录：{} 条",
        (time.perf_counter() - start) * 1000,
        len(history),
    )
    quote, round_ = choose_quote(quotes, history)
    logger.info("选中金句：{}，轮次：{}，候选数：{}", quote.id, round_, len(quotes))
    # 写入前构造全部负载；新建包含正文，覆盖则先更新快照再更新正文。
    blocks = render(quote, day)
    properties = record_properties(day, quote, round_, config.pending_status)
    start = time.perf_counter()
    if record is None:
        try:
            api.create_record(config.daily_data_source_id, properties, blocks)
        except UncertainCreate as error:
            logger.warning("创建结果不确定，按日期查询恢复")
            # 创建响应丢失时，延迟查询是否已落库；绝不盲目重发 POST。
            for delay in CREATE_RECOVERY_DELAYS:
                sleep(delay)
                record = existing()
                if record:
                    break
            if record is None:
                raise PublicationError(
                    "创建结果仍不确定，未重复创建；请稍后重新运行核对。"
                ) from error
    else:
        api.update_record(record["id"], properties, blocks)
    logger.info("Notion 保存每日记录耗时：{:.2f} ms", (time.perf_counter() - start) * 1000)
    # 更新首页前读回；若出现并发创建或写入不一致，停止发布。
    record = existing()
    if record is None:
        raise PublicationError("当天记录暂不可读，未更新首页；请稍后重试。")
    saved_quote = record_quote(record)
    if saved_quote != quote:
        raise PublicationError("当天记录与本次选句不一致，未更新首页；请让 Codex 核查。")
    logger.info("使用每日记录：{}，金句：{}", record["id"], quote.id)
    # 首页全部更新完成后才标记发布；失败时下次运行会重新抽取并覆盖。
    start = time.perf_counter()
    api.update_home(config.managed_block_id, blocks)
    logger.info("Notion 更新首页耗时：{:.2f} ms", (time.perf_counter() - start) * 1000)
    start = time.perf_counter()
    api.mark_published(record["id"], config.published_status)
    logger.info("Notion 标记发布耗时：{:.2f} ms", (time.perf_counter() - start) * 1000)
    logger.info("首页已更新，每日记录已标记发布")
    return {
        "status": RESULT_STATUS_PUBLISHED,
        "date": day.isoformat(),
        "quote": quote.text,
        "record_id": record["id"],
        "home": page_url(config.home_page_id, config.page_url_template),
    }
