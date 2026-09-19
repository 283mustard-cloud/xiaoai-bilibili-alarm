using System.Diagnostics;

namespace XiaoAiAlarm.Services;

public static class ProcessService
{
    public static async Task<(int ExitCode, string Output, string Error)> RunHiddenAsync(string file, IEnumerable<string> args, string? working = null, TimeSpan? timeout = null)
    {
        var psi = new ProcessStartInfo(file) { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, RedirectStandardError = true, RedirectStandardOutput = true, WorkingDirectory = working ?? AppContext.BaseDirectory };
        foreach (var arg in args) psi.ArgumentList.Add(arg);
        using var process = Process.Start(psi) ?? throw new InvalidOperationException($"无法启动 {file}");
        var outputTask = process.StandardOutput.ReadToEndAsync();
        var errorTask = process.StandardError.ReadToEndAsync();
        using var cts = new CancellationTokenSource(timeout ?? TimeSpan.FromMinutes(30));
        try { await process.WaitForExitAsync(cts.Token); }
        catch { try { process.Kill(true); } catch { } throw new TimeoutException($"{Path.GetFileName(file)} 运行超时"); }
        return (process.ExitCode, await outputTask, await errorTask);
    }

    public static void StartHidden(string file, IEnumerable<string> args, string working)
    {
        var psi = new ProcessStartInfo(file) { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, WorkingDirectory = working };
        foreach (var arg in args) psi.ArgumentList.Add(arg);
        Process.Start(psi);
    }
}
