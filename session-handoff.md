# 会话交接

此文件只保留最近一轮的摘要；长期记录见 `progress.md`，功能状态与证据见 `feature_list.json`。

## 当前已验证

- `./init.sh` 是离线验证入口，包含 pytest、Ruff 检查和格式检查；最近一次基线结果为 72 个测试通过。
- Python 发布程序从 Notion 读取已初始化的金句，并更新北京时间当天唯一的每日记录和首页；同日重跑会覆盖当天记录。上述行为由模拟 Notion 测试验证。

## 本轮改动

- 统一 harness 记录的北京时间格式和时间降序规则，并要求中文 commit message。
- 增加本交接摘要与 `clean-state-checklist.md`，在 `AGENTS.md` 中规定使用时机。

## 仍损坏或未验证

- 本轮未执行真实 Notion 发布；现有离线测试不能证明线上权限、页面当前结构或实际耗时。
- 全新环境的 `uv sync --locked` 尚未在当前沙箱验证。

## 下一步最佳动作

- 下一轮先读 `AGENTS.md`、`progress.md`、`feature_list.json` 和本文件，再运行 `./init.sh`；按用户新需求选择一个目标。
- 不把 `uv run qotd daily` 当作 smoke test，因为它会覆盖真实 Notion 当天展示。

## 命令

- 离线验证：`./init.sh`
- 查看工作区：`git status --short`
- 核对差异：`git diff --check`
- 真实手动发布（仅在明确需要时）：`uv run qotd daily`
