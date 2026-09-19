namespace XiaoAiAlarm.Services;

public static class Log
{
    private static readonly object Gate = new();
    public static void Initialize() => AppPaths.Ensure();
    public static void Info(string message) => Write("INFO", message);
    public static void Error(string message, Exception? ex = null) => Write("ERROR", message + (ex is null ? "" : $" | {ex}"));
    private static void Write(string level, string message)
    {
        lock (Gate)
        {
            try
            {
                if (File.Exists(AppPaths.LogFile) && new FileInfo(AppPaths.LogFile).Length > 2_000_000)
                    File.Move(AppPaths.LogFile, AppPaths.LogFile + ".1", true);
                File.AppendAllText(AppPaths.LogFile, $"{DateTimeOffset.Now:O} {level} {message}{Environment.NewLine}");
            }
            catch { }
        }
    }
}
