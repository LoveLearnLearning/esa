import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../widgets/profile_sheet.dart';
import '../widgets/conversation_move_dialog.dart';
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
    // 新对话默认归入未分组，避免沿用到上一个分组对话的分组。
    app.setActiveGroup(null);
    await app.newConversation();
    if (mounted) _showTeachingAssistant();
  }

  Future<void> _newConversationInGroup(ChatGroup group) async {
    final app = AppScope.of(context);
    if (app.activeWorkspace != WorkspaceType.teaching) {
      await app.switchWorkspace(WorkspaceType.teaching);
    }
    await app.newConversationInGroup(group.id);
    if (mounted) _showTeachingAssistant();
  }

  Future<void> _createGroupFromSidebar() async {
    final controller = TextEditingController();
    final accepted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('新建分组'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: '分组名称'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('创建'),
          ),
        ],
      ),
    );
    if (!mounted) {
      controller.dispose();
      return;
    }
    if (accepted == true && controller.text.trim().isNotEmpty) {
      await AppScope.of(context).createGroup(name: controller.text.trim());
    }
    controller.dispose();
  }

  Future<void> _renameGroup(ChatGroup group) async {
    final controller = TextEditingController(text: group.name);
    final accepted = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('重命名分组'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: '分组名称'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, controller.text),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    final name = accepted?.trim();
    if (!mounted) {
      controller.dispose();
      return;
    }
    if (name != null && name.isNotEmpty) {
      await AppScope.of(context).updateGroup(group.id, name: name);
    }
    controller.dispose();
  }

  Future<void> _deleteGroup(ChatGroup group) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('删除分组'),
        content: const Text('删除后，组内对话会移回未分组，此操作无法撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: TextButton.styleFrom(
              foregroundColor: const Color(0xFFE5484D),
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (!mounted) return;
    if (confirmed == true) {
      await AppScope.of(context).deleteGroup(group.id);
    }
  }

  Future<void> _deleteConversation(ChatConversation conversation) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('删除对话'),
        content: Text('确定要删除「${conversation.title}」吗？此操作无法撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: TextButton.styleFrom(
              foregroundColor: const Color(0xFFE5484D),
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (!mounted) return;
    if (confirmed == true) {
      await AppScope.of(context).deleteConversation(conversation.id);
    }
  }

  Future<void> _moveConversation(ChatConversation conversation) async {
    final app = AppScope.of(context);
    final target = await showMoveConversationDialog(context, app, conversation);
    if (target == null || !mounted) return;
    try {
      await app.moveConversationToGroup(conversation.id, target.groupId);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('移动失败：$error')));
    }
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
    return Scaffold(
      body: SafeArea(
        child: Row(
          children: [
            _TeacherRail(
              key: const ValueKey('teacher-global-rail'),
              section: _section,
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
                      query: _sidebarQuery,
                      onQueryChanged: (value) =>
                          setState(() => _sidebarQuery = value),
                      onSelect: (section) => unawaited(_select(section)),
                      onClass: _openClass,
                      onNewClass: () => unawaited(_createClassFromSidebar()),
                      onNewConversation: () => unawaited(_newConversation()),
                      onNewConversationInGroup: (group) =>
                          unawaited(_newConversationInGroup(group)),
                      onCreateGroup: () => unawaited(_createGroupFromSidebar()),
                      onRenameGroup: (group) => unawaited(_renameGroup(group)),
                      onDeleteGroup: (group) => unawaited(_deleteGroup(group)),
                      onDeleteConversation: (conversation) =>
                          unawaited(_deleteConversation(conversation)),
                      onMoveConversation: (conversation) =>
                          unawaited(_moveConversation(conversation)),
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
      drawer: Drawer(
        child: SafeArea(
          child: _TeacherSidebar(
            section: _section,
            selectedClass: _selectedClass,
            classes: _classes,
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
            onNewConversationInGroup: (group) {
              Navigator.pop(context);
              unawaited(_newConversationInGroup(group));
            },
            onCreateGroup: () {
              Navigator.pop(context);
              unawaited(_createGroupFromSidebar());
            },
            onRenameGroup: (group) {
              Navigator.pop(context);
              unawaited(_renameGroup(group));
            },
            onDeleteGroup: (group) {
              Navigator.pop(context);
              unawaited(_deleteGroup(group));
            },
            onDeleteConversation: (conversation) {
              Navigator.pop(context);
              unawaited(_deleteConversation(conversation));
            },
            onMoveConversation: (conversation) {
              Navigator.pop(context);
              unawaited(_moveConversation(conversation));
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
      bottomNavigationBar: AnimatedSize(
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeInOut,
        alignment: Alignment.bottomCenter,
        child: keyboardOpen
            ? const SizedBox.shrink()
            : _TeacherBottomBar(
                section: _section,
                showLearning: showLearning,
                onSelect: (section) => unawaited(_select(section)),
                onProfile: () => showProfileSheet(context),
              ),
      ),
    );
  }
}

class _TeacherRail extends StatelessWidget {
  const _TeacherRail({
    super.key,
    required this.section,
    required this.onSelect,
    required this.onProfile,
  });
  final TeacherSection section;
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
          style: context.texts.titleMedium?.copyWith(color: context.n.n700),
        ),
        const SizedBox(height: 24),
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
                backgroundColor: context.n.n300,
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
          backgroundColor: active ? context.n.n200 : Colors.transparent,
          foregroundColor: active ? context.n.n700 : context.n.n600,
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
    required this.query,
    required this.onQueryChanged,
    required this.onSelect,
    required this.onClass,
    required this.onNewClass,
    required this.onNewConversation,
    required this.onNewConversationInGroup,
    required this.onCreateGroup,
    required this.onRenameGroup,
    required this.onDeleteGroup,
    required this.onDeleteConversation,
    required this.onMoveConversation,
    required this.onOpenConversation,
    required this.onCollapse,
  });
  final TeacherSection section;
  final TeachingClass? selectedClass;
  final List<TeachingClass> classes;
  final String query;
  final ValueChanged<String> onQueryChanged;
  final ValueChanged<TeacherSection> onSelect;
  final ValueChanged<TeachingClass> onClass;
  final VoidCallback onNewClass;
  final VoidCallback onNewConversation;
  final ValueChanged<ChatGroup> onNewConversationInGroup;
  final VoidCallback onCreateGroup;
  final ValueChanged<ChatGroup> onRenameGroup;
  final ValueChanged<ChatGroup> onDeleteGroup;
  final ValueChanged<ChatConversation> onDeleteConversation;
  final ValueChanged<ChatConversation> onMoveConversation;
  final ValueChanged<ChatConversation> onOpenConversation;
  final VoidCallback onCollapse;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final normalized = query.trim().toLowerCase();
    bool matches(String value) =>
        normalized.isEmpty || value.toLowerCase().contains(normalized);
    final visibleClasses = normalized.isEmpty
        ? classes
        : classes
              .where(
                (item) =>
                    item.name.toLowerCase().contains(normalized) ||
                    item.course.toLowerCase().contains(normalized),
              )
              .toList();
    final groups = app.groups.where((group) {
      if (matches(group.name)) return true;
      return app
          .conversationsInGroup(group.id)
          .any((conversation) => matches(conversation.title));
    }).toList();
    final ungrouped = app.ungroupedConversations
        .where((conversation) => matches(conversation.title))
        .toList();
    final teachingConversations = app.conversations
        .where((item) => item.workspaceType == WorkspaceType.teaching)
        .where((item) => matches(item.title))
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
            key: const ValueKey('teacher-new-conversation'),
            onPressed: onNewConversation,
            icon: const Icon(LucideIcons.plus, size: 17),
            label: const Align(
              alignment: Alignment.centerLeft,
              child: Text('新建对话'),
            ),
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
              hintText: '搜索班级或对话',
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
              Expanded(child: Text('对话分组', style: context.texts.labelSmall)),
              IconButton(
                tooltip: '新建分组',
                onPressed: onCreateGroup,
                icon: const Icon(LucideIcons.plus, size: 16),
              ),
            ],
          ),
          const SizedBox(height: 7),
          Expanded(
            child: ListView(
              padding: EdgeInsets.zero,
              children: [
                if (groups.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    child: Text(
                      normalized.isEmpty ? '暂无对话分组' : '没有匹配的对话组',
                      style: context.texts.bodySmall,
                    ),
                  )
                else
                  ...groups.map((group) {
                    final conversations = app
                        .conversationsInGroup(group.id)
                        .where(
                          (conversation) =>
                              normalized.isEmpty ||
                              matches(group.name) ||
                              matches(conversation.title),
                        )
                        .toList();
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: _TeacherExpandableRow(
                        icon: LucideIcons.folder,
                        label: group.name,
                        onNewConversation: () =>
                            onNewConversationInGroup(group),
                        onRename: () => onRenameGroup(group),
                        onDelete: () => onDeleteGroup(group),
                        children: conversations
                            .map(
                              (conversation) => _TeacherConversationEntry(
                                conversation: conversation,
                                onTap: () => onOpenConversation(conversation),
                                onDelete: () =>
                                    onDeleteConversation(conversation),
                              ),
                            )
                            .toList(),
                      ),
                    );
                  }),
                const SizedBox(height: 12),
                Text(
                  '历史对话',
                  key: const ValueKey('teacher-history-heading'),
                  style: context.texts.labelSmall,
                ),
                const SizedBox(height: 6),
                if (ungrouped.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 8,
                    ),
                    child: Text(
                      normalized.isEmpty ? '暂无历史对话' : '没有匹配的历史对话',
                      style: context.texts.bodySmall,
                    ),
                  )
                else
                  for (final conversation in ungrouped)
                    _TeacherConversationEntry(
                      conversation: conversation,
                      onTap: () => onOpenConversation(conversation),
                      onDelete: () => onDeleteConversation(conversation),
                      onMoveToGroup: () => onMoveConversation(conversation),
                    ),
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 10),
                  child: Divider(),
                ),
                Row(
                  children: [
                    Expanded(
                      child: Text('我的班级', style: context.texts.labelSmall),
                    ),
                    Text('${classes.length}', style: context.texts.labelSmall),
                  ],
                ),
                const SizedBox(height: 7),
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
                    (conversation) => _TeacherConversationEntry(
                      conversation: conversation,
                      onTap: () => onOpenConversation(conversation),
                      onDelete: () => onDeleteConversation(conversation),
                      onMoveToGroup: () => onMoveConversation(conversation),
                    ),
                  ),
                ],
              ],
            ),
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
  });
  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 3),
    child: Material(
      color: selected ? context.n.n200 : Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: ListTile(
        dense: true,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        leading: Icon(
          icon,
          size: 17,
          color: selected ? context.n.n700 : context.n.n600,
        ),
        title: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
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
    color: selected ? context.n.n200 : Colors.transparent,
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

class _TeacherExpandableRow extends StatefulWidget {
  const _TeacherExpandableRow({
    required this.icon,
    required this.label,
    required this.children,
    this.onNewConversation,
    this.onRename,
    this.onDelete,
  });
  final IconData icon;
  final String label;
  final List<Widget> children;
  final VoidCallback? onNewConversation;
  final VoidCallback? onRename;
  final VoidCallback? onDelete;

  @override
  State<_TeacherExpandableRow> createState() => _TeacherExpandableRowState();
}

class _TeacherExpandableRowState extends State<_TeacherExpandableRow> {
  bool expanded = true;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      InkWell(
        borderRadius: BorderRadius.circular(7),
        onTap: () => setState(() => expanded = !expanded),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
          child: Row(
            children: [
              Icon(widget.icon, size: 17, color: context.n.n600),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  widget.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (widget.onNewConversation != null)
                IconButton(
                  tooltip: '在分组中新建对话',
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(
                    minWidth: 26,
                    minHeight: 26,
                  ),
                  iconSize: 14,
                  icon: const Icon(LucideIcons.plus),
                  onPressed: widget.onNewConversation,
                ),
              if (widget.onRename != null)
                IconButton(
                  tooltip: '重命名分组',
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(
                    minWidth: 26,
                    minHeight: 26,
                  ),
                  iconSize: 14,
                  icon: const Icon(LucideIcons.pencil),
                  onPressed: widget.onRename,
                ),
              if (widget.onDelete != null)
                IconButton(
                  tooltip: '删除分组',
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(
                    minWidth: 26,
                    minHeight: 26,
                  ),
                  iconSize: 14,
                  icon: const Icon(LucideIcons.trash2),
                  onPressed: widget.onDelete,
                ),
              Icon(
                expanded ? LucideIcons.chevronDown : LucideIcons.chevronRight,
                size: 14,
              ),
            ],
          ),
        ),
      ),
      if (expanded)
        Padding(
          padding: const EdgeInsets.only(left: 12),
          child: Column(children: widget.children),
        ),
    ],
  );
}

class _TeacherConversationEntry extends StatelessWidget {
  const _TeacherConversationEntry({
    required this.conversation,
    required this.onTap,
    this.onDelete,
    this.onMoveToGroup,
  });
  final ChatConversation conversation;
  final VoidCallback onTap;
  final VoidCallback? onDelete;
  final VoidCallback? onMoveToGroup;

  @override
  Widget build(BuildContext context) => ListTile(
    dense: true,
    minLeadingWidth: 18,
    contentPadding: const EdgeInsets.symmetric(horizontal: 8),
    leading: const Icon(LucideIcons.messageSquare, size: 15),
    title: Text(
      conversation.title,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: const TextStyle(fontSize: 12.5),
    ),
    trailing: onDelete == null && onMoveToGroup == null
        ? null
        : Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (onMoveToGroup != null)
                IconButton(
                  tooltip: '移动到分组',
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(
                    minWidth: 26,
                    minHeight: 26,
                  ),
                  iconSize: 14,
                  icon: const Icon(LucideIcons.folderInput),
                  onPressed: onMoveToGroup,
                ),
              if (onDelete != null)
                IconButton(
                  tooltip: '删除对话',
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(
                    minWidth: 26,
                    minHeight: 26,
                  ),
                  iconSize: 14,
                  icon: const Icon(LucideIcons.trash2),
                  onPressed: onDelete,
                ),
            ],
          ),
    onTap: onTap,
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
