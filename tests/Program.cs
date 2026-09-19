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
var before = new DateTime(2026, 9, 19, 21, 0, 0);
Check("future alarm starts today", TaskSchedulerService.CalculateFirstRun(new TimeOnly(21, 7), before) == new DateTime(2026, 9, 19, 21, 7, 0));
var sameMinute = new DateTime(2026, 9, 19, 21, 7, 30);
Check("same-minute alarm starts shortly", TaskSchedulerService.CalculateFirstRun(new TimeOnly(21, 7), sameMinute) == sameMinute.AddSeconds(5));
var after = new DateTime(2026, 9, 19, 21, 10, 0);
Check("past alarm starts tomorrow", TaskSchedulerService.CalculateFirstRun(new TimeOnly(21, 7), after) == new DateTime(2026, 9, 20, 21, 7, 0));
Console.WriteLine(failures.Count == 0 ? "All checks passed." : $"{failures.Count} failed.");
return failures.Count == 0 ? 0 : 1;
