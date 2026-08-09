import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/models.dart';

void main() {
  test('UserProfile parses the compatibility fields in a Profile V2 response', () {
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
  });

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
}
