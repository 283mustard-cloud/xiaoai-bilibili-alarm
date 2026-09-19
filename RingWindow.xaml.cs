using System.Windows;
using XiaoAiAlarm.Models;
using XiaoAiAlarm.Services;

namespace XiaoAiAlarm;

public partial class RingWindow : Window
{
    private readonly AlarmModel _alarm;
    private readonly AppSettings _settings;
    public RingWindow(AlarmModel alarm, AppSettings settings)
    {
        InitializeComponent(); _alarm = alarm; _settings = settings;
        AlarmTime.Text = alarm.Time; AlarmName.Text = alarm.Name; SnoozeButton.Content = $"贪睡 {alarm.SnoozeMinutes} 分钟";
        Loaded += (_, _) => Activate();
    }
    private async void Stop_Click(object sender, RoutedEventArgs e) { try { await XiaoMusicService.StopAsync(_settings); } catch { } Close(); }
    private async void Snooze_Click(object sender, RoutedEventArgs e)
    {
        try { await XiaoMusicService.StopAsync(_settings); await TaskSchedulerService.ScheduleSnoozeAsync(_alarm); Close(); }
        catch (Exception ex) { MessageBox.Show(ex.Message, "无法设置贪睡", MessageBoxButton.OK, MessageBoxImage.Error); }
    }
}
