import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/models/task_mode.dart';

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
      'project_id': 'project-1',
      'pinned': true,
      'sort_order': 4,
      'conversation_count': 3,
      'created_at': '2026-08-12T08:00:00Z',
      'updated_at': '2026-08-12T09:00:00Z',
    });

    expect(group.id, 'group-1');
    expect(group.userId, 'user-1');
    expect(group.name, '高数');
    expect(group.style, 'socratic');
    expect(group.tone, isNull);
    expect(group.projectId, 'project-1');
    expect(group.pinned, isTrue);
    expect(group.sortOrder, 4);
    expect(group.conversationCount, 3);
  });

  test('ChatConversation parses optional group id', () {
    final conversation = ChatConversation.fromJson({
      'conversation_id': 'conversation-1',
      'title': '线性代数',
      'updated_at': '2026-08-12T08:00:00Z',
      'workspace_type': 'learning',
      'group_id': 'group-1',
      'pinned': true,
    });

    expect(conversation.groupId, 'group-1');
    expect(conversation.pinned, isTrue);
  });

  test('account planner snapshot parses server-owned todos and goals', () {
    final snapshot = PlannerSnapshot.fromJson({
      'todos': [
        {
          'todo_id': 'todo-1',
          'title': '复习线性代数',
          'due_at': '2026-08-25T08:00:00Z',
          'done': true,
        },
      ],
      'goals': [
        {
          'goal_id': 'goal-1',
          'title': '通过期末考试',
          'description': '按周复习',
          'target_at': '2026-09-01T00:00:00Z',
          'progress': 60,
        },
      ],
    });

    expect(snapshot.todos.single.id, 'todo-1');
    expect(snapshot.todos.single.done, isTrue);
    expect(snapshot.todos.single.dueAt, isNotNull);
    expect(snapshot.goals.single.id, 'goal-1');
    expect(snapshot.goals.single.progress, 60);
  });

  test(
    'task modes send identifiers instead of client-authored instructions',
    () {
      expect(TaskMode.studyPlan.wireName, 'study_plan');
      expect(TaskMode.researchDataAnalysis.wireName, 'research_data_analysis');
      expect(
        TaskMode.values.map((mode) => mode.wireName).toSet(),
        hasLength(12),
      );
    },
  );

  test('ChatConversation parses research and classroom resource bindings', () {
    final research = ChatConversation.fromJson({
      'conversation_id': 'research-chat',
      'workspace_type': 'research',
      'research_project_id': 'project-1',
    });
    final teaching = ChatConversation.fromJson({
      'conversation_id': 'teaching-chat',
      'workspace_type': 'teaching',
      'classroom_binding': {
        'class_id': 'class-1',
        'class_name': 'Algorithms',
        'assignment_id': 'assignment-1',
        'assignment_title': 'Binary search',
      },
    });

    expect(research.workspaceType, WorkspaceType.research);
    expect(research.researchProjectId, 'project-1');
    expect(teaching.workspaceType, WorkspaceType.teaching);
    expect(teaching.classId, 'class-1');
    expect(teaching.className, 'Algorithms');
    expect(teaching.assignmentId, 'assignment-1');
    expect(teaching.assignmentTitle, 'Binary search');
  });

  test('CoreMemory V2 models preserve workspace scope and candidates', () {
    final memory = CoreMemoryItem.fromJson({
      'memory_id': 'memory-1',
      'memory_key': 'writing_style',
      'content': 'Use concise summaries',
      'category': 'preference',
      'scope_type': 'workspace',
      'workspace_type': 'research',
      'status': 'suppressed',
      'revision': 3,
    });
    final candidate = MemoryCandidateItem.fromJson({
      'candidate_id': 'candidate-1',
      'memory_key': 'writing_style',
      'proposed_content': 'Use evidence-first summaries',
      'category': 'preference',
      'scope_type': 'workspace',
      'workspace_type': 'research',
    });

    expect(memory.id, 'memory-1');
    expect(memory.scopeType, 'workspace');
    expect(memory.workspaceType, 'research');
    expect(memory.status, 'suppressed');
    expect(memory.revision, 3);
    expect(candidate.id, 'candidate-1');
    expect(candidate.workspaceType, 'research');
  });

  test('Project Profile and Agent Action parse approval contracts', () {
    final profile = ResearchProjectProfile.fromJson({
      'agent_instructions': 'Cite primary sources.',
      'revision': 4,
    });
    final action = AgentActionItem.fromJson({
      'action_id': 'action-1',
      'action_type': 'start_frontier_tracking',
      'status': 'pending',
      'workspace_type': 'research',
      'arguments': {'query': 'agent memory'},
      'resource_snapshot': {'project_id': 'project-1'},
      'created_at': '2026-08-14T00:00:00Z',
      'expires_at': '2026-08-14T00:30:00Z',
    });

    expect(profile.instructions, 'Cite primary sources.');
    expect(profile.revision, 4);
    expect(action.id, 'action-1');
    expect(action.status, 'pending');
    expect(action.arguments['query'], 'agent memory');
    expect(action.resourceSnapshot['project_id'], 'project-1');
    expect(action.expiresAt, isNotNull);
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
