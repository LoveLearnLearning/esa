// 界面 3 —— 历史对话侧边栏(覆盖式抽屉)
// 头部 + 开启新对话 / 搜索 + 分组列表(置顶/今天/本周/更早)+ 底部用户条

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import 'conversation_move_dialog.dart';
import '../widgets/esa_buttons.dart';
import 'profile_sheet.dart';

class HistoryDrawer extends StatefulWidget {
  const HistoryDrawer({
    super.key,
    this.onNewConversation,
    this.onNewConversationInGroup,
    this.onOpenConversation,
  });

  final VoidCallback? onNewConversation;
  final ValueChanged<ChatGroup>? onNewConversationInGroup;
  final ValueChanged<ChatConversation>? onOpenConversation;

  @override
  State<HistoryDrawer> createState() => _HistoryDrawerState();
}

class _HistoryDrawerState extends State<HistoryDrawer> {
  final _search = TextEditingController();
  final _rename = TextEditingController();
  String _query = '';
  String? _renameId;

  @override
  void dispose() {
    _search.dispose();
    _rename.dispose();
    super.dispose();
  }

  void _startRename(ChatConversation c) {
    setState(() {
      _renameId = c.id;
      _rename.text = c.title;
    });
  }

  void _commitRename(AppState app) {
    if (_renameId != null) {
      app.renameConversation(_renameId!, _rename.text);
    }
    setState(() => _renameId = null);
  }

  Future<void> _startInGroup(AppState app) async {
    final group = await _pickGroup(context, app);
    if (group == null || !mounted) return;
    if (widget.onNewConversationInGroup != null) {
      widget.onNewConversationInGroup!(group);
    } else {
      await app.newConversationInGroup(group.id);
    }
    Navigator.of(context).pop();
  }

  Future<ChatGroup?> _pickGroup(BuildContext context, AppState app) async {
    final candidates = app.groups
        .where((group) => app.groupProjectId(group.id) == null)
        .toList();

    Widget option(ChatGroup group) => Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(EsaRadii.field),
        onTap: () => Navigator.of(context).pop(group),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
          child: Row(
            children: [
              Icon(LucideIcons.folder, size: 17, color: context.n.n600),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  group.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 13.5),
                ),
              ),
            ],
          ),
        ),
      ),
    );

    final empty = Padding(
      padding: const EdgeInsets.symmetric(vertical: 18),
      child: Text(
        '暂无分组，请先创建一个分组。',
        textAlign: TextAlign.center,
        style: TextStyle(fontSize: 12.5, color: context.n.n600),
      ),
    );

    Widget groupList() => ConstrainedBox(
      constraints: const BoxConstraints(maxHeight: 320),
      child: ListView.separated(
        shrinkWrap: true,
        itemCount: candidates.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (_, index) => option(candidates[index]),
      ),
    );

    if (MediaQuery.sizeOf(context).width < 600) {
      return showModalBottomSheet<ChatGroup>(
        context: context,
        showDragHandle: true,
        builder: (sheetContext) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('分组中新建对话', style: context.texts.titleMedium),
                const SizedBox(height: 12),
                if (candidates.isEmpty) empty else groupList(),
              ],
            ),
          ),
        ),
      );
    }

    return showDialog<ChatGroup>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('分组中新建对话'),
        content: SizedBox(
          width: 340,
          child: candidates.isEmpty ? empty : groupList(),
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

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final width = (MediaQuery.of(context).size.width * 0.88).clamp(
      0.0,
      EsaSpace.drawerWidth,
    );

    final filtered = app.conversations
        .where((c) => c.title.toLowerCase().contains(_query.toLowerCase()))
        .toList();

    return Drawer(
      width: width,
      elevation: 16,
      shape: RoundedRectangleBorder(
        borderRadius: const BorderRadius.horizontal(
          right: Radius.circular(EsaRadii.sheet),
        ),
        side: BorderSide(color: context.n.divider),
      ),
      clipBehavior: Clip.antiAlias,
      child: SafeArea(
        child: Column(
          children: [
            _header(context),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              child: Column(
                children: [
                  EsaRedButton(
                    label: '开启新对话',
                    leading: LucideIcons.plus,
                    height: 42,
                    radius: EsaRadii.button,
                    onPressed: () {
                      if (widget.onNewConversation != null) {
                        widget.onNewConversation!();
                      } else {
                        app.newConversation();
                      }
                      Navigator.of(context).pop();
                    },
                  ),
                  const SizedBox(height: 8),
                  OutlinedButton.icon(
                    key: const ValueKey('new-group-conversation'),
                    onPressed: () => _startInGroup(app),
                    icon: const Icon(LucideIcons.folderPlus, size: 16),
                    label: const Text('分组中新建对话'),
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(42),
                      padding: const EdgeInsets.symmetric(horizontal: 14),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(EsaRadii.button),
                      ),
                    ),
                  ),
                  const SizedBox(height: EsaSpace.md),
                  _searchBox(context),
                ],
              ),
            ),
            Expanded(
              child: filtered.isEmpty
                  ? _noResult(context)
                  : _groupedList(context, app, filtered),
            ),
            _userBar(context, app),
          ],
        ),
      ),
    );
  }

  Widget _header(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.n.divider)),
      ),
      child: Row(
        children: [
          Container(
            width: 26,
            height: 26,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: EsaColors.accent,
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Text(
              'E',
              style: TextStyle(
                color: EsaColors.onAccent,
                fontWeight: FontWeight.w800,
                fontSize: 15,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Text('星知智链', style: context.texts.titleMedium),
          const Spacer(),
          _MiniIconButton(
            icon: LucideIcons.x,
            onTap: () => Navigator.of(context).pop(),
          ),
        ],
      ),
    );
  }

  Widget _searchBox(BuildContext context) {
    return Container(
      height: 40,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: context.n.n100,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.field),
      ),
      child: Row(
        children: [
          Icon(LucideIcons.search, size: 16, color: context.n.n600),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: _search,
              onChanged: (v) => setState(() => _query = v),
              decoration: const InputDecoration(
                isCollapsed: true,
                filled: false,
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                hintText: '搜索历史对话',
              ),
              style: const TextStyle(fontSize: 13.5),
            ),
          ),
        ],
      ),
    );
  }

  Widget _groupedList(
    BuildContext context,
    AppState app,
    List<ChatConversation> items,
  ) {
    final now = DateTime.now();
    final pinned = <ChatConversation>[];
    final today = <ChatConversation>[];
    final week = <ChatConversation>[];
    final earlier = <ChatConversation>[];
    for (final c in items) {
      if (c.pinned) {
        pinned.add(c);
        continue;
      }
      final diff = now.difference(c.updatedAt);
      if (c.updatedAt.year == now.year &&
          c.updatedAt.month == now.month &&
          c.updatedAt.day == now.day) {
        today.add(c);
      } else if (diff.inDays < 7) {
        week.add(c);
      } else {
        earlier.add(c);
      }
    }
    int byTime(ChatConversation a, ChatConversation b) =>
        b.updatedAt.compareTo(a.updatedAt);
    pinned.sort(byTime);
    today.sort(byTime);
    week.sort(byTime);
    earlier.sort(byTime);

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      children: [
        _group(context, app, '置顶', 'PINNED', pinned, accent: true),
        _group(context, app, '今天', 'TODAY', today),
        _group(context, app, '本周', 'THIS WEEK', week),
        _group(context, app, '更早', 'EARLIER', earlier),
      ],
    );
  }

  Widget _group(
    BuildContext context,
    AppState app,
    String cn,
    String en,
    List<ChatConversation> items, {
    bool accent = false,
  }) {
    if (items.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          child: Row(
            children: [
              Text(
                cn,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 1.2,
                  color: accent ? EsaColors.accent : context.n.n700,
                ),
              ),
              const SizedBox(width: 8),
              Text(en, style: TextStyle(fontSize: 10, color: context.n.n500)),
              const SizedBox(width: 8),
              Expanded(child: Divider(color: context.n.divider, height: 1)),
            ],
          ),
        ),
        const SizedBox(height: 6),
        for (final c in items) _row(context, app, c),
      ],
    );
  }

  Widget _row(BuildContext context, AppState app, ChatConversation c) {
    final active = app.activeId == c.id;
    final editing = _renameId == c.id;
    String? groupName;
    if (c.groupId != null) {
      for (final group in app.groups) {
        if (group.id == c.groupId) {
          groupName = group.name;
          break;
        }
      }
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 2),
      decoration: BoxDecoration(
        color: active ? context.n.n200 : Colors.transparent,
        borderRadius: BorderRadius.circular(EsaRadii.field),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(EsaRadii.field),
          onTap: editing
              ? null
              : () {
                  if (widget.onOpenConversation != null) {
                    widget.onOpenConversation!(c);
                  } else {
                    app.setActive(c.id);
                  }
                  Navigator.of(context).pop();
                },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: editing
                      ? _renameField(context, app)
                      : Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              c.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 13.5),
                            ),
                            if (groupName != null)
                              Text(
                                groupName,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontSize: 10.5,
                                  color: context.n.n600,
                                ),
                              ),
                          ],
                        ),
                ),
                if (!editing) ...[
                  _MiniIconButton(
                    icon: LucideIcons.star,
                    size: 24,
                    tooltip: c.pinned ? '取消置顶' : '置顶',
                    color: c.pinned ? EsaColors.accent : context.n.n600,
                    fill: c.pinned,
                    onTap: () => app.togglePin(c.id),
                  ),
                  if (c.workspaceType != WorkspaceType.research ||
                      c.researchProjectId != null)
                    _MiniIconButton(
                      icon: LucideIcons.folderInput,
                      size: 24,
                      tooltip: '移动到分组',
                      onTap: () => _moveConversation(context, app, c),
                    ),
                  _MiniIconButton(
                    icon: LucideIcons.pencil,
                    size: 24,
                    tooltip: '重命名',
                    onTap: () => _startRename(c),
                  ),
                  _MiniIconButton(
                    icon: LucideIcons.trash2,
                    size: 24,
                    tooltip: '删除',
                    hoverRed: true,
                    onTap: () => app.deleteConversation(c.id),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _moveConversation(
    BuildContext context,
    AppState app,
    ChatConversation conversation,
  ) async {
    final target = await showMoveConversationDialog(
      context,
      app,
      conversation,
    );
    if (target == null || !context.mounted) return;
    try {
      await app.moveConversationToGroup(conversation.id, target.groupId);
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('移动失败：$error')),
      );
    }
  }

  Widget _renameField(BuildContext context, AppState app) {
    return Focus(
      onKeyEvent: (node, event) {
        if (event is KeyDownEvent &&
            event.logicalKey == LogicalKeyboardKey.escape) {
          setState(() => _renameId = null);
          return KeyEventResult.handled;
        }
        return KeyEventResult.ignored;
      },
      child: TextField(
        controller: _rename,
        autofocus: true,
        onSubmitted: (_) => _commitRename(app),
        onTapOutside: (_) => _commitRename(app),
        decoration: const InputDecoration(
          isCollapsed: true,
          contentPadding: EdgeInsets.symmetric(vertical: 6, horizontal: 8),
        ),
        style: const TextStyle(fontSize: 13.5),
      ),
    );
  }

  Widget _noResult(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          '没有匹配「$_query」的对话。',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: context.n.n600),
        ),
      ),
    );
  }

  Widget _userBar(BuildContext context, AppState app) {
    final initial = app.username.isEmpty ? 'U' : app.username.characters.first;
    return Container(
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: context.n.divider)),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: () => showProfileSheet(context),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: EsaColors.accent,
                    borderRadius: BorderRadius.circular(EsaRadii.button),
                  ),
                  child: Text(
                    initial.toUpperCase(),
                    style: const TextStyle(
                      color: EsaColors.onAccent,
                      fontSize: 15,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        app.username,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.texts.titleMedium?.copyWith(
                          fontSize: 13.5,
                        ),
                      ),
                      Text(
                        '${app.role} · 已登录',
                        style: TextStyle(fontSize: 11, color: context.n.n600),
                      ),
                    ],
                  ),
                ),
                Icon(LucideIcons.chevronRight, size: 18, color: context.n.n600),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _MiniIconButton extends StatelessWidget {
  const _MiniIconButton({
    required this.icon,
    required this.onTap,
    this.size = 30,
    this.tooltip,
    this.color,
    this.fill = false,
    this.hoverRed = false,
  });

  final IconData icon;
  final VoidCallback onTap;
  final double size;
  final String? tooltip;
  final Color? color;
  final bool fill;
  final bool hoverRed;

  @override
  Widget build(BuildContext context) {
    final button = InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(EsaRadii.iconButton),
      hoverColor: hoverRed
          ? EsaColors.accent.withValues(alpha: 0.12)
          : context.n.n200,
      child: SizedBox(
        width: size,
        height: size,
        child: Icon(
          icon,
          size: size * 0.56,
          color: fill ? EsaColors.accent : (color ?? context.n.n600),
        ),
      ),
    );
    return tooltip == null ? button : Tooltip(message: tooltip!, child: button);
  }
}
