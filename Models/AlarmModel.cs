namespace XiaoAiAlarm.Models;

public enum RepeatKind { Workdays, Daily, Weekdays }
public enum SoundKind { BilibiliLatest, BilibiliVideo, LocalFile }

public sealed class AlarmModel
{
    public string Id { get; set; } = Guid.NewGuid().ToString("N");
    public string Name { get; set; } = "新闹钟";
    public bool Enabled { get; set; } = true;
    public string Time { get; set; } = "07:30";
    public RepeatKind Repeat { get; set; } = RepeatKind.Workdays;
    public List<DayOfWeek> Weekdays { get; set; } = [DayOfWeek.Monday, DayOfWeek.Tuesday, DayOfWeek.Wednesday, DayOfWeek.Thursday, DayOfWeek.Friday];
    public SoundKind Sound { get; set; } = SoundKind.BilibiliLatest;
    public string SourceUrl { get; set; } = "";
    public string TitleFilter { get; set; } = ".*";
    public string LocalFile { get; set; } = "";
    public string PreparedFile { get; set; } = "";
    public string PreparedTitle { get; set; } = "";
    public DateTimeOffset? PreparedAt { get; set; }
    public int PrepareMinutes { get; set; } = 30;
    public int SnoozeMinutes { get; set; } = 10;
    public DateTimeOffset? LastFiredAt { get; set; }
    public string LastResult { get; set; } = "尚未运行";
}

public sealed class AppSettings
{
    public string XiaoMusicUrl { get; set; } = "http://127.0.0.1:58090";
    public string DeviceId { get; set; } = "";
    public string XiaoMusicLauncher { get; set; } = "";
    public string PythonExecutable { get; set; } = "";
    public string YtDlpExecutable { get; set; } = "";
    public string FfmpegExecutable { get; set; } = "";
    public string MediaDirectory { get; set; } = "";
}

public sealed class AppData
{
    public int Version { get; set; } = 1;
    public AppSettings Settings { get; set; } = new();
    public List<AlarmModel> Alarms { get; set; } = [];
}
