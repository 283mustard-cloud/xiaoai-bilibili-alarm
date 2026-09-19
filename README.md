# 小爱 B 站闹钟

用一台常开的 Windows 电脑，让小爱音箱在指定日期和时间播放 B 站账号的最新投稿、指定视频或本地音频。无需把音箱切换成蓝牙音箱。

项目提供本地网页控制台，可调整：

- 播放时间
- 中国法定工作日、每天、指定星期或指定日期
- 额外播放和跳过日期
- B 站账号最新投稿、指定视频或本地音频
- 立即更新、试听和停止播放

## 工作方式

1. `yt-dlp` 获取 B 站视频并转成 MP3。
2. XiaoMusic 把电脑上的音频地址发送给小爱音箱播放。
3. 本地控制台在 `http://127.0.0.1:58100` 运行，并负责调度。
4. 调度规则集中在 `schedule_rules.py`，`alarm_app.decide()` 是纯函数形式的调度策略，可离线回归测试。

调度细节：

- 网络内容在播放前 30 分钟开始准备；准备失败每 10 分钟重试一次，直到播放时间。
- 到点播放；若音箱或小米服务暂时不可用，1 分钟内自动重试。
- **错过也能补播**：机器晚唤醒或程序晚启动时，播放时间后 15 分钟内仍会补播（日志会记录迟到分钟数）。
- 同一期内容只准备一次、同一次闹钟只播放一次；失败会记录到 `logs/alarm.log`。
- 每个 BV 单独存一个 MP3，只保留最近 3 期，自动清理更早的文件。

## 环境要求

- Windows 10/11
- Python 3.11 或更新版本
- 常开且与音箱位于同一局域网的电脑
- 已加入米家的兼容小爱音箱

## 安装

```powershell
git clone https://github.com/283mustard-cloud/xiaoai-bilibili-alarm.git
cd xiaoai-bilibili-alarm
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
Copy-Item xiaomusic-config.example.json xiaomusic-config.json
```

编辑 `xiaomusic-config.json`，填写小米账号、本机音乐目录和下载目录。首次启动 XiaoMusic：

```powershell
python launch_xiaomusic.py
```

打开 `http://127.0.0.1:58090/static/default/setting.html`，完成登录并选中音箱。然后启动闹钟控制台：

```powershell
python alarm_app.py
```

打开 `http://127.0.0.1:58100`，填写音箱设备 ID 和播放来源，保存后先执行“现在更新内容”和“试听当前内容”。

确认播放正常后，以管理员身份运行：

```powershell
.\migrate_to_app.ps1
```

它会注册一个登录时自动启动的 Windows 计划任务（优先使用 `.venv` 里的解释器）。网页中的调度设置会立即生效。

注意这个任务**只有登录触发器，没有定时触发器**，因为播放时间保存在 `alarm_app.py` 的配置里而不是计划任务里。因此：

- 电脑需要保持登录、保持运行；
- **电脑如果在播放时间前进入睡眠，闹钟不会唤醒它**（`WakeToRun` 对没有定时触发器的任务没有意义，所以脚本已不再设置它）；
- 需要唤醒的话，请另建一个带「每日触发 + 唤醒计算机」的独立任务来唤醒机器，由本程序负责播放。

如需让音箱访问电脑上的 58090 端口，以管理员身份运行：

```powershell
.\allow_lan.ps1
```

### 端口看护（可选）

应用任务本身无法从“被外部杀掉”中恢复：它的重启设置只对任务计划程序观察到的失败生效。
如果需要电脑长时间无人值守，以管理员身份运行：

```powershell
.\register_watchdog.ps1
```

它注册一个每 5 分钟执行一次的 `XiaoAiBiliAlarm-Watchdog` 任务，检查 58100 是否在监听；
若没有监听就重启 `XiaoAiBiliAlarm-App`。平时不写日志（每天一条心跳），
只有异常和恢复动作会记到 `logs/watchdog.log`。

看护任务同样以当前用户身份运行，因此**只在用户已登录时有效**；鼠标/键盘无人操作不受影响。

## 测试

调度逻辑可以完全离线验证，不需要网络、音箱或真实配置：

```powershell
python tests\test_alarm_schedule.py
```

覆盖凌晨闹钟的跨日准备窗口、晚唤醒补播、准备与播放重试、调休工作日、
法定假日、日历数据跨年回退、以及“任务结果不被调度器覆盖”等情况。

控制台默认监听 58100。想在不打扰已运行实例（也不会让音箱出声）的情况下
单独起一个实例验证界面，可以换端口：

```powershell
$env:XIAOAI_ALARM_PORT=58101; python alarm_app.py
```

## 配置说明

`config.json` 里的可选项：

- `play_time`：播放时间，北京时间 `HH:MM`。
- `schedule_mode`：`workdays` / `daily` / `weekdays` / `dates`。
- `include_dates` / `exclude_dates`：额外播放和跳过日期，跳过优先。
- `prepare_lead_minutes`：提前准备内容的分钟数，默认 30。
- `source_type`：`latest` / `video` / `local`。

## 配置和隐私

`config.json`、`xiaomusic-config.json`、`conf/`、音频、日志及缓存均已加入 `.gitignore`。请勿提交小米账号、密码、Cookie 或设备 ID。

控制台只监听本机回环地址。XiaoMusic 的媒体服务需对局域网开放，防火墙规则仅允许本地子网访问。

## 已知限制

- B 站页面或接口变化时，可能需要更新 `yt-dlp`。
- 中国法定工作日依赖 `chinesecalendar` 的节假日数据。数据只覆盖到已发布年份（例如 2027 年安排公布前只到 2026 年）；超出范围时会记录警告并退化为“周一至周五”，不再中断调度，但调休判断会不准确，应及时升级依赖。
- 电脑休眠、断网或小米服务不可用时无法按时播放；15 分钟补偿窗口之外不会再补播。
- 计划任务随用户登录启动且没有定时触发器，电脑需保持登录并且不能睡眠到错过播放时间；睡眠唤醒需要另建带唤醒设置的定时任务。
- 是否兼容取决于音箱型号和 XiaoMusic 支持情况。

## 许可证

[MIT](LICENSE)
