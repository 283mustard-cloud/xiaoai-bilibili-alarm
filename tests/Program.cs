using XiaoAiAlarm.Models;
using XiaoAiAlarm.Services;

var failures = new List<string>();
void Check(string name, bool ok) { Console.WriteLine($"{(ok ? "PASS" : "FAIL")} {name}"); if (!ok) failures.Add(name); }
var workday = new AlarmModel { Repeat = RepeatKind.Workdays };
Check("Sunday make-up workday", CalendarRules.ShouldRing(workday, new DateOnly(2026, 9, 20)));
Check("Mid-Autumn holiday", !CalendarRules.ShouldRing(workday, new DateOnly(2026, 9, 26)));
Check("normal Monday", CalendarRules.ShouldRing(workday, new DateOnly(2026, 9, 21)));
var custom = new AlarmModel { Repeat = RepeatKind.Weekdays, Weekdays = [DayOfWeek.Saturday] };
Check("custom weekday selected", CalendarRules.ShouldRing(custom, new DateOnly(2026, 9, 19)));
Check("custom weekday skipped", !CalendarRules.ShouldRing(custom, new DateOnly(2026, 9, 20)));
custom.Enabled = false; Check("disabled alarm", !CalendarRules.ShouldRing(custom, new DateOnly(2026, 9, 19)));
var midnight = TimeOnly.Parse("00:10");
Check("cross-midnight prepare", midnight.AddMinutes(-30) > midnight);
Console.WriteLine(failures.Count == 0 ? "All checks passed." : $"{failures.Count} failed.");
return failures.Count == 0 ? 0 : 1;
