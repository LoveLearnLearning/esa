import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/esa_segmented.dart';
import 'schedule_page.dart';

enum PlannerTab { schedule, todo, deadline, goal }

const _todosStorageKey = 'esa.planner.todos';
const _goalsStorageKey = 'esa.planner.goals';

class _PlannerTodo {
  const _PlannerTodo({
    required this.id,
    required this.title,
    required this.createdAt,
    this.dueAt,
    this.done = false,
  });

  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime? dueAt;
  final bool done;

  _PlannerTodo copyWith({String? title, DateTime? dueAt, bool? done}) =>
      _PlannerTodo(
        id: id,
        title: title ?? this.title,
        createdAt: createdAt,
        dueAt: dueAt ?? this.dueAt,
        done: done ?? this.done,
      );

  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'created_at': createdAt.toIso8601String(),
    'due_at': dueAt?.toIso8601String() ?? '',
    'done': done,
  };

  factory _PlannerTodo.fromJson(Map<String, dynamic> json) => _PlannerTodo(
    id:
        json['id']?.toString() ??
        DateTime.now().microsecondsSinceEpoch.toString(),
    title: json['title']?.toString() ?? '',
    createdAt:
        DateTime.tryParse(json['created_at']?.toString() ?? '') ??
        DateTime.now(),
    dueAt: DateTime.tryParse(json['due_at']?.toString() ?? ''),
    done: json['done'] as bool? ?? false,
  );
}

class _PlannerGoal {
  const _PlannerGoal({
    required this.id,
    required this.title,
    required this.createdAt,
    this.description = '',
    this.targetAt,
    this.progress = 0,
  });

  final String id;
  final String title;
  final String description;
  final DateTime createdAt;
  final DateTime? targetAt;
  final int progress;

  _PlannerGoal copyWith({
    String? title,
    String? description,
    DateTime? targetAt,
    int? progress,
  }) => _PlannerGoal(
    id: id,
    title: title ?? this.title,
    description: description ?? this.description,
    createdAt: createdAt,
    targetAt: targetAt ?? this.targetAt,
    progress: progress ?? this.progress,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'description': description,
    'created_at': createdAt.toIso8601String(),
    'target_at': targetAt?.toIso8601String() ?? '',
    'progress': progress,
  };

  factory _PlannerGoal.fromJson(Map<String, dynamic> json) => _PlannerGoal(
    id:
        json['id']?.toString() ??
        DateTime.now().microsecondsSinceEpoch.toString(),
    title: json['title']?.toString() ?? '',
    description: json['description']?.toString() ?? '',
    createdAt:
        DateTime.tryParse(json['created_at']?.toString() ?? '') ??
        DateTime.now(),
    targetAt: DateTime.tryParse(json['target_at']?.toString() ?? ''),
    progress: ((json['progress'] as num?)?.toInt() ?? 0).clamp(0, 100).toInt(),
  );
}

class _DeadlineEntry {
  const _DeadlineEntry({
    required this.title,
    required this.dueAt,
    required this.isTodo,
    this.done = false,
    this.sourceId,
    this.assignment,
  });

  final String title;
  final DateTime dueAt;
  final bool isTodo;
  final bool done;
  final String? sourceId;
  final TeachingAssignment? assignment;
}

class PlannerPage extends StatefulWidget {
  const PlannerPage({
    super.key,
    this.initialTab = PlannerTab.schedule,
    this.onOpenAssignments,
  });

  final PlannerTab initialTab;
  final VoidCallback? onOpenAssignments;

  @override
  State<PlannerPage> createState() => _PlannerPageState();
}

class _PlannerPageState extends State<PlannerPage> {
  late PlannerTab _tab;
  List<_PlannerTodo> _todos = const [];
  List<_PlannerGoal> _goals = const [];
  List<TeachingAssignment> _assignments = const [];
  bool _localLoaded = false;
  bool _deadlineRequested = false;
  bool _loadingDeadlines = false;
  String? _deadlineError;

  @override
  void initState() {
    super.initState();
    _tab = widget.initialTab;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_localLoaded) return;
    _localLoaded = true;
    unawaited(_loadLocal());
  }

  @override
  void didUpdateWidget(covariant PlannerPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.initialTab != widget.initialTab &&
        _tab != widget.initialTab) {
      setState(() => _tab = widget.initialTab);
    }
  }

  Future<void> _loadLocal() async {
    final prefs = await SharedPreferences.getInstance();
    final todosRaw = prefs.getString(_todosStorageKey);
    final goalsRaw = prefs.getString(_goalsStorageKey);
    if (!mounted) return;
    setState(() {
      _todos = _decodeTodos(todosRaw);
      _goals = _decodeGoals(goalsRaw);
    });
    if (_tab == PlannerTab.deadline && !_deadlineRequested) {
      unawaited(_loadAssignments());
    }
  }

  List<_PlannerTodo> _decodeTodos(String? raw) {
    if (raw == null || raw.isEmpty) return const [];
    try {
      final list = jsonDecode(raw) as List;
      return list
          .whereType<Map>()
          .map((item) => _PlannerTodo.fromJson(Map<String, dynamic>.from(item)))
          .toList();
    } catch (_) {
      return const [];
    }
  }

  List<_PlannerGoal> _decodeGoals(String? raw) {
    if (raw == null || raw.isEmpty) return const [];
    try {
      final list = jsonDecode(raw) as List;
      return list
          .whereType<Map>()
          .map((item) => _PlannerGoal.fromJson(Map<String, dynamic>.from(item)))
          .toList();
    } catch (_) {
      return const [];
    }
  }

  Future<void> _saveTodos() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _todosStorageKey,
      jsonEncode(_todos.map((item) => item.toJson()).toList()),
    );
  }

  Future<void> _saveGoals() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _goalsStorageKey,
      jsonEncode(_goals.map((item) => item.toJson()).toList()),
    );
  }

  Future<void> _loadAssignments({bool force = false}) async {
    if (!force && _deadlineRequested) return;
    _deadlineRequested = true;
    setState(() {
      _loadingDeadlines = true;
      _deadlineError = null;
    });
    try {
      final api = AppScope.of(context).api;
      final all = await api.listStudentAssignments();
      final due = all.where((item) => item.dueAt != null).toList()
        ..sort((a, b) => a.dueAt!.compareTo(b.dueAt!));
      if (!mounted) return;
      setState(() => _assignments = due);
    } on ApiException catch (error) {
      if (mounted) setState(() => _deadlineError = error.detail);
    } catch (_) {
      if (mounted) {
        setState(() => _deadlineError = '作业截止时间暂时无法加载');
      }
    } finally {
      if (mounted) setState(() => _loadingDeadlines = false);
    }
  }

  void _selectTab(PlannerTab tab) {
    if (_tab == tab) return;
    setState(() => _tab = tab);
    if (tab == PlannerTab.deadline && !_deadlineRequested) {
      unawaited(_loadAssignments());
    }
  }

  Future<void> _addTodo() async {
    final titleController = TextEditingController();
    DateTime? dueAt;
    final created = await showDialog<_PlannerTodo>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) {
          Widget dateButton() => OutlinedButton.icon(
            onPressed: () async {
              final picked = await showDatePicker(
                context: context,
                initialDate:
                    dueAt ?? DateTime.now().add(const Duration(days: 1)),
                firstDate: DateTime(2020),
                lastDate: DateTime(2035),
              );
              if (picked != null) setDialogState(() => dueAt = picked);
            },
            icon: const Icon(LucideIcons.calendarDays, size: 16),
            label: Text(dueAt == null ? '选择截止日期' : _dateLabel(dueAt!)),
          );
          return AlertDialog(
            title: const Text('新建待办'),
            content: SizedBox(
              width: 420,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    key: const ValueKey('planner-todo-title'),
                    controller: titleController,
                    autofocus: true,
                    decoration: const InputDecoration(labelText: '待办内容'),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(width: double.infinity, child: dateButton()),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext),
                child: const Text('取消'),
              ),
              FilledButton(
                key: const ValueKey('planner-save-todo'),
                onPressed: () {
                  final title = titleController.text.trim();
                  if (title.isEmpty) return;
                  Navigator.pop(
                    dialogContext,
                    _PlannerTodo(
                      id: DateTime.now().microsecondsSinceEpoch.toString(),
                      title: title,
                      createdAt: DateTime.now(),
                      dueAt: dueAt,
                    ),
                  );
                },
                child: const Text('添加'),
              ),
            ],
          );
        },
      ),
    );
    titleController.dispose();
    if (created == null || !mounted) return;
    setState(() => _todos = [created, ..._todos]);
    await _saveTodos();
  }

  void _toggleTodo(String id, bool done) {
    setState(() {
      _todos = [
        for (final todo in _todos)
          todo.id == id ? todo.copyWith(done: done) : todo,
      ];
    });
    unawaited(_saveTodos());
  }

  void _deleteTodo(String id) {
    setState(() => _todos = _todos.where((item) => item.id != id).toList());
    unawaited(_saveTodos());
  }

  Future<void> _addGoal() async {
    final titleController = TextEditingController();
    final descriptionController = TextEditingController();
    DateTime? targetAt;
    var progress = 0;
    final created = await showDialog<_PlannerGoal>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('新建目标'),
          content: SizedBox(
            width: 440,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  key: const ValueKey('planner-goal-title'),
                  controller: titleController,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: '目标名称'),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: descriptionController,
                  minLines: 2,
                  maxLines: 3,
                  decoration: const InputDecoration(labelText: '目标说明'),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: () async {
                    final picked = await showDatePicker(
                      context: context,
                      initialDate:
                          targetAt ??
                          DateTime.now().add(const Duration(days: 30)),
                      firstDate: DateTime(2020),
                      lastDate: DateTime(2040),
                    );
                    if (picked != null) setDialogState(() => targetAt = picked);
                  },
                  icon: const Icon(LucideIcons.flag, size: 16),
                  label: Text(
                    targetAt == null ? '选择目标日期' : _dateLabel(targetAt!),
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Text('初始进度'),
                    const Spacer(),
                    Text('$progress%'),
                  ],
                ),
                Slider(
                  value: progress.toDouble(),
                  max: 100,
                  divisions: 10,
                  label: '$progress%',
                  onChanged: (value) =>
                      setDialogState(() => progress = value.round()),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('取消'),
            ),
            FilledButton(
              key: const ValueKey('planner-save-goal'),
              onPressed: () {
                final title = titleController.text.trim();
                if (title.isEmpty) return;
                Navigator.pop(
                  dialogContext,
                  _PlannerGoal(
                    id: DateTime.now().microsecondsSinceEpoch.toString(),
                    title: title,
                    description: descriptionController.text.trim(),
                    createdAt: DateTime.now(),
                    targetAt: targetAt,
                    progress: progress,
                  ),
                );
              },
              child: const Text('创建'),
            ),
          ],
        ),
      ),
    );
    titleController.dispose();
    descriptionController.dispose();
    if (created == null || !mounted) return;
    setState(() => _goals = [created, ..._goals]);
    await _saveGoals();
  }

  void _updateGoalProgress(String id, int progress) {
    setState(() {
      _goals = [
        for (final goal in _goals)
          goal.id == id
              ? goal.copyWith(progress: progress.clamp(0, 100).toInt())
              : goal,
      ];
    });
    unawaited(_saveGoals());
  }

  void _deleteGoal(String id) {
    setState(() => _goals = _goals.where((item) => item.id != id).toList());
    unawaited(_saveGoals());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _header(context),
            Expanded(child: _tabContent(context)),
          ],
        ),
      ),
    );
  }

  Widget _header(BuildContext context) {
    final pendingCount = _todos.where((item) => !item.done).length;
    final goalsCount = _goals.length;
    final action = switch (_tab) {
      PlannerTab.todo => FilledButton.icon(
        key: const ValueKey('planner-add-todo'),
        onPressed: _addTodo,
        icon: const Icon(LucideIcons.plus, size: 16),
        label: const Text('新建待办'),
      ),
      PlannerTab.goal => FilledButton.icon(
        key: const ValueKey('planner-add-goal'),
        onPressed: _addGoal,
        icon: const Icon(LucideIcons.plus, size: 16),
        label: const Text('新建目标'),
      ),
      PlannerTab.deadline => IconButton(
        tooltip: '刷新截止时间',
        onPressed: _loadingDeadlines
            ? null
            : () => unawaited(_loadAssignments(force: true)),
        icon: _loadingDeadlines
            ? const SizedBox.square(
                dimension: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(LucideIcons.refreshCw, size: 18),
      ),
      PlannerTab.schedule => const SizedBox.shrink(),
    };
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(bottom: BorderSide(color: context.n.divider)),
      ),
      child: Column(
        children: [
          Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: EsaColors.accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(EsaRadii.button),
                ),
                child: const Icon(
                  LucideIcons.calendarDays,
                  size: 19,
                  color: EsaColors.accent,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('日程', style: context.texts.headlineSmall),
                    const SizedBox(height: 2),
                    Text(switch (_tab) {
                      PlannerTab.schedule => '查看每周课程安排',
                      PlannerTab.todo => '$pendingCount 项待办未完成',
                      PlannerTab.deadline => '作业与待办截止时间',
                      PlannerTab.goal => '$goalsCount 个目标进行中',
                    }, style: context.texts.bodySmall),
                  ],
                ),
              ),
              action,
            ],
          ),
          const SizedBox(height: 12),
          EsaSegmented<PlannerTab>(
            value: _tab,
            segments: const [
              EsaSegment(PlannerTab.schedule, '课表'),
              EsaSegment(PlannerTab.todo, 'Todo'),
              EsaSegment(PlannerTab.deadline, 'Deadline'),
              EsaSegment(PlannerTab.goal, 'Goal'),
            ],
            onChanged: _selectTab,
          ),
        ],
      ),
    );
  }

  Widget _tabContent(BuildContext context) => switch (_tab) {
    PlannerTab.schedule => const SchedulePage(),
    PlannerTab.todo => _todoView(context),
    PlannerTab.deadline => _deadlineView(context),
    PlannerTab.goal => _goalView(context),
  };

  Widget _todoView(BuildContext context) {
    if (_todos.isEmpty) {
      return _emptyState(
        context,
        icon: LucideIcons.clipboardCheck,
        title: '暂无待办',
        message: '把今天要做的事情记下来，日程页会帮你统一管理。',
      );
    }
    final pending = _todos.where((item) => !item.done).length;
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
      children: [
        Row(
          children: [
            Text('全部 ${_todos.length}', style: context.texts.titleMedium),
            const SizedBox(width: 12),
            Text('未完成 $pending', style: context.texts.bodySmall),
            const Spacer(),
            Text(
              '${(_todos.length - pending) / _todos.length * 100}%',
              style: context.texts.bodySmall,
            ),
          ],
        ),
        const SizedBox(height: 12),
        LinearProgressIndicator(
          value: (_todos.length - pending) / _todos.length,
          minHeight: 5,
        ),
        const SizedBox(height: 16),
        for (final todo in _todos) ...[
          _todoCard(context, todo),
          const SizedBox(height: 8),
        ],
      ],
    );
  }

  Widget _todoCard(BuildContext context, _PlannerTodo todo) {
    final overdue =
        !todo.done &&
        todo.dueAt != null &&
        todo.dueAt!.isBefore(DateTime.now());
    return Container(
      key: ValueKey('planner-todo-${todo.id}'),
      padding: const EdgeInsets.fromLTRB(12, 8, 6, 8),
      decoration: BoxDecoration(
        color: context.n.n100,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.card),
      ),
      child: Row(
        children: [
          Checkbox(
            value: todo.done,
            onChanged: (value) => _toggleTodo(todo.id, value ?? false),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  todo.title,
                  style: TextStyle(
                    decoration: todo.done ? TextDecoration.lineThrough : null,
                    color: todo.done ? context.n.n500 : null,
                  ),
                ),
                if (todo.dueAt != null) ...[
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      Icon(
                        overdue ? LucideIcons.circleAlert : LucideIcons.clock3,
                        size: 13,
                        color: overdue
                            ? const Color(0xFFE5484D)
                            : context.n.n500,
                      ),
                      const SizedBox(width: 5),
                      Text(
                        overdue
                            ? '已逾期 ${_dateLabel(todo.dueAt!)}'
                            : _dateLabel(todo.dueAt!),
                        style: TextStyle(
                          fontSize: 12,
                          color: overdue
                              ? const Color(0xFFE5484D)
                              : context.n.n500,
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          IconButton(
            tooltip: '删除待办',
            onPressed: () => _deleteTodo(todo.id),
            icon: const Icon(LucideIcons.trash2, size: 17),
          ),
        ],
      ),
    );
  }

  Widget _deadlineView(BuildContext context) {
    final entries = <_DeadlineEntry>[
      for (final todo in _todos.where((item) => item.dueAt != null))
        _DeadlineEntry(
          title: todo.title,
          dueAt: todo.dueAt!,
          isTodo: true,
          done: todo.done,
          sourceId: todo.id,
        ),
      for (final assignment in _assignments)
        _DeadlineEntry(
          title: assignment.title,
          dueAt: assignment.dueAt!,
          isTodo: false,
          done: assignment.submissionId != null,
          sourceId: assignment.id,
          assignment: assignment,
        ),
    ]..sort((a, b) => a.dueAt.compareTo(b.dueAt));
    if (entries.isEmpty && !_loadingDeadlines && _deadlineError == null) {
      return _emptyState(
        context,
        icon: LucideIcons.calendarClock,
        title: '暂无截止时间',
        message: '给待办设置截止日期，或等待教师发布作业。',
      );
    }
    final now = DateTime.now();
    final todayStart = DateTime(now.year, now.month, now.day);
    final tomorrowStart = todayStart.add(const Duration(days: 1));
    final overdue = entries
        .where((item) => !item.done && item.dueAt.isBefore(todayStart))
        .toList();
    final today = entries
        .where(
          (item) =>
              !item.done &&
              !item.dueAt.isBefore(todayStart) &&
              item.dueAt.isBefore(tomorrowStart),
        )
        .toList();
    final upcoming = entries
        .where((item) => !item.done && !item.dueAt.isBefore(tomorrowStart))
        .toList();
    final completed = entries.where((item) => item.done).toList();

    Widget section({
      required String title,
      required List<_DeadlineEntry> items,
      required IconData icon,
      Color? color,
    }) {
      if (items.isEmpty) return const SizedBox.shrink();
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 14, bottom: 8),
            child: Row(
              children: [
                Icon(icon, size: 16, color: color ?? context.n.n600),
                const SizedBox(width: 7),
                Text(title, style: context.texts.titleMedium),
                const SizedBox(width: 8),
                Text('${items.length}', style: context.texts.bodySmall),
              ],
            ),
          ),
          for (final item in items) ...[
            _deadlineCard(context, item),
            const SizedBox(height: 8),
          ],
        ],
      );
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
      children: [
        if (_deadlineError != null)
          Container(
            margin: const EdgeInsets.only(top: 10),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFE5484D).withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(EsaRadii.card),
            ),
            child: Row(
              children: [
                const Icon(
                  LucideIcons.circleAlert,
                  size: 16,
                  color: Color(0xFFE5484D),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '$_deadlineError，暂只显示本地待办截止时间。',
                    style: context.texts.bodySmall,
                  ),
                ),
              ],
            ),
          ),
        if (_loadingDeadlines && _assignments.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Center(child: CircularProgressIndicator()),
          ),
        section(
          title: '已逾期',
          items: overdue,
          icon: LucideIcons.circleAlert,
          color: const Color(0xFFE5484D),
        ),
        section(
          title: '今天',
          items: today,
          icon: LucideIcons.sun,
          color: const Color(0xFFD97706),
        ),
        section(
          title: '即将到来',
          items: upcoming,
          icon: LucideIcons.calendarClock,
        ),
        section(
          title: '已完成',
          items: completed,
          icon: LucideIcons.checkCircle2,
          color: const Color(0xFF059669),
        ),
      ],
    );
  }

  Widget _deadlineCard(BuildContext context, _DeadlineEntry entry) {
    final now = DateTime.now();
    final todayStart = DateTime(now.year, now.month, now.day);
    final overdue = !entry.done && entry.dueAt.isBefore(todayStart);
    return InkWell(
      key: ValueKey('planner-deadline-${entry.sourceId}'),
      onTap: entry.isTodo
          ? () => _toggleTodo(entry.sourceId!, !entry.done)
          : widget.onOpenAssignments,
      borderRadius: BorderRadius.circular(EsaRadii.card),
      child: Container(
        padding: const EdgeInsets.fromLTRB(13, 12, 10, 12),
        decoration: BoxDecoration(
          color: context.n.n100,
          border: Border.all(color: context.n.divider),
          borderRadius: BorderRadius.circular(EsaRadii.card),
        ),
        child: Row(
          children: [
            Container(
              width: 34,
              height: 34,
              decoration: BoxDecoration(
                color: overdue
                    ? const Color(0xFFE5484D).withValues(alpha: 0.12)
                    : EsaColors.accent.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Icon(
                entry.isTodo ? LucideIcons.listTodo : LucideIcons.clipboardList,
                size: 17,
                color: overdue ? const Color(0xFFE5484D) : EsaColors.accent,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    entry.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.texts.titleMedium?.copyWith(
                      decoration: entry.done
                          ? TextDecoration.lineThrough
                          : null,
                      color: entry.done ? context.n.n500 : null,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    entry.isTodo
                        ? '待办 · ${_dueLabel(entry.dueAt, now)}'
                        : '${entry.assignment?.course ?? '作业'} · ${_dueLabel(entry.dueAt, now)}',
                    style: context.texts.bodySmall,
                  ),
                ],
              ),
            ),
            Icon(
              entry.done ? LucideIcons.checkCircle2 : LucideIcons.chevronRight,
              size: 17,
              color: entry.done ? const Color(0xFF059669) : context.n.n500,
            ),
          ],
        ),
      ),
    );
  }

  Widget _goalView(BuildContext context) {
    if (_goals.isEmpty) {
      return _emptyState(
        context,
        icon: LucideIcons.flag,
        title: '暂无目标',
        message: '设定一个可追踪的目标，用进度条记录你的推进。',
      );
    }
    final average =
        _goals.fold<int>(0, (sum, item) => sum + item.progress) / _goals.length;
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
      children: [
        Row(
          children: [
            Text('目标 ${_goals.length}', style: context.texts.titleMedium),
            const SizedBox(width: 12),
            Text('平均进度 ${average.round()}%', style: context.texts.bodySmall),
          ],
        ),
        const SizedBox(height: 14),
        for (final goal in _goals) ...[
          _goalCard(context, goal),
          const SizedBox(height: 10),
        ],
      ],
    );
  }

  Widget _goalCard(BuildContext context, _PlannerGoal goal) {
    final achieved = goal.progress >= 100;
    return Container(
      key: ValueKey('planner-goal-${goal.id}'),
      padding: const EdgeInsets.fromLTRB(15, 14, 8, 10),
      decoration: BoxDecoration(
        color: context.n.n100,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.card),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                achieved ? LucideIcons.flag : LucideIcons.target,
                size: 17,
                color: achieved ? const Color(0xFF059669) : context.n.n700,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  goal.title,
                  style: context.texts.titleMedium?.copyWith(
                    decoration: achieved ? TextDecoration.lineThrough : null,
                  ),
                ),
              ),
              IconButton(
                tooltip: '删除目标',
                onPressed: () => _deleteGoal(goal.id),
                icon: const Icon(LucideIcons.trash2, size: 17),
              ),
            ],
          ),
          if (goal.description.isNotEmpty) ...[
            const SizedBox(height: 4),
            Padding(
              padding: const EdgeInsets.only(left: 25),
              child: Text(goal.description, style: context.texts.bodySmall),
            ),
          ],
          Padding(
            padding: const EdgeInsets.only(left: 25),
            child: Row(
              children: [
                Text(
                  '${goal.progress}%',
                  style: const TextStyle(
                    color: Color(0xFF4B8CFF),
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(width: 10),
                if (goal.targetAt != null)
                  Text(
                    '目标日期 ${_dateLabel(goal.targetAt!)}',
                    style: context.texts.bodySmall,
                  ),
              ],
            ),
          ),
          Slider(
            value: goal.progress.toDouble(),
            max: 100,
            divisions: 10,
            label: '${goal.progress}%',
            onChanged: (value) => _updateGoalProgress(goal.id, value.round()),
          ),
        ],
      ),
    );
  }

  Widget _emptyState(
    BuildContext context, {
    required IconData icon,
    required String title,
    required String message,
  }) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 36, color: context.n.n500),
          const SizedBox(height: 14),
          Text(title, style: context.texts.titleLarge),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: context.texts.bodySmall,
          ),
        ],
      ),
    ),
  );
}

String _dateLabel(DateTime value) =>
    '${value.year}年${value.month}月${value.day}日';

String _timeLabel(DateTime value) =>
    '${value.hour.toString().padLeft(2, '0')}:'
    '${value.minute.toString().padLeft(2, '0')}';

String _dueLabel(DateTime value, DateTime now) {
  final todayStart = DateTime(now.year, now.month, now.day);
  final tomorrowStart = todayStart.add(const Duration(days: 1));
  if (value.isBefore(todayStart)) {
    final days = todayStart.difference(value).inDays;
    return '已逾期 $days 天';
  }
  if (value.isBefore(tomorrowStart)) return '今天 ${_timeLabel(value)}';
  final days = value.difference(todayStart).inDays;
  return '${_dateLabel(value)} · $days 天后';
}
