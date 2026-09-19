using XiaoAiAlarm.Models;

namespace XiaoAiAlarm.Services;

public static class AlarmRunner
{
    public static async Task<int> RunAsync(string mode, string id)
    {
        try
        {
            Log.Info($"后台入口启动：mode={mode}, id={id}, pid={Environment.ProcessId}, session={Environment.UserInteractive}");
            var data = await DataStore.LoadAsync();
            var alarm = data.Alarms.FirstOrDefault(a => a.Id == id);
            if (alarm is null) { Log.Error($"后台任务跳过：找不到闹钟 {id}"); return 2; }
            if (!alarm.Enabled) { Log.Info($"后台任务跳过：{alarm.Name} 已关闭"); return 0; }
            var now = DateTimeOffset.Now;
            var targetDate = DateOnly.FromDateTime(now.DateTime);
            if (mode == "--prepare-now")
            {
                await PrepareAsync(alarm, data.Settings);
            }
            else if (mode == "--prepare")
            {
                var alarmTime = TimeOnly.Parse(alarm.Time);
                if (alarmTime.AddMinutes(-alarm.PrepareMinutes) > alarmTime) targetDate = targetDate.AddDays(1);
                if (!CalendarRules.ShouldRing(alarm, targetDate)) { Log.Info($"准备任务跳过：{targetDate} 不符合重复规则"); return 0; }
                var targetAlarm = targetDate.ToDateTime(alarmTime);
                if (now.LocalDateTime > targetAlarm.AddMinutes(15)) return 0;
                await PrepareAsync(alarm, data.Settings);
            }
            else if (mode == "--fire-now")
            {
                await FireAsync(alarm, data.Settings);
            }
            else if (mode == "--preview-now")
            {
                await PreviewAsync(alarm, data.Settings);
            }
            else
            {
                if (!CalendarRules.ShouldRing(alarm, targetDate)) { Log.Info($"播放任务跳过：{targetDate} 不符合重复规则 repeat={alarm.Repeat}"); return 0; }
                var scheduled = targetDate.ToDateTime(TimeOnly.Parse(alarm.Time));
                if (now.LocalDateTime > scheduled.AddMinutes(15))
                {
                    await DataStore.UpdateAlarmAsync(alarm.Id, a => a.LastResult = "电脑错过闹钟超过 15 分钟，未补播");
                    return 0;
                }
                if (alarm.LastFiredAt?.Date == now.Date && alarm.LastResult == "播放成功") { Log.Info("播放任务跳过：今天已经播放成功"); return 0; }
                await FireAsync(alarm, data.Settings);
            }
            return 0;
        }
        catch (Exception ex) { Log.Error($"后台任务 {mode} {id} 失败", ex); return 1; }
    }

    public static async Task PrepareAsync(AlarmModel alarm, AppSettings settings)
    {
        try
        {
            var prepared = await MediaService.PrepareAsync(alarm, settings);
            await XiaoMusicService.RefreshAsync(settings);
            await DataStore.UpdateAlarmAsync(alarm.Id, a => { a.PreparedFile = prepared.File; a.PreparedTitle = prepared.Title; a.PreparedAt = DateTimeOffset.Now; a.LastResult = "内容更新成功"; });
            Log.Info($"{alarm.Name} 内容已更新：{prepared.Title}");
        }
        catch (Exception ex)
        {
            await DataStore.UpdateAlarmAsync(alarm.Id, a => a.LastResult = "内容更新失败，保留上次铃声");
            Log.Error($"{alarm.Name} 内容更新失败，保留原文件", ex);
            throw;
        }
    }

    public static async Task FireAsync(AlarmModel alarm, AppSettings settings)
    {
        var file = ResolvePlayableFile(alarm, settings);
        if (!File.Exists(file))
        {
            await PrepareAsync(alarm, settings);
            var current = await DataStore.LoadAsync();
            alarm = current.Alarms.First(a => a.Id == alarm.Id);
            file = ResolvePlayableFile(alarm, settings);
        }
        if (!File.Exists(file)) throw new FileNotFoundException("没有可播放的铃声文件");
        try
        {
            await XiaoMusicService.PlayWithRetryAsync(settings, Path.GetFileNameWithoutExtension(file), alarm.Volume);
            await DataStore.UpdateAlarmAsync(alarm.Id, a => { a.LastFiredAt = DateTimeOffset.Now; a.LastResult = "播放成功"; });
            Log.Info($"{alarm.Name} 已推送到小爱音箱");
        }
        catch
        {
            await DataStore.UpdateAlarmAsync(alarm.Id, a => { a.LastFiredAt = DateTimeOffset.Now; a.LastResult = "播放失败，已重试 4 次"; });
            throw;
        }
    }

    public static async Task PreviewAsync(AlarmModel alarm, AppSettings settings)
    {
        var file = ResolvePlayableFile(alarm, settings);
        if (!File.Exists(file))
            throw new InvalidOperationException("当前没有可试听的缓存。请先点击“立即更新”；试听不会临时访问 B 站，以免 412 导致失败。");
        if (!string.Equals(file, alarm.PreparedFile, StringComparison.OrdinalIgnoreCase) && alarm.Sound != SoundKind.LocalFile)
            await DataStore.UpdateAlarmAsync(alarm.Id, a => a.PreparedFile = file);
        await XiaoMusicService.PlayWithRetryAsync(settings, Path.GetFileNameWithoutExtension(file), alarm.Volume);
        await DataStore.UpdateAlarmAsync(alarm.Id, a => { a.LastFiredAt = DateTimeOffset.Now; a.LastResult = "试听成功"; });
        Log.Info($"{alarm.Name} 试听成功：{file}");
    }

    private static string ResolvePlayableFile(AlarmModel alarm, AppSettings settings)
    {
        if (alarm.Sound == SoundKind.LocalFile) return alarm.LocalFile;
        if (File.Exists(alarm.PreparedFile)) return alarm.PreparedFile;
        var mediaRoot = string.IsNullOrWhiteSpace(settings.MediaDirectory) ? AppPaths.Media : settings.MediaDirectory;
        if (!Directory.Exists(mediaRoot)) return alarm.PreparedFile;
        var oldName = Path.GetFileName(alarm.PreparedFile);
        var marker = oldName.LastIndexOf("-BV", StringComparison.OrdinalIgnoreCase);
        if (marker >= 0)
        {
            var suffix = oldName[(marker + 1)..];
            var sameVideo = Directory.GetFiles(mediaRoot, $"*-{suffix}").OrderByDescending(File.GetLastWriteTimeUtc).FirstOrDefault();
            if (sameVideo is not null) return sameVideo;
        }
        return Directory.GetFiles(mediaRoot, $"小爱闹钟-{alarm.Id[..8]}-*.mp3").OrderByDescending(File.GetLastWriteTimeUtc).FirstOrDefault() ?? alarm.PreparedFile;
    }
}
