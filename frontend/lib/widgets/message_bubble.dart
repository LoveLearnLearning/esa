// 用户消息 —— 右对齐气泡 最大宽 78% 底色 neutral-200 圆角 18

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../utils/clipboard.dart';
import 'copyable_selection_area.dart';
import 'esa_markdown.dart';

class UserBubble extends StatefulWidget {
  const UserBubble({
    super.key,
    required this.text,
    this.markdown = false,
    this.codeBlockPrefix,
    this.codeOverrideFor,
    this.onOpenCodeEditorWithId,
    this.onCodeChangedWithId,
    this.codeOverrideVersion = 0,
  });

  final String text;
  final bool markdown;
  final String? codeBlockPrefix;
  final String? Function(String blockId)? codeOverrideFor;
  final void Function(String blockId, String code, String language)?
  onOpenCodeEditorWithId;
  final void Function(String blockId, String code, String language)?
  onCodeChangedWithId;
  final int codeOverrideVersion;

  @override
  State<UserBubble> createState() => _UserBubbleState();
}

class _UserBubbleState extends State<UserBubble> {
  bool _copied = false;
  Timer? _copyTimer;

  @override
  void dispose() {
    _copyTimer?.cancel();
    super.dispose();
  }

  Future<void> _copy() async {
    final copied = await copyText(widget.text);
    if (!mounted) return;
    if (!copied) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('复制失败，请手动选择消息复制。')));
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
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.78,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 13),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [Color(0xFF132B55), Color(0xFF0E2344)],
                ),
                border: Border.all(color: const Color(0xFF24436E)),
                borderRadius: BorderRadius.circular(14),
              ),
              child: widget.markdown || containsFencedCode(widget.text)
                  ? EsaMarkdown(
                      data: widget.text,
                      selectable: true,
                      codeBlockPrefix: widget.codeBlockPrefix,
                      codeOverrideFor: widget.codeOverrideFor,
                      onOpenCodeEditorWithId: widget.onOpenCodeEditorWithId,
                      onCodeChangedWithId: widget.onCodeChangedWithId,
                      codeOverrideVersion: widget.codeOverrideVersion,
                    )
                  : CopyableSelectionArea(
                      child: Text(widget.text, style: context.texts.bodyMedium),
                    ),
            ),
            const SizedBox(height: 4),
            Tooltip(
              message: _copied ? '已复制' : '复制',
              child: Material(
                color: Colors.transparent,
                borderRadius: BorderRadius.circular(EsaRadii.iconButton),
                child: InkWell(
                  onTap: () {
                    _copy();
                  },
                  borderRadius: BorderRadius.circular(EsaRadii.iconButton),
                  child: SizedBox(
                    // 触屏最小命中区；图标尺寸不变
                    width: 42,
                    height: 42,
                    child: Icon(
                      _copied ? LucideIcons.check : LucideIcons.copy,
                      size: 15,
                      color: _copied ? EsaColors.accent : context.n.n600,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
