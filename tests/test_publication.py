import asyncio
import copy
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from loguru import logger

from qotd.cli import Config
from qotd.logging_setup import configure_logging
from qotd.models import PublicationError, Quote, choose_quote, plain, rich_text
from qotd.notion import UncertainCreate
from qotd.publisher import prepare_candidates, publish, record_properties
from qotd.render import SLOT_TYPES, render


def run_publish(api, config=None, **kwargs):
    """在真实事件循环中运行一次模拟发布。"""
    return asyncio.run(publish(api, config or CONFIG, **kwargs))


async def no_sleep(_delay):
    """使创建结果不确定的恢复测试无需实际等待。"""


def id_(number):
    return str(UUID(int=number))


NOW = datetime(2026, 10, 16, 17, tzinfo=UTC)  # Shanghai: Oct 17, 01:00
CONFIG = Config(
    page_url_template="https://www.notion.so/{page_id}",
    home_page_id=id_(100),
    managed_block_id=id_(101),
    quotes_data_source_id=id_(102),
    daily_data_source_id=id_(103),
)


def make_quote(number):
    return Quote(
        id_(number),
        f"金句 {number}",
        "《测试书》",
        "https://www.notion.so/book",
        f"完整原文 {number}",
        f"读书讲解稿 · 第1节第{number}段",
        f"https://www.notion.so/source#paragraph{number}",
    )


def scripted_choice(choices):
    """按预设 ID 从本次实际候选中取值，模拟连续重发的随机结果。"""
    iterator = iter(choices)

    def choose(candidates, _history):
        wanted = next(iterator).id
        return next(candidate for candidate in candidates if candidate.id == wanted), 1

    return choose


def page(quote):
    return {
        "id": quote.id,
        "properties": {
            "金句": {"title": rich_text(quote.text)},
            "书籍": {"relation": [{"id": id_(200)}]},
            "参与轮换": {"checkbox": True},
            "原文": {"rich_text": rich_text(quote.context)},
            "原文位置": {"rich_text": rich_text(quote.source_label)},
            "原文链接": {"url": quote.source_url},
        },
    }


class FakeNotion:
    def __init__(self):
        self.quotes = [page(make_quote(i)) for i in range(1, 9)]
        self.records = []
        self.home = None
        self.user_content = "用户写在发布区以外的内容"
        self.creates = 0
        self.book_reads = 0
        self.quote_reads = 0
        self.quote_query_properties = []
        self.daily_queries = 0
        self.daily_query_filters = []
        self.fail_home = False
        self.fail_record = False
        self.fail_status = False
        self.uncertain = False
        self.no_commit = False

    async def preflight(self, config):
        pass

    async def query(self, source, filter_=None, *, filter_properties=None):
        if source == CONFIG.quotes_data_source_id:
            assert filter_ == {"property": "参与轮换", "checkbox": {"equals": True}}
            assert filter_properties == ["书籍"]
            self.quote_query_properties.append(filter_properties)
            # 模拟 Notion 的属性投影，分页候选不包含原文和标题。
            return [
                {
                    "id": row["id"],
                    "properties": {"书籍": row["properties"]["书籍"]},
                    "archived": row.get("archived", False),
                    "in_trash": row.get("in_trash", False),
                }
                for row in self.quotes
                if row["properties"].get("参与轮换", {}).get("checkbox") is True
            ]
        self.daily_queries += 1
        self.daily_query_filters.append(filter_)
        if filter_ is None:
            return list(self.records)
        operation, day = next(iter(filter_["date"].items()))
        return [
            row
            for row in self.records
            if {
                "equals": row["properties"]["日期"]["date"]["start"] == day,
                "before": row["properties"]["日期"]["date"]["start"] < day,
                "after": row["properties"]["日期"]["date"]["start"] > day,
            }[operation]
        ]

    async def page(self, id_):
        for quote in self.quotes:
            if quote["id"] == id_:
                self.quote_reads += 1
                return copy.deepcopy(quote)
        self.book_reads += 1
        return {
            "id": id_,
            "url": "https://www.notion.so/book",
            "properties": {"书名": {"title": rich_text("《测试书》")}},
        }

    async def create_record(self, source, properties, blocks):
        self.creates += 1
        if not self.no_commit:
            self.records.append(
                {
                    "id": id_(300 + self.creates),
                    "properties": properties,
                    "blocks": copy.deepcopy(blocks),
                }
            )
        if self.uncertain or self.no_commit:
            raise UncertainCreate("timeout")
        return self.records[-1]

    async def update_home(self, parent, blocks):
        if self.fail_home:
            self.fail_home = False
            self.home = copy.deepcopy(blocks[:2])
            raise PublicationError("failed mid-update")
        self.home = copy.deepcopy(blocks)

    async def update_record(self, id_, properties, blocks):
        row = next(row for row in self.records if row["id"] == id_)
        if tuple(block["type"] for block in row["blocks"]) != SLOT_TYPES:
            raise PublicationError("每日记录区块结构已改变")
        row["properties"] = copy.deepcopy(properties)
        if self.fail_record:
            self.fail_record = False
            row["blocks"][:2] = copy.deepcopy(blocks[:2])
            raise PublicationError("failed mid-record-update")
        row["blocks"] = copy.deepcopy(blocks)

    async def mark_published(self, id_, status):
        if self.fail_status:
            self.fail_status = False
            raise PublicationError("failed status write")
        row = next(row for row in self.records if row["id"] == id_)
        row["properties"]["发布状态"] = {"select": {"name": status}}


def test_publication_timing_is_written_to_daily_log(tmp_path):
    """用模拟 Notion 验证各关键阶段的耗时进入每日文件日志。"""
    try:
        configure_logging(tmp_path)
        run_publish(FakeNotion(), CONFIG, now=NOW)
        log_file = next((tmp_path / "logs").glob("qotd_*.log"))
        content = log_file.read_text()
        for label in (
            "Notion 发布前核验耗时",
            "Notion 查询可轮换金句耗时",
            "准备抽选候选耗时",
            "Notion 查询所选金句及书籍耗时",
            "组装所选金句展示数据耗时",
            "Notion 查询每日记录耗时",
            "核对轮换历史耗时",
            "筛选",
            "排序",
            "随机选择",
            "Notion 保存每日记录耗时",
            "Notion 更新首页耗时",
            "Notion 标记发布耗时",
        ):
            assert re.search(rf"{re.escape(label)}：\d+\.\d{{2}} ms", content)
    finally:
        logger.remove()


def test_independent_reads_overlap_and_daily_records_are_queried_once_before_write():
    """首页核验、金句与每日记录查询并发，写入前只全量查一次每日记录。"""

    class GatedNotion(FakeNotion):
        def __init__(self):
            super().__init__()
            self.started = []
            self.ready = asyncio.Event()

        async def gate(self, label):
            self.started.append(label)
            if len(self.started) == 3:
                self.ready.set()
            await asyncio.wait_for(self.ready.wait(), timeout=2)

        async def preflight(self, config):
            await self.gate("首页")

        async def query(self, source, filter_=None, *, filter_properties=None):
            if source == CONFIG.quotes_data_source_id:
                await self.gate("金句")
            elif filter_ is None:
                await self.gate("每日记录")
            return await super().query(source, filter_, filter_properties=filter_properties)

    api = GatedNotion()
    run_publish(api, now=NOW)
    assert set(api.started) == {"首页", "金句", "每日记录"}
    assert api.daily_queries == 2
    assert api.daily_query_filters == [
        None,
        {"property": "日期", "date": {"equals": "2026-10-17"}},
    ]


def test_complete_round_and_next_round_with_real_reservations():
    api = FakeNotion()
    for offset in range(9):
        run_publish(api, CONFIG, now=NOW + timedelta(days=offset))
    ids = [r["properties"]["金句"]["relation"][0]["id"] for r in api.records]
    assert len(set(ids[:8])) == 8
    assert [r["properties"]["轮次"]["number"] for r in api.records] == [1] * 8 + [2]


def test_custom_home_url_flows_through_publication():
    api = FakeNotion()
    config = replace(CONFIG, page_url_template="https://notion.so/{page_id}")
    result = run_publish(api, config, now=NOW)
    assert api.records[0]["properties"]["发布状态"]["select"]["name"] == "已发布"
    assert result["home"] == "https://notion.so/00000000000000000000000000000064"


def test_same_day_overwrites_one_record_and_home(monkeypatch):
    api = FakeNotion()
    monkeypatch.setattr(
        "qotd.publisher.choose_quote", scripted_choice([make_quote(1), make_quote(2)])
    )
    first = run_publish(api, CONFIG, now=NOW)
    second = run_publish(api, CONFIG, now=NOW)
    assert first["date"] == "2026-10-17"
    assert first["record_id"] == second["record_id"]
    assert first["quote"] == "金句 1" and second["quote"] == "金句 2"
    assert len(api.records) == 1
    assert api.records[0]["properties"]["金句"]["relation"][0]["id"] == id_(2)
    assert api.records[0]["properties"]["发布状态"]["select"]["name"] == "已发布"
    assert api.records[0]["blocks"] == api.home == render(make_quote(2), date(2026, 10, 17))
    assert api.creates == 1
    assert api.user_content == "用户写在发布区以外的内容"


@pytest.mark.parametrize("failure", ["fail_record", "fail_home", "fail_status"])
def test_partial_failure_next_run_reselects_and_overwrites(monkeypatch, failure):
    api = FakeNotion()
    monkeypatch.setattr(
        "qotd.publisher.choose_quote",
        scripted_choice([make_quote(1), make_quote(2), make_quote(3)]),
    )
    run_publish(api, CONFIG, now=NOW)
    setattr(api, failure, True)
    with pytest.raises(PublicationError):
        run_publish(api, CONFIG, now=NOW)
    result = run_publish(api, CONFIG, now=NOW)
    assert api.creates == 1
    assert len(api.records) == 1
    assert api.records[0]["properties"]["金句"]["relation"][0]["id"] == id_(3)
    assert api.records[0]["properties"]["发布状态"]["select"]["name"] == "已发布"
    assert api.records[0]["blocks"] == api.home == render(make_quote(3), date(2026, 10, 17))
    assert result["record_id"] == api.records[0]["id"]


def test_single_quote_can_be_published_again_same_day():
    api = FakeNotion()
    api.quotes = [page(make_quote(1))]
    first = run_publish(api, CONFIG, now=NOW)
    second = run_publish(api, CONFIG, now=NOW)
    assert first["quote"] == second["quote"] == "金句 1"
    assert len(api.records) == api.creates == 1


def test_only_final_same_day_quote_counts_in_next_round(monkeypatch):
    api = FakeNotion()
    api.quotes = [page(make_quote(1)), page(make_quote(2))]
    choices = iter([make_quote(1), make_quote(2)])
    original_choose = choose_quote

    def choose(quotes, history):
        if not history:
            wanted = next(choices).id
            return next(candidate for candidate in quotes if candidate.id == wanted), 1
        return original_choose(quotes, history)

    monkeypatch.setattr("qotd.publisher.choose_quote", choose)
    run_publish(api, CONFIG, now=NOW)
    run_publish(api, CONFIG, now=NOW)
    run_publish(api, CONFIG, now=NOW + timedelta(days=1))
    assert [row["properties"]["金句"]["relation"][0]["id"] for row in api.records] == [
        id_(2),
        id_(1),
    ]
    assert [row["properties"]["轮次"]["number"] for row in api.records] == [1, 1]


def test_uncertain_create_after_commit_is_not_replayed():
    api = FakeNotion()
    api.uncertain = True
    run_publish(api, CONFIG, now=NOW, sleep=no_sleep)
    assert api.creates == len(api.records) == 1


def test_uncertain_create_without_visible_commit_stops():
    api = FakeNotion()
    api.no_commit = True
    with pytest.raises(PublicationError, match="未重复创建"):
        run_publish(api, CONFIG, now=NOW, sleep=no_sleep)
    assert api.creates == 1
    assert api.home is None


def test_duplicate_current_day_stops_before_home_change():
    api = FakeNotion()
    run_publish(api, CONFIG, now=NOW)
    api.records.append(copy.deepcopy(api.records[0]))
    expected = copy.deepcopy(api.home)
    with pytest.raises(PublicationError, match="多条"):
        run_publish(api, CONFIG, now=NOW)
    assert api.home == expected
    assert api.creates == 1


def test_future_record_stops_before_any_write():
    api = FakeNotion()
    run_publish(api, CONFIG, now=NOW + timedelta(days=1))
    expected = copy.deepcopy(api.home)
    with pytest.raises(PublicationError, match="未来日期"):
        run_publish(api, CONFIG, now=NOW)
    assert api.home == expected
    assert api.creates == 1


def test_invalid_daily_date_stops_before_any_write():
    api = FakeNotion()
    properties = record_properties(date(2026, 10, 16), make_quote(1), 1)
    properties["日期"] = {"date": {"start": "无效日期"}}
    api.records = [{"id": id_(400), "properties": properties}]
    with pytest.raises(PublicationError, match="每日记录日期无效"):
        run_publish(api, CONFIG, now=NOW)
    assert api.creates == 0
    assert api.home is None


@pytest.mark.parametrize("snapshot", ["not-json", "{}", "null", '"wrong"', '{"id": null}'])
def test_invalid_snapshot_never_causes_reselection(snapshot):
    api = FakeNotion()
    props = record_properties(date(2026, 10, 17), make_quote(1), 1)
    props["展示快照"] = {"rich_text": rich_text(snapshot)}
    api.records = [{"id": id_(400), "properties": props}]
    with pytest.raises(PublicationError, match="快照无效"):
        run_publish(api, CONFIG, now=NOW)
    assert api.creates == 0
    assert api.home is None


def test_snapshot_and_relation_mismatch_stops():
    api = FakeNotion()
    props = record_properties(date(2026, 10, 17), make_quote(1), 1)
    props["金句"] = {"relation": [{"id": id_(2)}]}
    api.records = [{"id": id_(400), "properties": props}]
    with pytest.raises(PublicationError, match="不一致"):
        run_publish(api, CONFIG, now=NOW)
    assert api.home is None


def test_new_quote_joins_current_round_and_retired_quotes_do_not_block_next():
    quotes = [make_quote(1), make_quote(2)]
    chosen, round_ = choose_quote(quotes + [make_quote(3)], [(id_(1), 1), (id_(2), 1)])
    assert (chosen.id, round_) == (id_(3), 1)
    chosen, round_ = choose_quote(quotes[:1], [(id_(1), 1), (id_(2), 1)])
    assert (chosen.id, round_) == (id_(1), 2)


def test_deleted_and_archived_quotes_skipped_without_book_reads():
    api = FakeNotion()
    api.quotes[0]["archived"] = True
    api.quotes[1]["in_trash"] = True
    quotes = prepare_candidates(api.quotes)
    assert len(quotes) == 6
    assert api.book_reads == 0
    assert quotes[0].book_id == id_(200)


def test_only_selected_quote_and_book_are_read(monkeypatch):
    api = FakeNotion()
    api.quotes = [page(make_quote(i)) for i in (1, 2, 3)]
    api.quotes[1]["properties"]["书籍"] = {"relation": [{"id": id_(201)}]}
    calls = []

    async def read_page(page_id):
        calls.append(page_id)
        if page_id == id_(2):
            return next(row for row in api.quotes if row["id"] == page_id)
        return {
            "id": page_id,
            "url": f"https://www.notion.so/{page_id}",
            "properties": {"书名": {"title": rich_text(f"《书 {page_id}》")}},
        }

    api.page = read_page
    monkeypatch.setattr(
        "qotd.publisher.choose_quote",
        lambda candidates, _history: (next(c for c in candidates if c.id == id_(2)), 1),
    )
    result = run_publish(api, CONFIG, now=NOW)
    assert result["quote"] == "金句 2"
    assert set(calls) == {id_(2), id_(201)}
    snapshot = json.loads(plain(api.records[0]["properties"]["展示快照"]["rich_text"]))
    assert snapshot["context"] == "完整原文 2"
    assert snapshot["source_label"] == "读书讲解稿 · 第1节第2段"
    assert (
        api.records[0]["blocks"][1]["quote"]["rich_text"][-1]["text"]["content"]
        == f"《书 {id_(201)}》"
    )
    assert plain(api.records[0]["blocks"][3]["paragraph"]["rich_text"]) == "完整原文 2"


@pytest.mark.parametrize("change", ["archived", "disabled", "book", "id"])
def test_selected_quote_changed_after_query_stops_before_write(monkeypatch, change):
    """分页抽选之后再次读取金句，数据变化时不保存混合快照。"""
    api = FakeNotion()
    original_page = api.page

    async def changed_page(page_id):
        row = await original_page(page_id)
        if page_id == id_(1):
            if change == "archived":
                row["archived"] = True
            elif change == "disabled":
                row["properties"]["参与轮换"]["checkbox"] = False
            elif change == "book":
                row["properties"]["书籍"]["relation"] = [{"id": id_(201)}]
            else:
                row["id"] = id_(9)
        return row

    api.page = changed_page
    monkeypatch.setattr(
        "qotd.publisher.choose_quote",
        lambda candidates, _history: (next(c for c in candidates if c.id == id_(1)), 1),
    )
    with pytest.raises(PublicationError, match="查询后已变更"):
        run_publish(api, CONFIG, now=NOW)
    assert api.creates == 0
    assert api.home is None


def test_selected_quote_and_book_reads_overlap(monkeypatch):
    """所选金句与书籍是独立页面读取，可同时等待 Notion 响应。"""
    api = FakeNotion()
    original_page = api.page
    started = set()
    ready = asyncio.Event()

    async def gated_page(page_id):
        started.add(page_id)
        if len(started) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=2)
        return await original_page(page_id)

    api.page = gated_page
    monkeypatch.setattr(
        "qotd.publisher.choose_quote",
        lambda candidates, _history: (next(c for c in candidates if c.id == id_(1)), 1),
    )
    run_publish(api, CONFIG, now=NOW)
    assert started == {id_(1), id_(200)}
    assert api.quote_reads == api.book_reads == 1


def test_selected_book_read_failure_stops_before_write(monkeypatch):
    """所选书籍读取失败时停止发布，其他书籍不被读取。"""
    api = FakeNotion()
    api.quotes[1]["properties"]["书籍"] = {"relation": [{"id": id_(201)}]}
    calls = []

    async def read_book(page_id):
        calls.append(page_id)
        raise PublicationError("书籍读取失败")

    api.page = read_book
    monkeypatch.setattr(
        "qotd.publisher.choose_quote",
        lambda candidates, _history: (next(c for c in candidates if c.id == id_(2)), 1),
    )
    with pytest.raises(PublicationError, match="书籍读取失败"):
        run_publish(api, CONFIG, now=NOW)
    assert set(calls) == {id_(2), id_(201)}
    assert api.creates == 0
    assert api.home is None


def test_empty_pool_and_missing_book_relation_fail_before_write():
    with pytest.raises(PublicationError, match="初始化"):
        choose_quote([], [])
    api = FakeNotion()
    api.quotes[0]["properties"]["书籍"] = {"relation": []}
    with pytest.raises(PublicationError, match="关联"):
        run_publish(api, CONFIG, now=NOW)
    assert api.creates == 0
    assert api.book_reads == 0


def test_layout_links_and_long_original_text_are_preserved():
    quote = make_quote(1)
    blocks = render(quote, date(2026, 10, 17))
    assert tuple(b["type"] for b in blocks) == SLOT_TYPES
    texts = blocks[1]["quote"]["rich_text"]
    assert plain(texts) == quote.text + "　——" + quote.book
    assert texts[-1]["text"]["link"]["url"] == quote.book_url
    assert texts[0]["annotations"]["bold"] is True
    assert texts[-1]["annotations"] == {"color": "blue", "bold": True}
    assert blocks[2]["paragraph"]["rich_text"] == blocks[4]["paragraph"]["rich_text"] == []
    assert plain(blocks[3]["paragraph"]["rich_text"]) == quote.context
    assert blocks[5]["paragraph"]["rich_text"][0]["text"]["link"]["url"] == quote.source_url
    assert blocks[5]["paragraph"]["color"] == "default"
    assert blocks[5]["paragraph"]["rich_text"][0]["annotations"] == {"color": "blue", "bold": True}
    long = Quote(id_(1), "金句", "书名", quote.book_url, "全文" * 3000)
    assert plain(render(long, date(2026, 10, 17))[3]["paragraph"]["rich_text"]) == long.context
    assert all(len(item["text"]["content"]) <= 2000 for item in rich_text(long.context))


def test_missing_original_shows_placeholder_and_no_retired_features():
    quote = Quote(id_(1), "金句", "书名", "https://www.notion.so/book")
    blocks = render(quote, date(2026, 10, 17))
    assert plain(blocks[3]["paragraph"]["rich_text"]) == "原文待补充"
    assert not any(
        term in json.dumps(blocks, ensure_ascii=False)
        for term in ("感想", "前一段", "后一段", "heading_2", "toggle")
    )
