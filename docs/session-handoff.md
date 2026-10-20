# 会话交接

此文件只保留最近一轮的摘要，不存放会话记录列表；会话记录在 `docs/progress.md` 中按时间升序排列，最新记录追加在底部。功能状态与证据见 `docs/feature_list.json`。项目根目录的 `AGENTS.md` 是 Harness 索引入口。

## 当前已验证

- `./docs/init.sh` 是离线验证入口，会先切回项目根目录，再运行 pytest、Ruff 检查和格式检查；本轮修改前基线为 72 个测试通过。
- Python 发布程序从 Notion 读取已初始化的金句，并更新北京时间当天唯一的每日记录和首页；同日重跑会覆盖当天记录。上述行为由模拟 Notion 测试验证。

## 本轮改动

- 在根目录 `AGENTS.md` 中规定按改动范围选择验证：Python、测试和脚本改动运行 `./docs/init.sh`，仅文档或配置改动执行定向检查，无需重复运行完整测试。
- 同步更新收尾清单与功能清单；本轮修改后只执行文档和配置的定向检查。

## 仍损坏或未验证

- 本轮未执行真实 Notion 发布；现有离线测试不能证明线上权限、页面当前结构或实际耗时。
- 全新环境的 `uv sync --locked` 尚未在当前沙箱验证。

## 下一步最佳动作

- 下一轮先读根目录 `AGENTS.md` 指向的 `docs/progress.md`、`docs/feature_list.json` 和本文件，再按实际改动范围选择验证；涉及代码或脚本时运行 `./docs/init.sh`。
- 不把 `uv run qotd daily` 当作 smoke test，因为它会覆盖真实 Notion 当天展示。

## 命令

- 代码或脚本改动的离线验证：`./docs/init.sh`
- 查看工作区：`git status --short`
- 核对差异：`git diff --check`
- 真实手动发布（仅在明确需要时）：`uv run qotd daily`
