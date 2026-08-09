import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/models.dart';

void main() {
  test(
    'UserProfile parses the compatibility fields in a Profile V2 response',
    () {
      final profile = UserProfile.fromJson({
        'major': 'cs',
        'grade': '大二',
        'current_week': 3,
        'total_weeks': 18,
        'profile_enabled': true,
        'explicit': const [],
      });

      expect(profile.grade, '大二');
      expect(profile.currentWeek, 3);
      expect(profile.totalWeeks, 18);
      expect(profile.profileEnabled, isTrue);
    },
  );

  test('UserProfile can also read explicit Profile V2 fields', () {
    final profile = UserProfile.fromJson({
      'explicit': [
        {'field': 'major', 'value': 'cs'},
        {'field': 'grade', 'value': '大三'},
        {'field': 'current_week', 'value': 8},
        {'field': 'total_weeks', 'value': 20},
        {'field': 'profile_enabled', 'value': false},
      ],
    });

    expect(profile.grade, '大三');
    expect(profile.currentWeek, 8);
    expect(profile.totalWeeks, 20);
    expect(profile.profileEnabled, isFalse);
  });

  test('ScheduleCourse round-trips local timetable fields', () {
    const course = ScheduleCourse(
      id: 'course-1',
      name: '数据结构',
      teacher: '李老师',
      location: '教一 203',
      weekday: 3,
      startPeriod: 3,
      endPeriod: 4,
      startWeek: 1,
      endWeek: 16,
      colorValue: 0xFF2563EB,
    );

    final restored = ScheduleCourse.fromJson(course.toJson());

    expect(restored.id, course.id);
    expect(restored.name, course.name);
    expect(restored.teacher, course.teacher);
    expect(restored.location, course.location);
    expect(restored.weekday, 3);
    expect(restored.startPeriod, 3);
    expect(restored.endPeriod, 4);
    expect(restored.occursInWeek(8), isTrue);
    expect(restored.occursInWeek(18), isFalse);
  });

  test('ScheduleSettings calculates and restores period times', () {
    const settings = ScheduleSettings(
      morningPeriodCount: 3,
      afternoonPeriodCount: 2,
      eveningPeriodCount: 1,
      morningStartMinutes: 8 * 60 + 20,
      afternoonStartMinutes: 13 * 60 + 30,
      eveningStartMinutes: 19 * 60,
      periodDurationMinutes: 50,
      breakDurationMinutes: 10,
    );

    expect(settings.periodStartLabel(1), '08:20');
    expect(settings.periodEndLabel(1), '09:10');
    expect(settings.periodStartLabel(2), '09:20');
    expect(settings.courseTimeLabel(1, 2), '08:20–10:10');
    expect(settings.periodStartLabel(4), '13:30');
    expect(settings.periodStartLabel(6), '19:00');
    expect(settings.totalPeriods, 6);

    final restored = ScheduleSettings.fromJson(settings.toJson());
    expect(restored.morningStartMinutes, 500);
    expect(restored.afternoonStartMinutes, 810);
    expect(restored.eveningStartMinutes, 1140);
    expect(restored.morningPeriodCount, 3);
    expect(restored.afternoonPeriodCount, 2);
    expect(restored.eveningPeriodCount, 1);
    expect(restored.periodDurationMinutes, 50);
    expect(restored.breakDurationMinutes, 10);
  });
}
