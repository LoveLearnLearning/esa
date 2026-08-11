// 界面 3 —— 历史对话侧边栏(覆盖式抽屉)
// 头部 + 开启新对话 / 搜索 + 分组列表(置顶/今天/本周/更早)+ 底部用户条

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/esa_buttons.dart';
import 'profile_sheet.dart';

class HistoryDrawer extends StatefulWidget {
  const HistoryDrawer({super.key});

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
                      app.newConversation();
                      Navigator.of(context).pop();
                    },
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
                  app.setActive(c.id);
                  Navigator.of(context).pop();
                },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            child: Row(
              children: [
                Expanded(
                  child: editing
                      ? _renameField(context, app)
                      : Text(
                          c.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: 13.5),
                        ),
                ),
                if (!editing) ...[
                  _MiniIconButton(
                    icon: LucideIcons.star,
                    size: 24,
                    color: c.pinned ? EsaColors.accent : context.n.n600,
                    fill: c.pinned,
                    onTap: () => app.togglePin(c.id),
                  ),
                  _MiniIconButton(
                    icon: LucideIcons.pencil,
                    size: 24,
                    onTap: () => _startRename(c),
                  ),
                  _MiniIconButton(
                    icon: LucideIcons.trash2,
                    size: 24,
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
    this.color,
    this.fill = false,
    this.hoverRed = false,
  });

  final IconData icon;
  final VoidCallback onTap;
  final double size;
  final Color? color;
  final bool fill;
  final bool hoverRed;

  @override
  Widget build(BuildContext context) {
    return InkWell(
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
  }
}
