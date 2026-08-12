import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';

class TeachingWorkspacePage extends StatefulWidget {
  const TeachingWorkspacePage({super.key});

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
    if (_loading && _overview == null) _load();
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
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('创建班级'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: name, decoration: const InputDecoration(labelText: '班级名称')),
              const SizedBox(height: 10),
              TextField(controller: course, decoration: const InputDecoration(labelText: '课程目录中的准确名称')),
              const SizedBox(height: 10),
              TextField(controller: term, decoration: const InputDecoration(labelText: '学期')),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('创建')),
        ],
      ),
    );
    if (confirmed == true && mounted) {
      try {
        await AppScope.of(context).api.createTeachingClass(
          name: name.text.trim(),
          course: course.text.trim(),
          term: term.text.trim(),
        );
        await _load();
      } on ApiException catch (error) {
        if (mounted) _snack(error.detail);
      }
    }
    name.dispose();
    course.dispose();
    term.dispose();
  }

  void _snack(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

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
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 16),
              sliver: SliverToBoxAdapter(
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('教学工作台', style: context.texts.headlineMedium),
                          const SizedBox(height: 6),
                          Text('围绕班级、作业和学习证据处理日常教学任务。', style: TextStyle(color: context.n.n600)),
                        ],
                      ),
                    ),
                    FilledButton.icon(
                      key: const ValueKey('create-class'),
                      onPressed: _createClass,
                      icon: const Icon(LucideIcons.plus, size: 17),
                      label: const Text('创建班级'),
                    ),
                  ],
                ),
              ),
            ),
            if (_loading)
              const SliverFillRemaining(child: Center(child: CircularProgressIndicator()))
            else if (_error != null)
              SliverFillRemaining(child: _TeachingEmpty(title: '工作台加载失败', message: _error!, onRetry: _load))
            else ...[
              SliverPadding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                sliver: SliverToBoxAdapter(
                  child: Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      _Metric(label: '活动班级', value: '${_overview?['class_count'] ?? 0}', icon: LucideIcons.school),
                      _Metric(label: '待复核', value: '${_overview?['pending_review_count'] ?? 0}', icon: LucideIcons.scanSearch),
                      _Metric(label: '待发布反馈', value: '${_overview?['ready_feedback_count'] ?? 0}', icon: LucideIcons.send),
                    ],
                  ),
                ),
              ),
              if (classes.isEmpty)
                const SliverFillRemaining(
                  hasScrollBody: false,
                  child: _TeachingEmpty(title: '还没有班级', message: '创建班级后即可邀请学生并发布诊断作业。'),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(24, 22, 24, 32),
                  sliver: SliverGrid.builder(
                    gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                      maxCrossAxisExtent: 430,
                      mainAxisExtent: 190,
                      crossAxisSpacing: 14,
                      mainAxisSpacing: 14,
                    ),
                    itemCount: classes.length,
                    itemBuilder: (context, index) {
                      final item = classes[index];
                      return Card(
                        child: InkWell(
                          borderRadius: BorderRadius.circular(8),
                          onTap: () async {
                            await Navigator.of(context).push<void>(
                              MaterialPageRoute(
                                builder: (_) => AppScope(
                                  state: AppScope.of(context),
                                  child: TeachingClassPage(classroom: item),
                                ),
                              ),
                            );
                            await _load();
                          },
                          child: Padding(
                            padding: const EdgeInsets.all(18),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Icon(LucideIcons.school, size: 20),
                                const SizedBox(height: 14),
                                Text(item.name, style: context.texts.titleLarge),
                                const SizedBox(height: 5),
                                Text('${item.course}${item.term.isEmpty ? '' : ' · ${item.term}'}'),
                                const Spacer(),
                                Text('${item.studentCount} 名学生 · ${item.openAssignmentCount} 个开放作业'),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
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
  const TeachingClassPage({super.key, required this.classroom});
  final TeachingClass classroom;

  @override
  State<TeachingClassPage> createState() => _TeachingClassPageState();
}

class _TeachingClassPageState extends State<TeachingClassPage> with SingleTickerProviderStateMixin {
  Map<String, dynamic>? _detail;
  Map<String, dynamic>? _dashboard;
  bool _loading = true;
  bool _requestedLoad = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedLoad) return;
    _requestedLoad = true;
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final api = AppScope.of(context).api;
      final values = await Future.wait([
        api.getTeachingClass(widget.classroom.id),
        api.getClassDashboard(widget.classroom.id),
      ]);
      if (mounted) setState(() { _detail = values[0]; _dashboard = values[1]; });
    } on ApiException catch (error) {
      if (mounted) _snack(error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _snack(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  Future<void> _invite() async {
    final username = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('邀请学生'),
        content: TextField(controller: username, autofocus: true, decoration: const InputDecoration(labelText: '精确用户名')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('发送邀请')),
        ],
      ),
    );
    if (ok == true && mounted) {
      try {
        await AppScope.of(context).api.inviteStudent(widget.classroom.id, username.text.trim());
        await _load();
      } on ApiException catch (error) { if (mounted) _snack(error.detail); }
    }
    username.dispose();
  }

  Future<void> _createAssignment() async {
    final title = TextEditingController();
    final prompt = TextEditingController();
    final rubric = TextEditingController();
    final reference = TextEditingController();
    final kp = TextEditingController();
    final points = TextEditingController(text: '10');
    bool code = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('创建诊断作业'),
          content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(controller: title, decoration: const InputDecoration(labelText: '作业标题')),
                  const SizedBox(height: 10),
                  SegmentedButton<bool>(
                    segments: const [ButtonSegment(value: false, label: Text('简答题')), ButtonSegment(value: true, label: Text('代码题'))],
                    selected: {code},
                    onSelectionChanged: (value) => setDialogState(() => code = value.first),
                  ),
                  const SizedBox(height: 10),
                  TextField(controller: prompt, maxLines: 3, decoration: const InputDecoration(labelText: '题目')),
                  const SizedBox(height: 10),
                  TextField(controller: rubric, maxLines: 2, decoration: const InputDecoration(labelText: '评分标准')),
                  const SizedBox(height: 10),
                  TextField(controller: reference, maxLines: 2, decoration: const InputDecoration(labelText: '参考答案')),
                  const SizedBox(height: 10),
                  Row(children: [
                    Expanded(child: TextField(controller: kp, decoration: const InputDecoration(labelText: '知识点 ID'))),
                    const SizedBox(width: 10),
                    SizedBox(width: 100, child: TextField(controller: points, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: '分值'))),
                  ]),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('保存草稿')),
          ],
        ),
      ),
    );
    if (ok == true && mounted) {
      try {
        await AppScope.of(context).api.createTeachingAssignment(
          classId: widget.classroom.id,
          title: title.text.trim(),
          instructions: '',
          questions: [{
            'question_type': code ? 'code' : 'short_answer',
            'prompt': prompt.text.trim(),
            'max_points': double.tryParse(points.text) ?? 10,
            'rubric': rubric.text.trim(),
            'reference_answer': reference.text.trim(),
            'kp_id': kp.text.trim().isEmpty ? null : kp.text.trim(),
          }],
        );
        await _load();
      } on ApiException catch (error) { if (mounted) _snack(error.detail); }
    }
    for (final item in [title, prompt, rubric, reference, kp, points]) { item.dispose(); }
  }

  @override
  Widget build(BuildContext context) {
    final members = (_detail?['members'] as List? ?? const []).whereType<Map>().toList();
    final assignments = (_detail?['assignments'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => TeachingAssignment.fromJson(Map<String, dynamic>.from(item)))
        .toList();
    final knowledge = (_dashboard?['knowledge_points'] as List? ?? const []).whereType<Map>().toList();
    final alerts = (_dashboard?['alerts'] as List? ?? const []).whereType<Map>().toList();
    return Scaffold(
      appBar: AppBar(title: Text(widget.classroom.name), actions: [
        IconButton(tooltip: '邀请学生', onPressed: _invite, icon: const Icon(LucideIcons.userPlus)),
        IconButton(tooltip: '新建作业', onPressed: _createAssignment, icon: const Icon(LucideIcons.filePlus2)),
      ]),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(24),
              children: [
                Wrap(spacing: 12, runSpacing: 12, children: [
                  _Metric(label: '活动学生', value: '${_dashboard?['student_count'] ?? 0}', icon: LucideIcons.users),
                  _Metric(label: '已发布证据', value: '${_dashboard?['published_evidence_count'] ?? 0}', icon: LucideIcons.badgeCheck),
                  _Metric(label: '关注学生', value: '${alerts.length}', icon: LucideIcons.circleAlert),
                ]),
                const SizedBox(height: 24),
                Text('班级知识薄弱点', style: context.texts.titleLarge),
                const SizedBox(height: 10),
                if (knowledge.isEmpty)
                  const Text('暂无正式学习证据。发布学生反馈后会生成班级聚合。')
                else
                  Wrap(
                    spacing: 10,
                    runSpacing: 10,
                    children: knowledge.map((raw) {
                      final ratio = (raw['average_score_ratio'] as num?)?.toDouble() ?? 0;
                      final color = ratio < .6 ? context.scheme.error : ratio < .8 ? const Color(0xFFE5A000) : const Color(0xFF1B8A5A);
                      return Container(
                        width: 210,
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(border: Border.all(color: color.withValues(alpha: .5)), borderRadius: BorderRadius.circular(8)),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(raw['name']?.toString() ?? '', style: context.texts.titleMedium),
                          const SizedBox(height: 5),
                          Text('平均表现 ${(ratio * 100).round()}% · ${raw['evaluated_student_count']} 人有证据'),
                        ]),
                      );
                    }).toList(),
                  ),
                const SizedBox(height: 26),
                Text('作业', style: context.texts.titleLarge),
                const SizedBox(height: 10),
                if (assignments.isEmpty) const Text('还没有作业。') else ...assignments.map(
                  (item) => Card(
                    margin: const EdgeInsets.only(bottom: 10),
                    child: ListTile(
                      leading: const Icon(LucideIcons.clipboardList),
                      title: Text(item.title),
                      subtitle: Text('${item.status == 'draft' ? '草稿' : '已发布'} · ${item.submittedCount}/${item.studentCount} 已提交'),
                      trailing: item.status == 'draft'
                          ? FilledButton(onPressed: () async { await AppScope.of(context).api.publishTeachingAssignment(item.id); await _load(); }, child: const Text('发布'))
                          : const Icon(LucideIcons.chevronRight),
                      onTap: item.status == 'draft' ? null : () async {
                        await Navigator.of(context).push<void>(MaterialPageRoute(builder: (_) => AppScope(state: AppScope.of(context), child: TeachingReviewPage(assignment: item))));
                        await _load();
                      },
                    ),
                  ),
                ),
                const SizedBox(height: 22),
                Text('学生', style: context.texts.titleLarge),
                const SizedBox(height: 10),
                if (members.isEmpty) const Text('尚未邀请学生。') else ...members.map((raw) => ListTile(
                  leading: const Icon(LucideIcons.userRound),
                  title: Text(raw['student_username']?.toString() ?? ''),
                  subtitle: Text(raw['status'] == 'active' ? '已加入 · ${raw['submission_count']} 次提交' : '邀请状态：${raw['status']}'),
                )),
              ],
            ),
    );
  }
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
  bool _requestedLoad = false;
  bool _working = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedLoad) return;
    _requestedLoad = true;
    _load();
  }

  Future<void> _load() async {
    final api = AppScope.of(context).api;
    final list = await api.listTeachingSubmissions(widget.assignment.id);
    if (!mounted) return;
    TeachingSubmission? selected;
    if (list.isNotEmpty) {
      selected = await api.getTeachingSubmission(list.first.id);
    }
    setState(() {
      _submissions = list;
      _selected = selected;
      _loading = false;
    });
  }

  Future<void> _select(TeachingSubmission item) async {
    final detail = await AppScope.of(context).api.getTeachingSubmission(item.id);
    if (mounted) setState(() => _selected = detail);
  }

  Future<void> _analyze() async {
    final current = _selected;
    if (current == null) return;
    final value = await AppScope.of(
      context,
    ).api.analyzeTeachingSubmission(current.id);
    if (mounted) setState(() => _selected = value);
  }

  Future<void> _analyzeAll() async {
    setState(() => _working = true);
    try {
      await AppScope.of(
        context,
      ).api.analyzeTeachingAssignment(widget.assignment.id);
      await _load();
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.detail)));
      }
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _review() async {
    final current = _selected;
    if (current == null) return;
    final api = AppScope.of(context).api;
    final reviews = <Map<String, dynamic>>[];
    for (final answer in current.answers) {
      final score = TextEditingController(
        text: (answer.finalScore ?? answer.aiScore ?? 0).toStringAsFixed(1),
      );
      final feedback = TextEditingController(text: answer.feedback);
      final kp = TextEditingController(text: answer.kpId ?? '');
      final accepted = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('复核：${answer.prompt}'),
          content: SizedBox(
            width: 480,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('学生答案：${answer.answerText}'),
                const SizedBox(height: 12),
                TextField(
                  controller: score,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    labelText:
                        '最终得分 / ${answer.maxPoints.toStringAsFixed(1)}',
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: feedback,
                  maxLines: 3,
                  decoration: const InputDecoration(labelText: '教师评语'),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: kp,
                  decoration: const InputDecoration(labelText: '知识点 ID'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确认本题'),
            ),
          ],
        ),
      );
      if (accepted != true) {
        score.dispose();
        feedback.dispose();
        kp.dispose();
        return;
      }
      reviews.add({
        'answer_id': answer.id,
        'score': double.tryParse(score.text) ?? 0,
        'error_type': answer.raw['ai_error_type'],
        'feedback': feedback.text.trim(),
        'kp_id': kp.text.trim().isEmpty ? null : kp.text.trim(),
      });
      score.dispose();
      feedback.dispose();
      kp.dispose();
    }
    final value = await api.reviewTeachingSubmission(current.id, reviews);
    if (mounted) setState(() => _selected = value);
  }

  Future<void> _publish() async {
    final current = _selected;
    if (current == null) return;
    final value = await AppScope.of(
      context,
    ).api.publishTeachingFeedback(current.id);
    if (mounted) setState(() => _selected = value);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
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
        ? const Center(child: CircularProgressIndicator())
        : _submissions.isEmpty
        ? const _TeachingEmpty(title: '暂无提交', message: '学生提交后可在这里启动分析并复核。')
        : LayoutBuilder(builder: (context, constraints) {
            final queue = SizedBox(
              width: constraints.maxWidth >= 760 ? 240 : double.infinity,
              child: ListView(
                shrinkWrap: true,
                children: _submissions.map((item) => ListTile(
                  selected: _selected?.id == item.id,
                  title: Text(item.studentUsername),
                  subtitle: Text('${item.analysisStatus} · ${item.feedbackStatus}'),
                  onTap: () => _select(item),
                )).toList(),
              ),
            );
            final detail = Expanded(child: _selected == null ? const SizedBox() : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Row(children: [
                  Expanded(child: Text(_selected!.studentUsername, style: context.texts.headlineSmall)),
                  if (_selected!.analysisStatus != 'completed') FilledButton.icon(onPressed: _analyze, icon: const Icon(LucideIcons.sparkles, size: 17), label: const Text('AI 分析')),
                  if (_selected!.analysisStatus == 'completed' && _selected!.feedbackStatus == 'unpublished') FilledButton(onPressed: _review, child: const Text('复核并调整')),
                  if (_selected!.feedbackStatus == 'ready') FilledButton(onPressed: _publish, child: const Text('发布反馈')),
                ]),
                const SizedBox(height: 16),
                ..._selected!.answers.map((answer) => Card(
                  margin: const EdgeInsets.only(bottom: 12),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(answer.prompt, style: context.texts.titleMedium),
                      const SizedBox(height: 8), Text('学生答案：${answer.answerText}'),
                      const SizedBox(height: 10),
                      Text('AI 建议：${answer.aiScore?.toStringAsFixed(1) ?? '-'} / ${answer.maxPoints.toStringAsFixed(1)}'),
                      if (answer.feedback.isNotEmpty) Text(answer.feedback),
                    ]),
                  ),
                )),
              ],
            ));
            return constraints.maxWidth >= 760
                ? Row(children: [queue, const VerticalDivider(width: 1), detail])
                : Column(children: [SizedBox(height: 160, child: queue), const Divider(height: 1), detail]);
          }),
  );
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value, required this.icon});
  final String label; final String value; final IconData icon;
  @override
  Widget build(BuildContext context) => Container(
    width: 190,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(color: context.scheme.surfaceContainerLow, border: Border.all(color: context.n.divider), borderRadius: BorderRadius.circular(8)),
    child: Row(children: [Icon(icon, size: 20), const SizedBox(width: 12), Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(value, style: context.texts.titleLarge), Text(label)])]),
  );
}

class _TeachingEmpty extends StatelessWidget {
  const _TeachingEmpty({required this.title, required this.message, this.onRetry});
  final String title; final String message; final VoidCallback? onRetry;
  @override
  Widget build(BuildContext context) => Center(child: Padding(
    padding: const EdgeInsets.all(28),
    child: Column(mainAxisSize: MainAxisSize.min, children: [
      const Icon(LucideIcons.presentation, size: 40), const SizedBox(height: 14),
      Text(title, style: context.texts.titleLarge), const SizedBox(height: 7), Text(message, textAlign: TextAlign.center),
      if (onRetry != null) ...[const SizedBox(height: 14), OutlinedButton(onPressed: onRetry, child: const Text('重试'))],
    ]),
  ));
}
