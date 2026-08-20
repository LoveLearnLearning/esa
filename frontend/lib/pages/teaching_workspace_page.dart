import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

/// Teacher workspace pages. They intentionally use the existing teaching API
/// models instead of manufacturing dashboard data in the client.
class TeachingWorkspacePage extends StatefulWidget {
  const TeachingWorkspacePage({super.key, this.onOpenChat});

  final VoidCallback? onOpenChat;

  @override
  State<TeachingWorkspacePage> createState() => _TeachingWorkspacePageState();
}

class _TeachingWorkspacePageState extends State<TeachingWorkspacePage> {
  Map<String, dynamic>? _overview;
  bool _loading = true;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_overview == null && _loading) _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final value = await AppScope.of(context).api.getTeachingOverview();
      if (mounted) setState(() => _overview = value);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } catch (_) {
      if (mounted) setState(() => _error = '无法连接教学服务，请稍后重试');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _createClass() async {
    final name = TextEditingController();
    final course = TextEditingController();
    final term = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('创建班级'),
        content: SizedBox(
          width: 430,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: name,
                autofocus: true,
                decoration: const InputDecoration(labelText: '班级名称'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: course,
                decoration: const InputDecoration(labelText: '课程目录中的准确名称'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: term,
                decoration: const InputDecoration(labelText: '学期（可选）'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('创建班级'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      try {
        await AppScope.of(context).api.createTeachingClass(
          name: name.text.trim(),
          course: course.text.trim(),
          term: term.text.trim(),
        );
        await _load();
      } on ApiException catch (error) {
        _snack(error.detail);
      }
    }
    for (final controller in [name, course, term]) {
      controller.dispose();
    }
  }

  void _snack(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  Future<void> _openClass(TeachingClass classroom) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AppScope(
          state: AppScope.of(context),
          child: TeachingClassPage(
            classroom: classroom,
            onOpenChat: widget.onOpenChat,
          ),
        ),
      ),
    );
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    final classes = (_overview?['classes'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => TeachingClass.fromJson(Map<String, dynamic>.from(item)))
        .toList();
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _load,
        child: CustomScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            SliverToBoxAdapter(
              child: _PageHeader(
                eyebrow: '教学空间',
                title: '教学工作台',
                subtitle: '先处理需要教师判断的事项，再进入班级和作业。',
                action: FilledButton.icon(
                  key: const ValueKey('create-class'),
                  onPressed: _createClass,
                  icon: const Icon(LucideIcons.plus, size: 17),
                  label: const Text('新建班级'),
                ),
              ),
            ),
            if (_loading)
              const SliverFillRemaining(
                child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
              )
            else if (_error != null)
              SliverFillRemaining(
                child: _TeachingEmpty(
                  title: '工作台加载失败',
                  message: _error!,
                  onRetry: _load,
                ),
              )
            else ...[
              SliverToBoxAdapter(
                child: _WorkQueue(
                  pendingReview:
                      (_overview?['pending_review_count'] as num?)?.toInt() ??
                      0,
                  readyFeedback:
                      (_overview?['ready_feedback_count'] as num?)?.toInt() ??
                      0,
                  classCount:
                      (_overview?['class_count'] as num?)?.toInt() ??
                      classes.length,
                ),
              ),
              SliverToBoxAdapter(
                child: _SectionHeading(
                  title: '我的班级',
                  trailing: Text(
                    '${classes.length} 个活动班级',
                    style: context.texts.bodySmall,
                  ),
                ),
              ),
              if (classes.isEmpty)
                const SliverFillRemaining(
                  hasScrollBody: false,
                  child: _TeachingEmpty(
                    title: '还没有班级',
                    message: '创建班级后即可邀请学生并发布诊断作业。',
                  ),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 32),
                  sliver: SliverList.builder(
                    itemCount: classes.length,
                    itemBuilder: (context, index) => _ClassRow(
                      classroom: classes[index],
                      onTap: () => _openClass(classes[index]),
                    ),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class TeachingClassPage extends StatefulWidget {
  const TeachingClassPage({
    super.key,
    required this.classroom,
    this.onOpenChat,
    this.onBack,
  });

  final TeachingClass classroom;
  final VoidCallback? onOpenChat;
  final VoidCallback? onBack;

  @override
  State<TeachingClassPage> createState() => _TeachingClassPageState();
}

enum _ClassTab { overview, assignments, students, insights }

class _TeachingClassPageState extends State<TeachingClassPage> {
  Map<String, dynamic>? _detail;
  Map<String, dynamic>? _dashboard;
  bool _loading = true;
  _ClassTab _tab = _ClassTab.overview;
  bool _requestedLoad = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_requestedLoad) {
      _requestedLoad = true;
      _load();
    }
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final api = AppScope.of(context).api;
      final values = await Future.wait([
        api.getTeachingClass(widget.classroom.id),
        api.getClassDashboard(widget.classroom.id),
      ]);
      if (mounted) {
        setState(() {
          _detail = values[0];
          _dashboard = values[1];
        });
      }
    } on ApiException catch (error) {
      _snack(error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _snack(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  Future<void> _invite() async {
    final username = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('邀请学生'),
        content: TextField(
          controller: username,
          autofocus: true,
          decoration: const InputDecoration(labelText: '精确用户名'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('发送邀请'),
          ),
        ],
      ),
    );
    if (ok == true && mounted) {
      try {
        await AppScope.of(
          context,
        ).api.inviteStudent(widget.classroom.id, username.text.trim());
        await _load();
      } on ApiException catch (error) {
        _snack(error.detail);
      }
    }
    username.dispose();
  }

  Future<void> _createAssignment() async {
    final draft = await showDialog<_AssignmentDraftResult>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) =>
          _CreateAssignmentDialog(knowledge: _knowledge),
    );
    if (draft != null && mounted) {
      try {
        await AppScope.of(context).api.createTeachingAssignment(
          classId: widget.classroom.id,
          title: draft.title,
          instructions: draft.instructions,
          dueAt: draft.dueAt,
          questions: draft.questions,
        );
        await _load();
        if (mounted) setState(() => _tab = _ClassTab.assignments);
      } on ApiException catch (error) {
        _snack(error.detail);
      }
    }
  }

  Future<void> _openBoundChat([TeachingAssignment? assignment]) async {
    try {
      await AppScope.of(
        context,
      ).openTeachingContext(widget.classroom, assignment: assignment);
      if (!mounted) return;
      if (widget.onBack == null && Navigator.of(context).canPop()) {
        Navigator.of(context).pop();
      }
      widget.onOpenChat?.call();
    } on ApiException catch (error) {
      _snack(error.detail);
    }
  }

  List<TeachingAssignment> get _assignments =>
      (_detail?['assignments'] as List? ?? const [])
          .whereType<Map>()
          .map(
            (item) =>
                TeachingAssignment.fromJson(Map<String, dynamic>.from(item)),
          )
          .toList();

  List<Map<String, dynamic>> get _members =>
      (_detail?['members'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();

  List<Map<String, dynamic>> get _knowledge =>
      (_dashboard?['knowledge_points'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();

  List<Map<String, dynamic>> get _alerts =>
      (_dashboard?['alerts'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _loading
          ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
          : CustomScrollView(
              slivers: [
                SliverToBoxAdapter(
                  child: _ClassHeader(
                    classroom: widget.classroom,
                    onBack: widget.onBack,
                    tab: _tab,
                    onTab: (tab) => setState(() => _tab = tab),
                    onInvite: _invite,
                    onCreateAssignment: _createAssignment,
                    onOpenChat: _openBoundChat,
                  ),
                ),
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(24, 20, 24, 36),
                    child: _buildTab(),
                  ),
                ),
              ],
            ),
    );
  }

  Widget _buildTab() => switch (_tab) {
    _ClassTab.overview => _ClassOverview(
      dashboard: _dashboard,
      knowledge: _knowledge,
      alerts: _alerts,
      onInsights: () => setState(() => _tab = _ClassTab.insights),
    ),
    _ClassTab.assignments => _AssignmentList(
      assignments: _assignments,
      onCreate: _createAssignment,
      onOpenChat: _openBoundChat,
      onPublish: (assignment) async {
        try {
          await AppScope.of(
            context,
          ).api.publishTeachingAssignment(assignment.id);
          await _load();
        } on ApiException catch (error) {
          _snack(error.detail);
        }
      },
      onReview: (assignment) async {
        await Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => AppScope(
              state: AppScope.of(context),
              child: TeachingReviewPage(assignment: assignment),
            ),
          ),
        );
        if (mounted) _load();
      },
    ),
    _ClassTab.students => _StudentList(
      classroom: widget.classroom,
      members: _members,
      onChanged: _load,
    ),
    _ClassTab.insights => _InsightsList(knowledge: _knowledge, alerts: _alerts),
  };
}

class TeachingReviewPage extends StatefulWidget {
  const TeachingReviewPage({super.key, required this.assignment});

  final TeachingAssignment assignment;

  @override
  State<TeachingReviewPage> createState() => _TeachingReviewPageState();
}

class _TeachingReviewPageState extends State<TeachingReviewPage> {
  List<TeachingSubmission> _submissions = const [];
  TeachingSubmission? _selected;
  bool _loading = true;
  bool _working = false;
  bool _requestedLoad = false;
  final Map<String, TextEditingController> _scores = {};
  final Map<String, TextEditingController> _feedback = {};
  final Map<String, TextEditingController> _knowledge = {};
  final Map<String, TextEditingController> _errors = {};

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_requestedLoad) {
      _requestedLoad = true;
      _load();
    }
  }

  @override
  void dispose() {
    for (final controller in [
      ..._scores.values,
      ..._feedback.values,
      ..._knowledge.values,
      ..._errors.values,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final api = AppScope.of(context).api;
      final list = await api.listTeachingSubmissions(widget.assignment.id);
      TeachingSubmission? selected;
      if (list.isNotEmpty) {
        selected = await api.getTeachingSubmission(list.first.id);
      }
      if (!mounted) return;
      setState(() {
        _submissions = list;
        _selected = selected;
        _loading = false;
      });
      _syncControllers(selected);
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _loading = false);
        _snack(error.detail);
      }
    }
  }

  void _syncControllers(TeachingSubmission? submission) {
    if (submission == null) return;
    for (final answer in submission.answers) {
      _scores.putIfAbsent(
        answer.id,
        () => TextEditingController(
          text: (answer.finalScore ?? answer.aiScore ?? 0).toStringAsFixed(1),
        ),
      );
      _feedback.putIfAbsent(
        answer.id,
        () => TextEditingController(text: answer.feedback),
      );
      _knowledge.putIfAbsent(
        answer.id,
        () => TextEditingController(text: answer.kpId ?? ''),
      );
      _errors.putIfAbsent(
        answer.id,
        () => TextEditingController(
          text:
              (answer.raw['final_error_type'] ?? answer.raw['ai_error_type'])
                  ?.toString() ??
              '',
        ),
      );
    }
  }

  void _snack(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  Future<void> _select(TeachingSubmission item) async {
    try {
      final detail = await AppScope.of(
        context,
      ).api.getTeachingSubmission(item.id);
      if (mounted) {
        setState(() => _selected = detail);
        _syncControllers(detail);
      }
    } on ApiException catch (error) {
      _snack(error.detail);
    }
  }

  Future<void> _analyze() async {
    final current = _selected;
    if (current == null) return;
    try {
      final value = await AppScope.of(
        context,
      ).api.analyzeTeachingSubmission(current.id);
      if (mounted) {
        setState(() => _selected = value);
        _syncControllers(value);
      }
    } on ApiException catch (error) {
      _snack(error.detail);
    }
  }

  Future<void> _analyzeAll() async {
    if (_working) return;
    setState(() => _working = true);
    try {
      final result = await AppScope.of(
        context,
      ).api.analyzeTeachingAssignment(widget.assignment.id);
      if (mounted) {
        _snack(
          '批量分析完成：${result['completed'] ?? 0} 份完成，${result['failed'] ?? 0} 份失败',
        );
        await _load();
      }
    } on ApiException catch (error) {
      _snack(error.detail);
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _saveReview() async {
    final current = _selected;
    if (current == null) return;
    final reviews = current.answers.map((answer) {
      final score = double.tryParse(_scores[answer.id]?.text ?? '') ?? 0;
      return <String, dynamic>{
        'answer_id': answer.id,
        'score': score.clamp(0, answer.maxPoints),
        'error_type': (_errors[answer.id]?.text.trim().isEmpty ?? true)
            ? null
            : _errors[answer.id]!.text.trim(),
        'feedback': _feedback[answer.id]?.text.trim() ?? '',
        'kp_id': (_knowledge[answer.id]?.text.trim().isEmpty ?? true)
            ? null
            : _knowledge[answer.id]!.text.trim(),
      };
    }).toList();
    try {
      final value = await AppScope.of(
        context,
      ).api.reviewTeachingSubmission(current.id, reviews);
      if (mounted) {
        setState(() => _selected = value);
        _syncControllers(value);
        _snack('复核已保存，发布反馈前仍可继续修改。');
      }
    } on ApiException catch (error) {
      _snack(error.detail);
    }
  }

  Future<void> _publish() async {
    final current = _selected;
    if (current == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('发布反馈？'),
        content: const Text('发布后会形成正式学习证据并更新学生掌握度。请确认教师复核已经完成。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('确认发布'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    if (!mounted) return;
    try {
      final value = await AppScope.of(
        context,
      ).api.publishTeachingFeedback(current.id);
      if (mounted) setState(() => _selected = value);
    } on ApiException catch (error) {
      _snack(error.detail);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: const BackButton(),
        title: Text('${widget.assignment.title} · 批改'),
        actions: [
          TextButton.icon(
            onPressed: _working ? null : _analyzeAll,
            icon: const Icon(LucideIcons.sparkles, size: 17),
            label: Text(_working ? '分析中' : '分析全部提交'),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
          : _submissions.isEmpty
          ? const _TeachingEmpty(title: '暂无提交', message: '学生提交后可在这里启动分析并复核。')
          : LayoutBuilder(
              builder: (context, constraints) {
                final queue = _SubmissionQueue(
                  submissions: _submissions,
                  selected: _selected,
                  onSelect: _select,
                );
                final detail = _selected == null
                    ? const _TeachingEmpty(
                        title: '选择一份提交',
                        message: '从左侧队列选择学生提交。',
                      )
                    : _ReviewDetail(
                        submission: _selected!,
                        scores: _scores,
                        feedback: _feedback,
                        knowledge: _knowledge,
                        errors: _errors,
                        onAnalyze: _analyze,
                        onSave: _saveReview,
                        onPublish: _publish,
                      );
                if (constraints.maxWidth < 820) {
                  return Column(
                    children: [
                      SizedBox(height: 170, child: queue),
                      const Divider(height: 1),
                      Expanded(child: detail),
                    ],
                  );
                }
                return Row(
                  children: [
                    SizedBox(width: 260, child: queue),
                    const VerticalDivider(width: 1),
                    Expanded(child: detail),
                  ],
                );
              },
            ),
    );
  }
}

class _AssignmentDraftResult {
  const _AssignmentDraftResult({
    required this.title,
    required this.instructions,
    required this.questions,
    this.dueAt,
  });

  final String title;
  final String instructions;
  final List<Map<String, dynamic>> questions;
  final DateTime? dueAt;
}

class _QuestionDraft {
  _QuestionDraft({
    String prompt = '',
    String points = '10',
    String rubric = '',
    String reference = '',
    this.isCode = false,
    this.kpId,
  }) : prompt = TextEditingController(text: prompt),
       points = TextEditingController(text: points),
       rubric = TextEditingController(text: rubric),
       reference = TextEditingController(text: reference);

  final TextEditingController prompt;
  final TextEditingController points;
  final TextEditingController rubric;
  final TextEditingController reference;
  bool isCode;
  String? kpId;

  _QuestionDraft copy() => _QuestionDraft(
    prompt: prompt.text,
    points: points.text,
    rubric: rubric.text,
    reference: reference.text,
    isCode: isCode,
    kpId: kpId,
  );

  void dispose() {
    prompt.dispose();
    points.dispose();
    rubric.dispose();
    reference.dispose();
  }
}

class _CreateAssignmentDialog extends StatefulWidget {
  const _CreateAssignmentDialog({required this.knowledge});
  final List<Map<String, dynamic>> knowledge;

  @override
  State<_CreateAssignmentDialog> createState() =>
      _CreateAssignmentDialogState();
}

class _CreateAssignmentDialogState extends State<_CreateAssignmentDialog> {
  final _title = TextEditingController();
  final _instructions = TextEditingController();
  final List<_QuestionDraft> _questions = [_QuestionDraft()];
  DateTime? _dueAt;
  String? _error;

  @override
  void dispose() {
    _title.dispose();
    _instructions.dispose();
    for (final question in _questions) {
      question.dispose();
    }
    super.dispose();
  }

  List<MapEntry<String, String>> get _knowledgeOptions {
    final values = <String, String>{};
    for (final item in widget.knowledge) {
      final id = item['kp_id']?.toString() ?? item['id']?.toString() ?? '';
      if (id.isEmpty) continue;
      values[id] = item['name']?.toString() ?? id;
    }
    return values.entries.toList();
  }

  Future<void> _pickDueAt() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: _dueAt ?? now.add(const Duration(days: 7)),
      firstDate: now,
      lastDate: now.add(const Duration(days: 730)),
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: _dueAt == null
          ? const TimeOfDay(hour: 23, minute: 59)
          : TimeOfDay.fromDateTime(_dueAt!),
    );
    if (time == null) return;
    setState(
      () => _dueAt = DateTime(
        date.year,
        date.month,
        date.day,
        time.hour,
        time.minute,
      ),
    );
  }

  void _addQuestion([_QuestionDraft? source]) {
    if (_questions.length >= 30) return;
    setState(() => _questions.add(source?.copy() ?? _QuestionDraft()));
  }

  void _removeQuestion(int index) {
    if (_questions.length == 1) return;
    final removed = _questions.removeAt(index);
    removed.dispose();
    setState(() {});
  }

  void _submit() {
    final title = _title.text.trim();
    if (title.isEmpty) {
      setState(() => _error = '请填写作业标题');
      return;
    }
    final questions = <Map<String, dynamic>>[];
    for (var index = 0; index < _questions.length; index++) {
      final draft = _questions[index];
      final prompt = draft.prompt.text.trim();
      final points = double.tryParse(draft.points.text.trim());
      if (prompt.isEmpty || points == null || points <= 0) {
        setState(() => _error = '请完整填写第 ${index + 1} 题的题目和有效分值');
        return;
      }
      questions.add({
        'question_type': draft.isCode ? 'code' : 'short_answer',
        'prompt': prompt,
        'max_points': points,
        'rubric': draft.rubric.text.trim(),
        'reference_answer': draft.reference.text.trim(),
        'kp_id': draft.kpId,
      });
    }
    Navigator.pop(
      context,
      _AssignmentDraftResult(
        title: title,
        instructions: _instructions.text.trim(),
        dueAt: _dueAt,
        questions: questions,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 680;
    return AlertDialog(
      title: const Text('新建诊断作业'),
      content: SizedBox(
        width: 720,
        height: MediaQuery.sizeOf(context).height * .72,
        child: Column(
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: TextField(
                    controller: _title,
                    autofocus: true,
                    decoration: const InputDecoration(labelText: '作业标题'),
                  ),
                ),
                if (!compact) ...[
                  const SizedBox(width: 10),
                  OutlinedButton.icon(
                    onPressed: _pickDueAt,
                    icon: const Icon(LucideIcons.calendarClock, size: 17),
                    label: Text(
                      _dueAt == null
                          ? '设置截止时间'
                          : '${_dueAt!.month}-${_dueAt!.day} ${_dueAt!.hour.toString().padLeft(2, '0')}:${_dueAt!.minute.toString().padLeft(2, '0')}',
                    ),
                  ),
                ],
              ],
            ),
            if (compact) ...[
              const SizedBox(height: 10),
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  onPressed: _pickDueAt,
                  icon: const Icon(LucideIcons.calendarClock, size: 17),
                  label: Text(_dueAt == null ? '设置截止时间' : '已设置截止时间'),
                ),
              ),
            ],
            const SizedBox(height: 10),
            TextField(
              controller: _instructions,
              maxLines: 2,
              decoration: const InputDecoration(labelText: '作业说明（可选）'),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Text(
                  '题目 ${_questions.length} / 30',
                  style: context.texts.titleMedium,
                ),
                const Spacer(),
                TextButton.icon(
                  onPressed: _questions.length >= 30 ? null : _addQuestion,
                  icon: const Icon(LucideIcons.plus, size: 16),
                  label: const Text('添加题目'),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Expanded(
              child: ListView.builder(
                itemCount: _questions.length,
                itemBuilder: (context, index) => _QuestionEditor(
                  key: ObjectKey(_questions[index]),
                  index: index,
                  draft: _questions[index],
                  knowledge: _knowledgeOptions,
                  canDelete: _questions.length > 1,
                  onChanged: () => setState(() {}),
                  onCopy: () => _addQuestion(_questions[index]),
                  onDelete: () => _removeQuestion(index),
                ),
              ),
            ),
            if (_error != null)
              Align(
                alignment: Alignment.centerLeft,
                child: Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    _error!,
                    style: TextStyle(color: context.scheme.error, fontSize: 12),
                  ),
                ),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(onPressed: _submit, child: const Text('保存草稿')),
      ],
    );
  }
}

class _QuestionEditor extends StatelessWidget {
  const _QuestionEditor({
    super.key,
    required this.index,
    required this.draft,
    required this.knowledge,
    required this.canDelete,
    required this.onChanged,
    required this.onCopy,
    required this.onDelete,
  });
  final int index;
  final _QuestionDraft draft;
  final List<MapEntry<String, String>> knowledge;
  final bool canDelete;
  final VoidCallback onChanged;
  final VoidCallback onCopy;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: context.scheme.surfaceContainerLow,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Column(
      children: [
        Row(
          children: [
            Text('第 ${index + 1} 题', style: context.texts.titleMedium),
            const Spacer(),
            IconButton(
              tooltip: '复制题目',
              onPressed: onCopy,
              icon: const Icon(LucideIcons.copy, size: 17),
            ),
            IconButton(
              tooltip: '删除题目',
              onPressed: canDelete ? onDelete : null,
              icon: const Icon(LucideIcons.trash2, size: 17),
            ),
          ],
        ),
        Row(
          children: [
            Expanded(
              child: SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('简答题')),
                  ButtonSegment(value: true, label: Text('代码文本题')),
                ],
                selected: {draft.isCode},
                onSelectionChanged: (value) {
                  draft.isCode = value.first;
                  onChanged();
                },
              ),
            ),
            const SizedBox(width: 10),
            SizedBox(
              width: 94,
              child: TextField(
                controller: draft.points,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: '分值'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        TextField(
          controller: draft.prompt,
          maxLines: 3,
          decoration: const InputDecoration(labelText: '题目内容'),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: draft.rubric,
          maxLines: 2,
          decoration: const InputDecoration(labelText: '评分标准'),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: draft.reference,
          maxLines: 2,
          decoration: const InputDecoration(labelText: '参考答案'),
        ),
        const SizedBox(height: 10),
        DropdownButtonFormField<String?>(
          initialValue: draft.kpId,
          isExpanded: true,
          decoration: const InputDecoration(labelText: '关联知识点（可选）'),
          items: [
            const DropdownMenuItem<String?>(value: null, child: Text('不关联知识点')),
            ...knowledge.map(
              (item) => DropdownMenuItem<String?>(
                value: item.key,
                child: Text(item.value, overflow: TextOverflow.ellipsis),
              ),
            ),
          ],
          onChanged: (value) => draft.kpId = value,
        ),
      ],
    ),
  );
}

class _PageHeader extends StatelessWidget {
  const _PageHeader({
    required this.eyebrow,
    required this.title,
    required this.subtitle,
    required this.action,
  });
  final String eyebrow;
  final String title;
  final String subtitle;
  final Widget action;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(24, 28, 24, 18),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(eyebrow, style: context.texts.labelSmall),
              const SizedBox(height: 7),
              Text(title, style: context.texts.headlineMedium),
              const SizedBox(height: 6),
              Text(subtitle, style: context.texts.bodySmall),
            ],
          ),
        ),
        const SizedBox(width: 16),
        action,
      ],
    ),
  );
}

class _WorkQueue extends StatelessWidget {
  const _WorkQueue({
    required this.pendingReview,
    required this.readyFeedback,
    required this.classCount,
  });
  final int pendingReview;
  final int readyFeedback;
  final int classCount;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(24, 0, 24, 18),
    child: Container(
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(color: context.n.divider),
          bottom: BorderSide(color: context.n.divider),
        ),
      ),
      padding: const EdgeInsets.symmetric(vertical: 15),
      child: Wrap(
        spacing: 12,
        runSpacing: 10,
        children: [
          _QueueItem(
            icon: LucideIcons.scanSearch,
            label: '待复核提交',
            value: '$pendingReview',
            color: const Color(0xFFE5A000),
          ),
          _QueueItem(
            icon: LucideIcons.send,
            label: '待发布反馈',
            value: '$readyFeedback',
            color: EsaColors.accent,
          ),
          _QueueItem(
            icon: LucideIcons.school,
            label: '活动班级',
            value: '$classCount',
            color: const Color(0xFF53B985),
          ),
        ],
      ),
    ),
  );
}

class _QueueItem extends StatelessWidget {
  const _QueueItem({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 220,
    child: Row(
      children: [
        Icon(icon, color: color, size: 19),
        const SizedBox(width: 10),
        Text(value, style: context.texts.titleLarge),
        const SizedBox(width: 7),
        Expanded(child: Text(label, style: context.texts.bodySmall)),
      ],
    ),
  );
}

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({required this.title, required this.trailing});
  final String title;
  final Widget trailing;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(24, 10, 24, 12),
    child: Row(
      children: [
        Text(title, style: context.texts.titleLarge),
        const Spacer(),
        trailing,
      ],
    ),
  );
}

class _ClassRow extends StatelessWidget {
  const _ClassRow({required this.classroom, required this.onTap});
  final TeachingClass classroom;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 10),
    child: InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
        child: Row(
          children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                color: EsaColors.accent.withValues(alpha: .15),
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(
                LucideIcons.school,
                color: EsaColors.accent,
                size: 19,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(classroom.name, style: context.texts.titleMedium),
                  const SizedBox(height: 4),
                  Text(
                    '${classroom.course}${classroom.term.isEmpty ? '' : ' · ${classroom.term}'}',
                    style: context.texts.bodySmall,
                  ),
                ],
              ),
            ),
            Text(
              '${classroom.studentCount} 名学生',
              style: context.texts.bodySmall,
            ),
            const SizedBox(width: 18),
            Text(
              '${classroom.openAssignmentCount} 个开放作业',
              style: context.texts.bodySmall,
            ),
            const SizedBox(width: 12),
            const Icon(LucideIcons.chevronRight, size: 18),
          ],
        ),
      ),
    ),
  );
}

class _ClassHeader extends StatelessWidget {
  const _ClassHeader({
    required this.classroom,
    required this.onBack,
    required this.tab,
    required this.onTab,
    required this.onInvite,
    required this.onCreateAssignment,
    required this.onOpenChat,
  });
  final TeachingClass classroom;
  final VoidCallback? onBack;
  final _ClassTab tab;
  final ValueChanged<_ClassTab> onTab;
  final VoidCallback onInvite;
  final VoidCallback onCreateAssignment;
  final Future<void> Function([TeachingAssignment?]) onOpenChat;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(24, 20, 24, 0),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            BackButton(onPressed: onBack),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(classroom.name, style: context.texts.headlineSmall),
                  const SizedBox(height: 4),
                  Text(
                    '${classroom.course}${classroom.term.isEmpty ? '' : ' · ${classroom.term}'}',
                    style: context.texts.bodySmall,
                  ),
                ],
              ),
            ),
            IconButton(
              tooltip: '打开班级对话',
              onPressed: () => onOpenChat(),
              icon: const Icon(LucideIcons.messageCircle),
            ),
            const SizedBox(width: 5),
            Tooltip(
              message: '邀请学生',
              child: IconButton(
                onPressed: onInvite,
                icon: const Icon(LucideIcons.userPlus),
              ),
            ),
            const SizedBox(width: 5),
            Tooltip(
              message: '新建作业',
              child: IconButton(
                onPressed: onCreateAssignment,
                icon: const Icon(LucideIcons.filePlus2),
              ),
            ),
          ],
        ),
        const SizedBox(height: 16),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: _ClassTab.values
                .map(
                  (item) => _TabButton(
                    label: _classTabLabel(item),
                    active: item == tab,
                    onTap: () => onTab(item),
                  ),
                )
                .toList(),
          ),
        ),
        const Divider(height: 1),
      ],
    ),
  );
}

String _classTabLabel(_ClassTab tab) => switch (tab) {
  _ClassTab.overview => '概览',
  _ClassTab.assignments => '作业',
  _ClassTab.students => '学生',
  _ClassTab.insights => '学情',
};

class _TabButton extends StatelessWidget {
  const _TabButton({
    required this.label,
    required this.active,
    required this.onTap,
  });
  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.fromLTRB(4, 10, 22, 11),
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(
            color: active ? EsaColors.accent : Colors.transparent,
            width: 2,
          ),
        ),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: active ? EsaColors.accent : context.n.n600,
          fontWeight: active ? FontWeight.w700 : FontWeight.w500,
        ),
      ),
    ),
  );
}

class _ClassOverview extends StatelessWidget {
  const _ClassOverview({
    required this.dashboard,
    required this.knowledge,
    required this.alerts,
    required this.onInsights,
  });
  final Map<String, dynamic>? dashboard;
  final List<Map<String, dynamic>> knowledge;
  final List<Map<String, dynamic>> alerts;
  final VoidCallback onInsights;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          _StatBlock(
            label: '学生人数',
            value: '${dashboard?['student_count'] ?? 0}',
            icon: LucideIcons.users,
          ),
          _StatBlock(
            label: '已发布证据',
            value: '${dashboard?['published_evidence_count'] ?? 0}',
            icon: LucideIcons.badgeCheck,
          ),
          _StatBlock(
            label: '关注学生',
            value: '${alerts.length}',
            icon: LucideIcons.circleAlert,
          ),
        ],
      ),
      const SizedBox(height: 24),
      _SectionTitleRow(
        title: '班级知识薄弱点',
        actionLabel: '查看学情',
        onTap: onInsights,
      ),
      const SizedBox(height: 10),
      if (knowledge.isEmpty)
        _MutedPanel(text: '暂无正式学习证据。发布学生反馈后会生成班级聚合。')
      else
        _KnowledgeRows(knowledge: knowledge, limit: 5),
      const SizedBox(height: 24),
      _SectionTitleRow(
        title: '关注学生',
        actionLabel: '${alerts.length} 人',
        onTap: null,
      ),
      const SizedBox(height: 10),
      if (alerts.isEmpty)
        _MutedPanel(text: '当前没有结构化关注项。')
      else
        ...alerts.take(5).map((raw) => _AlertRow(raw: raw)),
    ],
  );
}

class _AssignmentList extends StatelessWidget {
  const _AssignmentList({
    required this.assignments,
    required this.onCreate,
    required this.onOpenChat,
    required this.onPublish,
    required this.onReview,
  });
  final List<TeachingAssignment> assignments;
  final VoidCallback onCreate;
  final Future<void> Function([TeachingAssignment?]) onOpenChat;
  final Future<void> Function(TeachingAssignment) onPublish;
  final Future<void> Function(TeachingAssignment) onReview;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          Text('作业', style: context.texts.titleLarge),
          const Spacer(),
          FilledButton.icon(
            onPressed: onCreate,
            icon: const Icon(LucideIcons.plus, size: 17),
            label: const Text('新建诊断作业'),
          ),
        ],
      ),
      const SizedBox(height: 12),
      if (assignments.isEmpty)
        _MutedPanel(text: '还没有作业，从“新建诊断作业”开始。')
      else
        ...assignments.map(
          (item) => Card(
            margin: const EdgeInsets.only(bottom: 9),
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 16,
                vertical: 5,
              ),
              leading: Icon(
                item.status == 'draft'
                    ? LucideIcons.filePenLine
                    : LucideIcons.clipboardCheck,
                color: item.status == 'draft'
                    ? context.n.n600
                    : EsaColors.accent,
              ),
              title: Text(item.title),
              subtitle: Text(
                '${_assignmentStatus(item.status)} · ${item.submittedCount}/${item.studentCount} 已提交${item.dueAt == null ? '' : ' · 截止 ${_date(item.dueAt!)}'}',
              ),
              trailing: Wrap(
                spacing: 4,
                children: [
                  IconButton(
                    tooltip: '打开作业对话',
                    onPressed: () => onOpenChat(item),
                    icon: const Icon(LucideIcons.messageCircle, size: 18),
                  ),
                  if (item.status == 'draft')
                    TextButton(
                      onPressed: () => onPublish(item),
                      child: const Text('发布'),
                    )
                  else
                    TextButton(
                      onPressed: () => onReview(item),
                      child: const Text('打开批改'),
                    ),
                ],
              ),
              onTap: item.status == 'draft' ? null : () => onReview(item),
            ),
          ),
        ),
    ],
  );
}

String _assignmentStatus(String status) => switch (status) {
  'draft' => '草稿',
  'published' => '已发布',
  _ => status,
};
String _date(DateTime value) =>
    '${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

class _StudentList extends StatelessWidget {
  const _StudentList({
    required this.classroom,
    required this.members,
    required this.onChanged,
  });
  final TeachingClass classroom;
  final List<Map<String, dynamic>> members;
  final Future<void> Function() onChanged;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text('学生', style: context.texts.titleLarge),
      const SizedBox(height: 12),
      if (members.isEmpty)
        _MutedPanel(text: '尚未邀请学生。')
      else
        ...members.map((raw) {
          final status = raw['status']?.toString() ?? 'pending';
          return Card(
            margin: const EdgeInsets.only(bottom: 8),
            child: ListTile(
              leading: CircleAvatar(
                radius: 17,
                backgroundColor: EsaColors.accent.withValues(alpha: .16),
                child: Text(
                  (raw['student_username']?.toString() ?? '学').characters.first,
                ),
              ),
              title: Text(raw['student_username']?.toString() ?? '未命名学生'),
              subtitle: Text(
                status == 'active'
                    ? '已加入 · ${raw['submission_count'] ?? 0} 次提交'
                    : '邀请状态：${_memberStatus(status)}',
              ),
              trailing: const Icon(LucideIcons.chevronRight, size: 17),
              onTap: () async {
                final studentId = raw['student_id']?.toString() ?? '';
                if (studentId.isEmpty) return;
                await Navigator.of(context).push<void>(
                  MaterialPageRoute(
                    builder: (_) => AppScope(
                      state: AppScope.of(context),
                      child: TeachingStudentPage(
                        classroom: classroom,
                        studentId: studentId,
                        studentUsername:
                            raw['student_username']?.toString() ?? '学生',
                      ),
                    ),
                  ),
                );
                await onChanged();
              },
            ),
          );
        }),
    ],
  );
}

class TeachingStudentPage extends StatefulWidget {
  const TeachingStudentPage({
    super.key,
    required this.classroom,
    required this.studentId,
    required this.studentUsername,
  });

  final TeachingClass classroom;
  final String studentId;
  final String studentUsername;

  @override
  State<TeachingStudentPage> createState() => _TeachingStudentPageState();
}

class _TeachingStudentPageState extends State<TeachingStudentPage> {
  Map<String, dynamic>? _summary;
  String? _error;
  bool _loading = true;
  bool _requestedLoad = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_requestedLoad) {
      _requestedLoad = true;
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final value = await AppScope.of(
        context,
      ).api.getTeachingStudent(widget.classroom.id, widget.studentId);
      if (mounted) setState(() => _summary = value);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _remove() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('移除学生？'),
        content: Text(
          '将 ${widget.studentUsername} 移出 ${widget.classroom.name}。已有正式教学证据不会被伪造或改写。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: TextButton.styleFrom(
              foregroundColor: Theme.of(context).colorScheme.error,
            ),
            child: const Text('移除学生'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await AppScope.of(
        context,
      ).api.removeTeachingStudent(widget.classroom.id, widget.studentId);
      if (mounted) Navigator.pop(context);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.detail)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final evidence = (_summary?['evidence'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    final submissions = (_summary?['submissions'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
    final byKnowledge = <String, List<double>>{};
    for (final row in evidence) {
      final kp = row['kp_id']?.toString();
      final score = (row['final_score'] as num?)?.toDouble();
      final max = (row['max_points'] as num?)?.toDouble();
      if (kp != null &&
          kp.isNotEmpty &&
          score != null &&
          max != null &&
          max > 0) {
        byKnowledge.putIfAbsent(kp, () => []).add(score / max);
      }
    }
    return Scaffold(
      appBar: AppBar(
        title: const Text('学生详情'),
        actions: [
          IconButton(
            tooltip: '移除学生',
            onPressed: _remove,
            icon: const Icon(LucideIcons.userRoundMinus),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
          : _error != null
          ? _TeachingEmpty(title: '学生详情加载失败', message: _error!, onRetry: _load)
          : ListView(
              padding: const EdgeInsets.fromLTRB(24, 18, 24, 36),
              children: [
                Row(
                  children: [
                    CircleAvatar(
                      radius: 28,
                      backgroundColor: EsaColors.accent.withValues(alpha: .18),
                      child: Text(
                        widget.studentUsername.characters.firstOrNull ?? '学',
                        style: context.texts.titleLarge,
                      ),
                    ),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            widget.studentUsername,
                            style: context.texts.headlineSmall,
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '${widget.classroom.name} · 仅本班正式教学证据',
                            style: context.texts.bodySmall,
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _StatBlock(
                      label: '提交记录',
                      value: '${submissions.length}',
                      icon: LucideIcons.clipboardList,
                    ),
                    _StatBlock(
                      label: '正式证据',
                      value: '${evidence.length}',
                      icon: LucideIcons.badgeCheck,
                    ),
                    _StatBlock(
                      label: '已评估知识点',
                      value: '${byKnowledge.length}',
                      icon: LucideIcons.network,
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                Text('知识表现', style: context.texts.titleLarge),
                const SizedBox(height: 10),
                if (byKnowledge.isEmpty)
                  const _MutedPanel(text: '暂无已发布的知识点评估证据。')
                else
                  ...byKnowledge.entries.map((entry) {
                    final ratio =
                        entry.value.reduce((a, b) => a + b) /
                        entry.value.length;
                    return Container(
                      padding: const EdgeInsets.symmetric(vertical: 11),
                      decoration: BoxDecoration(
                        border: Border(
                          bottom: BorderSide(color: context.n.divider),
                        ),
                      ),
                      child: Row(
                        children: [
                          SizedBox(width: 180, child: Text(entry.key)),
                          Expanded(
                            child: LinearProgressIndicator(
                              value: ratio,
                              minHeight: 6,
                              borderRadius: BorderRadius.circular(4),
                              color: ratio < .6
                                  ? const Color(0xFFE5A000)
                                  : const Color(0xFF53B985),
                              backgroundColor: context.n.n200,
                            ),
                          ),
                          const SizedBox(width: 14),
                          SizedBox(
                            width: 48,
                            child: Text(
                              '${(ratio * 100).round()}%',
                              textAlign: TextAlign.right,
                            ),
                          ),
                        ],
                      ),
                    );
                  }),
                const SizedBox(height: 24),
                Text('最近提交', style: context.texts.titleLarge),
                const SizedBox(height: 10),
                if (submissions.isEmpty)
                  const _MutedPanel(text: '该学生还没有提交记录。')
                else
                  ...submissions.map(
                    (raw) => ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(LucideIcons.fileCheck2, size: 19),
                      title: Text(raw['title']?.toString() ?? '未命名作业'),
                      subtitle: Text(
                        _feedbackStatus(
                          raw['feedback_status']?.toString() ?? '',
                        ),
                      ),
                      trailing: Text(
                        raw['total_score'] == null
                            ? '待评分'
                            : '${raw['total_score']} / ${raw['total_points'] ?? '-'}',
                      ),
                    ),
                  ),
              ],
            ),
    );
  }
}

String _memberStatus(String status) => switch (status) {
  'pending' => '待接受',
  'rejected' => '已拒绝',
  'removed' => '已移除',
  _ => status,
};

class _InsightsList extends StatelessWidget {
  const _InsightsList({required this.knowledge, required this.alerts});
  final List<Map<String, dynamic>> knowledge;
  final List<Map<String, dynamic>> alerts;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text('班级学情', style: context.texts.titleLarge),
      const SizedBox(height: 5),
      Text('基于已发布教学证据聚合，不把证据不足推断为确定结论。', style: context.texts.bodySmall),
      const SizedBox(height: 16),
      if (knowledge.isEmpty)
        _MutedPanel(text: '暂无可用知识证据。')
      else
        _KnowledgeRows(knowledge: knowledge),
      if (alerts.isNotEmpty) ...[
        const SizedBox(height: 22),
        Text('需要关注', style: context.texts.titleMedium),
        const SizedBox(height: 8),
        ...alerts.map((raw) => _AlertRow(raw: raw)),
      ],
    ],
  );
}

class _KnowledgeRows extends StatelessWidget {
  const _KnowledgeRows({required this.knowledge, this.limit});
  final List<Map<String, dynamic>> knowledge;
  final int? limit;

  @override
  Widget build(BuildContext context) => Column(
    children: knowledge.take(limit ?? knowledge.length).map((raw) {
      final ratio = (raw['average_score_ratio'] as num?)?.toDouble();
      final percentage = ratio == null ? null : (ratio * 100).round();
      final color = ratio == null
          ? context.n.n500
          : ratio < .6
          ? const Color(0xFFE5A000)
          : const Color(0xFF53B985);
      return Container(
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: context.n.divider)),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 160,
              child: Text(
                raw['name']?.toString() ?? raw['kp_id']?.toString() ?? '未命名知识点',
              ),
            ),
            Expanded(
              child: LinearProgressIndicator(
                value: ratio,
                minHeight: 6,
                borderRadius: BorderRadius.circular(4),
                color: color,
                backgroundColor: context.n.n200,
              ),
            ),
            const SizedBox(width: 16),
            SizedBox(
              width: 55,
              child: Text(
                percentage == null ? '证据不足' : '$percentage%',
                textAlign: TextAlign.right,
              ),
            ),
            const SizedBox(width: 18),
            SizedBox(
              width: 80,
              child: Text(
                '${raw['evaluated_student_count'] ?? 0} 人',
                style: context.texts.bodySmall,
                textAlign: TextAlign.right,
              ),
            ),
          ],
        ),
      );
    }).toList(),
  );
}

class _AlertRow extends StatelessWidget {
  const _AlertRow({required this.raw});
  final Map<String, dynamic> raw;

  @override
  Widget build(BuildContext context) => ListTile(
    contentPadding: EdgeInsets.zero,
    dense: true,
    leading: const Icon(
      LucideIcons.circleAlert,
      size: 18,
      color: Color(0xFFE5A000),
    ),
    title: Text(
      raw['student_username']?.toString() ??
          raw['knowledge_point']?.toString() ??
          '需要关注的学习证据',
    ),
    subtitle: Text(
      raw['reason']?.toString() ?? raw['message']?.toString() ?? '需要进一步诊断',
    ),
    trailing: Text(
      '关注',
      style: TextStyle(
        color: const Color(0xFFE5A000),
        fontSize: 12,
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}

class _SectionTitleRow extends StatelessWidget {
  const _SectionTitleRow({
    required this.title,
    required this.actionLabel,
    required this.onTap,
  });
  final String title;
  final String actionLabel;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Text(title, style: context.texts.titleLarge),
      const Spacer(),
      if (onTap != null)
        TextButton(onPressed: onTap, child: Text(actionLabel))
      else
        Text(actionLabel, style: context.texts.bodySmall),
    ],
  );
}

class _StatBlock extends StatelessWidget {
  const _StatBlock({
    required this.label,
    required this.value,
    required this.icon,
  });
  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Container(
    width: 190,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: context.scheme.surfaceContainerLow,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Row(
      children: [
        Icon(icon, color: EsaColors.accent, size: 20),
        const SizedBox(width: 12),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(value, style: context.texts.headlineSmall),
            Text(label, style: context.texts.bodySmall),
          ],
        ),
      ],
    ),
  );
}

class _MutedPanel extends StatelessWidget {
  const _MutedPanel({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: context.scheme.surfaceContainerLow,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Text(text, style: context.texts.bodySmall),
  );
}

class _SubmissionQueue extends StatelessWidget {
  const _SubmissionQueue({
    required this.submissions,
    required this.selected,
    required this.onSelect,
  });
  final List<TeachingSubmission> submissions;
  final TeachingSubmission? selected;
  final ValueChanged<TeachingSubmission> onSelect;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(10),
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(7, 4, 7, 10),
        child: Row(
          children: [
            Text('提交队列', style: context.texts.titleMedium),
            const Spacer(),
            Text('${submissions.length} 份', style: context.texts.bodySmall),
          ],
        ),
      ),
      ...submissions.map(
        (item) => ListTile(
          selected: item.id == selected?.id,
          dense: true,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          title: Text(item.studentUsername),
          subtitle: Text(
            '${_analysisStatus(item.analysisStatus)} · ${_feedbackStatus(item.feedbackStatus)}',
          ),
          trailing: item.totalScore == null
              ? null
              : Text(item.totalScore!.toStringAsFixed(1)),
          onTap: () => onSelect(item),
        ),
      ),
    ],
  );
}

String _analysisStatus(String status) => switch (status) {
  'completed' => 'AI 已分析',
  'failed' => '分析失败',
  'running' => '分析中',
  _ => '未分析',
};
String _feedbackStatus(String status) => switch (status) {
  'published' => '已发布',
  'ready' => '待发布',
  _ => '待教师复核',
};

class _ReviewDetail extends StatelessWidget {
  const _ReviewDetail({
    required this.submission,
    required this.scores,
    required this.feedback,
    required this.knowledge,
    required this.errors,
    required this.onAnalyze,
    required this.onSave,
    required this.onPublish,
  });
  final TeachingSubmission submission;
  final Map<String, TextEditingController> scores;
  final Map<String, TextEditingController> feedback;
  final Map<String, TextEditingController> knowledge;
  final Map<String, TextEditingController> errors;
  final VoidCallback onAnalyze;
  final VoidCallback onSave;
  final VoidCallback onPublish;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(22, 20, 22, 28),
    children: [
      Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  submission.studentUsername,
                  style: context.texts.headlineSmall,
                ),
                const SizedBox(height: 5),
                Text(
                  '${_analysisStatus(submission.analysisStatus)} · ${_feedbackStatus(submission.feedbackStatus)}',
                  style: context.texts.bodySmall,
                ),
              ],
            ),
          ),
          if (submission.analysisStatus != 'completed')
            OutlinedButton.icon(
              onPressed: onAnalyze,
              icon: const Icon(LucideIcons.sparkles, size: 17),
              label: const Text('AI 分析'),
            ),
        ],
      ),
      const SizedBox(height: 18),
      if (submission.answers.isEmpty)
        _MutedPanel(text: '这份提交没有可复核题目。')
      else
        ...submission.answers.asMap().entries.map((entry) {
          final index = entry.key;
          final answer = entry.value;
          final score =
              scores[answer.id] ??
              TextEditingController(
                text: (answer.finalScore ?? answer.aiScore ?? 0)
                    .toStringAsFixed(1),
              );
          final notes =
              feedback[answer.id] ??
              TextEditingController(text: answer.feedback);
          final kp =
              knowledge[answer.id] ??
              TextEditingController(text: answer.kpId ?? '');
          final error =
              errors[answer.id] ??
              TextEditingController(
                text:
                    (answer.raw['final_error_type'] ??
                            answer.raw['ai_error_type'])
                        ?.toString() ??
                    '',
              );
          return _AnswerReview(
            index: index + 1,
            answer: answer,
            score: score,
            feedback: notes,
            knowledge: kp,
            errorType: error,
          );
        }),
      const SizedBox(height: 10),
      Row(
        mainAxisAlignment: MainAxisAlignment.end,
        children: [
          OutlinedButton(onPressed: onSave, child: const Text('保存复核')),
          const SizedBox(width: 10),
          FilledButton.icon(
            onPressed: submission.feedbackStatus == 'ready' ? onPublish : null,
            icon: const Icon(LucideIcons.send, size: 17),
            label: const Text('发布反馈'),
          ),
        ],
      ),
    ],
  );
}

class _AnswerReview extends StatelessWidget {
  const _AnswerReview({
    required this.index,
    required this.answer,
    required this.score,
    required this.feedback,
    required this.knowledge,
    required this.errorType,
  });
  final int index;
  final TeachingAnswer answer;
  final TextEditingController score;
  final TextEditingController feedback;
  final TextEditingController knowledge;
  final TextEditingController errorType;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 14),
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: context.scheme.surfaceContainerLow,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text('题目 $index', style: context.texts.titleMedium),
            const Spacer(),
            Text(
              'AI 建议 ${answer.aiScore?.toStringAsFixed(1) ?? '-'} / ${answer.maxPoints.toStringAsFixed(1)}',
              style: context.texts.bodySmall,
            ),
          ],
        ),
        const SizedBox(height: 10),
        Text(answer.prompt),
        const SizedBox(height: 10),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: context.n.n100,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text('学生答案\n${answer.answerText}'),
        ),
        const SizedBox(height: 12),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 130,
              child: TextField(
                controller: score,
                keyboardType: TextInputType.number,
                decoration: InputDecoration(
                  labelText: '教师得分 / ${answer.maxPoints.toStringAsFixed(1)}',
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: TextField(
                controller: errorType,
                decoration: const InputDecoration(labelText: '错因类型'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        TextField(
          controller: knowledge,
          decoration: const InputDecoration(labelText: '关联知识点 ID'),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: feedback,
          maxLines: 3,
          decoration: const InputDecoration(labelText: '教师评语（学生可见）'),
        ),
      ],
    ),
  );
}

class _TeachingEmpty extends StatelessWidget {
  const _TeachingEmpty({
    required this.title,
    required this.message,
    this.onRetry,
  });
  final String title;
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(LucideIcons.presentation, size: 40),
          const SizedBox(height: 14),
          Text(title, style: context.texts.titleLarge),
          const SizedBox(height: 7),
          Text(
            message,
            textAlign: TextAlign.center,
            style: context.texts.bodySmall,
          ),
          if (onRetry != null) ...[
            const SizedBox(height: 14),
            OutlinedButton(onPressed: onRetry, child: const Text('重试')),
          ],
        ],
      ),
    ),
  );
}
