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

它会注册一个登录时自动启动的 Windows 计划任务。网页中的调度设置会立即生效。

如需让音箱访问电脑上的 58090 端口，以管理员身份运行：

```powershell
.\allow_lan.ps1
```

## 配置和隐私

`config.json`、`xiaomusic-config.json`、`conf/`、音频、日志及缓存均已加入 `.gitignore`。请勿提交小米账号、密码、Cookie 或设备 ID。

控制台只监听本机回环地址。XiaoMusic 的媒体服务需对局域网开放，防火墙规则仅允许本地子网访问。

## 已知限制

- B 站页面或接口变化时，可能需要更新 `yt-dlp`。
- 中国法定工作日依赖 `chinesecalendar` 的节假日数据，新年度开始前应更新依赖。
- 电脑休眠、断网或小米服务不可用时无法按时播放。
- 是否兼容取决于音箱型号和 XiaoMusic 支持情况。

## 许可证

[MIT](LICENSE)
