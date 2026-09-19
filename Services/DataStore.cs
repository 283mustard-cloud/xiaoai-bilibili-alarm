using System.Text.Json;
using XiaoAiAlarm.Models;

namespace XiaoAiAlarm.Services;

public static class DataStore
{
    private static readonly SemaphoreSlim Gate = new(1, 1);
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true, PropertyNameCaseInsensitive = true };

    public static async Task<AppData> LoadAsync()
    {
        await Gate.WaitAsync();
        try
        {
            if (!File.Exists(AppPaths.DataFile)) return await ImportLegacyAsync();
            return JsonSerializer.Deserialize<AppData>(await File.ReadAllTextAsync(AppPaths.DataFile), Json) ?? new AppData();
        }
        catch (Exception ex) { Log.Error("读取配置失败", ex); return new AppData(); }
        finally { Gate.Release(); }
    }

    public static async Task SaveAsync(AppData data)
    {
        await Gate.WaitAsync();
        try
        {
            var temp = AppPaths.DataFile + ".tmp";
            await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(data, Json));
            File.Move(temp, AppPaths.DataFile, true);
        }
        finally { Gate.Release(); }
    }

    private static async Task<AppData> ImportLegacyAsync()
    {
        var data = new AppData();
        var legacy = Path.Combine(AppContext.BaseDirectory, "legacy-config.json");
        if (!File.Exists(legacy)) return data;
        try
        {
            using var doc = JsonDocument.Parse(await File.ReadAllTextAsync(legacy));
            var r = doc.RootElement;
            string Get(string key) => r.TryGetProperty(key, out var v) ? v.GetString() ?? "" : "";
            bool GetBool(string key, bool fallback) => r.TryGetProperty(key, out var v) ? v.GetBoolean() : fallback;
            data.Settings.XiaoMusicUrl = Get("xiaomusic_url");
            data.Settings.DeviceId = Get("device_id");
            data.Settings.XiaoMusicLauncher = Get("xiaomusic_launcher");
            data.Settings.PythonExecutable = Get("python_executable");
            data.Settings.MediaDirectory = Get("media_directory");
            data.Settings.YtDlpExecutable = Get("yt_dlp_executable");
            data.Settings.FfmpegExecutable = Get("ffmpeg_executable");
            data.Alarms.Add(new AlarmModel { Name = "CS 万事屋", Enabled = GetBool("enabled", true), Time = Get("play_time"), SourceUrl = Get("source_url"), TitleFilter = Get("title_pattern") });
            await SaveUnlockedAsync(data);
        }
        catch (Exception ex) { Log.Error("导入旧配置失败", ex); }
        return data;
    }

    public static async Task UpdateAlarmAsync(string id, Action<AlarmModel> update)
    {
        await Gate.WaitAsync();
        try
        {
            var data = File.Exists(AppPaths.DataFile)
                ? JsonSerializer.Deserialize<AppData>(await File.ReadAllTextAsync(AppPaths.DataFile), Json) ?? new AppData()
                : new AppData();
            var alarm = data.Alarms.FirstOrDefault(a => a.Id == id);
            if (alarm is null) return;
            update(alarm);
            await SaveUnlockedAsync(data);
        }
        finally { Gate.Release(); }
    }

    private static async Task SaveUnlockedAsync(AppData data)
    {
        var temp = AppPaths.DataFile + ".tmp";
        await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(data, Json));
        File.Move(temp, AppPaths.DataFile, true);
    }
}
