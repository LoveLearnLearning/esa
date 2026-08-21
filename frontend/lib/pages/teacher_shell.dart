import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/profile_sheet.dart';
import 'chat_page.dart';
import 'personal_knowledge_base_page.dart';
import 'teaching_workspace_page.dart';

enum TeacherSection { learning, research, knowledgeBase, workbench, assistant }

class TeacherShell extends StatefulWidget {
  const TeacherShell({super.key});

  @override
  State<TeacherShell> createState() => _TeacherShellState();
}

class _TeacherShellState extends State<TeacherShell> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  TeacherSection _section = TeacherSection.workbench;
  TeachingClass? _selectedClass;
  Map<String, dynamic>? _overview;
  bool _sidebarCollapsed = false;
  bool _loadedOverview = false;
  String _sidebarQuery = '';

  List<TeachingClass> get _classes =>
      (_overview?['classes'] as List? ?? const [])
          .whereType<Map>()
          .map(
            (item) => TeachingClass.fromJson(Map<String, dynamic>.from(item)),
          )
          .toList();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_loadedOverview) {
      _loadedOverview = true;
      unawaited(_loadOverview());
    }
  }

  Future<void> _loadOverview() async {
    try {
      final value = await AppScope.of(context).api.getTeachingOverview();
      if (mounted) setState(() => _overview = value);
    } on ApiException {
      // The main workspace owns the visible retry state.
    }
  }

  Future<void> _select(TeacherSection section) async {
    FocusManager.instance.primaryFocus?.unfocus();
    final workspace = switch (section) {
      TeacherSection.learning => WorkspaceType.learning,
      TeacherSection.research => WorkspaceType.research,
      TeacherSection.knowledgeBase => WorkspaceType.teaching,
      TeacherSection.workbench ||
      TeacherSection.assistant => WorkspaceType.teaching,
    };
    final app = AppScope.of(context);
    if (app.activeWorkspace != workspace) await app.switchWorkspace(workspace);
    if (!mounted) return;
    setState(() {
      _section = section;
      if (section != TeacherSection.workbench) _selectedClass = null;
    });
  }

  void _openClass(TeachingClass classroom) {
    setState(() {
      _section = TeacherSection.workbench;
      _selectedClass = classroom;
    });
  }

  void _showWorkbench() {
    setState(() {
      _section = TeacherSection.workbench;
      _selectedClass = null;
    });
  }

  void _showTeachingAssistant() {
    setState(() {
      _section = TeacherSection.assistant;
      _selectedClass = null;
    });
  }

  Future<void> _createClassFromSidebar() async {
    final name = TextEditingController();
    final course = TextEditingController();
    final term = TextEditingController();
    final confirmed = await showDialog<bool>(
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
    if (confirmed == true && mounted) {
      try {
        final classroom = await AppScope.of(context).api.createTeachingClass(
          name: name.text.trim(),
          course: course.text.trim(),
          term: term.text.trim(),
        );
        await _loadOverview();
        if (mounted) _openClass(classroom);
      } on ApiException catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(error.detail)));
        }
      }
    }
    for (final controller in [name, course, term]) {
      controller.dispose();
    }
  }

  Future<void> _newConversation() async {
    final app = AppScope.of(context);
    if (app.activeWorkspace != WorkspaceType.teaching) {
      await app.switchWorkspace(WorkspaceType.teaching);
    }
    await app.newConversation();
    if (mounted) _showTeachingAssistant();
  }

  Future<void> _openConversation(ChatConversation conversation) async {
    final app = AppScope.of(context);
    if (app.activeWorkspace != conversation.workspaceType) {
      await app.switchWorkspace(conversation.workspaceType);
    }
    await app.setActive(conversation.id);
    if (!mounted) return;
    setState(() {
      _section = conversation.workspaceType == WorkspaceType.research
          ? TeacherSection.research
          : conversation.workspaceType == WorkspaceType.learning
          ? TeacherSection.learning
          : TeacherSection.assistant;
      _selectedClass = null;
    });
  }

  Widget _page() {
    if (_selectedClass != null) {
      return TeachingClassPage(
        key: ValueKey('teacher-class-${_selectedClass!.id}'),
        classroom: _selectedClass!,
        onBack: _showWorkbench,
        onOpenChat: _showTeachingAssistant,
      );
    }
    return switch (_section) {
      TeacherSection.workbench => TeachingWorkspacePage(
        key: const ValueKey('teacher-workbench'),
        onOpenChat: _showTeachingAssistant,
      ),
      TeacherSection.assistant => ChatPage(
        key: const ValueKey('teacher-assistant'),
        embedded: true,
        embeddedTitle: '教学助手',
        onExitEmbedded: _showWorkbench,
      ),
      TeacherSection.learning => const ChatPage(
        key: ValueKey('teacher-learning'),
        embedded: true,
        embeddedTitle: '学习空间',
      ),
      TeacherSection.research => const ChatPage(
        key: ValueKey('teacher-research'),
        embedded: true,
        embeddedTitle: '科研空间',
      ),
      TeacherSection.knowledgeBase => const PersonalKnowledgeBasePage(),
    };
  }

  @override
  Widget build(BuildContext context) =>
      MediaQuery.sizeOf(context).width >= 900 ? _desktop() : _mobile();

  Widget _desktop() {
    final knowledgeBase = _section == TeacherSection.knowledgeBase;
    final showInspector = MediaQuery.sizeOf(context).width >= 1200;
    final showLearning = AppScope.of(
      context,
    ).availableWorkspaces.any((item) => item.type == WorkspaceType.learning);
    return Scaffold(
      body: SafeArea(
        child: Row(
          children: [
            _TeacherRail(
              key: const ValueKey('teacher-global-rail'),
              section: _section,
              showLearning: showLearning,
              onSelect: (section) => unawaited(_select(section)),
              onProfile: () => showProfileSheet(context),
            ),
            AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              width: _sidebarCollapsed || knowledgeBase ? 0 : 272,
              clipBehavior: Clip.hardEdge,
              decoration: const BoxDecoration(),
              child: _sidebarCollapsed || knowledgeBase
                  ? const SizedBox.shrink()
                  : _TeacherSidebar(
                      section: _section,
                      selectedClass: _selectedClass,
                      classes: _classes,
                      overview: _overview,
                      query: _sidebarQuery,
                      onQueryChanged: (value) =>
                          setState(() => _sidebarQuery = value),
                      onSelect: (section) => unawaited(_select(section)),
                      onClass: _openClass,
                      onNewClass: () => unawaited(_createClassFromSidebar()),
                      onNewConversation: () => unawaited(_newConversation()),
                      onOpenConversation: (conversation) =>
                          unawaited(_openConversation(conversation)),
                      onCollapse: () =>
                          setState(() => _sidebarCollapsed = true),
                    ),
            ),
            if (_sidebarCollapsed && !knowledgeBase)
              SizedBox(
                width: 40,
                child: Align(
                  alignment: Alignment.topCenter,
                  child: Padding(
                    padding: const EdgeInsets.only(top: 14),
                    child: IconButton(
                      tooltip: '展开教学侧栏',
                      onPressed: () =>
                          setState(() => _sidebarCollapsed = false),
                      icon: const Icon(LucideIcons.panelLeftOpen, size: 18),
                    ),
                  ),
                ),
              ),
            Expanded(
              child: ColoredBox(
                key: ValueKey('teacher-section-${_section.name}'),
                color: context.scheme.surface,
                child: _page(),
              ),
            ),
            if (showInspector && !knowledgeBase)
              SizedBox(
                width: 292,
                child: _TeacherInspector(
                  section: _section,
                  selectedClass: _selectedClass,
                  overview: _overview,
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _mobile() {
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    final showLearning = AppScope.of(
      context,
    ).availableWorkspaces.any((item) => item.type == WorkspaceType.learning);
    return Scaffold(
      key: _scaffoldKey,
      resizeToAvoidBottomInset: false,
      drawer: Drawer(
        child: SafeArea(
          child: _TeacherSidebar(
            section: _section,
            selectedClass: _selectedClass,
            classes: _classes,
            overview: _overview,
            query: _sidebarQuery,
            onQueryChanged: (value) => setState(() => _sidebarQuery = value),
            onSelect: (section) {
              Navigator.pop(context);
              unawaited(_select(section));
            },
            onClass: (classroom) {
              Navigator.pop(context);
              _openClass(classroom);
            },
            onNewClass: () {
              Navigator.pop(context);
              unawaited(_createClassFromSidebar());
            },
            onNewConversation: () {
              Navigator.pop(context);
              unawaited(_newConversation());
            },
            onOpenConversation: (conversation) {
              Navigator.pop(context);
              unawaited(_openConversation(conversation));
            },
            onCollapse: () => Navigator.pop(context),
          ),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _TeacherMobileHeader(
              title: _selectedClass?.name ?? _sectionLabel(_section),
              onMenu: () => _scaffoldKey.currentState?.openDrawer(),
              onProfile: () => showProfileSheet(context),
            ),
            Expanded(child: _page()),
          ],
        ),
      ),
      bottomNavigationBar: keyboardOpen
          ? null
          : _TeacherBottomBar(
              section: _section,
              showLearning: showLearning,
              onSelect: (section) => unawaited(_select(section)),
              onProfile: () => showProfileSheet(context),
            ),
    );
  }
}

class _TeacherRail extends StatelessWidget {
  const _TeacherRail({
    super.key,
    required this.section,
    required this.showLearning,
    required this.onSelect,
    required this.onProfile,
  });
  final TeacherSection section;
  final bool showLearning;
  final ValueChanged<TeacherSection> onSelect;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => Container(
    width: 60,
    decoration: BoxDecoration(
      color: context.scheme.surface,
      border: Border(right: BorderSide(color: context.n.divider)),
    ),
    child: Column(
      children: [
        const SizedBox(height: 18),
        Text(
          'ESA',
          style: context.texts.titleMedium?.copyWith(
            color: const Color(0xFF6EA3FF),
          ),
        ),
        const SizedBox(height: 24),
        if (showLearning)
          _RailButton(
            key: const ValueKey('teacher-learning-destination'),
            icon: LucideIcons.messageCircle,
            tooltip: '学习',
            active: section == TeacherSection.learning,
            onTap: () => onSelect(TeacherSection.learning),
          ),
        _RailButton(
          key: const ValueKey('teacher-research-destination'),
          icon: LucideIcons.search,
          tooltip: '科研',
          active: section == TeacherSection.research,
          onTap: () => onSelect(TeacherSection.research),
        ),
        _RailButton(
          key: const ValueKey('teacher-workbench-destination'),
          icon: LucideIcons.bookOpen,
          tooltip: '教学',
          active:
              section == TeacherSection.workbench ||
              section == TeacherSection.assistant,
          onTap: () => onSelect(TeacherSection.workbench),
        ),
        _RailButton(
          key: const ValueKey('teacher-knowledge-base-destination'),
          icon: LucideIcons.database,
          tooltip: '个人知识库',
          active: section == TeacherSection.knowledgeBase,
          onTap: () => onSelect(TeacherSection.knowledgeBase),
        ),
        const Spacer(),
        _RailButton(
          icon: LucideIcons.settings,
          tooltip: '设置',
          active: false,
          onTap: onProfile,
        ),
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Tooltip(
            message: '个人中心',
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: onProfile,
              child: CircleAvatar(
                radius: 16,
                backgroundColor: EsaColors.accent.withValues(alpha: .22),
                child: Text(
                  AppScope.of(context).username.characters.firstOrNull ?? '师',
                  style: context.texts.labelSmall,
                ),
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class _RailButton extends StatelessWidget {
  const _RailButton({
    super.key,
    required this.icon,
    required this.tooltip,
    required this.active,
    required this.onTap,
  });
  final IconData icon;
  final String tooltip;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: Tooltip(
      message: tooltip,
      child: IconButton(
        onPressed: onTap,
        style: IconButton.styleFrom(
          minimumSize: const Size(42, 42),
          backgroundColor: active
              ? EsaColors.accent.withValues(alpha: .17)
              : Colors.transparent,
          foregroundColor: active ? const Color(0xFF6EA3FF) : context.n.n600,
        ),
        icon: Icon(icon, size: 20),
      ),
    ),
  );
}

class _TeacherSidebar extends StatelessWidget {
  const _TeacherSidebar({
    required this.section,
    required this.selectedClass,
    required this.classes,
    required this.overview,
    required this.query,
    required this.onQueryChanged,
    required this.onSelect,
    required this.onClass,
    required this.onNewClass,
    required this.onNewConversation,
    required this.onOpenConversation,
    required this.onCollapse,
  });
  final TeacherSection section;
  final TeachingClass? selectedClass;
  final List<TeachingClass> classes;
  final Map<String, dynamic>? overview;
  final String query;
  final ValueChanged<String> onQueryChanged;
  final ValueChanged<TeacherSection> onSelect;
  final ValueChanged<TeachingClass> onClass;
  final VoidCallback onNewClass;
  final VoidCallback onNewConversation;
  final ValueChanged<ChatConversation> onOpenConversation;
  final VoidCallback onCollapse;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final normalized = query.trim().toLowerCase();
    final visibleClasses = normalized.isEmpty
        ? classes
        : classes
              .where(
                (item) =>
                    item.name.toLowerCase().contains(normalized) ||
                    item.course.toLowerCase().contains(normalized),
              )
              .toList();
    final teachingConversations = app.conversations
        .where((item) => item.workspaceType == WorkspaceType.teaching)
        .where(
          (item) =>
              normalized.isEmpty ||
              item.title.toLowerCase().contains(normalized),
        )
        .take(5)
        .toList();
    return Container(
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(right: BorderSide(color: context.n.divider)),
      ),
      padding: const EdgeInsets.fromLTRB(12, 17, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(child: Text('教学空间', style: context.texts.titleLarge)),
              IconButton(
                tooltip: '收起侧栏',
                onPressed: onCollapse,
                icon: const Icon(LucideIcons.chevronsLeft, size: 17),
              ),
            ],
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: onNewClass,
            icon: const Icon(LucideIcons.plus, size: 17),
            label: const Align(
              alignment: Alignment.centerLeft,
              child: Text('新建班级'),
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            onChanged: onQueryChanged,
            decoration: const InputDecoration(
              hintText: '搜索班级、作业或对话',
              prefixIcon: Icon(LucideIcons.search, size: 17),
              isDense: true,
            ),
          ),
          const SizedBox(height: 14),
          _SideEntry(
            icon: LucideIcons.layoutDashboard,
            label: '教学工作台',
            selected:
                section == TeacherSection.workbench && selectedClass == null,
            onTap: () => onSelect(TeacherSection.workbench),
          ),
          _SideEntry(
            icon: LucideIcons.circleDot,
            label: '待处理',
            badge:
                '${(overview?['pending_review_count'] as num?)?.toInt() ?? 0}',
            selected: false,
            onTap: () => onSelect(TeacherSection.workbench),
          ),
          _SideEntry(
            icon: LucideIcons.bot,
            label: '教学助手',
            selected: section == TeacherSection.assistant,
            onTap: () => onSelect(TeacherSection.assistant),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 10),
            child: Divider(),
          ),
          Row(
            children: [
              Expanded(child: Text('我的班级', style: context.texts.labelSmall)),
              Text('${classes.length}', style: context.texts.labelSmall),
            ],
          ),
          const SizedBox(height: 7),
          Expanded(
            child: ListView(
              padding: EdgeInsets.zero,
              children: [
                if (visibleClasses.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(
                      classes.isEmpty ? '暂无班级' : '没有匹配的班级',
                      style: context.texts.bodySmall,
                    ),
                  )
                else
                  ...visibleClasses.map(
                    (item) => _ClassEntry(
                      classroom: item,
                      selected: item.id == selectedClass?.id,
                      onTap: () => onClass(item),
                    ),
                  ),
                if (teachingConversations.isNotEmpty) ...[
                  const Padding(
                    padding: EdgeInsets.fromLTRB(2, 18, 2, 7),
                    child: Text('最近', style: TextStyle(fontSize: 11)),
                  ),
                  ...teachingConversations.map(
                    (conversation) => ListTile(
                      dense: true,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 8),
                      leading: const Icon(LucideIcons.messageSquare, size: 15),
                      title: Text(
                        conversation.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      onTap: () => onOpenConversation(conversation),
                    ),
                  ),
                ],
              ],
            ),
          ),
          TextButton.icon(
            key: const ValueKey('new-teacher-conversation'),
            onPressed: onNewConversation,
            icon: const Icon(LucideIcons.plus, size: 16),
            label: const Text('新建教学对话'),
          ),
        ],
      ),
    );
  }
}

class _SideEntry extends StatelessWidget {
  const _SideEntry({
    required this.icon,
    required this.label,
    required this.selected,
    required this.onTap,
    this.badge,
  });
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;
  final String? badge;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 3),
    child: Material(
      color: selected
          ? EsaColors.accent.withValues(alpha: .14)
          : Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: ListTile(
        dense: true,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        leading: Icon(
          icon,
          size: 17,
          color: selected ? const Color(0xFF6EA3FF) : context.n.n600,
        ),
        title: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
        trailing: badge == null
            ? null
            : Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                decoration: BoxDecoration(
                  color: context.n.n200,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(badge!, style: context.texts.labelSmall),
              ),
        onTap: onTap,
      ),
    ),
  );
}

class _ClassEntry extends StatelessWidget {
  const _ClassEntry({
    required this.classroom,
    required this.selected,
    required this.onTap,
  });
  final TeachingClass classroom;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    key: ValueKey('teacher-class-${classroom.id}'),
    color: selected
        ? EsaColors.accent.withValues(alpha: .15)
        : Colors.transparent,
    borderRadius: BorderRadius.circular(8),
    child: ListTile(
      dense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 10),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      title: Text(classroom.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(
        classroom.term.isEmpty ? classroom.course : classroom.term,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(
          color: context.n.n200,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          '${classroom.studentCount}',
          style: context.texts.labelSmall,
        ),
      ),
      onTap: onTap,
    ),
  );
}

class _TeacherInspector extends StatelessWidget {
  const _TeacherInspector({
    required this.section,
    required this.selectedClass,
    required this.overview,
  });
  final TeacherSection section;
  final TeachingClass? selectedClass;
  final Map<String, dynamic>? overview;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final conversation = app.activeConversation;
    return Container(
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(left: BorderSide(color: context.n.divider)),
      ),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(14, 18, 14, 24),
        children: [
          Text('当前上下文', style: context.texts.titleLarge),
          const SizedBox(height: 14),
          _InspectorBlock(
            title: selectedClass == null ? '教情速览' : '当前班级',
            children: selectedClass == null
                ? [
                    _InspectorLine(
                      label: '待复核',
                      value: '${overview?['pending_review_count'] ?? 0}',
                    ),
                    _InspectorLine(
                      label: '待发布',
                      value: '${overview?['ready_feedback_count'] ?? 0}',
                    ),
                    _InspectorLine(
                      label: '活动班级',
                      value: '${overview?['class_count'] ?? 0}',
                    ),
                  ]
                : [
                    Text(selectedClass!.name, style: context.texts.titleMedium),
                    const SizedBox(height: 5),
                    Text(
                      '${selectedClass!.course}${selectedClass!.term.isEmpty ? '' : ' · ${selectedClass!.term}'}',
                      style: context.texts.bodySmall,
                    ),
                    const SizedBox(height: 12),
                    _InspectorLine(
                      label: '学生',
                      value: '${selectedClass!.studentCount} 人',
                    ),
                    _InspectorLine(
                      label: '开放作业',
                      value: '${selectedClass!.openAssignmentCount}',
                    ),
                  ],
          ),
          _InspectorBlock(
            title: '教学责任链',
            children: const [
              _WorkflowLine(icon: LucideIcons.sparkles, text: 'AI 分析仅作为建议'),
              _WorkflowLine(
                icon: LucideIcons.clipboardCheck,
                text: '教师复核形成最终裁决',
              ),
              _WorkflowLine(icon: LucideIcons.send, text: '发布后写入正式学习证据'),
            ],
          ),
          if (section == TeacherSection.assistant)
            _InspectorBlock(
              title: '对话绑定',
              children: [
                _InspectorLine(
                  label: '班级',
                  value: conversation?.className ?? '未绑定',
                ),
                _InspectorLine(
                  label: '作业',
                  value: conversation?.assignmentTitle ?? '未绑定',
                ),
              ],
            ),
          _InspectorBlock(
            title: '权限范围',
            children: [
              Text(
                '仅显示本人班级内形成的教学证据，不读取学生私人对话、记忆或科研内容。',
                style: context.texts.bodySmall,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _InspectorBlock extends StatelessWidget {
  const _InspectorBlock({required this.title, required this.children});
  final String title;
  final List<Widget> children;

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
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: context.texts.titleMedium),
        const SizedBox(height: 12),
        ...children,
      ],
    ),
  );
}

class _InspectorLine extends StatelessWidget {
  const _InspectorLine({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      children: [
        Expanded(child: Text(label, style: context.texts.bodySmall)),
        Text(value, style: context.texts.titleMedium),
      ],
    ),
  );
}

class _WorkflowLine extends StatelessWidget {
  const _WorkflowLine({required this.icon, required this.text});
  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 9),
    child: Row(
      children: [
        Icon(icon, size: 16, color: context.n.n600),
        const SizedBox(width: 9),
        Expanded(child: Text(text, style: context.texts.bodySmall)),
      ],
    ),
  );
}

class _TeacherMobileHeader extends StatelessWidget {
  const _TeacherMobileHeader({
    required this.title,
    required this.onMenu,
    required this.onProfile,
  });
  final String title;
  final VoidCallback onMenu;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: 58,
    child: Row(
      children: [
        IconButton(
          tooltip: '打开教学导航',
          onPressed: onMenu,
          icon: const Icon(LucideIcons.panelLeftOpen),
        ),
        const SizedBox(width: 4),
        Expanded(
          child: Text(
            title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: context.texts.titleLarge,
          ),
        ),
        IconButton(
          tooltip: '个人中心',
          onPressed: onProfile,
          icon: const Icon(LucideIcons.circleUserRound),
        ),
        const SizedBox(width: 5),
      ],
    ),
  );
}

class _TeacherBottomBar extends StatelessWidget {
  const _TeacherBottomBar({
    required this.section,
    required this.showLearning,
    required this.onSelect,
    required this.onProfile,
  });
  final TeacherSection section;
  final bool showLearning;
  final ValueChanged<TeacherSection> onSelect;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) {
    final sections = <TeacherSection>[
      if (showLearning) TeacherSection.learning,
      TeacherSection.research,
      TeacherSection.knowledgeBase,
      TeacherSection.workbench,
    ];
    final selected = sections.indexWhere(
      (item) =>
          item == section ||
          (item == TeacherSection.workbench &&
              section == TeacherSection.assistant),
    );
    return NavigationBar(
      selectedIndex: selected,
      onDestinationSelected: (index) {
        if (index == sections.length) {
          onProfile();
        } else {
          onSelect(sections[index]);
        }
      },
      destinations: [
        if (showLearning)
          const NavigationDestination(
            key: ValueKey('teacher-mobile-learning'),
            icon: Icon(LucideIcons.messageCircle),
            label: '学习',
          ),
        const NavigationDestination(
          key: ValueKey('teacher-mobile-research'),
          icon: Icon(LucideIcons.search),
          label: '科研',
        ),
        const NavigationDestination(
          key: ValueKey('teacher-mobile-knowledge-base'),
          icon: Icon(LucideIcons.database),
          label: '资料库',
        ),
        const NavigationDestination(
          key: ValueKey('teacher-mobile-workbench'),
          icon: Icon(LucideIcons.bookOpen),
          label: '教学',
        ),
        const NavigationDestination(
          key: ValueKey('teacher-mobile-profile'),
          icon: Icon(LucideIcons.circleUserRound),
          label: '我的',
        ),
      ],
    );
  }
}

String _sectionLabel(TeacherSection section) => switch (section) {
  TeacherSection.learning => '学习空间',
  TeacherSection.research => '科研空间',
  TeacherSection.knowledgeBase => '个人知识库',
  TeacherSection.workbench => '教学工作台',
  TeacherSection.assistant => '教学助手',
};
