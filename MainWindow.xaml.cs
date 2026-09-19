using Microsoft.Win32;
using System.Globalization;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using XiaoAiAlarm.Models;
using XiaoAiAlarm.Services;

namespace XiaoAiAlarm;

public partial class MainWindow : Window
{
    private AppData _data = new();
    private string? _editingId;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += async (_, _) => await ReloadAsync();
    }

    private async Task ReloadAsync()
    {
        _data = await DataStore.LoadAsync();
        RenderList();
        ShowPage(ListPage);
    }

    private void RenderList()
    {
        AlarmList.Children.Clear();
        foreach (var alarm in _data.Alarms.OrderBy(a => a.Time)) AlarmList.Children.Add(CreateAlarmCard(alarm));
        if (_data.Alarms.Count == 0)
            AlarmList.Children.Add(new TextBlock { Text = "还没有闹钟。点击右上角新建一个。", Foreground = (Brush)FindResource("SubtleBrush"), FontSize = 16, Margin = new Thickness(0, 30, 0, 0), HorizontalAlignment = HorizontalAlignment.Center });
        var enabled = _data.Alarms.Count(a => a.Enabled);
        SystemStatus.Text = enabled == 0 ? "当前没有启用的闹钟。" : $"{enabled} 个闹钟已启用。关闭窗口不会影响唤醒和播放；后台任务不会显示控制台。";
    }

    private Border CreateAlarmCard(AlarmModel alarm)
    {
        var card = new Border { Background = Brushes.White, BorderBrush = new SolidColorBrush(Color.FromRgb(226, 226, 226)), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(10), Padding = new Thickness(20, 16, 16, 16), Margin = new Thickness(0, 0, 0, 10) };
        var grid = new Grid(); grid.ColumnDefinitions.Add(new ColumnDefinition()); grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var left = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
        var time = new TextBlock { Text = alarm.Time, FontSize = 32, FontWeight = FontWeights.SemiBold, Width = 115, VerticalAlignment = VerticalAlignment.Center };
        var texts = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
        texts.Children.Add(new TextBlock { Text = alarm.Name, FontSize = 16, FontWeight = FontWeights.SemiBold });
        texts.Children.Add(new TextBlock { Text = $"{RepeatText(alarm)} · {SoundText(alarm)}", Foreground = (Brush)FindResource("SubtleBrush"), Margin = new Thickness(0, 4, 0, 0) });
        texts.Children.Add(new TextBlock { Text = alarm.LastResult, Foreground = alarm.LastResult.Contains("失败") ? Brushes.Firebrick : (Brush)FindResource("SubtleBrush"), FontSize = 12, Margin = new Thickness(0, 4, 0, 0) });
        left.Children.Add(time); left.Children.Add(texts); grid.Children.Add(left);
        var actions = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center };
        var toggle = new CheckBox { Content = alarm.Enabled ? "已开启" : "已关闭", IsChecked = alarm.Enabled, FontSize = 14, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8) };
        toggle.Checked += async (_, _) => await SetEnabledAsync(alarm, true, toggle);
        toggle.Unchecked += async (_, _) => await SetEnabledAsync(alarm, false, toggle);
        var edit = new Button { Content = "编辑", Tag = alarm.Id }; edit.Click += Edit_Click;
        actions.Children.Add(toggle); actions.Children.Add(edit); Grid.SetColumn(actions, 1); grid.Children.Add(actions); card.Child = grid;
        return card;
    }

    private async Task SetEnabledAsync(AlarmModel alarm, bool enabled, CheckBox toggle)
    {
        if (alarm.Enabled == enabled) return;
        alarm.Enabled = enabled; toggle.Content = enabled ? "已开启" : "已关闭";
        try { await DataStore.SaveAsync(_data); await TaskSchedulerService.SyncAsync(alarm); RenderList(); }
        catch (Exception ex) { alarm.Enabled = !enabled; await DataStore.SaveAsync(_data); MessageBox.Show(ex.Message, "无法更新闹钟", MessageBoxButton.OK, MessageBoxImage.Error); RenderList(); }
    }

    private void Add_Click(object sender, RoutedEventArgs e) => OpenEditor(new AlarmModel(), true);
    private void Edit_Click(object sender, RoutedEventArgs e) { var id = (string)((Button)sender).Tag; var alarm = _data.Alarms.First(a => a.Id == id); OpenEditor(alarm, false); }

    private void OpenEditor(AlarmModel alarm, bool isNew)
    {
        _editingId = isNew ? null : alarm.Id;
        EditorTitle.Text = isNew ? "新建闹钟" : "编辑闹钟";
        NameBox.Text = alarm.Name; TimeBox.Text = alarm.Time; PrepareBox.Text = alarm.PrepareMinutes.ToString(); SnoozeBox.Text = alarm.SnoozeMinutes.ToString(); VolumeBox.Text = alarm.Volume.ToString();
        RepeatBox.SelectedIndex = (int)alarm.Repeat; SoundBox.SelectedIndex = (int)alarm.Sound; SourceBox.Text = alarm.SourceUrl; FilterBox.Text = alarm.TitleFilter; LocalBox.Text = alarm.LocalFile;
        foreach (CheckBox box in WeekdayPanel.Children) box.IsChecked = alarm.Weekdays.Contains(Enum.Parse<DayOfWeek>((string)box.Tag));
        PreparedInfo.Text = string.IsNullOrWhiteSpace(alarm.PreparedTitle) ? "尚未准备铃声" : $"当前铃声：{alarm.PreparedTitle}\n更新时间：{alarm.PreparedAt:yyyy-MM-dd HH:mm}";
        DeleteButton.Visibility = isNew ? Visibility.Collapsed : Visibility.Visible;
        UpdateConditionalFields(); ShowPage(EditPage);
    }

    private AlarmModel ReadEditor()
    {
        if (!TimeOnly.TryParseExact(TimeBox.Text.Trim(), "HH:mm", CultureInfo.InvariantCulture, DateTimeStyles.None, out _)) throw new InvalidOperationException("时间格式应为 HH:mm，例如 07:30");
        if (!int.TryParse(PrepareBox.Text, out var lead) || lead is < 0 or > 720) throw new InvalidOperationException("提前更新时间应为 0–720 分钟");
        if (!int.TryParse(SnoozeBox.Text, out var snooze) || snooze is < 1 or > 60) throw new InvalidOperationException("贪睡时间应为 1–60 分钟");
        if (!int.TryParse(VolumeBox.Text, out var volume) || volume is < 1 or > 100) throw new InvalidOperationException("闹钟音量应为 1–100");
        var repeat = Enum.Parse<RepeatKind>((string)((ComboBoxItem)RepeatBox.SelectedItem).Tag);
        var sound = Enum.Parse<SoundKind>((string)((ComboBoxItem)SoundBox.SelectedItem).Tag);
        if (sound != SoundKind.LocalFile && string.IsNullOrWhiteSpace(SourceBox.Text)) throw new InvalidOperationException("请填写 B 站来源地址");
        if (sound == SoundKind.LocalFile && !File.Exists(LocalBox.Text)) throw new InvalidOperationException("请选择有效的本地音频文件");
        var previous = _editingId is null ? null : _data.Alarms.First(a => a.Id == _editingId);
        return new AlarmModel
        {
            Id = previous?.Id ?? Guid.NewGuid().ToString("N"), Name = string.IsNullOrWhiteSpace(NameBox.Text) ? "闹钟" : NameBox.Text.Trim(), Enabled = previous?.Enabled ?? true,
            Time = TimeBox.Text.Trim(), Repeat = repeat, Weekdays = WeekdayPanel.Children.OfType<CheckBox>().Where(x => x.IsChecked == true).Select(x => Enum.Parse<DayOfWeek>((string)x.Tag)).ToList(),
            Sound = sound, SourceUrl = SourceBox.Text.Trim(), TitleFilter = string.IsNullOrWhiteSpace(FilterBox.Text) ? ".*" : FilterBox.Text.Trim(), LocalFile = LocalBox.Text,
            PreparedFile = previous?.PreparedFile ?? "", PreparedTitle = previous?.PreparedTitle ?? "", PreparedAt = previous?.PreparedAt, PrepareMinutes = lead, SnoozeMinutes = snooze, Volume = volume,
            LastFiredAt = previous?.LastFiredAt, LastResult = previous?.LastResult ?? "尚未运行"
        };
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var alarm = ReadEditor();
            if (alarm.Sound == SoundKind.LocalFile)
            {
                var root = string.IsNullOrWhiteSpace(_data.Settings.MediaDirectory) ? AppPaths.Media : _data.Settings.MediaDirectory; Directory.CreateDirectory(root);
                var target = Path.Combine(root, $"本地铃声-{alarm.Id[..8]}{Path.GetExtension(alarm.LocalFile)}");
                if (!Path.GetFullPath(alarm.LocalFile).Equals(Path.GetFullPath(target), StringComparison.OrdinalIgnoreCase)) File.Copy(alarm.LocalFile, target, true);
                alarm.LocalFile = target; alarm.PreparedFile = target; alarm.PreparedTitle = Path.GetFileNameWithoutExtension(target); alarm.PreparedAt = DateTimeOffset.Now;
            }
            var index = _data.Alarms.FindIndex(a => a.Id == alarm.Id); if (index >= 0) _data.Alarms[index] = alarm; else _data.Alarms.Add(alarm);
            await DataStore.SaveAsync(_data); await TaskSchedulerService.SyncAsync(alarm); RenderList(); ShowPage(ListPage);
        }
        catch (Exception ex) { MessageBox.Show(ex.Message, "无法保存", MessageBoxButton.OK, MessageBoxImage.Error); }
    }

    private async void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (_editingId is null || MessageBox.Show("删除这个闹钟？", "确认", MessageBoxButton.YesNo, MessageBoxImage.Question) != MessageBoxResult.Yes) return;
        await TaskSchedulerService.DeleteAsync(_editingId); _data.Alarms.RemoveAll(a => a.Id == _editingId); await DataStore.SaveAsync(_data); RenderList(); ShowPage(ListPage);
    }

    private async void Test_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Mouse.OverrideCursor = System.Windows.Input.Cursors.Wait;
            var alarm = ReadEditor();
            var index = _data.Alarms.FindIndex(a => a.Id == alarm.Id); if (index >= 0) _data.Alarms[index] = alarm; else _data.Alarms.Add(alarm);
            _editingId = alarm.Id;
            await DataStore.SaveAsync(_data);
            var latest = (await DataStore.LoadAsync()).Alarms.First(a => a.Id == alarm.Id);
            await AlarmRunner.PreviewAsync(latest, _data.Settings);
            MessageBox.Show("已将当前铃声推送到小爱音箱。", "试听成功", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex) { MessageBox.Show(ex.Message, "试听失败", MessageBoxButton.OK, MessageBoxImage.Error); }
        finally { Mouse.OverrideCursor = null; }
    }

    private async void UpdateNow_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Mouse.OverrideCursor = System.Windows.Input.Cursors.Wait;
            var alarm = ReadEditor();
            var index = _data.Alarms.FindIndex(a => a.Id == alarm.Id); if (index >= 0) _data.Alarms[index] = alarm; else _data.Alarms.Add(alarm);
            _editingId = alarm.Id;
            await DataStore.SaveAsync(_data);
            await AlarmRunner.PrepareAsync(alarm, _data.Settings);
            var latest = (await DataStore.LoadAsync()).Alarms.First(a => a.Id == alarm.Id);
            PreparedInfo.Text = $"当前铃声：{latest.PreparedTitle}\n更新时间：{latest.PreparedAt:yyyy-MM-dd HH:mm}";
            MessageBox.Show("最新内容已准备完成。", "更新成功", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex) { MessageBox.Show(FriendlyError(ex), "更新失败，已保留原铃声", MessageBoxButton.OK, MessageBoxImage.Warning); }
        finally { Mouse.OverrideCursor = null; }
    }

    private static string FriendlyError(Exception ex)
    {
        var text = ex.Message;
        if (text.Contains("412") || text.Contains("blocked", StringComparison.OrdinalIgnoreCase))
            return "B 站暂时限制了主页请求（412）。应用已自动重试，稍后可再次点击“立即更新”；现有铃声不会被删除。";
        return text;
    }

    private async void Stop_Click(object sender, RoutedEventArgs e) { try { await XiaoMusicService.StopAsync(_data.Settings); } catch (Exception ex) { MessageBox.Show(ex.Message, "停止失败"); } }
    private void Browse_Click(object sender, RoutedEventArgs e) { var d = new OpenFileDialog { Filter = "音频文件|*.mp3;*.m4a;*.wav;*.ogg;*.flac|所有文件|*.*" }; if (d.ShowDialog() == true) LocalBox.Text = d.FileName; }
    private void OpenFolder_Click(object sender, RoutedEventArgs e)
    {
        var alarm = _editingId is null ? null : _data.Alarms.FirstOrDefault(a => a.Id == _editingId);
        var folder = alarm is not null && File.Exists(alarm.PreparedFile) ? Path.GetDirectoryName(alarm.PreparedFile) : (string.IsNullOrWhiteSpace(_data.Settings.MediaDirectory) ? AppPaths.Media : _data.Settings.MediaDirectory);
        Directory.CreateDirectory(folder!);
        Process.Start(new ProcessStartInfo("explorer.exe", folder!) { UseShellExecute = true });
    }
    private void Back_Click(object sender, RoutedEventArgs e) { RenderList(); ShowPage(ListPage); }
    private void Repeat_Changed(object sender, SelectionChangedEventArgs e) => UpdateConditionalFields();
    private void Sound_Changed(object sender, SelectionChangedEventArgs e) => UpdateConditionalFields();

    private void UpdateConditionalFields()
    {
        if (!IsLoaded || RepeatBox.SelectedItem is null || SoundBox.SelectedItem is null) return;
        var repeat = (string)((ComboBoxItem)RepeatBox.SelectedItem).Tag; WeekdayPanel.Visibility = repeat == "Weekdays" ? Visibility.Visible : Visibility.Collapsed;
        var sound = (string)((ComboBoxItem)SoundBox.SelectedItem).Tag; BiliPanel.Visibility = sound == "LocalFile" ? Visibility.Collapsed : Visibility.Visible; LocalPanel.Visibility = sound == "LocalFile" ? Visibility.Visible : Visibility.Collapsed;
        SourceLabel.Text = sound == "BilibiliVideo" ? "B 站视频链接" : "UP 主主页"; FilterLabel.Visibility = FilterBox.Visibility = sound == "BilibiliLatest" ? Visibility.Visible : Visibility.Collapsed;
    }

    private void Settings_Click(object sender, RoutedEventArgs e)
    {
        var s = _data.Settings; XiaoUrlBox.Text = s.XiaoMusicUrl; DeviceBox.Text = s.DeviceId; LauncherBox.Text = s.XiaoMusicLauncher; PythonBox.Text = s.PythonExecutable; MediaBox.Text = s.MediaDirectory; YtDlpBox.Text = s.YtDlpExecutable; FfmpegBox.Text = s.FfmpegExecutable; ShowPage(SettingsPage);
    }

    private async void SaveSettings_Click(object sender, RoutedEventArgs e)
    {
        _data.Settings.XiaoMusicUrl = XiaoUrlBox.Text.Trim(); _data.Settings.DeviceId = DeviceBox.Text.Trim(); _data.Settings.XiaoMusicLauncher = LauncherBox.Text.Trim(); _data.Settings.PythonExecutable = PythonBox.Text.Trim(); _data.Settings.MediaDirectory = MediaBox.Text.Trim(); _data.Settings.YtDlpExecutable = YtDlpBox.Text.Trim(); _data.Settings.FfmpegExecutable = FfmpegBox.Text.Trim();
        await DataStore.SaveAsync(_data); ShowPage(ListPage);
    }

    private void ShowPage(UIElement page) { ListPage.Visibility = EditPage.Visibility = SettingsPage.Visibility = Visibility.Collapsed; page.Visibility = Visibility.Visible; SettingsButton.Visibility = page == ListPage ? Visibility.Visible : Visibility.Collapsed; }
    private static string RepeatText(AlarmModel a) => a.Repeat switch { RepeatKind.Workdays => "法定工作日", RepeatKind.Daily => "每天", _ => string.Join(" ", a.Weekdays.Select(x => "日一二三四五六"[(int)x])) };
    private static string SoundText(AlarmModel a) => a.Sound switch { SoundKind.BilibiliLatest => "B站最新投稿", SoundKind.BilibiliVideo => "B站视频", _ => "本地铃声" };
}
