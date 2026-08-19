import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_theme.dart';

class MoveConversationTarget {
  const MoveConversationTarget({this.groupId, required this.label});

  final String? groupId;
  final String label;
}

Future<MoveConversationTarget?> showMoveConversationDialog(
  BuildContext context,
  AppState app,
  ChatConversation conversation, {
  List<ChatGroup>? groups,
}) {
  final candidates =
      groups ??
      (conversation.researchProjectId != null
          ? app.groupsForProject(conversation.researchProjectId!)
          : app.groups
                .where((group) => app.groupProjectId(group.id) == null)
                .toList());
  return showDialog<MoveConversationTarget>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('移动到分组'),
      content: SizedBox(
        width: 340,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              conversation.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12.5),
            ),
            const SizedBox(height: 12),
            if (conversation.groupId != null) ...[
              _TargetRow(
                icon: LucideIcons.folderOpen,
                label: '未分组',
                selected: false,
                onTap: () => Navigator.pop(
                  dialogContext,
                  const MoveConversationTarget(groupId: null, label: '未分组'),
                ),
              ),
              const Divider(height: 14),
            ],
            if (candidates.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 14),
                child: Text(
                  '暂无分组，先创建一个分组再移动。',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 12.5,
                    color: Theme.of(dialogContext).colorScheme.onSurfaceVariant,
                  ),
                ),
              )
            else
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 320),
                child: ListView(
                  shrinkWrap: true,
                  children: [
                    for (final group in candidates)
                      _TargetRow(
                        icon: LucideIcons.folder,
                        label: group.name,
                        selected: conversation.groupId == group.id,
                        onTap: () => Navigator.pop(
                          dialogContext,
                          MoveConversationTarget(
                            groupId: group.id,
                            label: group.name,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('取消'),
        ),
      ],
    ),
  );
}

class _TargetRow extends StatelessWidget {
  const _TargetRow({
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
  Widget build(BuildContext context) => Material(
    color: selected
        ? EsaColors.accent.withValues(alpha: 0.12)
        : Colors.transparent,
    borderRadius: BorderRadius.circular(8),
    child: InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
        child: Row(
          children: [
            Icon(icon, size: 16, color: selected ? EsaColors.accent : null),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 13.5,
                  color: selected ? EsaColors.accent : null,
                  fontWeight: selected ? FontWeight.w600 : null,
                ),
              ),
            ),
            if (selected)
              const Icon(LucideIcons.check, size: 15, color: EsaColors.accent),
          ],
        ),
      ),
    ),
  );
}
