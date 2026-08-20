import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/profile_sheet.dart';
import 'chat_page.dart';
import 'teaching_workspace_page.dart';

enum TeacherSection { workbench, assistant }

class TeacherShell extends StatefulWidget {
  const TeacherShell({super.key});

  @override
  State<TeacherShell> createState() => _TeacherShellState();
}

class _TeacherShellState extends State<TeacherShell> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  TeacherSection _section = TeacherSection.workbench;
  bool _sidebarCollapsed = false;
  String _sidebarQuery = '';

  Future<void> _select(TeacherSection section) async {
    FocusManager.instance.primaryFocus?.unfocus();
    final app = AppScope.of(context);
    if (app.activeWorkspace != WorkspaceType.teaching) {
      await app.switchWorkspace(WorkspaceType.teaching);
    }
    if (!mounted) return;
    setState(() => _section = section);
  }

  Future<void> _newConversation() async {
    final app = AppScope.of(context);
    if (app.activeWorkspace != WorkspaceType.teaching) {
      await app.switchWorkspace(WorkspaceType.teaching);
    }
    await app.newConversation();
    if (!mounted) return;
    setState(() => _section = TeacherSection.assistant);
  }

  Future<void> _openConversation(ChatConversation conversation) async {
    await AppScope.of(context).setActive(conversation.id);
    if (!mounted) return;
    setState(() => _section = TeacherSection.assistant);
  }

  void _showTeachingAssistant() {
    if (!mounted) return;
    setState(() => _section = TeacherSection.assistant);
  }

  void _showWorkbench() {
    if (!mounted) return;
    setState(() => _section = TeacherSection.workbench);
  }

  Widget _page() => switch (_section) {
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
  };

  @override
  Widget build(BuildContext context) {
    return MediaQuery.sizeOf(context).width >= 1040 ? _desktop() : _mobile();
  }

  Widget _desktop() {
    final showContext = MediaQuery.sizeOf(context).width >= 1320;
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
              width: _sidebarCollapsed ? 0 : 276,
              child: _sidebarCollapsed
                  ? const SizedBox.shrink()
                  : _TeacherSidebar(
                      section: _section,
                      query: _sidebarQuery,
                      onQueryChanged: (value) =>
                          setState(() => _sidebarQuery = value),
                      onNewConversation: () => unawaited(_newConversation()),
                      onOpenConversation: (conversation) =>
                          unawaited(_openConversation(conversation)),
                      onCollapse: () =>
                          setState(() => _sidebarCollapsed = true),
                    ),
            ),
            if (_sidebarCollapsed)
              SizedBox(
                width: 38,
                child: Align(
                  alignment: Alignment.topCenter,
                  child: Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: IconButton(
                      tooltip: '展开侧栏',
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
            if (showContext)
              SizedBox(
                width: 292,
                child: _TeacherContextRail(section: _section),
              ),
          ],
        ),
      ),
    );
  }

  Widget _mobile() {
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      key: _scaffoldKey,
      resizeToAvoidBottomInset: false,
      drawer: Drawer(
        child: SafeArea(
          child: _TeacherSidebar(
            section: _section,
            query: _sidebarQuery,
            onQueryChanged: (value) => setState(() => _sidebarQuery = value),
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
              section: _section,
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
              onSelect: (section) => unawaited(_select(section)),
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
    width: 72,
    decoration: BoxDecoration(
      color: context.scheme.surface,
      border: Border(right: BorderSide(color: context.n.divider)),
    ),
    child: Column(
      children: [
        const SizedBox(height: 19),
        Text(
          'ESA',
          style: context.texts.titleMedium?.copyWith(
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 24),
        _TeacherRailButton(
          key: const ValueKey('teacher-workbench-destination'),
          icon: LucideIcons.layoutDashboard,
          tooltip: '教学工作台',
          active: section == TeacherSection.workbench,
          onTap: () => onSelect(TeacherSection.workbench),
        ),
        _TeacherRailButton(
          key: const ValueKey('teacher-assistant-destination'),
          icon: LucideIcons.messageSquareText,
          tooltip: '教学助手',
          active: section == TeacherSection.assistant,
          onTap: () => onSelect(TeacherSection.assistant),
        ),
        const Spacer(),
        _TeacherRailButton(
          icon: LucideIcons.settings,
          tooltip: '设置',
          active: false,
          onTap: onProfile,
        ),
        Padding(
          padding: const EdgeInsets.only(bottom: 18),
          child: Tooltip(
            message: '教师账号',
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: onProfile,
              child: CircleAvatar(
                radius: 17,
                backgroundColor: EsaColors.accent.withValues(alpha: .18),
                child: Text(
                  AppScope.of(context).username.characters.firstOrNull ?? '师',
                  style: context.texts.labelLarge,
                ),
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class _TeacherRailButton extends StatelessWidget {
  const _TeacherRailButton({
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
              ? EsaColors.accent.withValues(alpha: .18)
              : Colors.transparent,
          foregroundColor: active ? const Color(0xFF66A0FF) : context.n.n600,
        ),
        icon: Icon(icon, size: 21),
      ),
    ),
  );
}

class _TeacherSidebar extends StatelessWidget {
  const _TeacherSidebar({
    required this.section,
    required this.query,
    required this.onQueryChanged,
    required this.onNewConversation,
    required this.onOpenConversation,
    required this.onCollapse,
  });

  final TeacherSection section;
  final String query;
  final ValueChanged<String> onQueryChanged;
  final VoidCallback onNewConversation;
  final ValueChanged<ChatConversation> onOpenConversation;
  final VoidCallback onCollapse;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final normalized = query.trim().toLowerCase();
    final conversations = normalized.isEmpty
        ? app.conversations
        : app.conversations
              .where(
                (conversation) =>
                    conversation.title.toLowerCase().contains(normalized),
              )
              .toList();
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
                  '教学空间',
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
            key: const ValueKey('new-teacher-conversation'),
            onPressed: onNewConversation,
            icon: const Icon(LucideIcons.plus, size: 17),
            label: const Text('新建教学对话'),
          ),
          const SizedBox(height: 12),
          TextField(
            onChanged: onQueryChanged,
            decoration: const InputDecoration(
              hintText: '搜索教学对话',
              prefixIcon: Icon(LucideIcons.search, size: 17),
              isDense: true,
            ),
          ),
          const SizedBox(height: 18),
          Text('教学历史', style: context.texts.labelSmall),
          const SizedBox(height: 8),
          Expanded(
            child: app.loadingConversations
                ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
                : conversations.isEmpty
                ? Align(
                    alignment: Alignment.topLeft,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      child: Text(
                        normalized.isEmpty ? '暂无对话' : '没有匹配的对话',
                        style: context.texts.bodySmall?.copyWith(
                          color: context.n.n600,
                        ),
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: EdgeInsets.zero,
                    itemCount: conversations.length,
                    itemBuilder: (context, index) {
                      final conversation = conversations[index];
                      final active = conversation.id == app.activeId;
                      return ListTile(
                        key: ValueKey(
                          'teacher-conversation-${conversation.id}',
                        ),
                        dense: true,
                        selected: active,
                        leading: const Icon(
                          LucideIcons.messageSquare,
                          size: 17,
                        ),
                        title: Text(
                          conversation.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        onTap: () => onOpenConversation(conversation),
                      );
                    },
                  ),
          ),
          const Divider(),
          ListTile(
            dense: true,
            leading: const Icon(LucideIcons.userRoundCheck, size: 18),
            title: const Text('教师账号'),
            subtitle: Text(
              app.username,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}

class _TeacherContextRail extends StatelessWidget {
  const _TeacherContextRail({required this.section});

  final TeacherSection section;

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
        padding: const EdgeInsets.fromLTRB(20, 22, 20, 28),
        children: [
          Text('当前上下文', style: context.texts.titleLarge),
          const SizedBox(height: 22),
          _TeacherContextSection(
            title: '当前教学',
            children: [
              Text('教学空间', style: context.texts.titleMedium),
              const SizedBox(height: 5),
              Text(
                conversation?.title ??
                    (section == TeacherSection.workbench ? '教学工作台' : '新对话'),
                style: context.texts.bodySmall?.copyWith(color: context.n.n600),
              ),
            ],
          ),
          _TeacherContextSection(
            title: '绑定范围',
            children: [
              _TeacherContextLine(
                label: '班级',
                value: conversation?.classId ?? '未绑定',
              ),
              _TeacherContextLine(
                label: '作业',
                value: conversation?.assignmentId ?? '未绑定',
              ),
            ],
          ),
          const _TeacherContextSection(
            title: '教学闭环',
            children: [
              _TeacherWorkflowLine(icon: LucideIcons.school, text: '班级与邀请'),
              _TeacherWorkflowLine(
                icon: LucideIcons.clipboardCheck,
                text: '作业、提交与复核',
              ),
              _TeacherWorkflowLine(icon: LucideIcons.send, text: '反馈发布与学习证据'),
            ],
          ),
          _TeacherContextSection(
            title: '账号权限',
            children: [
              Row(
                children: [
                  const Icon(LucideIcons.badgeCheck, size: 17),
                  const SizedBox(width: 8),
                  Expanded(child: Text('教师 · ${app.username}')),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                '仅显示本人创建的班级、作业和已授权教学数据。',
                style: context.texts.bodySmall?.copyWith(color: context.n.n600),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TeacherContextSection extends StatelessWidget {
  const _TeacherContextSection({required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 22),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: context.texts.labelSmall),
        const SizedBox(height: 10),
        ...children,
        const SizedBox(height: 14),
        Divider(height: 1, color: context.n.divider),
      ],
    ),
  );
}

class _TeacherContextLine extends StatelessWidget {
  const _TeacherContextLine({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      children: [
        SizedBox(width: 44, child: Text(label, style: context.texts.bodySmall)),
        Expanded(
          child: Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: context.texts.bodySmall?.copyWith(color: context.n.n600),
          ),
        ),
      ],
    ),
  );
}

class _TeacherWorkflowLine extends StatelessWidget {
  const _TeacherWorkflowLine({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 10),
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
    required this.section,
    required this.onMenu,
    required this.onProfile,
  });

  final TeacherSection section;
  final VoidCallback onMenu;
  final VoidCallback onProfile;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: 58,
    child: Row(
      children: [
        IconButton(
          tooltip: '教学历史',
          onPressed: onMenu,
          icon: const Icon(LucideIcons.panelLeftOpen),
        ),
        const SizedBox(width: 4),
        Text('ESA', style: context.texts.titleMedium),
        const SizedBox(width: 14),
        Expanded(
          child: Text(
            switch (section) {
              TeacherSection.workbench => '教学工作台',
              TeacherSection.assistant => '教学助手',
            },
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: context.texts.titleLarge,
          ),
        ),
        IconButton(
          tooltip: '设置',
          onPressed: onProfile,
          icon: const Icon(LucideIcons.settings),
        ),
        const SizedBox(width: 6),
      ],
    ),
  );
}

class _TeacherBottomBar extends StatelessWidget {
  const _TeacherBottomBar({required this.section, required this.onSelect});

  final TeacherSection section;
  final ValueChanged<TeacherSection> onSelect;

  @override
  Widget build(BuildContext context) => NavigationBar(
    selectedIndex: section.index,
    onDestinationSelected: (index) => onSelect(TeacherSection.values[index]),
    destinations: const [
      NavigationDestination(
        key: ValueKey('teacher-mobile-workbench'),
        icon: Icon(LucideIcons.layoutDashboard),
        label: '教学',
      ),
      NavigationDestination(
        key: ValueKey('teacher-mobile-assistant'),
        icon: Icon(LucideIcons.messageSquareText),
        label: '助手',
      ),
    ],
  );
}
