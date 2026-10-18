"""计算原文中可直接匹配的摘抄范围，并读取人工标注范围。

此模块只处理字符偏移，不生成或改写原稿；概括性摘抄的语义定位
由 Codex 在 Notion 金句库初始化时完成。
"""

import unicodedata

from .settings import SOURCE_HIGHLIGHT_COLORS


def validate_ranges(value, length: int) -> tuple[tuple[int, int], ...]:
    """返回合法的字符范围元组，拒绝越界、重叠和无序范围。"""
    if not isinstance(value, (list, tuple)):
        raise ValueError("highlight ranges must be an array")
    ranges = []
    previous = 0
    for pair in value:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("invalid highlight range")
        start, end = pair
        if type(start) is not int or type(end) is not int:
            raise ValueError("highlight offsets must be integers")
        if not 0 <= start < end <= length or start < previous:
            raise ValueError("highlight ranges must be ordered, disjoint and in bounds")
        ranges.append((start, end))
        previous = end
    return tuple(ranges)


def ranges_from_rich_text(items: list[dict]) -> tuple[tuple[int, int], ...]:
    """读取 Codex 在金句库原文中以背景色标出的语义对应范围。

    只识别 Notion 的灰色背景标记；未标记文字不计入范围。
    """
    ranges = []
    offset = 0
    for item in items:
        text = item.get("plain_text", item.get("text", {}).get("content", ""))
        end = offset + len(text)
        if end > offset and item.get("annotations", {}).get("color") in SOURCE_HIGHLIGHT_COLORS:
            if ranges and ranges[-1][1] == offset:
                ranges[-1] = (ranges[-1][0], end)
            else:
                ranges.append((offset, end))
        offset = end
    return tuple(ranges)


def normalized(text: str) -> tuple[str, list[int]]:
    """规范化宽度并去掉标点空白，返回文字及原文偏移映射。"""
    chars, positions = [], []
    for offset, char in enumerate(text):
        for value in unicodedata.normalize("NFKC", char):
            if not value.isspace() and not unicodedata.category(value).startswith("P"):
                chars.append(value)
                positions.append(offset)
    return "".join(chars), positions


def matching_ranges(context: str, quote: str) -> tuple[tuple[int, int], ...]:
    """返回摘抄在原文中直接命中的字符范围。

    比较时忽略标点、空白及全半角差异；返回范围仍指向未经改动的
    原文字符。找不到直接匹配时返回空元组，不猜测语义位置。
    """
    text, positions = normalized(context)
    needle, _ = normalized(quote)
    if not needle:
        return ()
    ranges = []
    cursor = 0
    while (start := text.find(needle, cursor)) >= 0:
        end = positions[start + len(needle) - 1] + 1
        # 摘抄以标点结尾时，把原稿中的结尾标点一并标记。
        if unicodedata.category(quote.rstrip()[-1]).startswith("P"):
            while end < len(context) and unicodedata.category(context[end]).startswith("P"):
                end += 1
        source_start = positions[start]
        if ranges and source_start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((source_start, end))
        cursor = start + len(needle)
    return tuple(ranges)
