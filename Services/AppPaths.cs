namespace XiaoAiAlarm.Services;

public static class AppPaths
{
    public static string Root => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "XiaoAiAlarm");
    public static string DataFile => Path.Combine(Root, "alarms.json");
    public static string Media => Path.Combine(Root, "media");
    public static string Logs => Path.Combine(Root, "logs");
    public static string LogFile => Path.Combine(Logs, "app.log");
    public static string Executable => Environment.ProcessPath ?? Path.Combine(AppContext.BaseDirectory, "XiaoAiAlarm.exe");
    public static void Ensure() { Directory.CreateDirectory(Root); Directory.CreateDirectory(Media); Directory.CreateDirectory(Logs); }
}
