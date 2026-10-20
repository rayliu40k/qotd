# 会话交接

此文件只保留最近一轮的摘要；长期记录见 `docs/progress.md`，功能状态与证据见 `docs/feature_list.json`。项目根目录的 `AGENTS.md` 是 Harness 索引入口。

## 当前已验证

- `./docs/init.sh` 是离线验证入口，会先切回项目根目录，再运行 pytest、Ruff 检查和格式检查；本轮结果为 72 个测试通过。
- Python 发布程序从 Notion 读取已初始化的金句，并更新北京时间当天唯一的每日记录和首页；同日重跑会覆盖当天记录。上述行为由模拟 Notion 测试验证。

## 本轮改动

- 将 `init.sh`、`feature_list.json`、`progress.md`、`clean-state-checklist.md` 和本文件移至 `docs/`。
- 更新根目录 `AGENTS.md` 的索引、使用时机与命令，并修正验证脚本的项目根目录定位。

## 仍损坏或未验证

- 本轮未执行真实 Notion 发布；现有离线测试不能证明线上权限、页面当前结构或实际耗时。
- 全新环境的 `uv sync --locked` 尚未在当前沙箱验证。

## 下一步最佳动作

- 下一轮先读根目录 `AGENTS.md` 指向的 `docs/progress.md`、`docs/feature_list.json` 和本文件，再运行 `./docs/init.sh`；按用户新需求选择一个目标。
- 不把 `uv run qotd daily` 当作 smoke test，因为它会覆盖真实 Notion 当天展示。

## 命令

- 离线验证：`./docs/init.sh`
- 查看工作区：`git status --short`
- 核对差异：`git diff --check`
- 真实手动发布（仅在明确需要时）：`uv run qotd daily`
