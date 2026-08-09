import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../theme/esa_context.dart';
import 'chat_page.dart';
import 'knowledge_map_page.dart';
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      resizeToAvoidBottomInset: false,
      body: IndexedStack(
        index: _index,
        children: [
          const ChatPage(),
          const SchedulePage(),
          KnowledgeMapPage(
            onOpenChat: () => _select(0),
            onOpenSchedule: () => _select(1),
          ),
        ],
      ),
      bottomNavigationBar: DecoratedBox(
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
                indicatorColor: context.scheme.primary.withValues(alpha: 0.16),
                destinations: const [
                  NavigationDestination(
                    icon: Icon(LucideIcons.messageCircle),
                    selectedIcon: Icon(
                      LucideIcons.messageCircle,
                      color: Color(0xFF2563EB),
                    ),
                    label: '学习助手',
                  ),
                  NavigationDestination(
                    icon: Icon(LucideIcons.calendarDays),
                    selectedIcon: Icon(
                      LucideIcons.calendarDays,
                      color: Color(0xFF2563EB),
                    ),
                    label: '课表',
                  ),
                  NavigationDestination(
                    icon: Icon(LucideIcons.gitBranch),
                    selectedIcon: Icon(
                      LucideIcons.gitBranch,
                      color: Color(0xFF2563EB),
                    ),
                    label: '知识地图',
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
