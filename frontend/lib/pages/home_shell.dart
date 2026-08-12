import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../widgets/workspace_switcher.dart';
import 'chat_page.dart';
import 'knowledge_map_page.dart';
import 'research_workspace_page.dart';
import 'schedule_page.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  void _select(int index) {
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() => _index = index);
  }

  void _workspaceChanged() => setState(() => _index = 0);

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final workspace = app.activeWorkspace;
    final pages = _pages(workspace);
    final destinations = _destinations(workspace);
    if (_index >= pages.length) _index = 0;

    final content = Column(
      children: [
        WorkspaceSwitcher(onChanged: _workspaceChanged),
        Expanded(
          child: IndexedStack(index: _index, children: pages),
        ),
      ],
    );
    final wide = MediaQuery.sizeOf(context).width >= 880;
    if (wide) {
      return Scaffold(
        resizeToAvoidBottomInset: false,
        body: Row(
          children: [
            Expanded(child: content),
            DecoratedBox(
              decoration: BoxDecoration(
                color: context.scheme.surface,
                border: Border(left: BorderSide(color: context.n.divider)),
              ),
              child: SafeArea(
                child: NavigationRail(
                  selectedIndex: _index,
                  onDestinationSelected: _select,
                  backgroundColor: Colors.transparent,
                  indicatorColor: context.scheme.primary.withValues(
                    alpha: 0.16,
                  ),
                  labelType: NavigationRailLabelType.all,
                  minWidth: 76,
                  destinations: destinations
                      .map(
                        (item) => NavigationRailDestination(
                          icon: Icon(item.icon),
                          selectedIcon: Icon(
                            item.icon,
                            color: const Color(0xFF2563EB),
                          ),
                          label: Text(item.label),
                        ),
                      )
                      .toList(),
                ),
              ),
            ),
          ],
        ),
      );
    }

    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      resizeToAvoidBottomInset: false,
      body: content,
      bottomNavigationBar: keyboardOpen
          ? null
          : DecoratedBox(
              decoration: BoxDecoration(
                color: context.scheme.surface,
                border: Border(top: BorderSide(color: context.n.divider)),
              ),
              child: SafeArea(
                top: false,
                child: Center(
                  heightFactor: 1,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 460),
                    child: NavigationBar(
                      height: 64,
                      selectedIndex: _index,
                      onDestinationSelected: _select,
                      backgroundColor: Colors.transparent,
                      indicatorColor: context.scheme.primary.withValues(
                        alpha: 0.16,
                      ),
                      destinations: destinations
                          .map(
                            (item) => NavigationDestination(
                              icon: Icon(item.icon),
                              selectedIcon: Icon(
                                item.icon,
                                color: const Color(0xFF2563EB),
                              ),
                              label: item.label,
                            ),
                          )
                          .toList(),
                    ),
                  ),
                ),
              ),
            ),
    );
  }

  List<Widget> _pages(WorkspaceType workspace) => switch (workspace) {
    WorkspaceType.learning => [
      const ChatPage(),
      const SchedulePage(),
      KnowledgeMapPage(
        onOpenChat: () => _select(0),
        onOpenSchedule: () => _select(1),
      ),
    ],
    WorkspaceType.research => [
      ResearchWorkspacePage(onOpenChat: () => _select(1)),
      const ChatPage(),
    ],
    WorkspaceType.teaching => const [ChatPage(), _TeachingOverview()],
  };

  List<_Destination> _destinations(WorkspaceType workspace) =>
      switch (workspace) {
        WorkspaceType.learning => const [
          _Destination('学习助手', LucideIcons.messageCircle),
          _Destination('课表', LucideIcons.calendarDays),
          _Destination('知识地图', LucideIcons.gitBranch),
        ],
        WorkspaceType.research => const [
          _Destination('科研项目', LucideIcons.flaskConical),
          _Destination('科研对话', LucideIcons.messageCircle),
        ],
        WorkspaceType.teaching => const [
          _Destination('教学助手', LucideIcons.messageCircle),
          _Destination('教学工作台', LucideIcons.layoutDashboard),
        ],
      };
}

class _Destination {
  const _Destination(this.label, this.icon);

  final String label;
  final IconData icon;
}

class _TeachingOverview extends StatelessWidget {
  const _TeachingOverview();

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(LucideIcons.presentation, size: 42),
        const SizedBox(height: 16),
        Text('教学工作台', style: context.texts.headlineSmall),
        const SizedBox(height: 8),
        const Text('教学场景的独立模块将在后续垂直切片中接入。'),
      ],
    ),
  );
}
