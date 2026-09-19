using System.Net.Http;
using System.Net.Http.Json;
using XiaoAiAlarm.Models;

namespace XiaoAiAlarm.Services;

public static class XiaoMusicService
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(20) };

    public static async Task EnsureRunningAsync(AppSettings settings)
    {
        if (await IsRunningAsync(settings.XiaoMusicUrl)) return;
        if (!string.IsNullOrWhiteSpace(settings.XiaoMusicLauncher) && File.Exists(settings.XiaoMusicLauncher))
        {
            var python = File.Exists(settings.PythonExecutable) ? settings.PythonExecutable : "python.exe";
            ProcessService.StartHidden(python, [settings.XiaoMusicLauncher], Path.GetDirectoryName(settings.XiaoMusicLauncher)!);
            for (var i = 0; i < 20; i++) { await Task.Delay(1000); if (await IsRunningAsync(settings.XiaoMusicUrl)) return; }
        }
        throw new InvalidOperationException("XiaoMusic 未运行，无法连接小爱音箱");
    }

    public static async Task RefreshAsync(AppSettings settings)
    {
        await EnsureRunningAsync(settings);
        var response = await Http.PostAsJsonAsync(settings.XiaoMusicUrl.TrimEnd('/') + "/cmd", new { did = settings.DeviceId, cmd = "刷新列表" });
        response.EnsureSuccessStatusCode();
    }

    public static async Task PlayWithRetryAsync(AppSettings settings, string musicName, int volume)
    {
        Exception? last = null;
        for (var attempt = 1; attempt <= 4; attempt++)
        {
            try
            {
                await EnsureRunningAsync(settings);
                var volumeResponse = await Http.PostAsJsonAsync(settings.XiaoMusicUrl.TrimEnd('/') + "/setvolume", new { did = settings.DeviceId, volume = Math.Clamp(volume, 1, 100) });
                volumeResponse.EnsureSuccessStatusCode();
                var volumeText = await volumeResponse.Content.ReadAsStringAsync();
                if (!volumeText.Contains("OK", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("设置音箱音量失败：" + volumeText);
                await Task.Delay(800);
                var response = await Http.PostAsJsonAsync(settings.XiaoMusicUrl.TrimEnd('/') + "/playmusic", new { did = settings.DeviceId, musicname = musicName });
                response.EnsureSuccessStatusCode();
                var text = await response.Content.ReadAsStringAsync();
                if (!text.Contains("OK", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException(text);
                for (var check = 0; check < 4; check++)
                {
                    await Task.Delay(1200);
                    var status = await Http.GetFromJsonAsync<PlayerStatus>(settings.XiaoMusicUrl.TrimEnd('/') + "/getplayerstatus?did=" + Uri.EscapeDataString(settings.DeviceId));
                    if (status?.status == 1) return;
                }
                throw new InvalidOperationException("音箱已接收指令，但没有进入播放状态");
            }
            catch (Exception ex) { last = ex; Log.Error($"推送播放失败，第 {attempt} 次", ex); if (attempt < 4) await Task.Delay(TimeSpan.FromSeconds(8)); }
        }
        throw new InvalidOperationException("多次尝试后仍无法推送到小爱音箱", last);
    }

    private sealed class PlayerStatus
    {
        public int status { get; set; }
    }

    public static async Task StopAsync(AppSettings settings)
    {
        await EnsureRunningAsync(settings);
        var response = await Http.PostAsJsonAsync(settings.XiaoMusicUrl.TrimEnd('/') + "/device/stop", new { did = settings.DeviceId });
        response.EnsureSuccessStatusCode();
    }

    private static async Task<bool> IsRunningAsync(string baseUrl)
    {
        try { using var cts = new CancellationTokenSource(1500); var r = await Http.GetAsync(baseUrl.TrimEnd('/') + "/", cts.Token); return r.IsSuccessStatusCode; }
        catch { return false; }
    }
}
