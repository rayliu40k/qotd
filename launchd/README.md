# 每日金句 LaunchAgent

配置源文件是 [com.rayliu.qotd.daily.plist](com.rayliu.qotd.daily.plist)，安装位置是 `~/Library/LaunchAgents/com.rayliu.qotd.daily.plist`。任务按 Mac 系统时区每天 11:00 运行；当前 Mac 设置为北京时间。

| 操作 | 命令 | 说明 |
| --- | --- | --- |
| 查看状态 | `launchctl print gui/$(id -u)/com.rayliu.qotd.daily` | 能显示任务信息即已加载；`runs` 是执行次数，`last exit code = 0` 表示上次正常退出。 |
| 加载 | `launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.rayliu.qotd.daily.plist"` | 先查看状态，仅在任务尚未加载时执行；加载不会立即发布。 |
| 单次触发 | `launchctl kickstart gui/$(id -u)/com.rayliu.qotd.daily` | 立即运行一次；会重新抽句并覆盖当天展示。任务须先加载。 |
| 卸载 | `launchctl bootout gui/$(id -u)/com.rayliu.qotd.daily` | 停止当前调度，保留配置文件。下次登录时系统可能重新加载。 |

要彻底删除定时任务，先卸载，再删除已安装的 plist：

```sh
rm "$HOME/Library/LaunchAgents/com.rayliu.qotd.daily.plist"
```

项目内的配置源文件和 Python 程序不会受影响。定时任务修改配置后，需要重新安装 plist 并重新加载。`state = not running` 通常正常：程序发布完成后会退出，等待下一次触发。程序日志位于 [`../logs/`](../logs/)。
