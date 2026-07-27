// 界面 2 —— 对话主界面
// 顶栏 + 消息区(用户气泡 / 助手平铺 / 工具块 / 空状态)+ 输入区
// 侧边栏用 Scaffold.drawer 资料弹层用 showProfileSheet

import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/assistant_message.dart';
import '../widgets/composer.dart';
import '../widgets/history_drawer.dart';
import '../widgets/message_bubble.dart';
import '../widgets/tool_call_card.dart';

class ChatPage extends StatefulWidget {
  const ChatPage({super.key});

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  final _scrollController = ScrollController();

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    _scrollToBottom();
    final narrow = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      key: _scaffoldKey,
      drawerEdgeDragWidth: 24,
      drawer: const HistoryDrawer(),
      body: SafeArea(
        child: Column(
          children: [
            _TopBar(
              narrow: narrow,
              title: app.activeConversation?.title ?? 'ESA',
              onMenu: () => _scaffoldKey.currentState?.openDrawer(),
              onNewChat: app.newConversation,
            ),
            Expanded(
              child: app.loadingMessages && app.messages.isEmpty
                  ? const Center(child: CircularProgressIndicator())
                  : app.messages.isEmpty
                      ? _EmptyState(name: app.username, onPick: app.send)
                      : _messageList(context, app),
            ),
            Composer(busy: app.busy, onSend: app.send),
          ],
        ),
      ),
    );
  }

  Widget _messageList(BuildContext context, AppState app) {
    // 关闭工具详情时过滤掉 tool 消息 避免残留分隔间距
    final messages = app.toolsOn
        ? app.messages
        : app.messages.where((m) => !m.isTool).toList();
    return ListView.separated(
      controller: _scrollController,
      padding: const EdgeInsets.fromLTRB(20, 34, 20, 24),
      itemCount: messages.length,
      separatorBuilder: (_, _) => const SizedBox(height: EsaSpace.messageGap),
      itemBuilder: (context, index) {
        final m = messages[index];
        final Widget child;
        switch (m.role) {
          case MessageRole.user:
            child = UserBubble(text: m.text);
          case MessageRole.tool:
            child = Align(
              alignment: Alignment.centerLeft,
              child: ToolCallCard(name: m.name ?? 'tool', output: m.text),
            );
          case MessageRole.assistant:
            child = AssistantMessage(
              message: m,
              onRegenerate: () => app.regenerate(m.id),
            );
        }
        return Center(
          child: ConstrainedBox(
            constraints:
                const BoxConstraints(maxWidth: EsaSpace.contentMaxWidth),
            child: SizedBox(width: double.infinity, child: child),
          ),
        );
      },
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.narrow,
    required this.title,
    required this.onMenu,
    required this.onNewChat,
  });

  final bool narrow;
  final String title;
  final VoidCallback onMenu;
  final VoidCallback onNewChat;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: EsaSpace.headerHeight,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.n.divider)),
      ),
      child: Row(
        children: [
          _OutlineIconButton(icon: LucideIcons.menu, onTap: onMenu),
          const SizedBox(width: 10),
          _newChatButton(context),
          const SizedBox(width: 10),
          Container(width: 1, height: 24, color: context.n.divider),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.texts.titleMedium,
                ),
                Text(
                  'ESA · STUDY AGENT',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 1.2,
                    color: context.n.n600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _newChatButton(BuildContext context) {
    return InkWell(
      onTap: onNewChat,
      borderRadius: BorderRadius.circular(EsaRadii.button),
      child: Container(
        height: 38,
        padding: EdgeInsets.symmetric(horizontal: narrow ? 10 : 12),
        decoration: BoxDecoration(
          border: Border.all(color: context.n.divider),
          borderRadius: BorderRadius.circular(EsaRadii.button),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(LucideIcons.plus, size: 16, color: context.scheme.onSurface),
            if (!narrow) ...[
              const SizedBox(width: 8),
              Text('新对话', style: context.texts.titleMedium?.copyWith(fontSize: 13)),
            ],
          ],
        ),
      ),
    );
  }
}

class _OutlineIconButton extends StatelessWidget {
  const _OutlineIconButton({required this.icon, required this.onTap});
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(EsaRadii.button),
      child: Container(
        width: 38,
        height: 38,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          border: Border.all(color: context.n.divider),
          borderRadius: BorderRadius.circular(EsaRadii.button),
        ),
        child: Icon(icon, size: 18, color: context.scheme.onSurface),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.name, required this.onPick});
  final String name;
  final ValueChanged<String> onPick;

  static const _cards = [
    ('01', '讲解一道题', '把题目发给我，一步步带你理清思路'),
    ('02', '生成复习计划', '按考试时间为你排出每日任务'),
    ('03', '检索我的课件', '从上传的资料里找到相关知识点'),
    ('04', '批改作业', '指出错误并给出规范范例'),
  ];

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 34, 20, 24),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: EsaSpace.contentMaxWidth),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('WELCOME',
                  style:
                      context.texts.labelSmall?.copyWith(color: EsaColors.accent)),
              const SizedBox(height: EsaSpace.md),
              Text('你好，$name。', style: context.texts.headlineMedium),
              const SizedBox(height: EsaSpace.md),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: Text(
                  '我是你的学习智能体。可以讲题、排复习计划、检索课件或批改作业。选一个开始，或直接在下面提问。',
                  style: context.texts.bodyLarge,
                ),
              ),
              const SizedBox(height: EsaSpace.xl),
              for (final card in _cards) ...[
                _SuggestionCard(
                  index: card.$1,
                  title: card.$2,
                  desc: card.$3,
                  onTap: () => onPick(card.$2),
                ),
                const SizedBox(height: EsaSpace.sm),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _SuggestionCard extends StatelessWidget {
  const _SuggestionCard({
    required this.index,
    required this.title,
    required this.desc,
    required this.onTap,
  });

  final String index;
  final String title;
  final String desc;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(EsaRadii.card),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 15),
        decoration: BoxDecoration(
          border: Border.all(color: context.n.divider),
          borderRadius: BorderRadius.circular(EsaRadii.card),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 34,
              child: Text(
                index,
                style: const TextStyle(
                  color: EsaColors.accent,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 1.0,
                ),
              ),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style:
                          context.texts.titleMedium?.copyWith(fontSize: 15)),
                  const SizedBox(height: 2),
                  Text(desc,
                      style: TextStyle(fontSize: 12.5, color: context.n.n600)),
                ],
              ),
            ),
            Opacity(
              opacity: 0.5,
              child: Icon(LucideIcons.chevronRight,
                  size: 18, color: context.n.n600),
            ),
          ],
        ),
      ),
    );
  }
}
