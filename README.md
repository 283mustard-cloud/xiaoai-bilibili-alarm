# 小爱闹钟

面向 Windows 11 的原生桌面闹钟，将 B 站 UP 主最新投稿、指定视频或本地音频推送到小爱音箱播放。

## 功能

- 一级页面管理多个闹钟和独立开关
- 二级页面设置名称、时间、重复方式、铃声和贪睡时间
- 支持中国法定工作日、每天和指定星期
- 每个闹钟注册独立的 Windows 唤醒任务
- 到点播放和提前更新均由隐藏的同一个 EXE 执行，不弹控制台
- 支持 B 站 UP 主最新投稿、指定视频和本地音频
- 更新失败时保留上一次可用铃声，避免下载故障导致闹钟无声
- XiaoMusic 不在线时自动以隐藏方式启动，并重试小爱播放推送
- 电脑错过闹钟 15 分钟以上时不再突然补播

## 架构

应用使用 .NET 8 WPF，不依赖常驻的 Python 调度器。

每个启用的闹钟对应两个 Windows 计划任务：

1. `--prepare <id>`：在播放前准备网络音频。
2. `--fire <id>`：在设定时间唤醒电脑并推送到小爱音箱。

任务包含 `WakeToRun=true`、`StartWhenAvailable=true` 和 `Hidden=true`。主窗口关闭后任务仍能运行。

XiaoMusic 仍负责与小爱音箱通信。B 站内容由官方发布的 `yt-dlp.exe` 获取。

## 构建

安装 [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)，然后运行：

```powershell
.\build.ps1
```

输出位于 `publish/`。首次打开后，在“设置”中填写：

- XiaoMusic 地址
- 小爱音箱设备 ID
- XiaoMusic 启动脚本与 Python 路径
- XiaoMusic 音乐目录
- `yt-dlp.exe` 和 `ffmpeg.exe` 路径

配置保存在 `%LOCALAPPDATA%\XiaoAiAlarm\alarms.json`，不会写入程序目录。

## 测试

```powershell
dotnet run --project Tests\XiaoAiAlarm.Tests.csproj -c Release
```

测试覆盖法定节假日、调休工作日、指定星期、停用闹钟和凌晨跨日准备。

## 当前限制

- 法定工作日数据需要随国务院年度放假安排更新；仓库当前内置 2026 年数据，其他年份退化为周一至周五。
- XiaoMusic 的账号与设备兼容范围由 XiaoMusic 项目决定。
- 电脑必须支持并启用 Windows 唤醒定时器；完全关机时无法自动开机。

## 许可证

[MIT](LICENSE)
