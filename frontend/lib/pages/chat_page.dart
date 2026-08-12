// 界面 2 —— 对话主界面
// 顶栏 + 消息区(用户气泡 / 助手平铺 / 工具块 / 空状态)+ 输入区
// 侧边栏用 Scaffold.drawer 资料弹层用 showProfileSheet

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../models/task_mode.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/assistant_message.dart';
import '../widgets/composer.dart';
import '../widgets/history_drawer.dart';
import '../widgets/learning_dashboard.dart';
import '../widgets/memory_sheet.dart';
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
  final _streamRenderingPaused = ValueNotifier(false);
  bool _followOutput = true;
  bool _userScrollInProgress = false;
  bool _messagePointerDown = false;
  int _bottomScrollRequest = 0;
  String? _lastActiveId;
  TaskMode? _taskMode;

  @override
  void dispose() {
    _streamRenderingPaused.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _setFollowOutput(bool value) {
    // 真机拖动会连续产生很小的 ScrollUpdate。即使当前位置仍在底部阈值内，
    // 只要手指没有松开，就绝不能重新开启追底。
    if (value && _messagePointerDown) return;
    _followOutput = value;
    final paused = !value;
    if (_streamRenderingPaused.value != paused) {
      _streamRenderingPaused.value = paused;
    }
  }

  void _scrollToBottom() {
    if (!_followOutput) return;

    final request = ++_bottomScrollRequest;
    _scheduleBottomPass(request, 0);
  }

  void _scheduleBottomPass(int request, int pass) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          !_followOutput ||
          request != _bottomScrollRequest ||
          !_scrollController.hasClients) {
        return;
      }

      final position = _scrollController.position;
      final target = position.maxScrollExtent;
      if ((position.pixels - target).abs() > 0.5) position.jumpTo(target);

      // ListView 会在滚动后继续布局之前尚未创建的消息。跨数帧再次校准，
      // 避免只跳到懒加载列表的“旧底部”。
      if (pass < 6) {
        WidgetsBinding.instance.scheduleFrame();
        _scheduleBottomPass(request, pass + 1);
      }
    });
  }

  void _resumeFollowing() {
    _userScrollInProgress = false;
    _setFollowOutput(true);
    _scrollToBottom();
  }

  void _pauseFollowing() {
    _setFollowOutput(false);
    _bottomScrollRequest++;
  }

  void _handleMessagePointerDown(PointerDownEvent event) {
    // 在移动端，等到 ScrollStartNotification 才暂停已经太晚：流式回复可能
    // 已在手指产生位移前再次 jumpTo 底部。按下正文时立刻冻结追底和流式重绘。
    // 只有触摸/手写笔按下才收键盘：鼠标按下往往是要选中复制文本，
    // 收焦点会打断桌面端正在输入的用户。
    if (event.kind == PointerDeviceKind.touch ||
        event.kind == PointerDeviceKind.stylus) {
      FocusManager.instance.primaryFocus?.unfocus();
    }
    _messagePointerDown = true;
    _userScrollInProgress = true;
    _pauseFollowing();
  }

  void _finishMessagePointerInteraction(PointerEvent event) {
    _messagePointerDown = false;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scrollController.hasClients) return;
      final atBottom = _scrollController.position.extentAfter <= 24;
      _userScrollInProgress = false;
      _setFollowOutput(atBottom);
      if (atBottom) _scrollToBottom();
    });
  }

  bool _handleScrollNotification(ScrollNotification notification) {
    if (notification is UserScrollNotification) {
      if (notification.direction == ScrollDirection.idle) {
        if (_userScrollInProgress) {
          _setFollowOutput(notification.metrics.extentAfter <= 24);
          _userScrollInProgress = false;
        }
      } else {
        _userScrollInProgress = true;
        _pauseFollowing();
      }
    }

    if (notification is ScrollStartNotification &&
        notification.dragDetails != null) {
      _userScrollInProgress = true;
      _pauseFollowing();
    }

    if (notification is ScrollEndNotification && _userScrollInProgress) {
      _setFollowOutput(notification.metrics.extentAfter <= 24);
      _userScrollInProgress = false;
    }

    return false;
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (_lastActiveId != app.activeId) {
      _lastActiveId = app.activeId;
      _userScrollInProgress = false;
      _setFollowOutput(true);
    }
    _scrollToBottom();
    final narrow = MediaQuery.of(context).size.width < 600;

    return Scaffold(
      key: _scaffoldKey,
      resizeToAvoidBottomInset: false,
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
              onLearning: () => showLearningDashboard(context),
              onMemory: () => showMemorySheet(context),
            ),
            Expanded(
              // 触摸消息区/空状态的任意位置都收起键盘（覆盖空状态分支，
              // 消息列表内部的 Listener 有更细的追底处理）
              child: Listener(
                behavior: HitTestBehavior.translucent,
                onPointerDown: (event) {
                  if (event.kind == PointerDeviceKind.touch ||
                      event.kind == PointerDeviceKind.stylus) {
                    FocusManager.instance.primaryFocus?.unfocus();
                  }
                },
                child: app.loadingMessages && app.messages.isEmpty
                    ? const Center(child: CircularProgressIndicator())
                    : app.messages.isEmpty
                    ? _EmptyState(
                        name: app.username,
                        selected: _taskMode,
                        onPick: (mode) => setState(() => _taskMode = mode),
                      )
                    : _messageList(context, app),
              ),
            ),
            Composer(
              busy: app.busy,
              conversationId: app.activeId,
              taskMode: _taskMode,
              onClearTaskMode: () => setState(() => _taskMode = null),
              onUploadAttachment: (filename, bytes) =>
                  app.uploadConversationAttachment(
                    filename: filename,
                    bytes: bytes,
                  ),
              onRemoveAttachment: app.removeConversationAttachment,
              onSend: (text, markdown) {
                _resumeFollowing();
                app.send(
                  _taskMode?.buildPrompt(text) ?? text,
                  markdown: markdown,
                  displayText: text,
                );
              },
              onSendWithAttachment: (text, markdown, attachment) {
                _resumeFollowing();
                app.send(
                  _taskMode?.buildPrompt(text) ?? text,
                  markdown: markdown,
                  displayText: '$text\n\n📎 ${attachment.filename}',
                  attachmentIds: [attachment.id],
                );
              },
            ),
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
    return Listener(
      behavior: HitTestBehavior.translucent,
      onPointerDown: _handleMessagePointerDown,
      onPointerUp: _finishMessagePointerInteraction,
      onPointerCancel: _finishMessagePointerInteraction,
      onPointerSignal: (event) {
        if (event is PointerScrollEvent) {
          // 滚轮只暂停追底，不收键盘：滚轮说明在用鼠标，
          // 用户很可能一边打字一边翻历史消息
          _userScrollInProgress = true;
          _pauseFollowing();
        }
      },
      child: NotificationListener<ScrollNotification>(
        onNotification: _handleScrollNotification,
        child: ListView.separated(
          key: const ValueKey('chat-message-list'),
          controller: _scrollController,
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          padding: const EdgeInsets.fromLTRB(20, 34, 20, 24),
          itemCount: messages.length,
          separatorBuilder: (_, _) =>
              const SizedBox(height: EsaSpace.messageGap),
          itemBuilder: (context, index) {
            final m = messages[index];
            final Widget child;
            switch (m.role) {
              case MessageRole.user:
                child = UserBubble(text: m.text, markdown: m.markdown);
              case MessageRole.tool:
                child = Align(
                  alignment: Alignment.centerLeft,
                  child: ToolCallCard(name: m.name ?? 'tool', output: m.text),
                );
              case MessageRole.assistant:
                child = AssistantMessage(
                  message: m,
                  renderPaused: _streamRenderingPaused,
                  onContentChanged: _scrollToBottom,
                  onRegenerate: () {
                    _resumeFollowing();
                    app.regenerate(m.id);
                  },
                );
            }
            return Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(
                  maxWidth: EsaSpace.contentMaxWidth,
                ),
                child: SizedBox(width: double.infinity, child: child),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.narrow,
    required this.title,
    required this.onMenu,
    required this.onNewChat,
    required this.onLearning,
    required this.onMemory,
  });

  final bool narrow;
  final String title;
  final VoidCallback onMenu;
  final VoidCallback onNewChat;
  final VoidCallback onLearning;
  final VoidCallback onMemory;

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
          _OutlineIconButton(icon: LucideIcons.barChart3, onTap: onLearning),
          const SizedBox(width: 8),
          _OutlineIconButton(icon: LucideIcons.brain, onTap: onMemory),
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
              Text(
                '新对话',
                style: context.texts.titleMedium?.copyWith(fontSize: 13),
              ),
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
  const _EmptyState({
    required this.name,
    required this.selected,
    required this.onPick,
  });
  final String name;
  final TaskMode? selected;
  final ValueChanged<TaskMode> onPick;

  static const _cards = [
    ('01', TaskMode.explainProblem),
    ('02', TaskMode.studyPlan),
    ('03', TaskMode.searchMaterials),
    ('04', TaskMode.reviewHomework),
    ('05', TaskMode.concept),
    ('06', TaskMode.masteryReport),
    ('07', TaskMode.practiceRecommendation),
    ('08', TaskMode.academicSearch),
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
              Text(
                'WELCOME',
                style: context.texts.labelSmall?.copyWith(
                  color: EsaColors.accent,
                ),
              ),
              const SizedBox(height: EsaSpace.md),
              Text('你好，$name。', style: context.texts.headlineMedium),
              const SizedBox(height: EsaSpace.md),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: Text(
                  '我是你的学习智能体。选择一个任务模式，再在下方补充内容并发送。',
                  style: context.texts.bodyLarge,
                ),
              ),
              const SizedBox(height: EsaSpace.xl),
              for (final card in _cards) ...[
                _SuggestionCard(
                  index: card.$1,
                  title: card.$2.title,
                  desc: card.$2.description,
                  selected: selected == card.$2,
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
    required this.selected,
    required this.onTap,
  });

  final String index;
  final String title;
  final String desc;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(EsaRadii.card),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 15),
        decoration: BoxDecoration(
          color: selected ? EsaColors.accent.withValues(alpha: 0.08) : null,
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
                  Text(
                    title,
                    style: context.texts.titleMedium?.copyWith(fontSize: 15),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    desc,
                    style: TextStyle(fontSize: 12.5, color: context.n.n600),
                  ),
                ],
              ),
            ),
            Icon(
              selected ? LucideIcons.check : LucideIcons.chevronRight,
              size: 18,
              color: selected ? EsaColors.accent : context.n.n600,
            ),
          ],
        ),
      ),
    );
  }
}
