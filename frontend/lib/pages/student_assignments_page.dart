import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';

class StudentAssignmentsPage extends StatefulWidget {
  const StudentAssignmentsPage({
    super.key,
    required this.onOpenChat,
    this.onOpenChatWithPrompt,
    this.onHome,
  });

  final Future<void> Function(TeachingAssignment assignment) onOpenChat;
  final Future<void> Function(
    TeachingAssignment assignment, {
    String? initialPrompt,
  })?
  onOpenChatWithPrompt;
  final VoidCallback? onHome;

  @override
  State<StudentAssignmentsPage> createState() => _StudentAssignmentsPageState();
}

class _StudentAssignmentsPageState extends State<StudentAssignmentsPage> {
  List<TeachingClass> _classes = const [];
  List<TeachingAssignment> _assignments = const [];
  bool _loading = true;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loading && _classes.isEmpty && _assignments.isEmpty) _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final api = AppScope.of(context).api;
    try {
      final values = await Future.wait([
        api.listStudentClasses(),
        api.listStudentAssignments(),
      ]);
      if (!mounted) return;
      setState(() {
        _classes = values[0] as List<TeachingClass>;
        _assignments = values[1] as List<TeachingAssignment>;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } catch (_) {
      if (mounted) setState(() => _error = '无法连接教学服务，请稍后重试');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _respond(TeachingClass item, bool accept) async {
    final id = item.membershipId;
    if (id == null) return;
    try {
      await AppScope.of(context).api.respondClassInvitation(id, accept);
      await _load();
    } on ApiException catch (error) {
      if (mounted) _showError(error.detail);
    } catch (_) {
      if (mounted) _showError('无法连接教学服务，请稍后重试');
    }
  }

  void _showError(String message) => ScaffoldMessenger.of(
    context,
  ).showSnackBar(SnackBar(content: Text(message)));

  Future<void> _joinClass() async {
    final classCode = TextEditingController();
    final joined = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('加入班级'),
        content: TextField(
          controller: classCode,
          autofocus: true,
          textCapitalization: TextCapitalization.characters,
          maxLength: 8,
          decoration: const InputDecoration(labelText: '8 位班级号'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('加入'),
          ),
        ],
      ),
    );
    if (joined == true && mounted) {
      try {
        await AppScope.of(context).api.joinTeachingClass(classCode.text);
        await _load();
      } on ApiException catch (error) {
        if (mounted) _showError(error.detail);
      }
    }
    classCode.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final invitations = _classes
        .where((item) => item.membershipStatus == 'pending')
        .toList();
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _load,
        child: CustomScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(24, 28, 24, 12),
              sliver: SliverToBoxAdapter(
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('作业中心', style: context.texts.headlineMedium),
                          const SizedBox(height: 6),
                          Text(
                            '查看班级邀请、完成作业并接收教师反馈。',
                            style: context.texts.bodyMedium?.copyWith(
                              color: context.n.n600,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      tooltip: '加入班级',
                      onPressed: _joinClass,
                      icon: const Icon(LucideIcons.userPlus),
                    ),
                    IconButton(
                      tooltip: '刷新',
                      onPressed: _load,
                      icon: const Icon(LucideIcons.refreshCw),
                    ),
                  ],
                ),
              ),
            ),
            if (_loading)
              const SliverFillRemaining(
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_error != null)
              SliverFillRemaining(
                child: _MessageState(
                  icon: LucideIcons.circleAlert,
                  title: '作业中心加载失败',
                  message: _error!,
                  action: _load,
                ),
              )
            else ...[
              if (invitations.isNotEmpty)
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 12),
                  sliver: SliverList.separated(
                    itemCount: invitations.length,
                    separatorBuilder: (_, _) => const SizedBox(height: 10),
                    itemBuilder: (context, index) {
                      final item = invitations[index];
                      return Card(
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Wrap(
                            spacing: 12,
                            runSpacing: 12,
                            crossAxisAlignment: WrapCrossAlignment.center,
                            children: [
                              const Icon(LucideIcons.mailOpen, size: 20),
                              SizedBox(
                                width: 280,
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      item.name,
                                      style: context.texts.titleMedium,
                                    ),
                                    Text(
                                      '${item.course} · 教师 ${item.teacherUsername ?? ''}',
                                    ),
                                    if (item.classCode != null)
                                      Text('班级号：${item.classCode}'),
                                  ],
                                ),
                              ),
                              OutlinedButton(
                                onPressed: () => _respond(item, false),
                                child: const Text('拒绝'),
                              ),
                              FilledButton(
                                onPressed: () => _respond(item, true),
                                child: const Text('接受邀请'),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
              if (_assignments.isEmpty)
                const SliverFillRemaining(
                  hasScrollBody: false,
                  child: _MessageState(
                    icon: LucideIcons.clipboardCheck,
                    title: '暂无作业',
                    message: '教师发布作业后会显示在这里。你仍可浏览原有课程的全部知识点。',
                  ),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 32),
                  sliver: SliverGrid.builder(
                    gridDelegate:
                        const SliverGridDelegateWithMaxCrossAxisExtent(
                          maxCrossAxisExtent: 430,
                          mainAxisExtent: 190,
                          crossAxisSpacing: 14,
                          mainAxisSpacing: 14,
                        ),
                    itemCount: _assignments.length,
                    itemBuilder: (context, index) {
                      final item = _assignments[index];
                      return _AssignmentCard(
                        item: item,
                        onTap: () async {
                          await Navigator.of(context).push<void>(
                            MaterialPageRoute(
                              builder: (_) => AppScope(
                                state: AppScope.of(context),
                                child: StudentAssignmentPage(
                                  assignment: item,
                                  onOpenChat: widget.onOpenChat,
                                  onOpenChatWithPrompt:
                                      widget.onOpenChatWithPrompt,
                                  onHome: widget.onHome,
                                ),
                              ),
                            ),
                          );
                          await _load();
                        },
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

class _AssignmentCard extends StatelessWidget {
  const _AssignmentCard({required this.item, required this.onTap});
  final TeachingAssignment item;
  final VoidCallback onTap;

  String get _status {
    if (item.feedbackStatus == 'published') return '已反馈';
    if (item.submissionId != null) return '已提交';
    return '待完成';
  }

  @override
  Widget build(BuildContext context) => Card(
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(_status, style: TextStyle(color: context.scheme.primary)),
                const Spacer(),
                Text('${item.totalPoints.toStringAsFixed(0)} 分'),
              ],
            ),
            const SizedBox(height: 12),
            Text(item.title, style: context.texts.titleLarge),
            const SizedBox(height: 6),
            Text('${item.className} · ${item.course}'),
            const Spacer(),
            Row(
              children: [
                const Icon(LucideIcons.clock3, size: 15),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    item.dueAt == null
                        ? '无截止时间'
                        : '${item.dueAt!.month}月${item.dueAt!.day}日截止',
                  ),
                ),
                const Icon(LucideIcons.arrowRight, size: 17),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}

class StudentAssignmentPage extends StatefulWidget {
  const StudentAssignmentPage({
    super.key,
    required this.assignment,
    required this.onOpenChat,
    this.onOpenChatWithPrompt,
    this.onHome,
  });
  final TeachingAssignment assignment;
  final Future<void> Function(TeachingAssignment assignment) onOpenChat;
  final Future<void> Function(
    TeachingAssignment assignment, {
    String? initialPrompt,
  })?
  onOpenChatWithPrompt;
  final VoidCallback? onHome;

  @override
  State<StudentAssignmentPage> createState() => _StudentAssignmentPageState();
}

class _StudentAssignmentPageState extends State<StudentAssignmentPage> {
  TeachingAssignment? _detail;
  TeachingSubmission? _submission;
  final Map<String, TextEditingController> _answers = {};
  bool _loading = true;
  bool _saving = false;
  String? _error;
  bool _requestedLoad = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedLoad) return;
    _requestedLoad = true;
    _load();
  }

  Future<void> _load() async {
    try {
      final api = AppScope.of(context).api;
      final detail = await api.getStudentAssignment(widget.assignment.id);
      TeachingSubmission? submission;
      if (widget.assignment.submissionId case final id?) {
        submission = await api.getStudentSubmission(id);
      }
      if (!mounted) return;
      for (final question in detail.questions) {
        _answers.putIfAbsent(question.id, TextEditingController.new);
      }
      setState(() {
        _detail = detail;
        _submission = submission;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _submit() async {
    final detail = _detail;
    if (detail == null) return;
    if (_answers.values.any((item) => item.text.trim().isEmpty)) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请完成全部题目后再提交')));
      return;
    }
    setState(() => _saving = true);
    try {
      final submission = await AppScope.of(context).api.submitAssignment(
        detail.id,
        _answers.map((key, value) => MapEntry(key, value.text.trim())),
      );
      if (mounted) setState(() => _submission = submission);
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.detail)));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  void dispose() {
    for (final controller in _answers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(widget.assignment.title)),
    body: _loading
        ? const Center(child: CircularProgressIndicator())
        : _error != null
        ? _MessageState(
            icon: LucideIcons.circleAlert,
            title: '无法打开作业',
            message: _error!,
          )
        : ListView(
            padding: const EdgeInsets.all(24),
            children: [
              Text(_detail!.title, style: context.texts.headlineSmall),
              if (_detail!.instructions.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(_detail!.instructions),
              ],
              const SizedBox(height: 20),
              if (_submission == null)
                ..._detail!.questions.map(
                  (question) => Card(
                    margin: const EdgeInsets.only(bottom: 14),
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${question.prompt}  ·  ${question.maxPoints.toStringAsFixed(0)} 分',
                            style: context.texts.titleMedium,
                          ),
                          const SizedBox(height: 12),
                          TextField(
                            controller: _answers[question.id],
                            minLines: question.type == 'code' ? 8 : 4,
                            maxLines: 14,
                            style: question.type == 'code'
                                ? const TextStyle(fontFamily: 'JetBrainsMono')
                                : null,
                            decoration: const InputDecoration(
                              hintText: '输入你的答案',
                              border: OutlineInputBorder(),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                )
              else
                ..._submission!.answers.map(
                  (answer) => Card(
                    margin: const EdgeInsets.only(bottom: 14),
                    child: Padding(
                      padding: const EdgeInsets.all(18),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(answer.prompt, style: context.texts.titleMedium),
                          const SizedBox(height: 10),
                          Text('你的答案：${answer.answerText}'),
                          const SizedBox(height: 12),
                          if (_submission!.feedbackStatus == 'published') ...[
                            Text(
                              '${answer.finalScore?.toStringAsFixed(1) ?? '-'} / ${answer.maxPoints.toStringAsFixed(1)} 分',
                              style: context.texts.titleMedium,
                            ),
                            if (answer.feedback.isNotEmpty)
                              Text(answer.feedback),
                            if (answer.kpId != null)
                              Text('关联知识点：${answer.kpId}'),
                          ] else
                            const Text('已提交，等待 AI 分析与教师复核。'),
                        ],
                      ),
                    ),
                  ),
                ),
              const SizedBox(height: 10),
              if (_submission == null)
                FilledButton.icon(
                  onPressed: _saving ? null : _submit,
                  icon: const Icon(LucideIcons.send, size: 17),
                  label: Text(_saving ? '提交中' : '确认提交'),
                )
              else if (_submission!.feedbackStatus == 'published') ...[
                if (widget.onHome != null)
                  OutlinedButton.icon(
                    onPressed: () {
                      Navigator.pop(context);
                      widget.onHome!();
                    },
                    icon: const Icon(LucideIcons.house, size: 17),
                    label: const Text('返回首页'),
                  ),
                if (widget.onHome != null) const SizedBox(height: 10),
                FilledButton.icon(
                  onPressed: () async {
                    final prompt = _submission!.answers
                        .map(
                          (answer) =>
                              '题目：${answer.prompt}\n我的原答案：${answer.answerText}',
                        )
                        .join('\n\n');
                    Navigator.pop(context);
                    final open = widget.onOpenChatWithPrompt;
                    if (open != null) {
                      await open(widget.assignment, initialPrompt: prompt);
                    } else {
                      await widget.onOpenChat(widget.assignment);
                    }
                  },
                  icon: const Icon(LucideIcons.messageCircle, size: 17),
                  label: const Text('开始针对性学习'),
                ),
              ],
            ],
          ),
  );
}

class _MessageState extends StatelessWidget {
  const _MessageState({
    required this.icon,
    required this.title,
    required this.message,
    this.action,
  });
  final IconData icon;
  final String title;
  final String message;
  final VoidCallback? action;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 40),
          const SizedBox(height: 14),
          Text(title, style: context.texts.titleLarge),
          const SizedBox(height: 7),
          Text(message, textAlign: TextAlign.center),
          if (action != null) ...[
            const SizedBox(height: 14),
            OutlinedButton(onPressed: action, child: const Text('重试')),
          ],
        ],
      ),
    ),
  );
}
