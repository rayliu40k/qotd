# 每日金句项目工作约定

本仓库的 Python 程序只负责从已初始化的 Notion 金句库选句，并发布到 Notion 首页。Notion 是唯一的业务数据源；DOCX 解析、摘抄核对和金句初始化由 Codex 按 `initialize-daily-quote-book` skill 完成，不加入 Python 发布程序。

## 开工流程

1. 用 `pwd` 确认位于 `/usr/local/codex-workspace/qotd`。
2. 读取 `docs/progress.md`、`docs/feature_list.json` 和 `docs/session-handoff.md`，了解已验证状态、尚未完成的工作及上一轮交接；同时核对用户本轮的实际目标，不凭空启动清单外的功能。
3. 运行 `git status --short`、`git log --oneline -5`，保留已有未提交改动。
4. 运行 `./docs/init.sh`。基础验证失败时，先修复或记录明确的环境 blocker，再开发目标功能。
5. 修改真实 Notion 内容前，读取 `qotd.toml`；初始化书籍时还要读取 `initialize-daily-quote-book` skill，并核对现有页面与记录。

## Harness 文档索引

根目录只保留本文件作为入口。其余 Harness 文件放在 `docs/`；按当前工作阶段读取，不把历史记录当作待执行指令。

| 时机 | 文件 | 用途 |
|---|---|---|
| 开工、查询当前状态 | `docs/progress.md` | 已验证状态与按北京时间升序排列的会话记录，新记录在底部 |
| 开工、选择或更新功能 | `docs/feature_list.json` | 功能状态、验证要求与证据；以 `date` 升序排列，新功能在底部 |
| 开工、接续上一轮工作 | `docs/session-handoff.md` | 最近一轮的简短交接摘要 |
| 开工、修改后验证 | `docs/init.sh` | 从项目根目录运行的离线环境与测试入口：`./docs/init.sh` |
| 收尾、提交前 | `docs/clean-state-checklist.md` | 逐项核对验证、记录、差异及可交接状态 |

## 项目边界

- Python 入口是 `uv run qotd daily`；每次执行都会修改真实 Notion 首页和北京时间当天的记录。`docs/init.sh` 只准备环境并运行离线验证，绝不自动发布。
- `src/qotd/` 保存日常抽取、轮换、Notion 调用与六区块渲染；`tests/` 使用模拟 Notion 数据验证行为。不要在真实 Notion 创建测试日期或用发布命令做 smoke test。
- 新书初始化、原稿导入和语义定位属于 Codex 工作流。保留原始读书笔记及既有每日快照，复用匹配的金句页面，避免重复记录和无依据覆盖。
- 凭据仅在 `.env` 或环境变量中；不要写入日志、测试工件或提交。`.env` 权限保持为 `600`。
- 页面结构和字段名以现有 Notion 对象及 `src/qotd/settings.py` 为准。保持六区块阅读排版，不添加感想或其他首页入口。

## 工作与验证

- 一次只推进一个明确功能；`docs/feature_list.json` 同时最多一个 `in_progress`。
- `docs/feature_list.json` 每个功能保留北京时间 `date`（`YYYY-MM-DD HH:MM:SS`）：新建功能时记录创建时间，状态或证据有实质更新时记录该次更新时间；按此字段升序排列，最新置底。`docs/progress.md` 的会话标题使用 `### YYYY-MM-DD HH:MM:SS：主题`，会话记录也按时间升序排列，新记录追加在底部。历史时间只用可核实的来源回填，不猜测。
- 对 Python 变更运行 `./docs/init.sh`，其中包含 pytest、Ruff 检查与格式检查。需要验证真实 Notion 行为时，先明确写入影响，再按用户授权执行；离线测试通过不能替代线上验收。
- 不因代码存在或测试名称暗示功能完成。只有目标行为实现、要求的验证实际通过、证据写入 `docs/feature_list.json` 或 `docs/progress.md`，并且 `./docs/init.sh` 可重新运行，才能标为 `passing`。
- 不为通过检查而降低测试或验证要求。未验证的事实留空或写为“未验证”。

## 收尾

- 更新 `docs/progress.md` 与 `docs/feature_list.json`。
- 记录运行过的命令、结果、未解决风险和下一步。
- 对照 `docs/clean-state-checklist.md` 逐项检查。这是每轮结束前的可复用检查清单，不在文件中永久勾选；无法通过的项目写入进度和交接摘要。
- 更新 `docs/session-handoff.md`，用简短的当前已验证状态、本轮改动、未验证事项、下一步和命令覆盖上一轮摘要；它在收尾时写、下一轮开工时读，不充当长期历史日志。
- 核对 `git diff` 与工作区状态，只提交本轮相关且处于安全状态的文件；每次提交的 commit message 用中文，说明实际改动。
- 下一轮应能直接运行 `./docs/init.sh` 继续工作。
