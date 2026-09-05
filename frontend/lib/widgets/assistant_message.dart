// 助手回复 —— 不用气泡 平铺左对齐 顶部 ESA 标签 正文 15/1.75
// 等待/输出时末尾红方块光标 完成后显示复制 / 重新生成按钮

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../utils/clipboard.dart';
import 'esa_markdown.dart';

class AssistantMessage extends StatefulWidget {
  const AssistantMessage({
    super.key,
    required this.message,
    required this.onRegenerate,
    this.onContentChanged,
    this.renderPaused,
    this.onOpenCodeEditor,
    this.codeOverrideFor,
    this.onOpenCodeEditorWithId,
    this.onCodeChangedWithId,
    this.onRunCode,
    this.codeOverrideVersion = 0,
    this.sources = const [],
    this.onOpenSource,
  });

  final ChatMessage message;
  final VoidCallback onRegenerate;
  final VoidCallback? onContentChanged;
  final ValueListenable<bool>? renderPaused;
  final void Function(String code, String language)? onOpenCodeEditor;
  final String? Function(String blockId)? codeOverrideFor;
  final void Function(String blockId, String code, String language)?
  onOpenCodeEditorWithId;
  final void Function(String blockId, String code, String language)?
  onCodeChangedWithId;
  final CodeRunCallback? onRunCode;
  final int codeOverrideVersion;
  final List<SourceCitation> sources;
  final ValueChanged<SourceCitation>? onOpenSource;

  @override
  State<AssistantMessage> createState() => _AssistantMessageState();
}

class _AssistantMessageState extends State<AssistantMessage> {
  bool _copied = false;
  bool _reasoningExpanded = false;
  Timer? _copyTimer;
  Timer? _renderTimer;
  bool _renderPending = false;

  bool get _renderPaused => widget.renderPaused?.value ?? false;

  Duration get _renderInterval {
    final length = widget.message.text.length + widget.message.reasoning.length;
    if (length < 1500) return const Duration(milliseconds: 48);
    if (length < 6000) return const Duration(milliseconds: 80);
    return const Duration(milliseconds: 120);
  }

  @override
  void initState() {
    super.initState();
    widget.message.addListener(_handleMessageChanged);
    widget.renderPaused?.addListener(_handleRenderPausedChanged);
  }

  @override
  void didUpdateWidget(covariant AssistantMessage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.message != widget.message) {
      oldWidget.message.removeListener(_handleMessageChanged);
      widget.message.addListener(_handleMessageChanged);
      _renderTimer?.cancel();
      _renderTimer = null;
      _renderPending = false;
    }
    if (oldWidget.renderPaused != widget.renderPaused) {
      oldWidget.renderPaused?.removeListener(_handleRenderPausedChanged);
      widget.renderPaused?.addListener(_handleRenderPausedChanged);
    }
  }

  void _handleMessageChanged() {
    _renderPending = true;
    if (_renderPaused) {
      _renderTimer?.cancel();
      _renderTimer = null;
      return;
    }
    _scheduleRender();
  }

  void _handleRenderPausedChanged() {
    if (_renderPaused) {
      _renderTimer?.cancel();
      _renderTimer = null;
      return;
    }
    if (_renderPending) _scheduleRender(immediate: true);
  }

  void _scheduleRender({bool immediate = false}) {
    if (_renderTimer != null) return;
    _renderTimer = Timer(immediate ? Duration.zero : _renderInterval, () {
      _renderTimer = null;
      if (!mounted || _renderPaused || !_renderPending) return;
      _renderPending = false;
      setState(() {});
      widget.onContentChanged?.call();
    });
  }

  @override
  void dispose() {
    widget.message.removeListener(_handleMessageChanged);
    widget.renderPaused?.removeListener(_handleRenderPausedChanged);
    _copyTimer?.cancel();
    _renderTimer?.cancel();
    super.dispose();
  }

  Future<void> _copy() async {
    final copied = await copyText(_visibleAssistantText(widget.message.text));
    if (!mounted) return;
    if (!copied) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('复制失败，请手动选择正文复制。')));
      return;
    }
    setState(() => _copied = true);
    _copyTimer?.cancel();
    _copyTimer = Timer(const Duration(milliseconds: 1400), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return _buildMessage(context);
  }

  Widget _buildMessage(BuildContext context) {
    final m = widget.message;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 34,
          height: 34,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: EsaColors.accent.withValues(alpha: .18),
            border: Border.all(color: EsaColors.accent.withValues(alpha: .35)),
          ),
          child: const Text(
            'ESA',
            style: TextStyle(
              fontSize: 9,
              color: Color(0xFFD8D8DD),
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: context.n.n100,
              border: Border.all(color: context.n.divider),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text('ESA', style: context.texts.labelSmall),
                    const SizedBox(width: 8),
                    Text(m.createdAt ?? '', style: context.texts.bodySmall),
                  ],
                ),
                const SizedBox(height: EsaSpace.sm),
                if (m.reasoning.isNotEmpty) ...[
                  _reasoning(context, m),
                  const SizedBox(height: EsaSpace.md),
                ],
                _body(context, m),
                if (!m.typing && widget.sources.isNotEmpty) ...[
                  const SizedBox(height: EsaSpace.sm),
                  _SourceList(
                    sources: widget.sources,
                    onOpenSource: widget.onOpenSource,
                  ),
                ],
                if (!m.typing && m.text.isNotEmpty) ...[
                  const SizedBox(height: EsaSpace.sm),
                  Row(
                    children: [
                      _IconAction(
                        icon: LucideIcons.copy,
                        color: _copied ? EsaColors.accent : context.n.n600,
                        tooltip: '复制',
                        onTap: () {
                          _copy();
                        },
                      ),
                      const SizedBox(width: 4),
                      _IconAction(
                        icon: LucideIcons.refreshCw,
                        color: context.n.n600,
                        tooltip: '重新生成',
                        onTap: widget.onRegenerate,
                      ),
                      const Spacer(),
                      Icon(
                        LucideIcons.alertCircle,
                        size: 14,
                        color: context.n.n600,
                      ),
                      const SizedBox(width: 6),
                      Text(
                        'AI 生成',
                        style: TextStyle(
                          color: context.n.n600,
                          fontSize: 11.5,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _reasoning(BuildContext context, ChatMessage message) {
    final reasoning = message.reasoning.trim();
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: context.n.n100,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.toolCard),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: () {
              setState(() => _reasoningExpanded = !_reasoningExpanded);
            },
            borderRadius: BorderRadius.circular(EsaRadii.toolCard),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: EsaSpace.md,
                vertical: 10,
              ),
              child: Row(
                children: [
                  Icon(
                    LucideIcons.brain,
                    size: 15,
                    color: message.typing ? EsaColors.accent : context.n.n600,
                  ),
                  const SizedBox(width: EsaSpace.sm),
                  Text(
                    message.typing ? '正在思考' : '思考过程',
                    style: context.texts.titleMedium?.copyWith(fontSize: 13),
                  ),
                  const Spacer(),
                  Icon(
                    _reasoningExpanded
                        ? LucideIcons.chevronUp
                        : LucideIcons.chevronDown,
                    size: 16,
                    color: context.n.n600,
                  ),
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: EsaMotion.fade,
            alignment: Alignment.topCenter,
            child: _reasoningExpanded
                ? Container(
                    width: double.infinity,
                    padding: const EdgeInsets.fromLTRB(
                      EsaSpace.md,
                      0,
                      EsaSpace.md,
                      EsaSpace.md,
                    ),
                    decoration: BoxDecoration(
                      border: Border(top: BorderSide(color: context.n.divider)),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.only(top: EsaSpace.md),
                      child: EsaMarkdown(data: reasoning, selectable: true),
                    ),
                  )
                : Padding(
                    padding: const EdgeInsets.fromLTRB(
                      EsaSpace.md,
                      0,
                      EsaSpace.md,
                      EsaSpace.md,
                    ),
                    child: Text(
                      reasoning.replaceAll(RegExp(r'\s+'), ' '),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: context.texts.bodySmall?.copyWith(
                        color: context.n.n600,
                      ),
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _body(BuildContext context, ChatMessage m) {
    final visibleText = _visibleAssistantText(m.text);
    // 正在流式更新的 Markdown 节点不能加入 Flutter 的选择树。否则用户拖选
    // 其他正文时，这里的子节点又被流式重建，会触发 ConcurrentModificationError。
    // 生成完成后会立即恢复跨段落选择。
    final markdown = EsaMarkdown(
      data: visibleText,
      selectable: !m.typing,
      onEditCode: widget.onOpenCodeEditor,
      codeBlockPrefix: m.id,
      codeOverrideFor: widget.codeOverrideFor,
      onOpenCodeEditorWithId: widget.onOpenCodeEditorWithId,
      onCodeChangedWithId: widget.onCodeChangedWithId,
      onRunCode: widget.onRunCode,
      codeOverrideVersion: widget.codeOverrideVersion,
    );

    if (!m.typing) return markdown;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (visibleText.isNotEmpty) markdown,
        const Padding(
          padding: EdgeInsets.only(top: 2),
          child: _BlinkingCursor(),
        ),
      ],
    );
  }
}

class _SourceList extends StatelessWidget {
  const _SourceList({required this.sources, this.onOpenSource});

  final List<SourceCitation> sources;
  final ValueChanged<SourceCitation>? onOpenSource;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) => Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          for (final source in sources)
            ConstrainedBox(
              constraints: BoxConstraints(maxWidth: constraints.maxWidth),
              child: Material(
                color: Colors.transparent,
                child: InkWell(
                  onTap: source.canOpen && onOpenSource != null
                      ? () => onOpenSource!(source)
                      : null,
                  borderRadius: BorderRadius.circular(6),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 7,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: context.n.n200,
                      border: Border.all(color: context.n.divider),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          source.canOpen
                              ? LucideIcons.fileText
                              : LucideIcons.link,
                          size: 12,
                          color: source.canOpen
                              ? EsaColors.accent
                              : context.n.n600,
                        ),
                        const SizedBox(width: 5),
                        Flexible(
                          child: Text(
                            source.locationLabel.isEmpty
                                ? source.label
                                : source.locationLabel,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            softWrap: false,
                            style: TextStyle(
                              color: source.canOpen
                                  ? context.scheme.onSurface
                                  : context.n.n600,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

String _visibleAssistantText(String text) {
  final visible = _withoutTrailingAiLabel(_withoutToolCallMarkup(text));
  // A model may echo a complete citation line from the tool response. Remove
  // that line before rendering; the structured source badges are rendered
  // below the answer instead.
  final withoutCitationLines = visible.replaceAll(
    RegExp(r'^\s*【来源\s*\d+(?:\s*\|[^】]*)?】[^\r\n]*\s*$', multiLine: true),
    '',
  );
  return withoutCitationLines.replaceAll(
    RegExp(r'【来源\s*\d+(?:\s*\|[^】]*)?】'),
    '',
  );
}

String _withoutToolCallMarkup(String text) {
  const marker = '<tool_call>';
  var visible = text.replaceAll(
    RegExp(
      r'<tool_call\b[^>]*>.*?</tool_call\s*>',
      caseSensitive: false,
      dotAll: true,
    ),
    '',
  );

  // 流式过程中结束标签尚未到达时，从工具调用开始处隐藏后续内容。
  final openIndex = visible.toLowerCase().indexOf('<tool_call');
  if (openIndex >= 0) visible = visible.substring(0, openIndex);

  // 防止分块恰好落在 `<tool_call>` 中间时短暂显示半截协议标签。
  final lower = visible.toLowerCase();
  for (var length = marker.length - 1; length > 0; length--) {
    if (lower.endsWith(marker.substring(0, length))) {
      return visible.substring(0, visible.length - length);
    }
  }
  return visible;
}

String _withoutTrailingAiLabel(String text) {
  return text.replaceFirst(
    RegExp(r'(?:\r?\n)+\s*AI\s*生成\s*$', caseSensitive: false),
    '',
  );
}

class _BlinkingCursor extends StatefulWidget {
  const _BlinkingCursor();

  @override
  State<_BlinkingCursor> createState() => _BlinkingCursorState();
}

class _BlinkingCursorState extends State<_BlinkingCursor> {
  bool _on = true;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 530), (_) {
      if (mounted) setState(() => _on = !_on);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: _on ? 1 : 0,
      child: Container(width: 8, height: 16, color: EsaColors.accent),
    );
  }
}

class _IconAction extends StatelessWidget {
  const _IconAction({
    required this.icon,
    required this.color,
    required this.tooltip,
    required this.onTap,
  });

  final IconData icon;
  final Color color;
  final String tooltip;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(EsaRadii.iconButton),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(EsaRadii.iconButton),
          hoverColor: context.n.n200,
          child: SizedBox(
            // 触屏最小命中区（Apple 44pt 建议）；图标保持 15px 不变
            width: 42,
            height: 42,
            child: Icon(icon, size: 15, color: color),
          ),
        ),
      ),
    );
  }
}
