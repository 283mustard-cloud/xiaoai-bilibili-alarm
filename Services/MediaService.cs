using System.Text.Json;
using System.Text.RegularExpressions;
using XiaoAiAlarm.Models;

namespace XiaoAiAlarm.Services;

public static partial class MediaService
{
    public static async Task<(string File, string Title)> PrepareAsync(AlarmModel alarm, AppSettings settings)
    {
        if (alarm.Sound == SoundKind.LocalFile)
        {
            if (!File.Exists(alarm.LocalFile)) throw new FileNotFoundException("本地铃声文件不存在", alarm.LocalFile);
            return (alarm.LocalFile, Path.GetFileNameWithoutExtension(alarm.LocalFile));
        }
        var source = alarm.SourceUrl.Trim();
        if (string.IsNullOrEmpty(source)) throw new InvalidOperationException("没有设置 B 站来源");
        var command = ResolveYtDlp(settings);
        var prefix = command.ModuleMode ? new[] { "-m", "yt_dlp" } : Array.Empty<string>();
        string videoUrl = source, title = "B站视频", videoId = "video";
        if (alarm.Sound == SoundKind.BilibiliLatest)
        {
            var args = prefix.Concat(["--flat-playlist", "--playlist-end", "20", "--dump-single-json", source]);
            (int ExitCode, string Output, string Error) list = (-1, "", "");
            for (var attempt = 1; attempt <= 4; attempt++)
            {
                list = await ProcessService.RunHiddenAsync(command.File, args, timeout: TimeSpan.FromMinutes(3));
                if (list.ExitCode == 0) break;
                Log.Error($"读取 B 站主页失败，第 {attempt} 次：{list.Error}");
                if (attempt < 4) await Task.Delay(TimeSpan.FromSeconds(attempt * 6));
            }
            if (list.ExitCode != 0) throw new InvalidOperationException("读取 B 站主页失败：" + list.Error);
            using var doc = JsonDocument.Parse(list.Output);
            var pattern = new Regex(string.IsNullOrWhiteSpace(alarm.TitleFilter) ? ".*" : alarm.TitleFilter, RegexOptions.IgnoreCase);
            var entry = doc.RootElement.GetProperty("entries").EnumerateArray().FirstOrDefault(e => pattern.IsMatch(e.TryGetProperty("title", out var t) ? t.GetString() ?? "" : ""));
            if (entry.ValueKind == JsonValueKind.Undefined) throw new InvalidOperationException("最新 20 个投稿中没有符合标题筛选的内容");
            videoId = entry.TryGetProperty("id", out var id) ? id.GetString() ?? "video" : "video";
            title = entry.TryGetProperty("title", out var ti) ? ti.GetString() ?? title : title;
            videoUrl = entry.TryGetProperty("url", out var u) ? u.GetString() ?? "" : "";
            if (!videoUrl.StartsWith("http", StringComparison.OrdinalIgnoreCase)) videoUrl = "https://www.bilibili.com/video/" + videoId;
        }
        else
        {
            videoId = BvRegex().Match(source).Value;
            title = videoId;
        }
        var mediaRoot = string.IsNullOrWhiteSpace(settings.MediaDirectory) ? AppPaths.Media : settings.MediaDirectory;
        Directory.CreateDirectory(mediaRoot);
        var safeId = Regex.Replace(videoId, "[^a-zA-Z0-9_-]", "");
        var target = Path.Combine(mediaRoot, $"小爱闹钟-{alarm.Id[..8]}-{safeId}.mp3");
        if (File.Exists(target) && new FileInfo(target).Length > 100_000)
        {
            PruneOldFiles(mediaRoot, alarm.Id);
            return (target, title);
        }
        var outputTemplate = Path.Combine(mediaRoot, $".download-{alarm.Id}-%(id)s.%(ext)s");
        var downloadArgs = new List<string>(); downloadArgs.AddRange(prefix);
        downloadArgs.AddRange(["--no-playlist", "-x", "--audio-format", "mp3", "--audio-quality", "5"]);
        if (!string.IsNullOrWhiteSpace(settings.FfmpegExecutable) && File.Exists(settings.FfmpegExecutable)) { downloadArgs.Add("--ffmpeg-location"); downloadArgs.Add(settings.FfmpegExecutable); }
        downloadArgs.Add("-o"); downloadArgs.Add(outputTemplate); downloadArgs.Add(videoUrl);
        var result = await ProcessService.RunHiddenAsync(command.File, downloadArgs, timeout: TimeSpan.FromMinutes(30));
        if (result.ExitCode != 0) throw new InvalidOperationException("下载音频失败：" + result.Error);
        var downloaded = Directory.GetFiles(mediaRoot, $".download-{alarm.Id}-*.mp3").OrderByDescending(File.GetLastWriteTimeUtc).FirstOrDefault();
        if (downloaded is null) throw new InvalidOperationException("下载完成但没有生成 MP3 文件");
        File.Move(downloaded, target, true);
        PruneOldFiles(mediaRoot, alarm.Id);
        return (target, title);
    }

    private static void PruneOldFiles(string mediaRoot, string alarmId)
    {
        foreach (var file in Directory.GetFiles(mediaRoot, $"小爱闹钟-{alarmId[..8]}-*.mp3")
                     .OrderByDescending(File.GetLastWriteTimeUtc).Skip(3))
        {
            try { File.Delete(file); }
            catch (IOException ex) { Log.Error($"清理旧铃声失败：{file}", ex); }
            catch (UnauthorizedAccessException ex) { Log.Error($"清理旧铃声失败：{file}", ex); }
        }
    }

    private static (string File, bool ModuleMode) ResolveYtDlp(AppSettings settings)
    {
        if (File.Exists(settings.YtDlpExecutable)) return (settings.YtDlpExecutable, false);
        var bundled = Path.Combine(AppContext.BaseDirectory, "tools", "yt-dlp.exe");
        if (File.Exists(bundled)) return (bundled, false);
        if (File.Exists(settings.PythonExecutable)) return (settings.PythonExecutable, true);
        return ("python.exe", true);
    }

    [GeneratedRegex(@"BV[a-zA-Z0-9]+")]
    private static partial Regex BvRegex();
}
