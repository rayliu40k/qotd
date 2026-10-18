"""集中管理固定的 Notion 对象、字段、展示文案和技术限制。

运行时常调整的页面链接模板单独存放在 ``qotd.toml``。
"""

from urllib.parse import urlparse
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

HOME_PAGE_ID = "3fb2e3a6-cfa6-814a-9371-f5d09d3dd265"
MANAGED_BLOCK_ID = "e40a9f78-6efc-41c5-b591-3de3722ffedf"
QUOTES_DATA_SOURCE_ID = "00e255b1-bb21-4d54-84a7-b33dc0fcfb32"
DAILY_DATA_SOURCE_ID = "02db1092-97d0-4f5e-aee4-3323a21cd6b8"

QUOTE_TITLE = "金句"
QUOTE_BOOK = "书籍"
QUOTE_CONTEXT = "原文"
QUOTE_SOURCE_LABEL = "原文位置"
QUOTE_SOURCE_URL = "原文链接"
QUOTE_ENABLED = "参与轮换"

DAILY_TITLE = "日期标题"
DAILY_DATE = "日期"
DAILY_QUOTE = "金句"
DAILY_ROUND = "轮次"
DAILY_STATUS = "发布状态"
DAILY_SNAPSHOT = "展示快照"

PENDING_STATUS = "待发布"
PUBLISHED_STATUS = "已发布"
RESULT_STATUS_PUBLISHED = "published"
LINK_COLOR = "blue"
HIGHLIGHT_BACKGROUND_COLOR = "gray_background"
# Codex 在金句库原文属性中用灰色标记语义对应原句；兼容 Notion 返回的两种灰色值。
SOURCE_HIGHLIGHT_COLORS = frozenset({"default_background", "gray_background"})
BLOCK_DEFAULT_COLOR = "default"
MISSING_CONTEXT = "原文待补充"
MISSING_SOURCE_LABEL = "原文位置待补充"

NOTION_PAGE_SIZE = 100
NOTION_TEXT_LIMIT = 2000
NOTION_RICH_TEXT_LIMIT = 100
NOTION_MAX_ATTEMPTS = 5
NOTION_TIMEOUT_MS = 30_000
CREATE_RECOVERY_DELAYS = (1, 2, 4)
LOG_RETENTION_DAYS = 7
LOG_MAX_BYTES = 500_000_000


def page_url(page_id: str, template: str) -> str:
    """根据配置模板生成 Notion 页面链接。

    ``template`` 必须是 HTTPS 链接且只包含 ``{page_id}`` 占位符，
    避免配置错误在发布成功后才暴露。
    """
    if template.count("{page_id}") != 1:
        raise ValueError("页面链接模板必须包含一个 {page_id} 占位符。")
    try:
        url = template.format(page_id=page_id.replace("-", ""))
    except (KeyError, ValueError) as error:
        raise ValueError("页面链接模板无效，请检查 qotd.toml。") from error
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("页面链接模板必须生成 HTTPS 链接。")
    return url
