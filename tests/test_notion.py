import asyncio
import json
from collections import Counter
from datetime import date
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from loguru import logger

from qotd.models import PublicationError, Quote
from qotd.notion import Notion, UncertainCreate
from qotd.render import render


def api(handler, sleep=asyncio.sleep):
    return Notion(
        "unused",
        sleep=sleep,
        client=httpx.AsyncClient(
            base_url="https://api.notion.com/v1/", transport=httpx.MockTransport(handler)
        ),
    )


def invoke(adapter, method, *args, **kwargs):
    """运行异步 SDK 操作并关闭测试客户端。"""

    async def run():
        try:
            return await getattr(adapter, method)(*args, **kwargs)
        finally:
            await adapter.aclose()

    return asyncio.run(run())


def children():
    blocks = render(Quote(str(UUID(int=1)), "金句", "书名", "https://example.com"), date.today())
    return [dict(b, id=f"slot{i}", has_children=False) for i, b in enumerate(blocks)]


def test_query_preserves_filter_across_pages():
    requests = []
    urls = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        urls.append(request.url)
        second = len(requests) > 1
        return httpx.Response(
            200,
            json={
                "results": [{"id": 2 if second else 1}],
                "has_more": not second,
                "next_cursor": "cursor",
            },
        )

    filter_ = {"property": "参与轮换", "checkbox": {"equals": True}}
    assert len(invoke(api(handler), "query", "source", filter_, filter_properties=["书籍"])) == 2
    assert requests[1]["start_cursor"] == "cursor"
    assert all(request["filter"] == filter_ for request in requests)
    assert all(url.params.get_list("filter_properties") == ["书籍"] for url in urls)


def test_children_paginate():
    requests = []

    def handler(request):
        requests.append(request)
        second = len(requests) > 1
        return httpx.Response(
            200,
            json={
                "results": [{"id": len(requests)}],
                "has_more": not second,
                "next_cursor": "cursor",
            },
        )

    assert len(invoke(api(handler), "children", "parent")) == 2
    assert requests[1].url.params["start_cursor"] == "cursor"


def test_rate_limit_delay_and_server_retry():
    statuses = iter([429, 503, 200])
    waits = []

    async def sleep(delay):
        waits.append(delay)

    adapter = api(
        lambda _: httpx.Response(next(statuses), headers={"Retry-After": "3"}, json={}),
        sleep,
    )
    invoke(adapter, "page", "id")
    assert waits == [3, 2]


@pytest.mark.parametrize("failure", ["timeout", "server", "invalid-json"])
def test_create_is_never_blindly_retried(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if failure == "server":
            return httpx.Response(503)
        return httpx.Response(200, text="not json")

    with pytest.raises(UncertainCreate):
        invoke(api(handler), "create_record", "source", {}, [])
    assert len(calls) == 1
    assert calls[0].url.path == "/v1/pages"


def test_server_errors_and_credentials_never_leak():
    with pytest.raises(PublicationError) as error:
        invoke(api(lambda _: httpx.Response(401, json={"message": "secret-key"})), "page", "id")
    assert "secret-key" not in str(error.value)


@pytest.mark.parametrize("change", ["extra-block", "nested-child", "filled-spacer"])
def test_layout_changes_stop_before_any_mutation(change):
    rows = children()
    if change == "extra-block":
        rows.append(rows[0])
    elif change == "nested-child":
        rows[3]["has_children"] = True
    else:
        rows[2]["paragraph"]["rich_text"] = [{"type": "text", "text": {"content": "私人内容"}}]
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"results": rows, "has_more": False})

    with pytest.raises(PublicationError):
        invoke(api(handler), "update_home", "owned", children())
    assert methods == ["GET"]


def test_home_skips_unchanged_spacers_and_date_last():
    rows = children()
    writes = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        writes.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    invoke(api(handler), "update_home", "owned", rows)
    assert len(writes) == 4
    assert [path for path, _ in writes] == [f"/v1/blocks/slot{i}" for i in (1, 3, 5, 0)]


@pytest.mark.parametrize("old_color", ["gray", None])
def test_spacer_with_different_or_unknown_color_is_written(old_color):
    """留白颜色不同或未返回时保守写入，不跳过无法确认的样式。"""
    rows = children()
    if old_color is None:
        del rows[2]["paragraph"]["color"]
    else:
        rows[2]["paragraph"]["color"] = old_color
    writes = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        writes.append(request.url.path)
        return httpx.Response(200, json={})

    invoke(api(handler), "update_home", "owned", children())
    assert writes == [f"/v1/blocks/slot{i}" for i in (1, 2, 3, 5, 0)]


def test_existing_daily_record_updates_properties_and_changed_blocks():
    rows = children()
    writes = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        writes.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    properties = {"轮次": {"number": 2}, "发布状态": {"select": {"name": "待发布"}}}
    invoke(api(handler), "update_record", "record", properties, rows)
    assert writes[0] == ("/v1/pages/record", {"properties": properties})
    assert [path for path, _ in writes[1:]] == [f"/v1/blocks/slot{i}" for i in (1, 3, 5, 0)]


@pytest.mark.parametrize("method", ["update_home", "update_record"])
def test_content_blocks_are_serial_and_date_last(method):
    """同一页面最多有一个写请求；内容依序写入，日期最后写入。"""
    rows = children()
    writes = []
    active = 0
    events = []

    async def handler(request):
        nonlocal active
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        active += 1
        assert active == 1
        writes.append(request.url.path)
        await asyncio.sleep(0)
        active -= 1
        return httpx.Response(200, json={})

    args = ("owned", rows) if method == "update_home" else ("record", {}, rows)
    sink = logger.add(lambda message: events.append(str(message)))
    try:
        invoke(api(handler), method, *args)
    finally:
        logger.remove(sink)
    expected = [f"/v1/blocks/slot{i}" for i in (1, 3, 5, 0)]
    if method == "update_record":
        expected.insert(0, "/v1/pages/record")
    assert writes == expected
    assert any("开始顺序更新" in event for event in events)
    assert any("实际写入：[1, 3, 5]，跳过：[2, 4]" in event for event in events)
    assert any("日期区块更新完成" in event for event in events)


@pytest.mark.parametrize("method", ["update_home", "update_record"])
def test_content_failure_stops_at_failed_block_without_writing_date(method):
    """一个内容区块失败后，后续区块和日期均不写入。"""
    rows = children()
    writes = []
    events = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        writes.append(request.url.path)
        return httpx.Response(403 if request.url.path.endswith("slot3") else 200, json={})

    args = ("owned", rows) if method == "update_home" else ("record", {}, rows)
    sink = logger.add(lambda message: events.append(str(message)))
    try:
        with pytest.raises(PublicationError, match="区块 3"):
            invoke(api(handler), method, *args)
    finally:
        logger.remove(sink)
    expected = [f"/v1/blocks/slot{i}" for i in (1, 3)]
    if method == "update_record":
        expected.insert(0, "/v1/pages/record")
    assert writes == expected
    assert any("区块顺序更新失败：已写：[1]，已跳过：[2]，失败区块：3" in event for event in events)
    assert not any("日期区块更新完成" in event for event in events)


@pytest.mark.parametrize("method", ["update_home", "update_record"])
def test_external_conflict_retries_current_block_before_continuing(method):
    """即使顺序写入遇到外部 409，也只重试当前区块。"""
    rows = children()
    attempts = Counter()
    writes = []
    waits = []
    events = []

    async def no_sleep(delay):
        waits.append(delay)

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        path = request.url.path
        writes.append(path)
        if path == "/v1/pages/record":
            return httpx.Response(200, json={})
        index = int(path.rsplit("slot", 1)[1])
        attempts[index] += 1
        return httpx.Response(409 if index == 3 and attempts[index] == 1 else 200, json={})

    args = ("owned", rows) if method == "update_home" else ("record", {}, rows)
    sink = logger.add(lambda message: events.append(str(message)))
    try:
        invoke(api(handler, sleep=no_sleep), method, *args)
    finally:
        logger.remove(sink)
    expected = [f"/v1/blocks/slot{i}" for i in (1, 3, 3, 5, 0)]
    if method == "update_record":
        expected.insert(0, "/v1/pages/record")
    assert writes == expected
    assert waits == [0.2]
    assert attempts[3] == 2
    assert any("区块 3 写入冲突已恢复" in event for event in events)


def test_persistent_conflict_stops_before_later_blocks_and_date():
    """当前区块持续冲突时，有限重试后停止发布。"""
    rows = children()
    attempts = Counter()
    writes = []

    async def no_sleep(_delay):
        """跳过测试中的退避等待。"""

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        path = request.url.path
        writes.append(path)
        index = int(path.rsplit("slot", 1)[1])
        attempts[index] += 1
        return httpx.Response(409 if index == 3 else 200, json={})

    with pytest.raises(PublicationError, match="写入冲突"):
        invoke(api(handler, sleep=no_sleep), "update_home", "owned", rows)
    assert writes == [f"/v1/blocks/slot{i}" for i in (1, 3, 3, 3, 3, 3)]
    assert attempts[3] == 5
    assert attempts[1] == 1
    assert attempts[2] == 0


def test_changed_daily_record_layout_stops_before_property_update():
    rows = children()
    rows[2]["paragraph"]["rich_text"] = [{"type": "text", "text": {"content": "用户内容"}}]
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"results": rows, "has_more": False})

    with pytest.raises(PublicationError, match="每日记录空白间隔"):
        invoke(api(handler), "update_record", "record", {}, children())
    assert methods == ["GET"]


def test_preflight_rejects_sync_block_from_another_page():
    home, other = str(UUID(int=100)), str(UUID(int=200))
    config = SimpleNamespace(
        home_page_id=home,
        managed_block_id="managed",
        quotes_data_source_id="quotes",
        daily_data_source_id="daily",
    )

    def handler(request):
        if request.url.path.endswith("/children"):
            return httpx.Response(200, json={"results": children(), "has_more": False})
        if "/blocks/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "type": "synced_block",
                    "synced_block": {"synced_from": None},
                    "parent": {"page_id": other},
                },
            )
        return httpx.Response(200, json={})

    with pytest.raises(PublicationError, match="原始同步块"):
        invoke(api(handler), "preflight", config)


def test_preflight_reads_home_objects_concurrently_before_validation():
    home = str(UUID(int=100))
    config = SimpleNamespace(
        home_page_id=home,
        managed_block_id="managed",
        quotes_data_source_id="quotes",
        daily_data_source_id="daily",
    )
    arrived = asyncio.Event()
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        if len(paths) == 3:
            arrived.set()
        # 三项首页核验读取需要同时到达；数据源由独立查询验证。
        await asyncio.wait_for(arrived.wait(), timeout=2)
        if request.url.path == "/v1/blocks/managed/children":
            return httpx.Response(200, json={"results": children(), "has_more": False})
        if request.url.path == "/v1/blocks/managed":
            return httpx.Response(
                200,
                json={
                    "type": "synced_block",
                    "synced_block": {"synced_from": None},
                    "parent": {"page_id": home},
                },
            )
        return httpx.Response(200, json={})

    invoke(api(handler), "preflight", config)
    assert len(paths) == 3
    assert set(paths) == {
        f"/v1/pages/{home}",
        "/v1/blocks/managed",
        "/v1/blocks/managed/children",
    }
