# 每日金句

Notion 是唯一业务数据源，也是手机阅读入口。Codex 完成原稿解析、金句提取、上下文核对和增量初始化；Python 只负责随机轮换与每日发布，不包含文档解析、迁移、同步或 AI 调用。

## 当前入口

- [每日金句](https://www.notion.so/3fb2e3a6cfa6814a9371f5d09d3dd265)：私人阅读首页。
- [后台数据](https://www.notion.so/3fb2e3a6cfa681a483b2dda0d782d9d1)：金句库和每日记录。
- [本书原稿](https://www.notion.so/3fb2e3a6cfa681298c34f5652de0c91a)：DOCX 附件、7 节、84 个正文段落，来源是读书讲解稿。

没有感想功能。LaunchAgent 配置为每天北京时间 11:00。是否已由 macOS 加载新配置，以 `launchctl print` 的当前结果为准。

## 运行

安装 Python 3.12 和 uv，在本项目目录执行：

```sh
uv sync --locked
# 将 Notion 连接密钥填入 .env 的 NOTION_TOKEN= 后，不要提交或发送密钥
uv run qotd daily
```

聊天中的 Notion 连接与 Python API 凭据是独立授权的。请把 `.env` 对应的连接添加到“读书笔记”数据库、“每日金句”首页和“每日金句 · 后台数据”页。子页应继承访问权限。缺少访问权限时，Notion 也可能返回 404。

`.env` 不进入版本库或构建产物；文件权限应为 600。部署时通过环境变量注入 `NOTION_TOKEN` 也可。`qotd.toml` 只放可能经常调整的 `page_url_template`；固定的 Notion 页面及数据源 ID、发布状态、字段名、颜色、API 限制与日志保留参数集中在 [settings.py](src/qotd/settings.py)。从其他目录调用时使用绝对路径：

```sh
uv run --project /usr/local/codex-workspace/qotd qotd daily --config /usr/local/codex-workspace/qotd/qotd.toml
```

`--config` 必须指向实际存在的文件。若配置目录不可用，命令会改把错误写入当前工作目录的 `logs/`，然后停止发布。

## macOS 定时任务

常用命令和卸载方法见 [launchd/README.md](launchd/README.md)。

用户级配置文件见 [launchd/com.rayliu.qotd.daily.plist](launchd/com.rayliu.qotd.daily.plist)，安装位置是 `~/Library/LaunchAgents/com.rayliu.qotd.daily.plist`。它每天按 Mac 系统时区的 11:00 调用一次虚拟环境中的 `qotd daily`；当前 Mac 时区是北京时间。macOS 可能在配置文件安装后自动加载它，重复 `bootstrap` 会报错；先用 `launchctl print` 检查。修改配置文件不会自动更新已加载的任务，需卸载再加载才会生效。日志由程序写入项目 `logs/`。配置没有 `RunAtLoad` 或 `KeepAlive`，登录本身不会额外触发发布。

```sh
launchctl print gui/$(id -u)/com.rayliu.qotd.daily
# 仅当 print 提示服务不存在时，才手动加载：
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.rayliu.qotd.daily.plist"
# 需要停用时：
launchctl bootout gui/$(id -u)/com.rayliu.qotd.daily
```

每次触发都会重新抽取并覆盖当天金句。调整时间后需重新安装并加载配置文件。

## 发布行为

- 手动运行立即发布北京时间当天内容；加载新配置后的 LaunchAgent 每天 11:00 运行一次同一命令。
- 从启用轮换的金句中随机选择，一轮用完才重复，新金句可进入当前轮次。
- 每次运行都重新随机抽取。同一天已有每日记录时复用该页面 ID，覆盖其金句关联、轮次、展示快照和正文；每天最多保留一条记录。
- 轮次只根据当天以前的最终记录计算。同日被覆盖的金句不计入历史；重新抽取也可能碰巧得到同一句。
- 在 Notion 先保存本次快照及待发布状态，再更新每日记录正文和首页，最后标记发布完成。
- 更新不是事务；失败可能短暂留下部分内容。下一次运行会重新抽取并覆盖当天记录。创建请求超时或返回不确定结果时，先查询而非重复创建。
- 全部接口分页读取；限流、读取及安全更新会有限重试。重复日期、无效快照或未来记录会停止发布，请让 Codex 核对。
- 仅更新指定同步块内六个区块：日期、带书名链接的金句、空白、原文、空白、原文位置链接。结构改变或空白区被填写时停止，防止覆盖用户内容。
- 缺少原文时显示“原文待补充”。链接书名来自关联的书籍页，不单独复制书名字段。
- 首页金句使用粗体，原文中的对应文字使用粗体和灰色背景；书名和原文位置链接使用蓝色粗体。标点、空白和全半角差异不改变原文；概括性摘抄使用 Codex 在“原文”富文本中核验并标为灰色背景的片段，发布时呈现为粗体加灰色背景，不自动猜测语义。定位范围随展示快照保存；旧快照仍可读取并直接匹配。
- 使用 `notion-client` SDK 访问 Notion。`httpx` 保持为直接依赖，因为客户端明确捕获其传输异常，测试也使用它注入模拟 HTTP 客户端。关键路径、结果和错误由 Loguru 同时写入控制台与项目 `logs/`，命令入口不再使用 `print`；日志按北京时间逐日命名，仅保留最近七天，每个文件最多 500 MB。日志不包含连接密钥。

本机文件锁只防止同一台 Mac 的并发发布，不存储业务状态。Notion API 没有事务或唯一约束，不能多机同时运行。未来迁云时先停用 Mac 任务。

## 初始化与验证

初始化流程见 [Notion每日金句初始化 skill](/Users/rayliu/.codex/skills/initialize-daily-quote-book/SKILL.md)。直接编辑原读书笔记后，需要让 Codex 更新金句库，Python 不自动同步。

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

测试使用合成数据和模拟 HTTP，不向真实 Notion 写入测试日期。同日覆盖验收应确认记录 ID 不变、库中仍只有一条当天记录，且记录与首页均显示最后一次选句。
