import json
from datetime import date
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from qotd.models import PublicationError, Quote
from qotd.notion import Notion, UncertainCreate
from qotd.render import render


def api(handler, sleep=lambda _: None):
    return Notion(
        "unused",
        sleep=sleep,
        client=httpx.Client(
            base_url="https://api.notion.com/v1/", transport=httpx.MockTransport(handler)
        ),
    )


def children():
    blocks = render(Quote(str(UUID(int=1)), "金句", "书名", "https://example.com"), date.today())
    return [dict(b, id=f"slot{i}", has_children=False) for i, b in enumerate(blocks)]


def test_query_preserves_filter_across_pages():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
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
    assert len(api(handler).query("source", filter_)) == 2
    assert requests[1]["start_cursor"] == "cursor"
    assert all(request["filter"] == filter_ for request in requests)


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

    assert len(api(handler).children("parent")) == 2
    assert requests[1].url.params["start_cursor"] == "cursor"


def test_rate_limit_delay_and_server_retry():
    statuses = iter([429, 503, 200])
    waits = []
    adapter = api(
        lambda _: httpx.Response(next(statuses), headers={"Retry-After": "3"}, json={}),
        waits.append,
    )
    adapter.page("id")
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
        api(handler).create_record("source", {}, [])
    assert len(calls) == 1
    assert calls[0].url.path == "/v1/pages"


def test_server_errors_and_credentials_never_leak():
    with pytest.raises(PublicationError) as error:
        api(lambda _: httpx.Response(401, json={"message": "secret-key"})).page("id")
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
        api(handler).update_home("owned", children())
    assert methods == ["GET"]


def test_home_updates_only_owned_blocks_and_date_last():
    rows = children()
    writes = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        writes.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    api(handler).update_home("owned", rows)
    assert len(writes) == 6
    assert [p for p, _ in writes] == [f"/v1/blocks/slot{i}" for i in (1, 2, 3, 4, 5, 0)]


def test_existing_daily_record_updates_properties_and_all_blocks():
    rows = children()
    writes = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"results": rows, "has_more": False})
        writes.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    properties = {"轮次": {"number": 2}, "发布状态": {"select": {"name": "待发布"}}}
    api(handler).update_record("record", properties, rows)
    assert writes[0] == ("/v1/pages/record", {"properties": properties})
    assert [path for path, _ in writes[1:]] == [f"/v1/blocks/slot{i}" for i in (1, 2, 3, 4, 5, 0)]


def test_changed_daily_record_layout_stops_before_property_update():
    rows = children()
    rows[2]["paragraph"]["rich_text"] = [{"type": "text", "text": {"content": "用户内容"}}]
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json={"results": rows, "has_more": False})

    with pytest.raises(PublicationError, match="每日记录空白间隔"):
        api(handler).update_record("record", {}, children())
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
        api(handler).preflight(config)
