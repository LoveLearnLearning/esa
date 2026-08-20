// 界面 2 —— 对话主界面
// 顶栏 + 消息区(用户气泡 / 助手平铺 / 工具块 / 空状态)+ 输入区
// 侧边栏用 Scaffold.drawer 资料弹层用 showProfileSheet

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../models/task_mode.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/assistant_message.dart';
import '../widgets/agent_action_sheet.dart';
import '../widgets/attachment_preview/attachment_preview.dart';
import '../widgets/composer.dart';
import '../widgets/code_editor/code_editor_pane.dart';
import '../widgets/history_drawer.dart';
import '../widgets/learning_dashboard.dart';
import '../widgets/memory_sheet.dart';
import '../widgets/message_bubble.dart';
import '../widgets/tool_call_card.dart';

enum _CodeSource { composer, user, assistant }

class _CodeSession {
  const _CodeSession({
    required this.id,
    required this.value,
    required this.originalValue,
    required this.language,
    required this.source,
  });

  final String id;
  final String value;
  final String originalValue;
  final String language;
  final _CodeSource source;

  _CodeSession copyWith({
    String? value,
    String? language,
    _CodeSource? source,
  }) => _CodeSession(
    id: id,
    value: value ?? this.value,
    originalValue: originalValue,
    language: language ?? this.language,
    source: source ?? this.source,
  );
}

class _AttachmentSession {
  const _AttachmentSession({
    required this.conversationId,
    required this.attachment,
    this.content,
    this.error,
    this.loading = false,
  });

  final String conversationId;
  final DocumentAttachment attachment;
  final AttachmentContent? content;
  final String? error;
  final bool loading;

  _AttachmentSession copyWith({
    AttachmentContent? content,
    String? error,
    bool? loading,
  }) => _AttachmentSession(
    conversationId: conversationId,
    attachment: attachment,
    content: content ?? this.content,
    error: error,
    loading: loading ?? this.loading,
  );
}

class ChatPage extends StatefulWidget {
  const ChatPage({
    super.key,
    this.embedded = false,
    this.embeddedTitle,
    this.onExitEmbedded,
    this.homeMode = false,
    this.composerKey,
    this.onSelectedAttachmentsChanged,
    this.onContinueLearning,
    this.onViewAssignments,
    this.onOpenConversation,
    this.onStartChat,
  });

  /// The home shell owns global navigation and page chrome in embedded mode.
  final bool embedded;
  final String? embeddedTitle;
  final VoidCallback? onExitEmbedded;
  final bool homeMode;
  final GlobalKey<ComposerState>? composerKey;
  final ValueChanged<List<DocumentAttachment>>? onSelectedAttachmentsChanged;
  final VoidCallback? onContinueLearning;
  final VoidCallback? onViewAssignments;
  final ValueChanged<String>? onOpenConversation;

  /// 首页（学习仪表盘）模式下用户开始发送消息时，通知外壳切回对话视图。
  final VoidCallback? onStartChat;

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  final _scrollController = ScrollController();
  final _streamRenderingPaused = ValueNotifier(false);
  final _internalComposerKey = GlobalKey<ComposerState>();
  final _codeDrafts = <String, _CodeSession>{};
  int _codeDraftVersion = 0;
  bool _followOutput = true;
  bool _userScrollInProgress = false;
  bool _messagePointerDown = false;
  int _bottomScrollRequest = 0;
  int _scrollRestoreRequest = 0;
  String? _lastActiveId;
  WorkspaceType? _lastWorkspace;
  TaskMode? _taskMode;
  _CodeSession? _codeSession;
  _AttachmentSession? _attachmentSession;
  int _attachmentLoadRequest = 0;
  double _editorWidth = 0.46;
  bool _pendingSend = false;
  bool _chatTransitionScheduled = false;

  GlobalKey<ComposerState> get _composerKey =>
      widget.composerKey ?? _internalComposerKey;

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

  void _setStatePreservingChatScroll(
    VoidCallback mutation, {
    bool pauseFollowing = false,
  }) {
    final offset = _scrollController.hasClients
        ? _scrollController.position.pixels
        : null;
    if (pauseFollowing) _pauseFollowing();
    final request = ++_scrollRestoreRequest;
    setState(mutation);
    if (offset != null) _scheduleScrollRestore(request, offset, 0);
  }

  void _scheduleScrollRestore(int request, double offset, int pass) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || request != _scrollRestoreRequest) return;
      if (_scrollController.hasClients) {
        final position = _scrollController.position;
        final target = offset.clamp(
          position.minScrollExtent,
          position.maxScrollExtent,
        );
        if ((position.pixels - target).abs() > .5) position.jumpTo(target);
      }
      if (pass < 4) {
        WidgetsBinding.instance.scheduleFrame();
        _scheduleScrollRestore(request, offset, pass + 1);
      }
    });
  }

  void _openCodeEditor(
    String blockId,
    String code,
    String language, {
    required _CodeSource source,
  }) {
    final normalizedCode = code.trimRight();
    final normalizedLanguage = normalizeCodeLanguage(language);
    final existing = _codeDrafts[blockId];
    _setStatePreservingChatScroll(() {
      _attachmentSession = null;
      _codeSession = existing != null && existing.value == normalizedCode
          ? existing.copyWith(source: source, language: normalizedLanguage)
          : _CodeSession(
              id: blockId,
              value: normalizedCode,
              originalValue: normalizedCode,
              language: normalizedLanguage,
              source: source,
            );
    }, pauseFollowing: true);
  }

  void _closeCodeEditor() =>
      _setStatePreservingChatScroll(() => _codeSession = null);

  void _openAttachment(DocumentAttachment attachment) {
    final conversationId = AppScope.of(context).activeId;
    if (conversationId == null) return;
    _loadAttachment(conversationId, attachment);
  }

  Future<void> _loadAttachment(
    String conversationId,
    DocumentAttachment attachment,
  ) async {
    final request = ++_attachmentLoadRequest;
    _setStatePreservingChatScroll(() {
      _codeSession = null;
      _attachmentSession = _AttachmentSession(
        conversationId: conversationId,
        attachment: attachment,
        loading: true,
      );
    }, pauseFollowing: true);
    try {
      final content = await AppScope.of(
        context,
      ).api.fetchConversationAttachment(conversationId, attachment);
      if (!mounted || request != _attachmentLoadRequest) return;
      setState(() {
        _attachmentSession = _attachmentSession?.copyWith(
          content: content,
          loading: false,
        );
      });
    } on ApiException catch (error) {
      if (!mounted || request != _attachmentLoadRequest) return;
      setState(() {
        _attachmentSession = _attachmentSession?.copyWith(
          error: error.detail,
          loading: false,
        );
      });
    } catch (_) {
      if (!mounted || request != _attachmentLoadRequest) return;
      setState(() {
        _attachmentSession = _attachmentSession?.copyWith(
          error: '附件预览加载失败，请检查网络后重试。',
          loading: false,
        );
      });
    }
  }

  void _closeAttachment() {
    _attachmentLoadRequest++;
    _setStatePreservingChatScroll(() => _attachmentSession = null);
  }

  void _retryAttachment() {
    final session = _attachmentSession;
    if (session == null) return;
    _loadAttachment(session.conversationId, session.attachment);
  }

  void _updateCodeSession(_CodeSession session) {
    _codeDrafts[session.id] = session;
    if (session.id.startsWith('composer:')) {
      _composerKey.currentState?.replaceCodeBlock(
        session.id,
        session.value,
        language: session.language,
      );
    }
    setState(() {
      _codeSession = session;
      _codeDraftVersion++;
    });
  }

  void _syncComposerCodeBlock(String blockId, String code, String language) {
    final session = _codeSession;
    if (session == null ||
        session.source != _CodeSource.composer ||
        session.id != blockId) {
      return;
    }
    final next = session.copyWith(
      value: code.trimRight(),
      language: normalizeCodeLanguage(language),
    );
    if (next.value == session.value && next.language == session.language) {
      return;
    }
    _codeDrafts[blockId] = next;
    setState(() {
      _codeSession = next;
      _codeDraftVersion++;
    });
  }

  void _sendEditedAgentCode(AppState app) {
    final session = _codeSession;
    if (session == null ||
        session.source != _CodeSource.assistant ||
        session.value == session.originalValue) {
      return;
    }
    final language = normalizeCodeLanguage(session.language);
    final message = '```$language\n${session.value.trimRight()}\n```';
    setState(() => _codeSession = null);
    _resumeFollowing();
    app.send(message, markdown: true, displayText: message);
  }

  void _clearComposerCodeDrafts() {
    setState(() {
      _codeDrafts.removeWhere((id, _) => id.startsWith('composer:'));
      if (_codeSession?.id.startsWith('composer:') ?? false) {
        _codeSession = null;
      }
      _codeDraftVersion++;
    });
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
    if (_lastWorkspace != app.activeWorkspace) {
      _lastWorkspace = app.activeWorkspace;
      _taskMode = null;
      _codeSession = null;
      _attachmentSession = null;
    }
    if (_lastActiveId != app.activeId) {
      _lastActiveId = app.activeId;
      _userScrollInProgress = false;
      _codeSession = null;
      _attachmentSession = null;
      _attachmentLoadRequest++;
      _chatTransitionScheduled = false;
      if (app.activeId == null) _pendingSend = false;
      _setFollowOutput(true);
    }
    _scrollToBottom();
    final pageWidth = MediaQuery.sizeOf(context).width;
    final narrow = pageWidth < (widget.embedded ? 1040 : 600);

    final embeddedHeader =
        widget.embedded &&
        (app.messages.isNotEmpty || widget.onExitEmbedded != null) &&
        !narrow;
    final conversation = app.activeConversation;
    final bindingLabel = switch (conversation?.workspaceType) {
      WorkspaceType.research =>
        app.researchProjects
            .where((item) => item.id == conversation?.researchProjectId)
            .map((item) => '项目 · ${item.name}')
            .firstOrNull,
      WorkspaceType.teaching =>
        conversation?.assignmentTitle != null
            ? '课堂 · ${conversation?.className ?? conversation?.classId} / ${conversation?.assignmentTitle}'
            : conversation?.classId != null
            ? '课堂 · ${conversation?.className ?? conversation?.classId}'
            : null,
      _ => null,
    };
    final composer = Composer(
      key: _composerKey,
      busy: app.busy,
      conversationId: app.activeId,
      taskMode: _taskMode,
      onClearTaskMode: () => setState(() => _taskMode = null),
      onOpenCodeEditor: (blockId, code, language) => _openCodeEditor(
        blockId,
        code,
        language,
        source: _CodeSource.composer,
      ),
      onCodeBlockChanged: _syncComposerCodeBlock,
      onSelectedAttachmentsChanged: widget.onSelectedAttachmentsChanged,
      courseNames: <String>{
        ...app.learningCourses.map((item) => item.name),
        ...app.scheduleCourseNames,
      }.toList(),
      toolsOn: app.toolsOn,
      onToolsOnChanged: app.setToolsOn,
      onUploadAttachment: (filename, stream, length) =>
          app.uploadConversationAttachment(
            filename: filename,
            stream: stream,
            length: length,
          ),
      onRemoveAttachment: app.removeConversationAttachment,
      onSend: (text, markdown) {
        _resumeFollowing();
        _clearComposerCodeDrafts();
        setState(() => _pendingSend = true);
        app.send(
          _taskMode?.buildPrompt(text) ?? text,
          markdown: markdown,
          displayText: text,
        );
      },
      onSendWithAttachment: (text, markdown, attachment) {
        _resumeFollowing();
        _clearComposerCodeDrafts();
        setState(() => _pendingSend = true);
        app.send(
          _taskMode?.buildPrompt(text) ?? text,
          markdown: markdown,
          displayText: text,
          attachmentIds: [attachment.id],
          attachments: [attachment],
        );
      },
    );
    final mobileLanding = narrow && app.messages.isEmpty;
    // 首页（学习仪表盘）模式下用户从仪表盘发起发送后，一旦对话建立就自动切回对话视图。
    final shouldStartChat = widget.homeMode &&
        widget.onStartChat != null &&
        app.activeWorkspace == WorkspaceType.learning &&
        _pendingSend &&
        app.activeId != null &&
        app.messages.isNotEmpty;
    if (shouldStartChat && !_chatTransitionScheduled) {
      _chatTransitionScheduled = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        widget.onStartChat?.call();
        _chatTransitionScheduled = false;
      });
    }
    final messageArea = Listener(
      behavior: HitTestBehavior.translucent,
      onPointerDown: (event) {
        if (event.kind == PointerDeviceKind.touch ||
            event.kind == PointerDeviceKind.stylus) {
          FocusManager.instance.primaryFocus?.unfocus();
        }
      },
      child: widget.homeMode &&
              app.activeWorkspace == WorkspaceType.learning &&
              (app.activeId == null || !_pendingSend)
          ? _LearningHome(
              mobileComposer: mobileLanding ? composer : null,
              onContinue: widget.onContinueLearning,
              onViewAssignments: widget.onViewAssignments,
              onOpenConversation: widget.onOpenConversation,
            )
          : app.loadingMessages && app.messages.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : app.messages.isEmpty
          ? _EmptyState(
              name: app.username,
              workspace: app.activeWorkspace,
              selected: _taskMode,
              onPick: (mode) => setState(() => _taskMode = mode),
              mobileComposer: mobileLanding ? composer : null,
            )
          : _messageList(context, app),
    );
    final panelCompact = pageWidth < 900;
    final hasPanel = _codeSession != null || _attachmentSession != null;
    Widget panel({required bool compact}) {
      final code = _codeSession;
      if (code != null) {
        return CodeEditorPane(
          value: code.value,
          originalValue: code.originalValue,
          language: code.language,
          indentSize: app.codeEditorIndentSize,
          editorTheme: app.codeEditorTheme,
          sessionToken: app.api.sessionId ?? '',
          compact: compact,
          onChanged: (value) =>
              _updateCodeSession((_codeSession ?? code).copyWith(value: value)),
          onLanguageChanged: (language) => _updateCodeSession(
            (_codeSession ?? code).copyWith(language: language),
          ),
          onSendToAgent: code.source == _CodeSource.assistant
              ? () => _sendEditedAgentCode(app)
              : null,
          onClose: _closeCodeEditor,
        );
      }
      final attachment = _attachmentSession!;
      return AttachmentPreviewPane(
        attachment: attachment.attachment,
        content: attachment.content,
        loading: attachment.loading,
        error: attachment.error,
        compact: compact,
        onClose: _closeAttachment,
        onRetry: _retryAttachment,
      );
    }

    final pageBody = !hasPanel
        ? Expanded(child: messageArea)
        : panelCompact
        ? Expanded(child: panel(compact: true))
        : Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final maxEditor = constraints.maxWidth * .68;
                final minEditor = 360.0;
                final editorWidth = (constraints.maxWidth * _editorWidth).clamp(
                  minEditor,
                  maxEditor,
                );
                return Row(
                  children: [
                    Expanded(
                      child: Column(
                        children: [
                          Expanded(child: messageArea),
                          if (!mobileLanding) composer,
                        ],
                      ),
                    ),
                    MouseRegion(
                      cursor: SystemMouseCursors.resizeColumn,
                      child: GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onHorizontalDragUpdate: (details) {
                          final next =
                              (editorWidth - details.delta.dx) /
                              constraints.maxWidth;
                          _setStatePreservingChatScroll(
                            () => _editorWidth = next.clamp(.32, .68),
                          );
                        },
                        child: SizedBox(
                          width: 9,
                          child: Center(
                            child: Container(
                              width: 1,
                              color: context.n.divider,
                            ),
                          ),
                        ),
                      ),
                    ),
                    SizedBox(width: editorWidth, child: panel(compact: false)),
                  ],
                );
              },
            ),
          );
    final content = Column(
      children: [
        if (!widget.embedded)
          _TopBar(
            narrow: narrow,
            title: app.activeConversation?.title ?? 'ESA',
            onMenu: () => _scaffoldKey.currentState?.openDrawer(),
            onNewChat: app.newConversation,
            workspace: app.activeWorkspace,
            onLearning: app.activeWorkspace == WorkspaceType.learning
                ? () => showLearningDashboard(context)
                : null,
            onMemory: app.activeWorkspace == WorkspaceType.learning
                ? () => showMemorySheet(context)
                : () => showMemorySheet(context),
            onActions: () => showAgentActionSheet(context),
            bindingLabel: bindingLabel,
          ),
        if (embeddedHeader)
          _EmbeddedChatHeader(
            title:
                widget.embeddedTitle ?? app.activeConversation?.title ?? '新对话',
            bindingLabel: bindingLabel,
            onMemory: () => showMemorySheet(context),
            onActions: () => showAgentActionSheet(context),
            onBack: widget.onExitEmbedded,
          ),
        pageBody,
        if (!hasPanel && !mobileLanding) composer,
      ],
    );

    return Scaffold(
      key: _scaffoldKey,
      resizeToAvoidBottomInset: false,
      drawerEdgeDragWidth: 24,
      drawer: widget.embedded ? null : const HistoryDrawer(),
      body: widget.embedded ? content : SafeArea(child: content),
    );
  }

  Widget _messageList(BuildContext context, AppState app) {
    // 关闭工具详情时过滤掉 tool 消息 避免残留分隔间距
    final messages = app.toolsOn
        ? app.messages
        : app.messages.where((m) => !m.isTool || m.toolRunning).toList();
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
          padding: const EdgeInsets.fromLTRB(24, 20, 24, 24),
          itemCount: messages.length,
          separatorBuilder: (_, _) =>
              const SizedBox(height: EsaSpace.messageGap),
          itemBuilder: (context, index) {
            final m = messages[index];
            final Widget child;
            switch (m.role) {
              case MessageRole.user:
                child = UserBubble(
                  text: m.text,
                  markdown: m.markdown,
                  codeBlockPrefix: m.id,
                  codeOverrideFor: (blockId) => _codeDrafts[blockId]?.value,
                  onOpenCodeEditorWithId: (blockId, code, language) =>
                      _openCodeEditor(
                        blockId,
                        code,
                        language,
                        source: _CodeSource.user,
                      ),
                  codeOverrideVersion: _codeDraftVersion,
                  attachments: m.attachments,
                  onOpenAttachment: _openAttachment,
                  onEdit: (text) async {
                    _resumeFollowing();
                    await app.reviseUserMessage(m, text);
                  },
                  onCodeChangedWithId: (blockId, code, language) {
                    final existing = _codeDrafts[blockId];
                    if (existing == null) return;
                    _updateCodeSession(
                      existing.copyWith(
                        value: code,
                        language: normalizeCodeLanguage(language),
                      ),
                    );
                  },
                );
              case MessageRole.tool:
                child = Align(
                  alignment: Alignment.centerLeft,
                  child: ToolCallCard(
                    name: m.name ?? 'tool',
                    output: m.text,
                    running: m.toolRunning,
                  ),
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
                  onOpenCodeEditor: (code, language) => _openCodeEditor(
                    '${m.id}:0',
                    code,
                    language,
                    source: _CodeSource.assistant,
                  ),
                  codeOverrideFor: (blockId) => _codeDrafts[blockId]?.value,
                  onOpenCodeEditorWithId: (blockId, code, language) =>
                      _openCodeEditor(
                        blockId,
                        code,
                        language,
                        source: _CodeSource.assistant,
                      ),
                  codeOverrideVersion: _codeDraftVersion,
                  onCodeChangedWithId: (blockId, code, language) {
                    final existing = _codeDrafts[blockId];
                    if (existing == null) return;
                    _updateCodeSession(
                      existing.copyWith(
                        value: code,
                        language: normalizeCodeLanguage(language),
                      ),
                    );
                  },
                );
            }
            return Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 900),
                child: SizedBox(width: double.infinity, child: child),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _EmbeddedChatHeader extends StatelessWidget {
  const _EmbeddedChatHeader({
    required this.title,
    required this.onMemory,
    required this.onActions,
    this.bindingLabel,
    this.onBack,
  });
  final String title;
  final String? bindingLabel;
  final VoidCallback onMemory;
  final VoidCallback onActions;
  final VoidCallback? onBack;

  @override
  Widget build(BuildContext context) => Container(
    height: 50,
    padding: const EdgeInsets.symmetric(horizontal: 20),
    decoration: BoxDecoration(
      border: Border(bottom: BorderSide(color: context.n.divider)),
    ),
    child: Row(
      children: [
        if (onBack != null)
          IconButton(
            tooltip: '返回项目',
            onPressed: onBack,
            icon: const Icon(LucideIcons.arrowLeft, size: 18),
          ),
        Expanded(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.texts.titleMedium?.copyWith(fontSize: 16),
              ),
              if (bindingLabel != null)
                Text(
                  bindingLabel!,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.texts.labelSmall?.copyWith(
                    color: context.n.n600,
                  ),
                ),
            ],
          ),
        ),
        IconButton(
          tooltip: '长期记忆',
          onPressed: onMemory,
          icon: const Icon(LucideIcons.brain, size: 18),
        ),
        IconButton(
          tooltip: '待确认动作',
          onPressed: onActions,
          icon: const Icon(LucideIcons.shieldCheck, size: 18),
        ),
      ],
    ),
  );
}

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.narrow,
    required this.title,
    required this.onMenu,
    required this.onNewChat,
    required this.workspace,
    required this.onLearning,
    required this.onMemory,
    required this.onActions,
    this.bindingLabel,
  });

  final bool narrow;
  final String title;
  final VoidCallback onMenu;
  final VoidCallback onNewChat;
  final WorkspaceType workspace;
  final VoidCallback? onLearning;
  final VoidCallback? onMemory;
  final VoidCallback onActions;
  final String? bindingLabel;

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
                  bindingLabel ??
                      'ESA · ${workspace == WorkspaceType.learning
                          ? 'STUDY'
                          : workspace == WorkspaceType.teaching
                          ? 'TEACHING'
                          : 'RESEARCH'} AGENT',
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
          if (onLearning != null) ...[
            _OutlineIconButton(icon: LucideIcons.barChart3, onTap: onLearning!),
            const SizedBox(width: 8),
          ],
          if (onMemory != null)
            _OutlineIconButton(icon: LucideIcons.brain, onTap: onMemory!),
          const SizedBox(width: 8),
          _OutlineIconButton(icon: LucideIcons.shieldCheck, onTap: onActions),
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

class _LearningHome extends StatelessWidget {
  const _LearningHome({
    this.mobileComposer,
    this.onContinue,
    this.onViewAssignments,
    this.onOpenConversation,
  });

  final Widget? mobileComposer;
  final VoidCallback? onContinue;
  final VoidCallback? onViewAssignments;
  final ValueChanged<String>? onOpenConversation;

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final now = DateTime.now();
    final courses = app.learningCourses;
    final courseName = courses.isNotEmpty
        ? courses.first.name
        : app.scheduleCourseNames.firstOrNull ?? '尚未选择课程';
    final focusPoint =
        app.masteryReport?.stalePoints.firstOrNull ??
        app.masteryReport?.weakPoints.firstOrNull;
    final progress = courses.firstOrNull?.averageMastery;
    final assignments = [...app.studentAssignments]
      ..sort((a, b) {
        final left = a.dueAt ?? DateTime(9999);
        final right = b.dueAt ?? DateTime(9999);
        return left.compareTo(right);
      });
    final recent = _recentItems(app);

    return SingleChildScrollView(
      key: const ValueKey('learning-home-scroll'),
      padding: const EdgeInsets.fromLTRB(24, 24, 24, 12),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('今天', style: context.texts.headlineSmall),
              const SizedBox(height: 4),
              Text(
                '${now.month} 月 ${now.day} 日  ${_weekdayLabel(now.weekday)}',
                style: context.texts.bodySmall,
              ),
              const SizedBox(height: 22),
              _ContinueLearningSection(
                courseName: courseName,
                focusName: focusPoint?.name,
                progress: progress,
                lastStudiedAt: app.conversations.firstOrNull?.updatedAt,
                onContinue: onContinue,
              ),
              const SizedBox(height: 12),
              _HomeSection(
                title: '待办',
                count: assignments.length,
                actionLabel: '查看全部',
                onAction: onViewAssignments,
                child: assignments.isEmpty
                    ? const _HomeEmptyRow(label: '暂无待完成作业')
                    : Column(
                        children: [
                          for (
                            var index = 0;
                            index < assignments.take(4).length;
                            index++
                          ) ...[
                            if (index > 0) const Divider(height: 1),
                            _AssignmentHomeRow(
                              assignment: assignments[index],
                              onTap: onViewAssignments,
                            ),
                          ],
                        ],
                      ),
              ),
              const SizedBox(height: 12),
              _HomeSection(
                title: '最近',
                actionLabel: '查看全部',
                onAction: recent.isEmpty ? null : onContinue,
                child: recent.isEmpty
                    ? const _HomeEmptyRow(label: '暂无最近学习记录')
                    : Column(
                        children: [
                          for (
                            var index = 0;
                            index < recent.length;
                            index++
                          ) ...[
                            if (index > 0) const Divider(height: 1),
                            _RecentHomeRow(
                              item: recent[index],
                              onTap: recent[index].conversationId == null
                                  ? null
                                  : () => onOpenConversation?.call(
                                      recent[index].conversationId!,
                                    ),
                            ),
                          ],
                        ],
                      ),
              ),
              if (mobileComposer != null) ...[
                const SizedBox(height: 12),
                mobileComposer!,
              ],
            ],
          ),
        ),
      ),
    );
  }

  List<_HomeRecentItem> _recentItems(AppState app) {
    final items = <_HomeRecentItem>[];
    for (final attachment in app.recentAttachments.take(2)) {
      items.add(
        _HomeRecentItem(
          icon: LucideIcons.fileText,
          title: attachment.filename,
          meta: '资料 · ${_formatFileSize(attachment.sizeBytes)}',
          time: '最近使用',
        ),
      );
    }
    for (final conversation in app.conversations.take(4 - items.length)) {
      items.add(
        _HomeRecentItem(
          icon: LucideIcons.messageSquare,
          title: conversation.title,
          meta: '对话 · 学习空间',
          time: _relativeTime(conversation.updatedAt),
          conversationId: conversation.id,
        ),
      );
    }
    if (items.length < 4 && app.learningCourses.isNotEmpty) {
      items.add(
        _HomeRecentItem(
          icon: LucideIcons.bookOpen,
          title: app.learningCourses.first.name,
          meta: '课程内容',
          time: '继续学习',
        ),
      );
    }
    return items.take(4).toList();
  }
}

class _ContinueLearningSection extends StatelessWidget {
  const _ContinueLearningSection({
    required this.courseName,
    required this.focusName,
    required this.progress,
    required this.lastStudiedAt,
    required this.onContinue,
  });

  final String courseName;
  final String? focusName;
  final double? progress;
  final DateTime? lastStudiedAt;
  final VoidCallback? onContinue;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.fromLTRB(18, 16, 16, 16),
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      children: [
        Icon(
          LucideIcons.bookOpenCheck,
          size: 19,
          color: context.scheme.primary,
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('继续学习', style: context.texts.titleMedium),
              const SizedBox(height: 8),
              Text(
                focusName == null ? courseName : '$courseName / $focusName',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.texts.bodyLarge?.copyWith(height: 1.25),
              ),
              const SizedBox(height: 4),
              Text(
                '上次学习：${lastStudiedAt == null ? '暂无记录' : _relativeTime(lastStudiedAt!)}'
                '${progress == null ? '' : ' · 学习进度：${progress!.round()}%'}',
                style: context.texts.bodySmall,
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        FilledButton.icon(
          onPressed: onContinue,
          icon: const Icon(LucideIcons.play, size: 15),
          label: const Text('继续'),
          style: FilledButton.styleFrom(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          ),
        ),
      ],
    ),
  );
}

class _HomeSection extends StatelessWidget {
  const _HomeSection({
    required this.title,
    required this.child,
    this.count,
    this.actionLabel,
    this.onAction,
  });

  final String title;
  final int? count;
  final String? actionLabel;
  final VoidCallback? onAction;
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 8, 10),
          child: Row(
            children: [
              Text(title, style: context.texts.titleMedium),
              if (count != null) ...[
                const SizedBox(width: 7),
                Text('$count', style: context.texts.bodySmall),
              ],
              const Spacer(),
              if (actionLabel != null)
                TextButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ),
        ),
        Divider(height: 1, color: context.n.divider),
        child,
      ],
    ),
  );
}

class _AssignmentHomeRow extends StatelessWidget {
  const _AssignmentHomeRow({required this.assignment, this.onTap});

  final TeachingAssignment assignment;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final completed = assignment.submissionId != null;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        child: Row(
          children: [
            Checkbox(value: completed, onChanged: (_) => onTap?.call()),
            Expanded(
              child: Text(
                assignment.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  decoration: completed ? TextDecoration.lineThrough : null,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Text(
              _deadlineLabel(assignment.dueAt),
              style: context.texts.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class _RecentHomeRow extends StatelessWidget {
  const _RecentHomeRow({required this.item, this.onTap});

  final _HomeRecentItem item;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
      child: Row(
        children: [
          Icon(item.icon, size: 16, color: context.n.n600),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                const SizedBox(height: 2),
                Text(item.meta, style: context.texts.bodySmall),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(item.time, style: context.texts.bodySmall),
        ],
      ),
    ),
  );
}

class _HomeEmptyRow extends StatelessWidget {
  const _HomeEmptyRow({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(16),
    child: Align(
      alignment: Alignment.centerLeft,
      child: Text(label, style: context.texts.bodySmall),
    ),
  );
}

class _HomeRecentItem {
  const _HomeRecentItem({
    required this.icon,
    required this.title,
    required this.meta,
    required this.time,
    this.conversationId,
  });

  final IconData icon;
  final String title;
  final String meta;
  final String time;
  final String? conversationId;
}

String _weekdayLabel(int weekday) => const [
  '星期一',
  '星期二',
  '星期三',
  '星期四',
  '星期五',
  '星期六',
  '星期日',
][weekday.clamp(1, 7) - 1];

String _deadlineLabel(DateTime? value) =>
    value == null ? '无截止时间' : '${value.month} 月 ${value.day} 日';

String _relativeTime(DateTime value) {
  final now = DateTime.now();
  final local = value.toLocal();
  final today = DateTime(now.year, now.month, now.day);
  final day = DateTime(local.year, local.month, local.day);
  final days = today.difference(day).inDays;
  final time =
      '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  if (days == 0) return '今天 $time';
  if (days == 1) return '昨天 $time';
  return '${local.month} 月 ${local.day} 日';
}

String _formatFileSize(int bytes) {
  if (bytes <= 0) return '文件';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({
    required this.name,
    required this.workspace,
    required this.selected,
    required this.onPick,
    this.mobileComposer,
  });
  final String name;
  final WorkspaceType workspace;
  final TaskMode? selected;
  final ValueChanged<TaskMode> onPick;
  final Widget? mobileComposer;

  static const _cards = [
    (LucideIcons.calendarCheck2, Color(0xFF3478F6), TaskMode.studyPlan),
    (LucideIcons.lightbulb, Color(0xFF20C85A), TaskMode.concept),
    (LucideIcons.penLine, Color(0xFF8B5CF6), TaskMode.reviewHomework),
  ];

  static const _researchCards = [
    (LucideIcons.filePenLine, Color(0xFF20C85A), TaskMode.academicWriting),
    (
      LucideIcons.chartNoAxesCombined,
      Color(0xFF8B5CF6),
      TaskMode.researchDataAnalysis,
    ),
    (LucideIcons.flaskConical, Color(0xFFFFA514), TaskMode.researchPlanning),
  ];

  @override
  Widget build(BuildContext context) {
    final cards = switch (workspace) {
      WorkspaceType.learning => _cards,
      WorkspaceType.research => _researchCards,
      WorkspaceType.teaching => const <(IconData, Color, TaskMode)>[],
    };
    final mobile = MediaQuery.sizeOf(context).width < 1040;
    return SingleChildScrollView(
      padding: EdgeInsets.fromLTRB(20, mobile ? 10 : 24, 20, 28),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              if (!mobile) const SizedBox(height: 52),
              _AssistantOrb(compact: mobile),
              SizedBox(height: mobile ? 12 : 22),
              Text.rich(
                TextSpan(
                  children: const [
                    TextSpan(text: '你好，我是 '),
                    TextSpan(
                      text: 'ESA',
                      style: TextStyle(color: Color(0xFF4387FF)),
                    ),
                    TextSpan(text: ' 学习助手'),
                  ],
                ),
                textAlign: TextAlign.center,
                style: context.texts.headlineMedium?.copyWith(
                  fontSize: mobile ? 24 : 28,
                ),
              ),
              SizedBox(height: mobile ? 8 : 12),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 580),
                child: Text(
                  '我可以帮你制定学习计划、解释概念、辅导作业、检索资料，\n有什么想学习或解决的问题？尽管问我吧！',
                  textAlign: TextAlign.center,
                  style: context.texts.bodyLarge?.copyWith(
                    color: context.n.n600,
                  ),
                ),
              ),
              SizedBox(height: mobile ? 18 : 42),
              LayoutBuilder(
                builder: (context, constraints) {
                  final columns = mobile ? 2 : 4;
                  final gap = mobile ? 10.0 : 12.0;
                  final width =
                      (constraints.maxWidth - gap * (columns - 1)) / columns;
                  return Wrap(
                    spacing: gap,
                    runSpacing: gap,
                    children: [
                      for (final card in cards)
                        SizedBox(
                          width: width,
                          child: _SuggestionCard(
                            icon: card.$1,
                            accent: card.$2,
                            title: card.$3.title,
                            desc: card.$3.description,
                            selected: selected == card.$3,
                            onTap: () => onPick(card.$3),
                            compact: mobile,
                          ),
                        ),
                    ],
                  );
                },
              ),
              if (mobileComposer != null) ...[
                const SizedBox(height: 12),
                mobileComposer!,
                const SizedBox(height: 12),
                const _MobileLearningInsights(),
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
    required this.icon,
    required this.accent,
    required this.title,
    required this.desc,
    required this.selected,
    required this.onTap,
    required this.compact,
  });

  final IconData icon;
  final Color accent;
  final String title;
  final String desc;
  final bool selected;
  final VoidCallback onTap;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(EsaRadii.card),
      child: Container(
        height: compact ? 118 : 136,
        padding: EdgeInsets.all(compact ? 12 : 14),
        decoration: BoxDecoration(
          color: selected
              ? EsaColors.accent.withValues(alpha: 0.14)
              : context.n.n100,
          border: Border.all(
            color: selected ? EsaColors.accent : Colors.transparent,
          ),
          borderRadius: BorderRadius.circular(EsaRadii.card),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: compact ? 34 : 38,
                  height: compact ? 34 : 38,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: accent.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(9),
                  ),
                  child: Icon(icon, color: accent, size: compact ? 19 : 21),
                ),
                SizedBox(width: compact ? 9 : 11),
                Expanded(
                  child: Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.texts.titleMedium?.copyWith(
                      fontSize: compact ? 14 : 15,
                    ),
                  ),
                ),
              ],
            ),
            SizedBox(height: compact ? 7 : 9),
            Text(
              desc,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: compact ? 11 : 11.5,
                height: 1.35,
                color: context.n.n600,
              ),
            ),
            const Spacer(),
            Icon(
              selected ? LucideIcons.check : LucideIcons.arrowRight,
              size: compact ? 15 : 16,
            ),
          ],
        ),
      ),
    );
  }
}

class _AssistantOrb extends StatelessWidget {
  const _AssistantOrb({required this.compact});

  final bool compact;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: compact ? 86 : 112,
    height: compact ? 86 : 112,
    child: Stack(
      alignment: Alignment.center,
      children: [
        Container(
          width: compact ? 86 : 112,
          height: compact ? 86 : 112,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(
              color: const Color(0xFF1E65E8).withValues(alpha: .25),
            ),
          ),
        ),
        Container(
          width: compact ? 66 : 84,
          height: compact ? 66 : 84,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(
              color: const Color(0xFF2476FF).withValues(alpha: .5),
            ),
            boxShadow: const [
              BoxShadow(
                color: Color(0x553878FF),
                blurRadius: 28,
                spreadRadius: 2,
              ),
            ],
          ),
        ),
        Container(
          width: compact ? 46 : 58,
          height: compact ? 46 : 58,
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            gradient: LinearGradient(
              colors: [Color(0xFF61C9FF), Color(0xFF365BFF)],
            ),
          ),
          child: const Icon(
            LucideIcons.messageCircleMore,
            color: Colors.white,
            size: 30,
          ),
        ),
      ],
    ),
  );
}

class _MobileLearningInsights extends StatelessWidget {
  const _MobileLearningInsights();

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final report = app.masteryReport;
    final courses = app.learningCourses;
    final suggestions = report?.weakPoints.isNotEmpty == true
        ? [
            '优先复习 ${report!.weakPoints.first.name}',
            '待加强知识点 ${report.weakPoints.length} 个',
          ]
        : const ['暂无针对性建议，完成练习后会生成'];
    final courseLines = courses.isEmpty
        ? const ['还没有添加学习课程']
        : courses
              .take(2)
              .map(
                (course) =>
                    '${course.name}  ${course.averageMastery == null ? '未评估' : '${course.averageMastery!.round()}%'}',
              )
              .toList();
    final stateLines = report == null
        ? [app.learningOverviewError ?? '暂无学习状态记录']
        : [
            '已评估知识点 ${report.totalPoints}',
            '平均掌握度 ${report.averageMastery.round()}%',
            '待复习知识点 ${report.stalePoints.length}',
          ];
    return Column(
      children: [
        _InsightPanel(
          icon: LucideIcons.lightbulb,
          title: '今日学习建议',
          lines: suggestions,
        ),
        const SizedBox(height: 10),
        _InsightPanel(
          icon: LucideIcons.notebookTabs,
          title: '最近课程',
          lines: courseLines,
        ),
        const SizedBox(height: 10),
        _InsightPanel(
          icon: LucideIcons.chartNoAxesColumnIncreasing,
          title: '学习状态',
          lines: stateLines,
        ),
      ],
    );
  }
}

class _InsightPanel extends StatelessWidget {
  const _InsightPanel({
    required this.icon,
    required this.title,
    required this.lines,
  });
  final IconData icon;
  final String title;
  final List<String> lines;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 19),
            const SizedBox(width: 9),
            Text(title, style: context.texts.titleMedium),
          ],
        ),
        const SizedBox(height: 12),
        for (final line in lines)
          Padding(
            padding: const EdgeInsets.only(bottom: 7),
            child: Text(line, style: context.texts.bodySmall),
          ),
      ],
    ),
  );
}
