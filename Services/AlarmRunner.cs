using XiaoAiAlarm.Models;

namespace XiaoAiAlarm.Services;

public static class AlarmRunner
{
    public static async Task<int> RunAsync(string mode, string id)
    {
        try
        {
            var data = await DataStore.LoadAsync();
            var alarm = data.Alarms.FirstOrDefault(a => a.Id == id);
            if (alarm is null || !alarm.Enabled) return 0;
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
                if (!CalendarRules.ShouldRing(alarm, targetDate)) return 0;
                var targetAlarm = targetDate.ToDateTime(alarmTime);
                if (now.LocalDateTime > targetAlarm.AddMinutes(15)) return 0;
                await PrepareAsync(alarm, data.Settings);
            }
            else if (mode == "--fire-now")
            {
                await FireAsync(alarm, data.Settings);
            }
            else
            {
                if (!CalendarRules.ShouldRing(alarm, targetDate)) return 0;
                var scheduled = targetDate.ToDateTime(TimeOnly.Parse(alarm.Time));
                if (now.LocalDateTime > scheduled.AddMinutes(15))
                {
                    await DataStore.UpdateAlarmAsync(alarm.Id, a => a.LastResult = "电脑错过闹钟超过 15 分钟，未补播");
                    return 0;
                }
                if (alarm.LastFiredAt?.Date == now.Date && alarm.LastResult == "播放成功") return 0;
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
        var file = alarm.Sound == SoundKind.LocalFile ? alarm.LocalFile : alarm.PreparedFile;
        if (!File.Exists(file))
        {
            await PrepareAsync(alarm, settings);
            var current = await DataStore.LoadAsync();
            alarm = current.Alarms.First(a => a.Id == alarm.Id);
            file = alarm.Sound == SoundKind.LocalFile ? alarm.LocalFile : alarm.PreparedFile;
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
}
