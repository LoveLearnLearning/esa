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
      termStartDate: '2026-08-03',
    );

    expect(settings.periodStartLabel(1), '08:20');
    expect(settings.periodEndLabel(1), '09:10');
    expect(settings.periodStartLabel(2), '09:20');
    expect(settings.courseTimeLabel(1, 2), '08:20–10:10');
    expect(settings.periodStartLabel(4), '13:30');
    expect(settings.periodStartLabel(6), '19:00');
    expect(settings.totalPeriods, 6);
    expect(settings.weekForDate(DateTime(2026, 8, 3)), 1);
    expect(settings.weekForDate(DateTime(2026, 8, 17)), 3);

    final restored = ScheduleSettings.fromJson(settings.toJson());
    expect(restored.morningStartMinutes, 500);
    expect(restored.afternoonStartMinutes, 810);
    expect(restored.eveningStartMinutes, 1140);
    expect(restored.morningPeriodCount, 3);
    expect(restored.afternoonPeriodCount, 2);
    expect(restored.eveningPeriodCount, 1);
    expect(restored.periodDurationMinutes, 50);
    expect(restored.breakDurationMinutes, 10);
    expect(restored.termStartDate, '2026-08-03');
  });

  test('ChatGroup parses nullable style/tone and conversation count', () {
    final group = ChatGroup.fromJson({
      'group_id': 'group-1',
      'user_id': 'user-1',
      'name': '高数',
      'description': '高等数学复习',
      'custom_instruction': '用苏格拉底式提问引导我',
      'style': 'socratic',
      'tone': null,
      'conversation_count': 3,
      'created_at': '2026-08-12T08:00:00Z',
      'updated_at': '2026-08-12T09:00:00Z',
    });

    expect(group.id, 'group-1');
    expect(group.userId, 'user-1');
    expect(group.name, '高数');
    expect(group.style, 'socratic');
    expect(group.tone, isNull);
    expect(group.conversationCount, 3);
  });

  test('ChatConversation parses optional group id', () {
    final conversation = ChatConversation.fromJson({
      'conversation_id': 'conversation-1',
      'title': '线性代数',
      'updated_at': '2026-08-12T08:00:00Z',
      'workspace_type': 'learning',
      'group_id': 'group-1',
    });

    expect(conversation.groupId, 'group-1');
  });

  test(
    'teaching models parse backend identifiers and nested workflow data',
    () {
      final classroom = TeachingClass.fromJson({
        'class_id': 'class-1',
        'name': '数据结构 1 班',
        'canonical_course': '数据结构',
        'student_count': 12,
        'open_assignment_count': 2,
        'membership_status': 'active',
      });
      final assignment = TeachingAssignment.fromJson({
        'assignment_id': 'assignment-1',
        'class_id': 'class-1',
        'class_name': '数据结构 1 班',
        'canonical_course': '数据结构',
        'title': '二分查找诊断',
        'status': 'published',
        'total_points': 10,
        'questions': [
          {
            'question_id': 'question-1',
            'question_type': 'code',
            'prompt': '实现二分查找',
            'max_points': 10,
          },
        ],
      });
      final submission = TeachingSubmission.fromJson({
        'submission_id': 'submission-1',
        'assignment_id': 'assignment-1',
        'student_username': 'student',
        'analysis_status': 'completed',
        'feedback_status': 'published',
        'answers': [
          {
            'answer_id': 'answer-1',
            'question_id': 'question-1',
            'prompt': '实现二分查找',
            'answer_text': '代码答案',
            'max_points': 10,
            'ai_score': 7,
            'ai_feedback': 'AI 建议',
            'ai_kp_id': 'kp-ai',
            'final_score': 8,
            'final_feedback': '教师反馈',
            'final_kp_id': 'kp-final',
          },
        ],
      });

      expect(classroom.id, 'class-1');
      expect(classroom.course, '数据结构');
      expect(classroom.studentCount, 12);
      expect(assignment.id, 'assignment-1');
      expect(assignment.questions.single.type, 'code');
      expect(submission.studentUsername, 'student');
      expect(submission.answers.single.finalScore, 8);
      expect(submission.answers.single.feedback, '教师反馈');
      expect(submission.answers.single.kpId, 'kp-final');
    },
  );
}
