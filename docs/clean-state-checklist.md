# 收尾检查清单

每轮结束前对照检查；勾选状态只用于当次核对，不在此文件中保存。未通过的项目写入 `docs/progress.md` 和 `docs/session-handoff.md`，不要把未验证功能标为 `passing`。

- [ ] `pwd` 指向 `/usr/local/codex-workspace/qotd`；需要完整离线验证时，下一轮可以直接运行 `./docs/init.sh`。
- [ ] 已按改动范围验证并记录结果：涉及 Python、测试或可执行脚本时运行 `./docs/init.sh`；仅修改文档或配置时，执行适用的定向检查，无需运行该脚本。如因环境阻塞，已写明失败命令与原因。此脚本不能发布真实金句。
- [ ] 本轮目标行为已验证；若涉及真实 Notion，离线模拟与线上验收的边界已分别说明。
- [ ] `docs/feature_list.json` 状态、证据和 `date` 与实际相符，时间升序排列，最新在底部，最多一个 `in_progress`。
- [ ] `docs/progress.md` 的本轮记录包含目标、完成内容、验证结果、风险和下一步；会话标题带北京时间，记录按时间升序排列，最新在底部。
- [ ] `docs/session-handoff.md` 已更新为本轮的简短交接，未验证路径没有写成已完成。
- [ ] `git diff --check` 与 `git status --short` 已核对；没有凭据、临时文件或未记录的半成品进入提交。
- [ ] 只提交本轮相关且安全的文件，commit message 使用中文；提交后再次确认工作区状态，遗留改动已说明。
