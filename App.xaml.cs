using System.Windows;
using XiaoAiAlarm.Services;

namespace XiaoAiAlarm;

public partial class App : Application
{
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        AppPaths.Ensure();
        Log.Initialize();
        if (e.Args.Length >= 2 && (e.Args[0] == "--prepare" || e.Args[0] == "--prepare-now" || e.Args[0] == "--fire" || e.Args[0] == "--fire-now" || e.Args[0] == "--preview-now"))
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            var exit = await AlarmRunner.RunAsync(e.Args[0], e.Args[1]);
            if (exit == 0 && e.Args[0] == "--fire")
            {
                var data = await DataStore.LoadAsync();
                var alarm = data.Alarms.FirstOrDefault(a => a.Id == e.Args[1]);
                if (alarm?.LastFiredAt is not null && DateTimeOffset.Now - alarm.LastFiredAt < TimeSpan.FromMinutes(2) && alarm.LastResult == "播放成功")
                {
                    var ring = new RingWindow(alarm, data.Settings);
                    ring.ShowDialog();
                }
            }
            Shutdown(exit);
            return;
        }
        if (e.Args.Length == 1 && e.Args[0] == "--sync")
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            try
            {
                var data = await DataStore.LoadAsync();
                foreach (var alarm in data.Alarms) await TaskSchedulerService.SyncAsync(alarm);
                Shutdown(0);
            }
            catch (Exception ex) { Log.Error("同步 Windows 唤醒任务失败", ex); Shutdown(1); }
            return;
        }
        var window = new MainWindow();
        MainWindow = window;
        window.Show();
    }
}
