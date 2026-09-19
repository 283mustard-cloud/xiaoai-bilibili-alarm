using XiaoAiAlarm.Models;

namespace XiaoAiAlarm.Services;

public static class CalendarRules
{
    // 国务院公布的 2026 年调休工作日与法定休息日覆盖。
    private static readonly HashSet<DateOnly> WorkdayOverrides = Parse("2026-01-04,2026-02-14,2026-02-28,2026-05-09,2026-09-20,2026-10-10");
    private static readonly HashSet<DateOnly> HolidayOverrides = Parse("2026-01-01,2026-01-02,2026-01-03,2026-02-15,2026-02-16,2026-02-17,2026-02-18,2026-02-19,2026-02-20,2026-02-21,2026-02-22,2026-02-23,2026-04-04,2026-04-05,2026-04-06,2026-05-01,2026-05-02,2026-05-03,2026-05-04,2026-05-05,2026-06-19,2026-06-20,2026-06-21,2026-09-25,2026-09-26,2026-09-27,2026-10-01,2026-10-02,2026-10-03,2026-10-04,2026-10-05,2026-10-06,2026-10-07");
    private static HashSet<DateOnly> Parse(string value) => value.Split(',').Select(DateOnly.Parse).ToHashSet();

    public static bool ShouldRing(AlarmModel alarm, DateOnly date)
    {
        if (!alarm.Enabled) return false;
        return alarm.Repeat switch
        {
            RepeatKind.Daily => true,
            RepeatKind.Weekdays => alarm.Weekdays.Contains(date.DayOfWeek),
            _ => WorkdayOverrides.Contains(date) || (!HolidayOverrides.Contains(date) && date.DayOfWeek is not DayOfWeek.Saturday and not DayOfWeek.Sunday)
        };
    }
}
