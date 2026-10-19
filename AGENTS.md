# 每日金句项目工作约定

本仓库的 Python 程序只负责从已初始化的 Notion 金句库选句，并发布到 Notion 首页。Notion 是唯一的业务数据源；DOCX 解析、摘抄核对和金句初始化由 Codex 按 `initialize-daily-quote-book` skill 完成，不加入 Python 发布程序。

## 开工流程

1. 用 `pwd` 确认位于 `/usr/local/codex-workspace/qotd`。
2. 读取 `progress.md` 和 `feature_list.json`，了解已验证状态与尚未完成的工作；同时核对用户本轮的实际目标，不凭空启动清单外的功能。
3. 运行 `git status --short`、`git log --oneline -5`，保留已有未提交改动。
4. 运行 `./init.sh`。基础验证失败时，先修复或记录明确的环境 blocker，再开发目标功能。
5. 修改真实 Notion 内容前，读取 `qotd.toml`；初始化书籍时还要读取 `initialize-daily-quote-book` skill，并核对现有页面与记录。

## 项目边界

- Python 入口是 `uv run qotd daily`；每次执行都会修改真实 Notion 首页和北京时间当天的记录。`init.sh` 只准备环境并运行离线验证，绝不自动发布。
- `src/qotd/` 保存日常抽取、轮换、Notion 调用与六区块渲染；`tests/` 使用模拟 Notion 数据验证行为。不要在真实 Notion 创建测试日期或用发布命令做 smoke test。
- 新书初始化、原稿导入和语义定位属于 Codex 工作流。保留原始读书笔记及既有每日快照，复用匹配的金句页面，避免重复记录和无依据覆盖。
- 凭据仅在 `.env` 或环境变量中；不要写入日志、测试工件或提交。`.env` 权限保持为 `600`。
- 页面结构和字段名以现有 Notion 对象及 `src/qotd/settings.py` 为准。保持六区块阅读排版，不添加感想或其他首页入口。

## 工作与验证

- 一次只推进一个明确功能；`feature_list.json` 同时最多一个 `in_progress`。
- 对 Python 变更运行 `./init.sh`，其中包含 pytest、Ruff 检查与格式检查。需要验证真实 Notion 行为时，先明确写入影响，再按用户授权执行；离线测试通过不能替代线上验收。
- 不因代码存在或测试名称暗示功能完成。只有目标行为实现、要求的验证实际通过、证据写入 `feature_list.json` 或 `progress.md`，并且 `./init.sh` 可重新运行，才能标为 `passing`。
- 不为通过检查而降低测试或验证要求。未验证的事实留空或写为“未验证”。

## 收尾

更新 `progress.md` 与 `feature_list.json`，记录运行过的命令、结果、未解决风险和下一步。核对 `git diff` 与工作区状态，只提交本轮相关且处于安全状态的文件，提交信息说明实际改动。下一轮应能直接运行 `./init.sh` 继续工作。
