import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/profile_sheet.dart';
import 'chat_page.dart';
import 'knowledge_map_page.dart';
import 'research_project_page.dart';
import 'research_workspace_page.dart';
import 'schedule_page.dart';
import 'student_assignments_page.dart';

enum StudentSection { assistant, assignments, schedule, knowledge, research }

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  StudentSection _section = StudentSection.assistant;
  bool _sidebarCollapsed = false;
  bool _sidebarRequested = false;
  ResearchProject? _activeResearchProject;

  bool get _inResearch => _section == StudentSection.research;

  Future<void> _select(StudentSection section) async {
    FocusManager.instance.primaryFocus?.unfocus();
    final app = AppScope.of(context);
    final target = section == StudentSection.research
        ? WorkspaceType.research
        : WorkspaceType.learning;
    if (app.activeWorkspace != target) await app.switchWorkspace(target);
    if (!mounted) return;
    setState(() => _section = section);
  }

  Widget _page() => switch (_section) {
    StudentSection.assistant => const ChatPage(embedded: true),
    StudentSection.assignments => StudentAssignmentsPage(
      onOpenChat: () => unawaited(_select(StudentSection.assistant)),
    ),
    StudentSection.schedule => const SchedulePage(),
    StudentSection.knowledge => KnowledgeMapPage(
      embedded: true,
      onOpenChat: () => unawaited(_select(StudentSection.assistant)),
      onOpenSchedule: () => unawaited(_select(StudentSection.schedule)),
    ),
    StudentSection.research =>
      _activeResearchProject == null
          ? ResearchWorkspacePage(
              onOpenChat: () => unawaited(_select(StudentSection.research)),
              onOpenProject: (project) =>
                  setState(() => _activeResearchProject = project),
            )
          : ResearchProjectPage(
              project: _activeResearchProject!,
              embedded: true,
              onBack: () => setState(() => _activeResearchProject = null),
              onOpenChat: () => unawaited(_select(StudentSection.research)),
            ),
  };

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    return width >= 1040 ? _desktop() : _mobile();
  }

  Widget _desktop() {
    final app = AppScope.of(context);
    final width = MediaQuery.sizeOf(context).width;
    final showSidebar =
        _section != StudentSection.assistant ||
        app.messages.isNotEmpty ||
        _sidebarRequested;
    final showContext = width >= 1180;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            const SizedBox(
              height: 26,
              child: Center(
                child: Text(
                  'ESA 星知智链',
                  style: TextStyle(fontSize: 11, color: Color(0xFFADB8C9)),
                ),
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
                child: Row(
                  children: [
                    _GlobalRail(
                      key: const ValueKey('student-global-rail'),
                      section: _section,
                      onSelect: (section) {
                        if (section == StudentSection.assistant &&
                            _section == StudentSection.assistant) {
                          setState(() {
                            _sidebarRequested = true;
                            _sidebarCollapsed = false;
                          });
                        }
                        unawaited(_select(section));
                      },
                      onProfile: () => showProfileSheet(context),
                    ),
                    if (showSidebar) ...[
                      const SizedBox(width: 8),
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 180),
                        width: _sidebarCollapsed ? 0 : 258,
                        child: _sidebarCollapsed
                            ? const SizedBox.shrink()
                            : _WorkspaceSidebar(
                                section: _section,
                                onSelect: (section) =>
                                    unawaited(_select(section)),
                                onOpenProject: (project) => setState(
                                  () => _activeResearchProject = project,
                                ),
                                onCollapse: () =>
                                    setState(() => _sidebarCollapsed = true),
                              ),
                      ),
                      if (_sidebarCollapsed)
                        _RevealSidebarButton(
                          onTap: () =>
                              setState(() => _sidebarCollapsed = false),
                        ),
                    ],
                    const SizedBox(width: 10),
                    Expanded(
                      child: _SurfaceFrame(
                        key: ValueKey(_section),
                        child: _page(),
                      ),
                    ),
                    if (showContext) ...[
                      const SizedBox(width: 10),
                      SizedBox(
                        width: 268,
                        child: _StudentContextRail(
                          section: _section,
                          conversationActive: app.messages.isNotEmpty,
                          researchProject: _activeResearchProject,
                        ),
                      ),
                    ],
                  ],
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
    final conversationActive =
        _section == StudentSection.assistant && app.messages.isNotEmpty;
    final researchProjectActive =
        _section == StudentSection.research && _activeResearchProject != null;
    return Scaffold(
      resizeToAvoidBottomInset: false,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            if (conversationActive)
              _MobileConversationHeader(
                title: app.activeConversation?.title ?? '新对话',
                onBack: app.newConversation,
              )
            else if (!researchProjectActive)
              _MobileHeader(
                section: _section,
                onSelect: (section) => unawaited(_select(section)),
                onProfile: () => showProfileSheet(context),
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
              onLearning: () => unawaited(_select(StudentSection.assistant)),
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
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: EsaColors.dSurface,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: context.n.divider),
    ),
    child: ClipRRect(borderRadius: BorderRadius.circular(10), child: child),
  );
}

class _GlobalRail extends StatelessWidget {
  const _GlobalRail({
    super.key,
    required this.section,
    required this.onSelect,
    required this.onProfile,
  });

  final StudentSection section;
  final ValueChanged<StudentSection> onSelect;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => Container(
    width: 68,
    decoration: BoxDecoration(
      color: const Color(0xFF07111D),
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(10),
    ),
    child: Column(
      children: [
        const SizedBox(height: 19),
        const _EsaWordmark(compact: true),
        const SizedBox(height: 24),
        _RailButton(
          icon: LucideIcons.messageCircle,
          tooltip: '学习助手',
          active: section == StudentSection.assistant,
          onTap: () => onSelect(StudentSection.assistant),
        ),
        _RailButton(
          icon: LucideIcons.search,
          tooltip: '搜索',
          active: false,
          onTap: () => onSelect(StudentSection.assistant),
        ),
        _RailButton(
          icon: LucideIcons.mapPinned,
          tooltip: '知识地图',
          active: section == StudentSection.knowledge,
          onTap: () => onSelect(StudentSection.knowledge),
        ),
        _RailButton(
          icon: LucideIcons.graduationCap,
          tooltip: '研究空间',
          active: section == StudentSection.research,
          onTap: () => onSelect(StudentSection.research),
        ),
        const Spacer(),
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
    required this.onSelect,
    required this.onCollapse,
    required this.onOpenProject,
  });
  final StudentSection section;
  final ValueChanged<StudentSection> onSelect;
  final VoidCallback onCollapse;
  final ValueChanged<ResearchProject> onOpenProject;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final research = section == StudentSection.research;
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF091521),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: context.n.divider),
      ),
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 12),
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
          FilledButton.icon(
            onPressed: research
                ? () => onSelect(StudentSection.research)
                : () {
                    unawaited(app.newConversation());
                    onSelect(StudentSection.assistant);
                  },
            icon: const Icon(LucideIcons.plus, size: 17),
            label: Text(research ? '新建项目' : '新对话'),
          ),
          const SizedBox(height: 12),
          TextField(
            readOnly: true,
            onTap: () => onSelect(
              research ? StudentSection.research : StudentSection.assistant,
            ),
            decoration: InputDecoration(
              hintText: research ? '搜索项目' : '搜索学习内容',
              prefixIcon: const Icon(LucideIcons.search, size: 17),
              isDense: true,
            ),
          ),
          const SizedBox(height: 14),
          Text('功能', style: context.texts.labelSmall),
          const SizedBox(height: 6),
          if (research)
            _SideEntry(
              icon: LucideIcons.flaskConical,
              label: '科研项目',
              selected: true,
              onTap: () => onSelect(StudentSection.research),
            )
          else ...[
            _SideEntry(
              icon: LucideIcons.messageCircle,
              label: '学习助手',
              selected: section == StudentSection.assistant,
              onTap: () => onSelect(StudentSection.assistant),
            ),
            _SideEntry(
              icon: LucideIcons.clipboardCheck,
              label: '作业',
              selected: section == StudentSection.assignments,
              onTap: () => onSelect(StudentSection.assignments),
            ),
            _SideEntry(
              icon: LucideIcons.calendarDays,
              label: '课表',
              selected: section == StudentSection.schedule,
              onTap: () => onSelect(StudentSection.schedule),
            ),
            _SideEntry(
              icon: LucideIcons.gitBranch,
              label: '知识地图',
              selected: section == StudentSection.knowledge,
              onTap: () => onSelect(StudentSection.knowledge),
            ),
          ],
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: Text(
                  research ? '项目' : '课程',
                  style: context.texts.labelSmall,
                ),
              ),
              IconButton(
                tooltip: research ? '新建项目' : '新建分组',
                onPressed: research
                    ? () => onSelect(StudentSection.research)
                    : () => _showCreateGroup(context, app),
                icon: const Icon(LucideIcons.plus, size: 16),
              ),
            ],
          ),
          Expanded(
            child: ListView(
              padding: EdgeInsets.zero,
              children: research
                  ? _projectEntries(context, app)
                  : _learningEntries(context, app),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _projectEntries(BuildContext context, AppState app) {
    if (app.researchProjects.isEmpty) {
      return [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 16),
          child: Text('暂无科研项目', style: context.texts.bodySmall),
        ),
      ];
    }
    return [
      for (final project in app.researchProjects)
        _SideEntry(
          icon: LucideIcons.brainCircuit,
          label: project.name,
          selected: false,
          onTap: () => onOpenProject(project),
        ),
    ];
  }

  List<Widget> _learningEntries(BuildContext context, AppState app) => [
    for (final courseName
        in app.scheduleCourses
            .map((item) => item.name)
            .where((name) => name.trim().isNotEmpty)
            .toSet())
      _ExpandableSidebarRow(
        icon: LucideIcons.bookOpen,
        label: courseName,
        children: const [
          _TreeLeaf(label: '课程资料'),
          _TreeLeaf(label: '学习记录'),
        ],
      ),
    for (final group in app.groups)
      _ExpandableSidebarRow(
        icon: LucideIcons.folder,
        label: group.name,
        children: app
            .conversationsInGroup(group.id)
            .map(
              (conversation) => _ConversationEntry(
                conversation: conversation,
                onTap: () {
                  unawaited(app.setActive(conversation.id));
                  onSelect(StudentSection.assistant);
                },
              ),
            )
            .toList(),
      ),
    const SizedBox(height: 12),
    Text('最近对话', style: context.texts.labelSmall),
    const SizedBox(height: 6),
    for (final conversation in app.ungroupedConversations.take(6))
      _ConversationEntry(
        conversation: conversation,
        onTap: () {
          unawaited(app.setActive(conversation.id));
          onSelect(StudentSection.assistant);
        },
      ),
  ];

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
  });
  final IconData icon;
  final String label;
  final List<Widget> children;

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
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
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

class _TreeLeaf extends StatelessWidget {
  const _TreeLeaf({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(12, 7, 6, 7),
    child: Row(
      children: [
        Container(
          width: 4,
          height: 4,
          decoration: BoxDecoration(
            color: context.n.n500,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 9),
        Expanded(child: Text(label, style: context.texts.bodySmall)),
      ],
    ),
  );
}

class _ConversationEntry extends StatelessWidget {
  const _ConversationEntry({required this.conversation, required this.onTap});
  final ChatConversation conversation;
  final VoidCallback onTap;

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
    onTap: onTap,
  );
}

class _StudentContextRail extends StatelessWidget {
  const _StudentContextRail({
    required this.section,
    required this.conversationActive,
    required this.researchProject,
  });
  final StudentSection section;
  final bool conversationActive;
  final ResearchProject? researchProject;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final research = section == StudentSection.research;
    final recent = app.conversations.take(3).map((item) => item.title).toList();
    final courses = app.scheduleCourses
        .map((item) => item.name)
        .where((name) => name.trim().isNotEmpty)
        .toSet()
        .take(3)
        .toList();
    final projects = app.researchProjects
        .take(3)
        .map((item) => item.name)
        .toList();
    if (!research && !conversationActive) {
      return const _LearningOverviewRail();
    }
    if (research && researchProject != null) {
      return ListView(
        padding: const EdgeInsets.symmetric(vertical: 4),
        children: [
          _ContextCard(
            icon: LucideIcons.clipboardList,
            title: '项目上下文',
            lines: [
              '研究主题  ${researchProject!.name}',
              '研究阶段  模型构建与验证',
              '团队成员  个人项目',
            ],
          ),
          const _ContextCard(
            icon: LucideIcons.database,
            title: '数据集',
            lines: ['ADNI 1/2/3 MRI', 'ADNI FDG-PET', 'ADNI 认知量表'],
          ),
          const _ContextCard(
            icon: LucideIcons.lightbulb,
            title: '当前假设',
            lines: ['多模态融合显著优于单模态', 'rs-fMRI 连接特征贡献最大'],
          ),
          const _ContextCard(
            icon: LucideIcons.bookMarked,
            title: '关键参考文献',
            lines: [
              'Zhou et al., NeuroImage, 2023',
              'Chen et al., Med Image Anal, 2022',
            ],
          ),
          const _ContextCard(
            icon: LucideIcons.files,
            title: '文件',
            lines: ['项目计划.pdf', '数据预处理脚本.ipynb', '实验记录.md'],
          ),
        ],
      );
    }
    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 4),
      children: research
          ? [
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
            ]
          : [
              _ContextCard(
                icon: LucideIcons.bookOpen,
                title: '学习上下文',
                lines: [
                  courses.isEmpty ? '当前课程  暂未选择' : '当前课程  ${courses.first}',
                  '当前知识点  极限与连续',
                ],
              ),
              const _ProgressContextCard(),
              const _ContextCard(
                icon: LucideIcons.circleAlert,
                title: '薄弱知识点',
                lines: [
                  '无穷小与无穷大             48%',
                  '函数的连续性判定           56%',
                  '极限的运算法则             61%',
                ],
              ),
              _ContextCard(
                icon: LucideIcons.files,
                title: '相关资料',
                lines: recent.isEmpty ? const ['暂无相关资料'] : recent,
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
      color: const Color(0xFF0B1724),
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

class _ProgressContextCard extends StatelessWidget {
  const _ProgressContextCard();

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 10),
    padding: const EdgeInsets.all(15),
    decoration: BoxDecoration(
      color: const Color(0xFF0B1724),
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(11),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('掌握度', style: context.texts.titleMedium),
        const SizedBox(height: 12),
        const Row(
          children: [
            Text(
              '72',
              style: TextStyle(
                fontSize: 34,
                color: Color(0xFF4387FF),
                fontWeight: FontWeight.w700,
              ),
            ),
            Text('%', style: TextStyle(color: Color(0xFF4387FF))),
          ],
        ),
        const SizedBox(height: 8),
        const LinearProgressIndicator(value: .72, minHeight: 5),
        const SizedBox(height: 8),
        Text('较上次提升 8%  ↑', style: context.texts.bodySmall),
      ],
    ),
  );
}

class _LearningOverviewRail extends StatelessWidget {
  const _LearningOverviewRail();

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.symmetric(vertical: 4),
    children: [
      _ContextCard(
        icon: LucideIcons.lightbulb,
        title: '今日学习建议',
        lines: const ['专注于理解核心概念，', '通过练习巩固知识点', '今日目标进度          3/6 完成'],
      ),
      _ContextCard(
        icon: LucideIcons.notebookTabs,
        title: '最近课程',
        lines: const [
          '高等数学          进度 72%',
          '线性代数          进度 46%',
          '概率论与数理统计  进度 28%',
        ],
      ),
      _ContextCard(
        icon: LucideIcons.chartNoAxesColumnIncreasing,
        title: '学习状态',
        lines: const ['本周学习时长', '18.6 小时', '连续学习天数  7 天', '知识点掌握率  72%'],
      ),
    ],
  );
}

class _MobileHeader extends StatelessWidget {
  const _MobileHeader({
    required this.section,
    required this.onSelect,
    required this.onProfile,
  });
  final StudentSection section;
  final ValueChanged<StudentSection> onSelect;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(18, 14, 14, 10),
    child: Row(
      children: [
        const _EsaWordmark(),
        const SizedBox(width: 14),
        Expanded(
          child: Text(
            switch (section) {
              StudentSection.research => '研究空间',
              StudentSection.knowledge => '知识地图',
              StudentSection.assignments => '作业',
              StudentSection.schedule => '课表',
              StudentSection.assistant => '学习空间',
            },
            style: context.texts.headlineSmall,
          ),
        ),
        IconButton(
          tooltip: '通知',
          onPressed: () {},
          icon: const Icon(LucideIcons.bell),
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
  const _MobileConversationHeader({required this.title, required this.onBack});

  final String title;
  final VoidCallback onBack;

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
            tooltip: '搜索对话',
            onPressed: () {},
            icon: const Icon(LucideIcons.search, size: 21),
          ),
          IconButton(
            tooltip: '更多',
            onPressed: () {},
            icon: const Icon(LucideIcons.ellipsis, size: 21),
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
      (StudentSection.assistant, '学习助手'),
      (StudentSection.assignments, '作业'),
      (StudentSection.schedule, '课表'),
      (StudentSection.knowledge, '知识地图'),
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
      color: EsaColors.dSurface,
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
