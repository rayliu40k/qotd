import json
from datetime import date

import pytest

from qotd.highlights import matching_ranges, ranges_from_rich_text
from qotd.models import PublicationError, Quote, plain, rich_text
from qotd.render import context_text, render

ID = "00000000-0000-0000-0000-000000000001"


def quote(context, text, **kwargs):
    return Quote(ID, text, "书", "https://www.notion.so/book", context, **kwargs)


def highlighted(items):
    assert all(
        item.get("annotations", {}).get("color") == "gray_background"
        for item in items
        if item.get("annotations", {}).get("bold") is True
    )
    return "".join(
        item["text"]["content"] for item in items if item.get("annotations", {}).get("bold") is True
    )


def test_only_matching_original_text_gets_bold_gray_background():
    items = context_text(quote("前文。金句。后文。", "金句。"))
    assert plain(items) == "前文。金句。后文。"
    assert highlighted(items) == "金句。"
    assert all(
        item.get("annotations", {}).get("color") != "gray_background"
        for item in items
        if item.get("annotations", {}).get("bold") is not True
    )


def test_missing_comma_highlights_original_without_rewriting_it():
    original = "前文。投资有时候也像钓鱼，不动的时候是常态，发现机会后迅速下手这些都是机会。后文。"
    selected = "投资有时候也像钓鱼，不动的时候是常态，发现机会后迅速下手，这些都是机会。"
    items = context_text(quote(original, selected))
    assert plain(items) == original
    assert highlighted(items) == (
        "投资有时候也像钓鱼，不动的时候是常态，发现机会后迅速下手这些都是机会。"
    )


def test_width_whitespace_and_punctuation_matching_keeps_original_characters():
    original = "前文；他说ＡＩ　已经来了！后文。"
    items = context_text(quote(original, "AI已经来了。"))
    assert plain(items) == original
    assert highlighted(items) == "ＡＩ　已经来了！"


def test_repeated_match_highlights_both_occurrences():
    items = context_text(quote("等待。中间文字。等待。", "等待。"))
    assert highlighted(items) == "等待。等待。"
    assert plain(items) == "等待。中间文字。等待。"


def test_no_matching_wording_does_not_guess_semantic_location():
    assert highlighted(context_text(quote("原文的一段话。", "不同的概括。"))) == ""
    assert matching_ranges("原文", "！？") == ()


def test_codex_curated_ranges_are_preserved_in_snapshot_and_rendering():
    original = "背景。他收购公司。增加业绩。股价上涨。其他内容。"
    start, end = original.index("他收购"), original.index("其他")
    source = quote(original, "通过买公司推动股价上涨。", context_highlights=((start, end),))
    snapshot = Quote.from_snapshot(source.snapshot())
    assert snapshot == source
    assert highlighted(context_text(snapshot)) == original[start:end]
    assert plain(context_text(snapshot)) == original


@pytest.mark.parametrize("source_color", ["default_background", "gray_background"])
def test_source_rich_text_annotation_is_loaded_without_extra_database_field(source_color):
    items = rich_text("背景。")
    for text in ("收购公司。", "提升业绩。"):
        items.append(
            {
                "type": "text",
                "text": {"content": text},
                "annotations": {"color": source_color},
            }
        )
    items.extend(rich_text("结尾。"))
    page = {
        "id": ID,
        "properties": {
            "金句": {"title": rich_text("概括句")},
            "原文": {"rich_text": items},
            "原文位置": {"rich_text": []},
            "原文链接": {"url": None},
        },
    }
    book = {
        "id": ID,
        "url": "https://www.notion.so/book",
        "properties": {"书名": {"title": rich_text("书")}},
    }
    source = Quote.from_page(page, book, "https://www.notion.so/{page_id}")
    assert ranges_from_rich_text(items) == ((3, 13),)
    assert highlighted(context_text(source)) == "收购公司。提升业绩。"


def test_yellow_source_annotation_is_not_used_as_semantic_highlight():
    items = [
        {
            "type": "text",
            "text": {"content": "概括性摘抄对应的原句。"},
            "annotations": {"color": "yellow_background"},
        }
    ]
    assert ranges_from_rich_text(items) == ()


def test_legacy_snapshot_gains_highlight_without_changing_reserved_data():
    original = "前文。金句。后文。"
    data = json.loads(quote(original, "金句。").snapshot())
    data.pop("context_highlights")
    snapshot = json.dumps(data, ensure_ascii=False)
    parsed = Quote.from_snapshot(snapshot)
    blocks = render(parsed, date(2026, 10, 17))
    assert highlighted(blocks[3]["paragraph"]["rich_text"]) == "金句。"
    assert json.loads(snapshot) == data
    assert len(blocks) == 6


@pytest.mark.parametrize(
    "ranges", [[[0, 999]], [[3, 2]], [[0, 3], [2, 4]], [[True, 3]], "bad", [[0]], [[0.1, 2]]]
)
def test_invalid_snapshot_highlight_ranges_stop_publication(ranges):
    data = json.loads(quote("完整原文", "原文").snapshot())
    data["context_highlights"] = ranges
    with pytest.raises(PublicationError, match="快照无效"):
        Quote.from_snapshot(json.dumps(data))


def test_long_highlight_splits_at_notion_limit_and_keeps_every_character():
    original = "前文。" + "很长的金句" * 1000 + "。后文。"
    selected = "很长的金句" * 1000
    items = context_text(quote(original, selected))
    assert highlighted(items) == selected
    assert plain(items) == original
    assert all(len(item["text"]["content"]) <= 2000 for item in items)
