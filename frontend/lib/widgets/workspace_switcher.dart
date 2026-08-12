import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../state/app_state.dart';
import '../theme/esa_context.dart';

class WorkspaceSwitcher extends StatelessWidget {
  const WorkspaceSwitcher({super.key, this.onChanged});

  final VoidCallback? onChanged;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return Material(
      color: context.scheme.surface,
      child: SafeArea(
        bottom: false,
        child: Container(
          height: 58,
          padding: const EdgeInsets.symmetric(horizontal: 18),
          decoration: BoxDecoration(
            border: Border(bottom: BorderSide(color: context.n.divider)),
          ),
          child: Row(
            children: [
              const Icon(LucideIcons.orbit, size: 19),
              const SizedBox(width: 10),
              MenuAnchor(
                alignmentOffset: const Offset(0, 8),
                menuChildren: app.availableWorkspaces
                    .map(
                      (workspace) => MenuItemButton(
                        key: ValueKey(
                          'workspace-option-${workspace.type.wireName}',
                        ),
                        onPressed: () {
                          final operation = app.switchWorkspace(workspace.type);
                          onChanged?.call();
                          unawaited(operation);
                        },
                        child: SizedBox(
                          width: 280,
                          child: ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            title: Text(workspace.name),
                            subtitle: workspace.description.isEmpty
                                ? null
                                : Text(workspace.description),
                          ),
                        ),
                      ),
                    )
                    .toList(),
                builder: (context, controller, child) => InkWell(
                  key: const ValueKey('workspace-switcher'),
                  borderRadius: BorderRadius.circular(8),
                  onTap: () => controller.isOpen
                      ? controller.close()
                      : controller.open(),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 6,
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          app.activeWorkspace.label,
                          style: context.texts.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(width: 6),
                        const Icon(LucideIcons.chevronsUpDown, size: 15),
                      ],
                    ),
                  ),
                ),
              ),
              const Spacer(),
              Text(
                app.accountRole == 'teacher' ? '教师账号' : '学生账号',
                style: context.texts.labelSmall?.copyWith(
                  color: context.n.n600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
