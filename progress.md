# 每日金句进度

## 当前已验证状态

- 仓库根目录：`/usr/local/codex-workspace/qotd`
- 标准环境与验证入口：`./init.sh`（离线 pytest、Ruff 检查与格式检查）
- 真实发布命令：`uv run qotd daily`，会覆盖北京时间当天的展示；不可当作 smoke test
- 业务存储：Notion 中的读书笔记、金句库、每日记录库与首页；本地不保存业务数据库
- 当前最高优先级未完成功能：没有已确认并排定的产品功能；新需求由用户确定后加入 `feature_list.json`
- 当前 blocker：未发现代码测试 blocker；本会话未验证真实 Notion 读写或全新环境安装

## 会话记录

### 2026-10-19：将 Harness 模板改为本项目实际内容

- 本轮目标：整理 `AGENTS.md`、`init.sh`、`progress.md` 与 `feature_list.json`。
- 已确认的项目行为：Python 仅执行每日选句与发布；Codex 单独负责书籍初始化；同日重新发布复用当天记录并覆盖首页；六区块布局；Notion 是业务数据源。
- 开工基线：`./init.sh` 原为 npm 示例，因无 `package.json` 失败；现有 `.venv/bin/pytest -q` 为 66 passed，`.venv/bin/ruff check .` 与 `format --check .` 均通过。
- 环境说明：本会话的受限环境中，直接运行 `uv run --locked` 无法读取用户缓存；设置可写的 `UV_CACHE_DIR` 后，`uv run --no-sync pytest -q` 通过。`uv sync --locked --offline` 在当前 macOS 沙箱中触发 uv 运行时错误；未据此推断正常用户环境也会失败。
- 修改后验证：`./init.sh` 成功，66 passed；Ruff 检查通过，18 个文件格式正确。`python3 -m json.tool feature_list.json`、`bash -n init.sh`、`git diff --check` 均通过。脚本未执行真实发布。
- 真实 Notion 读写：本轮未执行；首页和数据库的实时状态尚未核验。
- 下一步：按用户新需求选择单项工作；修改 Python 时先运行 `./init.sh`，完成后记录实际验证结果。
