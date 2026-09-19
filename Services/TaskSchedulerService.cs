using System.Diagnostics;
using System.Security;
using System.Text;
using XiaoAiAlarm.Models;

namespace XiaoAiAlarm.Services;

public static class TaskSchedulerService
{
    public static async Task SyncAsync(AlarmModel alarm)
    {
        await DeleteAsync(alarm.Id);
        if (!alarm.Enabled) return;
        var time = TimeOnly.Parse(alarm.Time);
        var prepare = time.AddMinutes(-Math.Clamp(alarm.PrepareMinutes, 0, 720));
        await CreateAsync(alarm, "Prepare", prepare, "--prepare");
        await CreateAsync(alarm, "Fire", time, "--fire");
    }

    public static async Task DeleteAsync(string id)
    {
        await RunSchtasksAsync(["/Delete", "/TN", $"XiaoAiAlarm-{id}-Prepare", "/F"], ignoreFailure: true);
        await RunSchtasksAsync(["/Delete", "/TN", $"XiaoAiAlarm-{id}-Fire", "/F"], ignoreFailure: true);
    }

    private static async Task CreateAsync(AlarmModel alarm, string suffix, TimeOnly time, string mode)
    {
        var name = $"XiaoAiAlarm-{alarm.Id}-{suffix}";
        var user = $"{Environment.UserDomainName}\\{Environment.UserName}";
        var start = DateTime.Today.AddDays(1).Add(time.ToTimeSpan()).ToString("s");
        var exe = SecurityElement.Escape(AppPaths.Executable);
        var args = SecurityElement.Escape($"{mode} {alarm.Id}");
        var author = SecurityElement.Escape(user);
        var xml = $"""
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>{author}</Author><Description>小爱闹钟：{SecurityElement.Escape(alarm.Name)} {suffix}</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>{start}</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{author}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>true</Hidden><WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT45M</ExecutionTimeLimit><Priority>4</Priority></Settings>
  <Actions Context="Author"><Exec><Command>{exe}</Command><Arguments>{args}</Arguments><WorkingDirectory>{SecurityElement.Escape(AppContext.BaseDirectory.TrimEnd('\\'))}</WorkingDirectory></Exec></Actions>
</Task>
""";
        var file = Path.Combine(Path.GetTempPath(), $"{name}.xml");
        await File.WriteAllTextAsync(file, xml, Encoding.Unicode);
        try { await RunSchtasksAsync(["/Create", "/TN", name, "/XML", file, "/F"]); }
        finally { try { File.Delete(file); } catch { } }
    }

    private static async Task RunSchtasksAsync(IEnumerable<string> args, bool ignoreFailure = false)
    {
        var psi = new ProcessStartInfo("schtasks.exe") { UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, RedirectStandardError = true, RedirectStandardOutput = true };
        foreach (var arg in args) psi.ArgumentList.Add(arg);
        using var process = Process.Start(psi) ?? throw new InvalidOperationException("无法启动 Windows 任务计划程序");
        var stdout = await process.StandardOutput.ReadToEndAsync();
        var stderr = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        if (process.ExitCode != 0 && !ignoreFailure) throw new InvalidOperationException($"创建唤醒任务失败：{stderr}{stdout}".Trim());
    }
}
