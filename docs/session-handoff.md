# 会话交接

会话历史见 `docs/progress.md`，功能状态见 `docs/feature_list.json`。

## 当前已验证

- `./docs/init.sh`：98 passed，Ruff 检查与格式检查通过。
- `uv run qotd republish` 独立于 `daily`：离线模拟确认只用北京时间当天唯一已发布记录的关联金句，保留记录身份、轮次和状态，刷新快照、记录正文与首页，并读回核对。
- `daily` 原有抽选逻辑和 LaunchAgent 配置未改，既有回归测试通过。

## 本轮改动

- 新增重发流程、保留状态的 Notion 记录刷新方法、CLI 分流与模拟测试。
- 更新 README、设计文档和 Harness 记录。

## 未验证与下一步

- 未执行真实 Notion 发布或重发；线上端到端结果尚未验收。
- Notion 多次写入不是事务。重发失败后记录仍标“已发布”，内容可能暂时混合；再次运行同一重发命令可覆盖修复，若仍失败让 Codex 核查。
- 需要线上验收时，先确认会修改北京时间当天记录及首页，再执行 `uv run qotd republish`；不要用 `launchctl kickstart` 测试重发，它仍会运行随机抽句的 `daily`。

## 命令

- 离线验证：`./docs/init.sh`
- 检查差异：`git diff --check`
