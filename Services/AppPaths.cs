namespace XiaoAiAlarm.Services;

public static class AppPaths
{
    // Keep runtime data beside the installed app so desktop, packaged launchers and
    // Task Scheduler always resolve the same configuration directory.
    public static string Root => Path.Combine(AppContext.BaseDirectory, "data");
    public static string DataFile => Path.Combine(Root, "alarms.json");
    public static string Media => Path.Combine(Root, "media");
    public static string Logs => Path.Combine(Root, "logs");
    public static string LogFile => Path.Combine(Logs, "app.log");
    public static string Executable => Environment.ProcessPath ?? Path.Combine(AppContext.BaseDirectory, "XiaoAiAlarm.exe");
    public static void Ensure()
    {
        Directory.CreateDirectory(Root); Directory.CreateDirectory(Media); Directory.CreateDirectory(Logs);
        if (File.Exists(DataFile)) return;
        var user = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var candidates = new[]
        {
            Path.Combine(user, "AppData", "Local", "XiaoAiAlarm", "alarms.json"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "XiaoAiAlarm", "alarms.json")
        }.Concat(Directory.Exists(Path.Combine(user, "AppData", "Local", "Packages"))
            ? Directory.GetDirectories(Path.Combine(user, "AppData", "Local", "Packages"), "OpenAI.Codex_*")
                .Select(p => Path.Combine(p, "LocalCache", "Local", "XiaoAiAlarm", "alarms.json"))
            : []);
        var newest = candidates.Where(File.Exists).Distinct(StringComparer.OrdinalIgnoreCase).OrderByDescending(File.GetLastWriteTimeUtc).FirstOrDefault();
        if (newest is not null) File.Copy(newest, DataFile, false);
    }
}
