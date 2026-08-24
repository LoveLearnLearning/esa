import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/profile_sheet.dart';
import '../widgets/memory_sheet.dart';
import '../widgets/history_drawer.dart';
import '../widgets/agent_action_sheet.dart';
import '../widgets/composer.dart';
import 'chat_page.dart';
import 'knowledge_map_page.dart';
import 'planner_page.dart';
import 'personal_knowledge_base_page.dart';
import 'research_project_page.dart';
import 'research_workspace_page.dart';
import 'student_assignments_page.dart';

enum StudentSection {
  home,
  assignments,
  schedule,
  knowledge,
  knowledgeBase,
  research,
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  final _mobileScaffoldKey = GlobalKey<ScaffoldState>();
  final _composerKey = GlobalKey<ComposerState>();
  StudentSection _section = StudentSection.home;
  bool _sidebarCollapsed = false;
  bool _scheduleRequested = false;
  String _sidebarQuery = '';
  List<DocumentAttachment> _selectedAttachments = const [];
  ResearchProject? _activeResearchProject;
  bool _researchProjectChatOpen = false;
  bool _learningChatOpen = false;

  bool get _inResearch => _section == StudentSection.research;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_scheduleRequested) return;
    _scheduleRequested = true;
    final app = AppScope.of(context);
    if (app.isLoggedIn) unawaited(app.loadSchedule());
  }

  Future<void> _select(StudentSection section) async {
    FocusManager.instance.primaryFocus?.unfocus();
    final app = AppScope.of(context);
    final target = section == StudentSection.research
        ? WorkspaceType.research
        : WorkspaceType.learning;
    if (app.activeWorkspace != target) await app.switchWorkspace(target);
    if (section == StudentSection.home && app.activeId != null) {
      await app.newConversation();
    }
    if (!mounted) return;
    setState(() {
      _section = section;
      _learningChatOpen = false;
      if (section != StudentSection.research) _researchProjectChatOpen = false;
    });
  }

  void _showHome() {
    FocusManager.instance.primaryFocus?.unfocus();
    if (!mounted) return;
    setState(() {
      _section = StudentSection.home;
      _learningChatOpen = false;
      _researchProjectChatOpen = false;
    });
  }

  Future<void> _openAssignment(TeachingAssignment assignment) async {
    await AppScope.of(context).openLearningAssignmentContext(assignment);
    if (!mounted) return;
    setState(() {
      _section = StudentSection.home;
      _learningChatOpen = true;
      _researchProjectChatOpen = false;
    });
  }

  Widget _page() => switch (_section) {
    StudentSection.home => ChatPage(
      key: ValueKey(_learningChatOpen ? 'learning-chat' : 'learning-home'),
      embedded: true,
      homeMode: !_learningChatOpen,
      composerKey: _composerKey,
      onSelectedAttachmentsChanged: _setSelectedAttachments,
      onExitEmbedded: _learningChatOpen
          ? () => setState(() => _learningChatOpen = false)
          : null,
      onViewAssignments: _learningChatOpen
          ? null
          : () => unawaited(_select(StudentSection.assignments)),
      onContinueLearning: _learningChatOpen
          ? null
          : () => unawaited(_continueLearning()),
      onOpenConversation: (id) => unawaited(_openLearningConversation(id)),
      onStartChat: _openChatInput,
    ),
    StudentSection.assignments => StudentAssignmentsPage(
      onOpenChat: _openAssignment,
    ),
    StudentSection.schedule => PlannerPage(
      initialTab: PlannerTab.schedule,
      onOpenAssignments: () => unawaited(_select(StudentSection.assignments)),
    ),
    StudentSection.knowledge => KnowledgeMapPage(
      embedded: true,
      onOpenChat: _showHome,
      onOpenSchedule: () => unawaited(_select(StudentSection.schedule)),
    ),
    StudentSection.knowledgeBase => const PersonalKnowledgeBasePage(),
    StudentSection.research =>
      _activeResearchProject == null
          ? ResearchWorkspacePage(
              onOpenChat: () => unawaited(_select(StudentSection.research)),
              onOpenProject: (project) => setState(() {
                _activeResearchProject = project;
                _researchProjectChatOpen = false;
              }),
            )
          : _researchProjectChatOpen
          ? ChatPage(
              embedded: true,
              embeddedTitle: _activeResearchProject!.name,
              onExitEmbedded: () =>
                  setState(() => _researchProjectChatOpen = false),
            )
          : ResearchProjectPage(
              project: _activeResearchProject!,
              embedded: true,
              onBack: () => setState(() {
                _activeResearchProject = null;
                _researchProjectChatOpen = false;
              }),
              onProjectUpdated: (project) =>
                  setState(() => _activeResearchProject = project),
              onOpenChat: () => setState(() => _researchProjectChatOpen = true),
            ),
  };

  void _setSelectedAttachments(List<DocumentAttachment> attachments) {
    if (!mounted) return;
    setState(() => _selectedAttachments = List.of(attachments));
  }

  Future<void> _openLearningConversation(String id) async {
    final app = AppScope.of(context);
    await app.setActive(id);
    if (!mounted) return;
    setState(() {
      _section = StudentSection.home;
      _learningChatOpen = true;
      _researchProjectChatOpen = false;
    });
  }

  Future<void> _startGroupConversation(ChatGroup group) async {
    final app = AppScope.of(context);
    final projectId = app.groupProjectId(group.id);
    await app.newConversationInGroup(group.id, researchProjectId: projectId);
    if (!mounted) return;
    if (projectId != null) {
      _activeResearchProject = app.researchProjects
          .where((project) => project.id == projectId)
          .firstOrNull;
    }
    setState(() {
      _section = projectId != null
          ? StudentSection.research
          : StudentSection.home;
      _learningChatOpen = projectId == null;
      _researchProjectChatOpen = projectId != null;
      _selectedAttachments = const [];
    });
  }

  Future<void> _startNewConversation() async {
    final app = AppScope.of(context);
    await app.newConversation();
    if (!mounted) return;
    setState(() {
      _section = StudentSection.home;
      _learningChatOpen = true;
      _researchProjectChatOpen = false;
      _selectedAttachments = const [];
    });
  }

  /// 首页（学习仪表盘）上开始输入/发送时切回对话视图。
  void _openChatInput() {
    if (!mounted || _learningChatOpen) return;
    setState(() => _learningChatOpen = true);
  }

  /// 首页“继续学习”优先恢复最近对话；没有历史时，按真实课程启动学习。
  Future<void> _continueLearning() async {
    if (!mounted || _learningChatOpen) return;
    final app = AppScope.of(context);
    final recent = app.conversations.firstOrNull;
    if (recent != null) {
      await _openLearningConversation(recent.id);
      return;
    }
    final courseName =
        app.learningCourses.firstOrNull?.name ??
        app.scheduleCourseNames.firstOrNull;
    if (courseName == null) return;
    final focusName =
        app.masteryReport?.stalePoints.firstOrNull?.name ??
        app.masteryReport?.weakPoints.firstOrNull?.name;
    await app.newConversation();
    if (!mounted) return;
    setState(() => _learningChatOpen = true);
    final target = focusName == null
        ? '继续学习“$courseName”，请结合我的学习记录建议本次最合适的下一步。'
        : '继续学习“$courseName”中的“$focusName”，请结合我的掌握度和学习证据继续讲解。';
    await app.send(target, displayText: '继续学习：${focusName ?? courseName}');
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    return width >= 1040 ? _desktop() : _mobile();
  }

  Widget _desktop() {
    final width = MediaQuery.sizeOf(context).width;
    final knowledgeBase = _section == StudentSection.knowledgeBase;
    final showContext = width >= 1320 && !knowledgeBase;
    return Scaffold(
      body: SafeArea(
        child: Row(
          children: [
            _GlobalRail(
              key: const ValueKey('student-global-rail'),
              section: _section,
              onSelect: (section) => unawaited(_select(section)),
              onProfile: () => showProfileSheet(context),
              onActions: () => showAgentActionSheet(context),
            ),
            AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              width: _sidebarCollapsed || knowledgeBase ? 0 : 276,
              child: _sidebarCollapsed || knowledgeBase
                  ? const SizedBox.shrink()
                  : _WorkspaceSidebar(
                      section: _section,
                      query: _sidebarQuery,
                      onQueryChanged: (value) =>
                          setState(() => _sidebarQuery = value),
                      onNewConversation: () =>
                          unawaited(_startNewConversation()),
                      onNewConversationInGroup: (group) =>
                          unawaited(_startGroupConversation(group)),
                      onOpenConversation: (conversation) =>
                          unawaited(_openLearningConversation(conversation.id)),
                      onOpenProject: (project) => setState(() {
                        _activeResearchProject = project;
                        _researchProjectChatOpen = false;
                      }),
                      onCollapse: () =>
                          setState(() => _sidebarCollapsed = true),
                    ),
            ),
            if (_sidebarCollapsed && !knowledgeBase)
              _RevealSidebarButton(
                onTap: () => setState(() => _sidebarCollapsed = false),
              ),
            Expanded(
              child: _SurfaceFrame(key: ValueKey(_section), child: _page()),
            ),
            if (showContext)
              SizedBox(
                width: 292,
                child: _StudentContextRail(
                  section: _section,
                  researchProject: _activeResearchProject,
                  selectedAttachments: _selectedAttachments,
                  onAddAttachment: () =>
                      unawaited(_composerKey.currentState?.pickAttachment()),
                  onRemoveAttachment: () => unawaited(
                    _composerKey.currentState?.removeSelectedAttachment(),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _mobile() {
    final app = AppScope.of(context);
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    final conversationActive = _learningChatOpen || _researchProjectChatOpen;
    final historyAvailable =
        conversationActive || _section == StudentSection.home;
    final researchProjectActive =
        _section == StudentSection.research && _activeResearchProject != null;
    return Scaffold(
      key: _mobileScaffoldKey,
      resizeToAvoidBottomInset: false,
      drawer: historyAvailable
          ? HistoryDrawer(
              onNewConversation: () => unawaited(_startNewConversation()),
              onNewConversationInGroup: (group) =>
                  unawaited(_startGroupConversation(group)),
              onOpenConversation: (conversation) =>
                  unawaited(_openLearningConversation(conversation.id)),
            )
          : null,
      drawerEnableOpenDragGesture: historyAvailable,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            if (conversationActive)
              _MobileConversationHeader(
                title: _learningChatOpen
                    ? app.activeConversation?.title ?? '新对话'
                    : _researchProjectChatOpen
                    ? _activeResearchProject?.name ?? '项目对话'
                    : '项目对话',
                onBack: _learningChatOpen
                    ? () => setState(() => _learningChatOpen = false)
                    : _researchProjectChatOpen
                    ? () => setState(() => _researchProjectChatOpen = false)
                    : () => _showHome(),
                onHistory: () => _mobileScaffoldKey.currentState?.openDrawer(),
              )
            else if (!researchProjectActive)
              _MobileHeader(
                section: _section,
                onSelect: (section) => unawaited(_select(section)),
                onProfile: () => showProfileSheet(context),
                onMemory: () => showMemorySheet(context),
                onActions: () => showAgentActionSheet(context),
                onHistory: _section == StudentSection.home
                    ? () => _mobileScaffoldKey.currentState?.openDrawer()
                    : null,
              ),
            if (!_inResearch)
              _MobileLearningTabs(
                section: _section,
                onSelect: (section) => unawaited(_select(section)),
              ),
            Expanded(child: _page()),
          ],
        ),
      ),
      bottomNavigationBar: keyboardOpen
          ? null
          : _MobileBottomBar(
              research: _inResearch,
              onLearning: () => unawaited(_select(StudentSection.home)),
              onResearch: () => unawaited(_select(StudentSection.research)),
              onProfile: () => showProfileSheet(context),
            ),
    );
  }
}

class _SurfaceFrame extends StatelessWidget {
  const _SurfaceFrame({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) =>
      ColoredBox(color: context.scheme.surface, child: child);
}

class _GlobalRail extends StatelessWidget {
  const _GlobalRail({
    super.key,
    required this.section,
    required this.onSelect,
    required this.onProfile,
    required this.onActions,
  });

  final StudentSection section;
  final ValueChanged<StudentSection> onSelect;
  final VoidCallback onProfile;
  final VoidCallback onActions;

  @override
  Widget build(BuildContext context) => Container(
    width: 72,
    decoration: BoxDecoration(
      color: context.scheme.surface,
      border: Border(right: BorderSide(color: context.n.divider)),
    ),
    child: Column(
      children: [
        const SizedBox(height: 19),
        const _EsaWordmark(compact: true),
        const SizedBox(height: 24),
        _RailButton(
          icon: LucideIcons.house,
          tooltip: '首页',
          active: section == StudentSection.home,
          onTap: () => onSelect(StudentSection.home),
        ),
        _RailButton(
          icon: LucideIcons.clipboardCheck,
          tooltip: '作业与任务',
          active: section == StudentSection.assignments,
          onTap: () => onSelect(StudentSection.assignments),
        ),
        _RailButton(
          icon: LucideIcons.calendarDays,
          tooltip: '日程',
          active: section == StudentSection.schedule,
          onTap: () => onSelect(StudentSection.schedule),
        ),
        _RailButton(
          icon: LucideIcons.mapPin,
          tooltip: '知识地图',
          active: section == StudentSection.knowledge,
          onTap: () => onSelect(StudentSection.knowledge),
        ),
        _RailButton(
          key: const ValueKey('student-knowledge-base-destination'),
          icon: LucideIcons.database,
          tooltip: '个人知识库',
          active: section == StudentSection.knowledgeBase,
          onTap: () => onSelect(StudentSection.knowledgeBase),
        ),
        _RailButton(
          key: const ValueKey('student-research-destination'),
          icon: LucideIcons.microscope,
          tooltip: '研究空间',
          active: section == StudentSection.research,
          onTap: () => onSelect(StudentSection.research),
        ),
        const Spacer(),
        _RailButton(
          icon: LucideIcons.shieldCheck,
          tooltip: '待确认动作',
          active: false,
          onTap: onActions,
        ),
        _RailButton(
          icon: LucideIcons.settings,
          tooltip: '设置',
          active: false,
          onTap: onProfile,
        ),
        const SizedBox(height: 12),
        _UserAvatar(onTap: onProfile),
        const SizedBox(height: 18),
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
    padding: const EdgeInsets.only(bottom: 12),
    child: Tooltip(
      message: tooltip,
      child: IconButton(
        onPressed: onTap,
        style: IconButton.styleFrom(
          minimumSize: const Size(42, 42),
          backgroundColor: active
              ? EsaColors.accent.withValues(alpha: 0.18)
              : Colors.transparent,
          foregroundColor: active ? const Color(0xFF66A0FF) : context.n.n600,
          side: active
              ? BorderSide(color: EsaColors.accent.withValues(alpha: 0.22))
              : BorderSide.none,
        ),
        icon: Icon(icon, size: 21),
      ),
    ),
  );
}

class _WorkspaceSidebar extends StatelessWidget {
  const _WorkspaceSidebar({
    required this.section,
    required this.query,
    required this.onQueryChanged,
    required this.onNewConversation,
    required this.onNewConversationInGroup,
    required this.onOpenConversation,
    required this.onCollapse,
    required this.onOpenProject,
  });
  final StudentSection section;
  final String query;
  final ValueChanged<String> onQueryChanged;
  final VoidCallback onNewConversation;
  final ValueChanged<ChatGroup> onNewConversationInGroup;
  final ValueChanged<ChatConversation> onOpenConversation;
  final VoidCallback onCollapse;
  final ValueChanged<ResearchProject> onOpenProject;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final research = section == StudentSection.research;
    return Container(
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(right: BorderSide(color: context.n.divider)),
      ),
      padding: const EdgeInsets.fromLTRB(14, 18, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  research ? '科研空间' : '学习空间',
                  style: context.texts.titleLarge?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              IconButton(
                tooltip: '收起侧栏',
                onPressed: onCollapse,
                icon: const Icon(LucideIcons.chevronsLeft, size: 17),
              ),
            ],
          ),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            key: research
                ? const ValueKey('new-research-chat')
                : const ValueKey('new-conversation'),
            onPressed: research
                ? () => unawaited(app.newConversation())
                : onNewConversation,
            icon: const Icon(LucideIcons.plus, size: 17),
            label: Text(research ? '新建对话' : '新对话'),
          ),
          const SizedBox(height: 12),
          TextField(
            onChanged: onQueryChanged,
            decoration: InputDecoration(
              hintText: research ? '搜索项目' : '搜索学习内容',
              prefixIcon: const Icon(LucideIcons.search, size: 17),
              isDense: true,
            ),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: Text(
                  research ? '科研项目' : '对话分组',
                  style: context.texts.labelSmall,
                ),
              ),
              IconButton(
                tooltip: research ? '新建项目' : '新建分组',
                onPressed: research
                    ? () => _createResearchProject(context, app)
                    : () => _showCreateGroup(context, app),
                icon: const Icon(LucideIcons.plus, size: 16),
              ),
            ],
          ),
          Expanded(
            child: ListView(
              padding: EdgeInsets.zero,
              children: research
                  ? _projectEntries(context, app, query)
                  : _learningEntries(context, app, query),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _projectEntries(
    BuildContext context,
    AppState app,
    String query,
  ) {
    final normalized = query.trim().toLowerCase();
    final projects = normalized.isEmpty
        ? app.researchProjects
        : app.researchProjects
              .where(
                (project) => project.name.toLowerCase().contains(normalized),
              )
              .toList();
    if (projects.isEmpty) {
      return [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Text(
            normalized.isEmpty ? '暂无科研项目' : '没有匹配的项目',
            style: context.texts.bodySmall,
          ),
        ),
      ];
    }
    return [
      for (final project in projects)
        _SideEntry(
          icon: LucideIcons.brainCircuit,
          label: project.name,
          selected: false,
          onTap: () => onOpenProject(project),
        ),
    ];
  }

  Future<void> _createResearchProject(
    BuildContext context,
    AppState app,
  ) async {
    final name = TextEditingController();
    final description = TextEditingController();
    final create = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('新建科研项目'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: name,
                autofocus: true,
                decoration: const InputDecoration(labelText: '项目名称'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: description,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(labelText: '研究目标或说明'),
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
            onPressed: () =>
                Navigator.pop(dialogContext, name.text.trim().isNotEmpty),
            child: const Text('创建并打开'),
          ),
        ],
      ),
    );
    if (create == true && context.mounted) {
      final project = await app.createResearchProject(
        name.text,
        description.text,
      );
      if (context.mounted) onOpenProject(project);
    }
    name.dispose();
    description.dispose();
  }

  List<Widget> _learningEntries(
    BuildContext context,
    AppState app,
    String query,
  ) {
    final normalized = query.trim().toLowerCase();
    bool matches(String value) =>
        normalized.isEmpty || value.toLowerCase().contains(normalized);
    final groups = app.groups.where((group) {
      if (matches(group.name)) return true;
      return app
          .conversationsInGroup(group.id)
          .any((conversation) => matches(conversation.title));
    }).toList();
    final ungrouped = app.ungroupedConversations
        .where((conversation) => matches(conversation.title))
        .toList();

    Widget groupList() {
      Widget entry(ChatGroup group, int index, {required bool reorderable}) {
        final conversations = app
            .conversationsInGroup(group.id)
            .where(
              (conversation) =>
                  normalized.isEmpty ||
                  matches(group.name) ||
                  matches(conversation.title),
            )
            .toList();
        final row = _ExpandableSidebarRow(
          icon: LucideIcons.folder,
          label: group.name,
          onNewConversation: () => onNewConversationInGroup(group),
          onRename: () => _renameGroup(context, app, group),
          onDelete: () => _deleteGroup(context, app, group),
          children: conversations
              .map(
                (conversation) => _ConversationEntry(
                  conversation: conversation,
                  onTap: () => onOpenConversation(conversation),
                  onDelete: () =>
                      _deleteConversation(context, app, conversation),
                ),
              )
              .toList(),
        );
        return Padding(
          key: ValueKey(group.id),
          padding: const EdgeInsets.only(bottom: 4),
          child: reorderable
              ? ReorderableDelayedDragStartListener(index: index, child: row)
              : row,
        );
      }

      if (normalized.isNotEmpty) {
        return Column(
          children: [
            for (var index = 0; index < groups.length; index++)
              entry(groups[index], index, reorderable: false),
          ],
        );
      }
      return ReorderableListView.builder(
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        buildDefaultDragHandles: false,
        itemCount: groups.length,
        onReorder: (oldIndex, newIndex) =>
            app.reorderGroups(oldIndex, newIndex),
        itemBuilder: (context, index) =>
            entry(groups[index], index, reorderable: true),
      );
    }

    return [
      if (groups.isEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Text(
            normalized.isEmpty ? '暂无对话分组' : '没有匹配的对话组',
            style: context.texts.bodySmall,
          ),
        )
      else
        groupList(),
      const SizedBox(height: 12),
      Text(
        '历史对话',
        key: const ValueKey('workspace-history-heading'),
        style: context.texts.labelSmall,
      ),
      const SizedBox(height: 6),
      if (ungrouped.isEmpty)
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          child: Text(
            normalized.isEmpty ? '暂无历史对话' : '没有匹配的历史对话',
            style: context.texts.bodySmall,
          ),
        )
      else
        for (final conversation in ungrouped)
          _ConversationEntry(
            conversation: conversation,
            onTap: () => onOpenConversation(conversation),
            onDelete: () => _deleteConversation(context, app, conversation),
          ),
    ];
  }

  Future<void> _renameGroup(
    BuildContext context,
    AppState app,
    ChatGroup group,
  ) async {
    final controller = TextEditingController(text: group.name);
    final accepted = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('重命名分组'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: '分组名称'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    final name = accepted?.trim();
    if (name != null && name.isNotEmpty) {
      await app.updateGroup(group.id, name: name);
    }
    controller.dispose();
  }

  Future<void> _deleteConversation(
    BuildContext context,
    AppState app,
    ChatConversation conversation,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除对话'),
        content: Text('确定要删除「${conversation.title}」吗？此操作无法撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(
              foregroundColor: const Color(0xFFE5484D),
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await app.deleteConversation(conversation.id);
    }
  }

  Future<void> _deleteGroup(
    BuildContext context,
    AppState app,
    ChatGroup group,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除分组'),
        content: const Text('删除后，组内对话会移回未分组，此操作无法撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(
              foregroundColor: const Color(0xFFE5484D),
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await app.deleteGroup(group.id);
    }
  }

  Future<void> _showCreateGroup(BuildContext context, AppState app) async {
    final controller = TextEditingController();
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('新建分组'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: '分组名称'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('创建'),
          ),
        ],
      ),
    );
    if (accepted == true && controller.text.trim().isNotEmpty) {
      await app.createGroup(name: controller.text.trim());
    }
    controller.dispose();
  }
}

class _RevealSidebarButton extends StatelessWidget {
  const _RevealSidebarButton({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Align(
    alignment: Alignment.center,
    child: IconButton(
      tooltip: '展开侧栏',
      onPressed: onTap,
      icon: const Icon(LucideIcons.chevronsRight, size: 17),
    ),
  );
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
      color: selected
          ? EsaColors.accent.withValues(alpha: 0.15)
          : Colors.transparent,
      borderRadius: BorderRadius.circular(7),
      child: InkWell(
        borderRadius: BorderRadius.circular(7),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
          child: Row(
            children: [
              Icon(
                icon,
                size: 17,
                color: selected ? const Color(0xFF5D98FF) : context.n.n600,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    color: selected ? const Color(0xFF6EA3FF) : null,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _ExpandableSidebarRow extends StatefulWidget {
  const _ExpandableSidebarRow({
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
  State<_ExpandableSidebarRow> createState() => _ExpandableSidebarRowState();
}

class _ExpandableSidebarRowState extends State<_ExpandableSidebarRow> {
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

class _ConversationEntry extends StatelessWidget {
  const _ConversationEntry({
    required this.conversation,
    required this.onTap,
    this.onDelete,
  });
  final ChatConversation conversation;
  final VoidCallback onTap;
  final VoidCallback? onDelete;

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
    trailing: onDelete == null
        ? null
        : IconButton(
            tooltip: '删除对话',
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 26, minHeight: 26),
            iconSize: 14,
            icon: const Icon(LucideIcons.trash2),
            onPressed: onDelete,
          ),
    onTap: onTap,
  );
}

class _StudentContextRail extends StatefulWidget {
  const _StudentContextRail({
    required this.section,
    required this.researchProject,
    required this.selectedAttachments,
    required this.onAddAttachment,
    required this.onRemoveAttachment,
  });
  final StudentSection section;
  final ResearchProject? researchProject;
  final List<DocumentAttachment> selectedAttachments;
  final VoidCallback onAddAttachment;
  final VoidCallback onRemoveAttachment;

  @override
  State<_StudentContextRail> createState() => _StudentContextRailState();
}

class _StudentContextRailState extends State<_StudentContextRail> {
  bool _citeCourseMaterials = true;
  bool _rememberLearning = true;
  bool _webSearch = false;

  void _reset() {
    setState(() {
      _citeCourseMaterials = true;
      _rememberLearning = true;
      _webSearch = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final research = widget.section == StudentSection.research;
    final recent = app.conversations.take(3).map((item) => item.title).toList();
    final projects = app.researchProjects
        .take(3)
        .map((item) => item.name)
        .toList();
    if (research && widget.researchProject != null) {
      return _ContextRailFrame(
        child: _ResearchProjectContextRail(project: widget.researchProject!),
      );
    }
    if (research) {
      return _ContextRailFrame(
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            _ContextCard(
              icon: LucideIcons.clipboardList,
              title: '研究项目',
              lines: projects.isEmpty ? const ['还没有研究项目'] : projects,
            ),
            _ContextCard(
              icon: LucideIcons.messageSquare,
              title: '最近研究对话',
              lines: recent.isEmpty ? const ['暂无研究对话'] : recent,
            ),
          ],
        ),
      );
    }

    final courseName =
        app.learningCourses.firstOrNull?.name ??
        app.scheduleCourseNames.firstOrNull ??
        '尚未选择课程';
    final related = <String>{
      ...?app.masteryReport?.stalePoints.map((item) => item.name),
      ...?app.masteryReport?.weakPoints.map((item) => item.name),
    }.take(5).toList();
    final chapter = related.firstOrNull;

    return _ContextRailFrame(
      child: ListView(
        key: const ValueKey('learning-context-panel'),
        padding: const EdgeInsets.fromLTRB(16, 18, 16, 20),
        children: [
          Text(
            '当前上下文',
            style: context.texts.titleLarge?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 18),
          _ContextSection(
            title: '当前课程',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(courseName, style: context.texts.bodyMedium),
                const SizedBox(height: 4),
                Text(
                  chapter == null ? '尚未选择章节' : '重点：$chapter',
                  style: context.texts.bodySmall,
                ),
              ],
            ),
          ),
          _ContextSection(
            title: '已选资料 ${widget.selectedAttachments.length}',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (widget.selectedAttachments.isEmpty)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Text('暂未选择资料', style: context.texts.bodySmall),
                  )
                else
                  for (final attachment in widget.selectedAttachments)
                    _SelectedAttachmentRow(
                      attachment: attachment,
                      onRemove: widget.onRemoveAttachment,
                    ),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: widget.onAddAttachment,
                    icon: const Icon(LucideIcons.plus, size: 15),
                    label: const Text('添加资料'),
                  ),
                ),
              ],
            ),
          ),
          _ContextSection(
            title: '相关知识点',
            child: related.isEmpty
                ? Text('暂无相关知识点', style: context.texts.bodySmall)
                : Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final item in related) _KnowledgeTag(label: item),
                    ],
                  ),
          ),
          _ContextSection(
            title: '本次对话设置',
            child: Column(
              children: [
                _ContextToggle(
                  title: '引用课程资料',
                  subtitle: '优先引用已选择的课程资料',
                  value: _citeCourseMaterials,
                  onChanged: (value) =>
                      setState(() => _citeCourseMaterials = value),
                ),
                _ContextToggle(
                  title: '长期记忆',
                  subtitle: '记住本次学习中的关键信息',
                  value: _rememberLearning,
                  onChanged: (value) =>
                      setState(() => _rememberLearning = value),
                ),
                _ContextToggle(
                  title: '联网搜索',
                  subtitle: '需要时联网补充信息',
                  value: _webSearch,
                  onChanged: (value) => setState(() => _webSearch = value),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: Text('回答风格', style: context.texts.bodyMedium),
                    ),
                    Text(
                      _answerStyleLabel(app.preferences.preferredStyle),
                      style: context.texts.bodySmall,
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed: _reset,
                    child: const Text('重置设置'),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ContextRailFrame extends StatelessWidget {
  const _ContextRailFrame({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: context.scheme.surface,
      border: Border(left: BorderSide(color: context.n.divider)),
    ),
    child: child,
  );
}

class _ContextSection extends StatelessWidget {
  const _ContextSection({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.only(bottom: 16),
    margin: const EdgeInsets.only(bottom: 16),
    decoration: BoxDecoration(
      border: Border(bottom: BorderSide(color: context.n.divider)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: context.texts.labelMedium),
        const SizedBox(height: 10),
        child,
      ],
    ),
  );
}

class _SelectedAttachmentRow extends StatelessWidget {
  const _SelectedAttachmentRow({
    required this.attachment,
    required this.onRemove,
  });

  final DocumentAttachment attachment;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      children: [
        Icon(LucideIcons.fileText, size: 16, color: context.n.n600),
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                attachment.filename,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.texts.bodySmall,
              ),
              Text(
                '${attachment.extension.isEmpty ? '文件' : attachment.extension.toUpperCase()} · ${_contextFileSize(attachment.sizeBytes)}',
                style: context.texts.labelSmall,
              ),
            ],
          ),
        ),
        IconButton(
          tooltip: '移除资料',
          onPressed: onRemove,
          icon: const Icon(LucideIcons.x, size: 15),
          constraints: const BoxConstraints(minWidth: 30, minHeight: 30),
          padding: EdgeInsets.zero,
        ),
      ],
    ),
  );
}

class _KnowledgeTag extends StatelessWidget {
  const _KnowledgeTag({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(6),
    ),
    child: Text(label, style: context.texts.labelSmall),
  );
}

class _ContextToggle extends StatelessWidget {
  const _ContextToggle({
    required this.title,
    required this.subtitle,
    required this.value,
    required this.onChanged,
  });

  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: context.texts.bodySmall),
              const SizedBox(height: 2),
              Text(subtitle, style: context.texts.labelSmall),
            ],
          ),
        ),
        Transform.scale(
          scale: 0.72,
          alignment: Alignment.topRight,
          child: Switch(value: value, onChanged: onChanged),
        ),
      ],
    ),
  );
}

String _contextFileSize(int bytes) {
  if (bytes <= 0) return '大小未知';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}

String _answerStyleLabel(String value) => switch (value) {
  'detailed' => '详细',
  'socratic' => '苏格拉底',
  'concise' => '默认',
  _ => '默认',
};

String _projectStatusLabel(String status) => switch (status) {
  'active' => '进行中',
  'archived' => '已归档',
  'completed' => '已完成',
  _ => status.isEmpty ? '未设置' : status,
};

String _dateLabel(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-'
    '${value.month.toString().padLeft(2, '0')}-'
    '${value.day.toString().padLeft(2, '0')}';

class _ResearchProjectContextRail extends StatefulWidget {
  const _ResearchProjectContextRail({required this.project});

  final ResearchProject project;

  @override
  State<_ResearchProjectContextRail> createState() =>
      _ResearchProjectContextRailState();
}

class _ResearchProjectContextRailState
    extends State<_ResearchProjectContextRail> {
  bool _loading = true;
  List<ResearchDataset> _datasets = const [];
  List<ResearchDocument> _documents = const [];
  List<FrontierTrackingJob> _frontierJobs = const [];
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loading) unawaited(_load());
  }

  @override
  void didUpdateWidget(covariant _ResearchProjectContextRail oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.project.id != widget.project.id) {
      _loading = true;
      unawaited(_load());
    }
  }

  Future<void> _load() async {
    final api = AppScope.of(context).api;
    try {
      final values = await Future.wait([
        api.listResearchDatasets(widget.project.id),
        api.listResearchDocuments(widget.project.id),
        api.listFrontierJobs(widget.project.id),
      ]);
      if (!mounted) return;
      setState(() {
        _datasets = values[0] as List<ResearchDataset>;
        _documents = values[1] as List<ResearchDocument>;
        _frontierJobs = values[2] as List<FrontierTrackingJob>;
        _error = null;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.detail;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = '项目数据暂时无法加载';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 4),
      children: [
        if (_error != null)
          _ContextCard(
            icon: LucideIcons.circleAlert,
            title: '加载失败',
            lines: [_error!],
          ),
        _ContextCard(
          icon: LucideIcons.clipboardList,
          title: '项目上下文',
          lines: [
            '研究主题  ${widget.project.name}',
            '项目状态  ${_projectStatusLabel(widget.project.status)}',
            '最近更新  ${_dateLabel(widget.project.updatedAt)}',
            if (widget.project.description.trim().isNotEmpty)
              widget.project.description.trim(),
          ],
        ),
        _ContextCard(
          icon: LucideIcons.database,
          title: '数据集',
          lines: _datasets.isEmpty
              ? const ['暂无数据集']
              : _datasets.take(3).map((item) => item.name).toList(),
        ),
        _ContextCard(
          icon: LucideIcons.bookMarked,
          title: '前沿检索',
          lines: _frontierJobs.isEmpty
              ? const ['暂无前沿检索记录']
              : _frontierJobs.take(3).map((item) => item.query).toList(),
        ),
        _ContextCard(
          icon: LucideIcons.files,
          title: '项目文档',
          lines: _documents.isEmpty
              ? const ['暂无项目文档']
              : _documents.take(3).map((item) => item.title).toList(),
        ),
      ],
    );
  }
}

class _ContextCard extends StatelessWidget {
  const _ContextCard({
    required this.icon,
    required this.title,
    required this.lines,
  });
  final IconData icon;
  final String title;
  final List<String> lines;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.fromLTRB(14, 14, 14, 16),
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(11),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 17, color: context.n.n700),
            const SizedBox(width: 8),
            Expanded(child: Text(title, style: context.texts.titleMedium)),
          ],
        ),
        const SizedBox(height: 12),
        for (final line in lines) ...[
          Text(line, style: context.texts.bodySmall),
          const SizedBox(height: 7),
        ],
      ],
    ),
  );
}

class _MobileHeader extends StatelessWidget {
  const _MobileHeader({
    required this.section,
    required this.onSelect,
    required this.onProfile,
    required this.onMemory,
    required this.onActions,
    this.onHistory,
  });
  final StudentSection section;
  final ValueChanged<StudentSection> onSelect;
  final VoidCallback onProfile;
  final VoidCallback onMemory;
  final VoidCallback onActions;
  final VoidCallback? onHistory;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(18, 14, 14, 10),
    child: Row(
      children: [
        const _EsaWordmark(),
        const SizedBox(width: 14),
        Expanded(
          child: Text(switch (section) {
            StudentSection.home => '首页',
            StudentSection.research => '研究空间',
            StudentSection.knowledge => '知识地图',
            StudentSection.knowledgeBase => '个人知识库',
            StudentSection.assignments => '作业',
            StudentSection.schedule => '日程',
          }, style: context.texts.headlineSmall),
        ),
        IconButton(
          tooltip: '长期记忆',
          onPressed: onMemory,
          icon: const Icon(LucideIcons.brain),
        ),
        IconButton(
          tooltip: '待确认动作',
          onPressed: onActions,
          icon: const Icon(LucideIcons.shieldCheck),
        ),
        if (onHistory != null)
          IconButton(
            tooltip: '历史对话',
            onPressed: onHistory,
            icon: const Icon(LucideIcons.panelLeftOpen),
          ),
        IconButton(
          tooltip: '设置',
          onPressed: onProfile,
          icon: const Icon(LucideIcons.settings),
        ),
      ],
    ),
  );
}

class _MobileConversationHeader extends StatelessWidget {
  const _MobileConversationHeader({
    required this.title,
    required this.onBack,
    required this.onHistory,
  });

  final String title;
  final VoidCallback onBack;
  final VoidCallback onHistory;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: 58,
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      child: Row(
        children: [
          IconButton(
            tooltip: '返回学习首页',
            onPressed: onBack,
            icon: const Icon(LucideIcons.chevronLeft, size: 25),
          ),
          Expanded(
            child: Text(
              title,
              textAlign: TextAlign.center,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: context.texts.titleLarge?.copyWith(fontSize: 17),
            ),
          ),
          IconButton(
            tooltip: '历史对话',
            onPressed: onHistory,
            icon: const Icon(LucideIcons.panelLeftOpen, size: 21),
          ),
        ],
      ),
    ),
  );
}

class _MobileLearningTabs extends StatelessWidget {
  const _MobileLearningTabs({required this.section, required this.onSelect});
  final StudentSection section;
  final ValueChanged<StudentSection> onSelect;

  @override
  Widget build(BuildContext context) {
    const entries = [
      (StudentSection.home, '首页'),
      (StudentSection.assignments, '作业'),
      (StudentSection.schedule, '日程'),
      (StudentSection.knowledge, '知识'),
      (StudentSection.knowledgeBase, '资料库'),
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 2, 12, 6),
      child: SizedBox(
        height: 40,
        child: Row(
          children: [
            for (var index = 0; index < entries.length; index++) ...[
              if (index > 0) const SizedBox(width: 4),
              Expanded(
                child: Builder(
                  builder: (context) {
                    final entry = entries[index];
                    final active = section == entry.$1;
                    return TextButton(
                      onPressed: () => onSelect(entry.$1),
                      style: TextButton.styleFrom(
                        backgroundColor: active
                            ? EsaColors.accent.withValues(alpha: 0.16)
                            : Colors.transparent,
                        foregroundColor: active
                            ? const Color(0xFF70A3FF)
                            : context.n.n600,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                      ),
                      child: Text(entry.$2),
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

class _MobileBottomBar extends StatelessWidget {
  const _MobileBottomBar({
    required this.research,
    required this.onLearning,
    required this.onResearch,
    required this.onProfile,
  });
  final bool research;
  final VoidCallback onLearning;
  final VoidCallback onResearch;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: context.scheme.surface,
      border: Border(top: BorderSide(color: context.n.divider)),
    ),
    child: SafeArea(
      top: false,
      child: Row(
        children: [
          _BottomDestination(
            key: const ValueKey('student-learning-destination'),
            icon: LucideIcons.graduationCap,
            label: '学习',
            active: !research,
            onTap: onLearning,
          ),
          _BottomDestination(
            key: const ValueKey('student-research-destination'),
            icon: LucideIcons.layers3,
            label: '研究',
            active: research,
            onTap: onResearch,
          ),
          _BottomDestination(
            key: const ValueKey('student-profile-destination'),
            icon: LucideIcons.userRound,
            label: '我的',
            active: false,
            onTap: onProfile,
          ),
        ],
      ),
    ),
  );
}

class _BottomDestination extends StatelessWidget {
  const _BottomDestination({
    super.key,
    required this.icon,
    required this.label,
    required this.active,
    this.onTap,
  });
  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Expanded(
    child: InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 10),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              color: active ? const Color(0xFF4B8CFF) : context.n.n600,
            ),
            const SizedBox(height: 3),
            Text(
              label,
              style: TextStyle(
                fontSize: 12,
                color: active ? const Color(0xFF4B8CFF) : context.n.n600,
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class _EsaWordmark extends StatelessWidget {
  const _EsaWordmark({this.compact = false});
  final bool compact;

  @override
  Widget build(BuildContext context) => Text(
    'ESA',
    style: TextStyle(
      color: const Color(0xFF6B9DFF),
      fontSize: compact ? 15 : 26,
      fontWeight: FontWeight.w800,
      letterSpacing: 0,
    ),
  );
}

class _UserAvatar extends StatelessWidget {
  const _UserAvatar({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    borderRadius: BorderRadius.circular(30),
    child: Container(
      width: 36,
      height: 36,
      decoration: const BoxDecoration(
        shape: BoxShape.circle,
        color: EsaColors.accent,
      ),
      child: const Icon(LucideIcons.userRound, size: 19, color: Colors.white),
    ),
  );
}
