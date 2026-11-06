# 会话交接

会话历史见 `docs/progress.md`，功能状态见 `docs/feature_list.json`。

## 当前已验证

- `./docs/init.sh`：103 passed，Ruff 检查与格式检查通过。
- `uv run qotd republish` 离线模拟确认：只写变化的快照和区块；完全一致时零写入且日志明确说明；记录与首页独立读回并行验证。
- `daily` 原有抽选逻辑和 LaunchAgent 配置未改，既有回归测试通过。

## 本轮改动

- 优化重发流程的并行读取、语义差异比较和选择性写入；补充无变化 CLI 提示与离线测试。
- 更新功能证据和进度记录。

## 未验证与下一步

- 未执行真实 Notion 重发；线上端到端结果及实际耗时未验收。
- Notion 多次写入不是事务。重发失败后内容可能暂时混合；再次运行同一命令或核查记录与首页。
- 线上验收时先确认会修改北京时间当天记录及首页，再运行 `uv run qotd republish`；`launchctl kickstart` 仍只运行 `daily`。

## 命令

- 离线验证：`./docs/init.sh`
- 检查差异：`git diff --check`
