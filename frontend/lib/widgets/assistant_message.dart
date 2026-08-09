// 助手回复 —— 不用气泡 平铺左对齐 顶部 ESA 标签 正文 15/1.75
// 等待/输出时末尾红方块光标 完成后显示复制 / 重新生成按钮

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

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
  });

  final ChatMessage message;
  final VoidCallback onRegenerate;
  final VoidCallback? onContentChanged;

  @override
  State<AssistantMessage> createState() => _AssistantMessageState();
}

class _AssistantMessageState extends State<AssistantMessage> {
  bool _copied = false;
  bool _reasoningExpanded = false;
  Timer? _copyTimer;

  @override
  void initState() {
    super.initState();
    widget.message.addListener(_handleMessageChanged);
  }

  @override
  void didUpdateWidget(covariant AssistantMessage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.message == widget.message) return;
    oldWidget.message.removeListener(_handleMessageChanged);
    widget.message.addListener(_handleMessageChanged);
  }

  void _handleMessageChanged() {
    widget.onContentChanged?.call();
  }

  @override
  void dispose() {
    widget.message.removeListener(_handleMessageChanged);
    _copyTimer?.cancel();
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
    return ListenableBuilder(
      listenable: widget.message,
      builder: (context, _) => _buildMessage(context),
    );
  }

  Widget _buildMessage(BuildContext context) {
    final m = widget.message;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('ESA', style: context.texts.labelSmall),
        const SizedBox(height: EsaSpace.sm),
        if (m.reasoning.isNotEmpty) ...[
          _reasoning(context, m),
          const SizedBox(height: EsaSpace.md),
        ],
        _body(context, m),
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
              Icon(LucideIcons.alertCircle, size: 14, color: context.n.n600),
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
    final markdown = EsaMarkdown(data: visibleText, selectable: true);

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

String _visibleAssistantText(String text) {
  return _withoutTrailingAiLabel(_withoutToolCallMarkup(text));
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
            width: 30,
            height: 30,
            child: Icon(icon, size: 15, color: color),
          ),
        ),
      ),
    );
  }
}
