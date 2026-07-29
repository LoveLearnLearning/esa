// 助手回复 —— 不用气泡 平铺左对齐 顶部 ESA 标签 正文 15/1.75
// 等待/输出时末尾红方块光标 完成后显示复制 / 重新生成按钮

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../models/models.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import 'esa_markdown.dart';

class AssistantMessage extends StatefulWidget {
  const AssistantMessage({
    super.key,
    required this.message,
    required this.onRegenerate,
  });

  final ChatMessage message;
  final VoidCallback onRegenerate;

  @override
  State<AssistantMessage> createState() => _AssistantMessageState();
}

class _AssistantMessageState extends State<AssistantMessage> {
  bool _copied = false;
  Timer? _copyTimer;

  @override
  void dispose() {
    _copyTimer?.cancel();
    super.dispose();
  }

  void _copy() {
    Clipboard.setData(ClipboardData(text: widget.message.text));
    setState(() => _copied = true);
    _copyTimer?.cancel();
    _copyTimer = Timer(const Duration(milliseconds: 1400), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final m = widget.message;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('ESA', style: context.texts.labelSmall),
        const SizedBox(height: EsaSpace.sm),
        _body(context, m),
        if (!m.typing && m.text.isNotEmpty) ...[
          const SizedBox(height: EsaSpace.sm),
          Row(
            children: [
              _IconAction(
                icon: LucideIcons.copy,
                color: _copied ? EsaColors.accent : context.n.n600,
                tooltip: '复制',
                onTap: _copy,
              ),
              const SizedBox(width: 4),
              _IconAction(
                icon: LucideIcons.refreshCw,
                color: context.n.n600,
                tooltip: '重新生成',
                onTap: widget.onRegenerate,
              ),
            ],
          ),
        ],
      ],
    );
  }

  Widget _body(BuildContext context, ChatMessage m) {
    final markdown = EsaMarkdown(data: m.text, selectable: !m.typing);

    if (!m.typing) return markdown;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        markdown,
        const Padding(
          padding: EdgeInsets.only(top: 2),
          child: _BlinkingCursor(),
        ),
      ],
    );
  }
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
