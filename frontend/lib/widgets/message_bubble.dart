// 用户消息 —— 右对齐气泡 最大宽 78% 底色 neutral-200 圆角 18

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
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
    this.onRunCode,
    this.codeOverrideVersion = 0,
    this.attachments = const [],
    this.onOpenAttachment,
    this.onEdit,
  });

  final String text;
  final bool markdown;
  final String? codeBlockPrefix;
  final String? Function(String blockId)? codeOverrideFor;
  final void Function(String blockId, String code, String language)?
  onOpenCodeEditorWithId;
  final void Function(String blockId, String code, String language)?
  onCodeChangedWithId;
  final CodeRunCallback? onRunCode;
  final int codeOverrideVersion;
  final List<DocumentAttachment> attachments;
  final ValueChanged<DocumentAttachment>? onOpenAttachment;
  final Future<void> Function(String text)? onEdit;

  @override
  State<UserBubble> createState() => _UserBubbleState();
}

class _UserBubbleState extends State<UserBubble> {
  bool _copied = false;
  late final TextEditingController _editor;
  bool _editing = false;
  bool _savingEdit = false;
  Timer? _copyTimer;

  @override
  void initState() {
    super.initState();
    _editor = TextEditingController(text: widget.text);
  }

  @override
  void didUpdateWidget(covariant UserBubble oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_editing && oldWidget.text != widget.text) _editor.text = widget.text;
  }

  @override
  void dispose() {
    _copyTimer?.cancel();
    _editor.dispose();
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

  Future<void> _saveEdit() async {
    final input = _editor.text.trim();
    if (input.isEmpty || _savingEdit || widget.onEdit == null) return;
    setState(() => _savingEdit = true);
    try {
      await widget.onEdit!(input);
      if (!mounted) return;
      setState(() => _editing = false);
    } finally {
      if (mounted) setState(() => _savingEdit = false);
    }
  }

  void _cancelEdit() {
    _editor.text = widget.text;
    setState(() => _editing = false);
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
                gradient: context.isDark
                    ? const LinearGradient(
                        colors: [Color(0xFF132B55), Color(0xFF0E2344)],
                      )
                    : LinearGradient(
                        colors: [
                          EsaColors.accent.withValues(alpha: 0.88),
                          EsaColors.accent600.withValues(alpha: 0.92),
                        ],
                      ),
                border: Border.all(
                  color: context.isDark
                      ? const Color(0xFF24436E)
                      : EsaColors.accent.withValues(alpha: 0.5),
                ),
                borderRadius: BorderRadius.circular(14),
              ),
              child: _editing
                  ? _editField(context)
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        widget.markdown || containsFencedCode(widget.text)
                            ? EsaMarkdown(
                                data: widget.text,
                                selectable: true,
                                codeBlockPrefix: widget.codeBlockPrefix,
                                codeOverrideFor: widget.codeOverrideFor,
                                onOpenCodeEditorWithId:
                                    widget.onOpenCodeEditorWithId,
                                onCodeChangedWithId: widget.onCodeChangedWithId,
                                onRunCode: widget.onRunCode,
                                codeOverrideVersion: widget.codeOverrideVersion,
                              )
                            : CopyableSelectionArea(
                                child: Text(
                                  widget.text,
                                  style: context.texts.bodyMedium,
                                ),
                              ),
                        if (widget.attachments.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              for (final attachment in widget.attachments)
                                _MessageAttachmentChip(
                                  attachment: attachment,
                                  onTap: widget.onOpenAttachment == null
                                      ? null
                                      : () => widget.onOpenAttachment!(
                                          attachment,
                                        ),
                                ),
                            ],
                          ),
                        ],
                      ],
                    ),
            ),
            const SizedBox(height: 4),
            if (!_editing)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  _bubbleAction(
                    tooltip: _copied ? '已复制' : '复制',
                    icon: _copied ? LucideIcons.check : LucideIcons.copy,
                    color: _copied ? EsaColors.accent : context.n.n600,
                    onTap: _copy,
                  ),
                  if (widget.onEdit != null)
                    _bubbleAction(
                      tooltip: '编辑消息',
                      icon: LucideIcons.pencil,
                      color: context.n.n600,
                      onTap: () => setState(() => _editing = true),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  Widget _editField(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      TextField(
        controller: _editor,
        autofocus: true,
        minLines: 2,
        maxLines: 10,
        keyboardType: TextInputType.multiline,
        style: context.texts.bodyMedium,
        decoration: const InputDecoration(isDense: true, hintText: '修改这条消息'),
        onSubmitted: (_) => _saveEdit(),
      ),
      const SizedBox(height: 10),
      Row(
        mainAxisAlignment: MainAxisAlignment.end,
        children: [
          TextButton(
            onPressed: _savingEdit ? null : _cancelEdit,
            child: const Text('取消'),
          ),
          const SizedBox(width: 8),
          FilledButton.icon(
            onPressed: _savingEdit ? null : _saveEdit,
            icon: _savingEdit
                ? const SizedBox.square(
                    dimension: 15,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(LucideIcons.check, size: 16),
            label: const Text('重新发送'),
          ),
        ],
      ),
    ],
  );

  Widget _bubbleAction({
    required String tooltip,
    required IconData icon,
    required Color color,
    required VoidCallback onTap,
  }) => Tooltip(
    message: tooltip,
    child: Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(EsaRadii.iconButton),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(EsaRadii.iconButton),
        child: SizedBox(
          width: 42,
          height: 42,
          child: Icon(icon, size: 15, color: color),
        ),
      ),
    ),
  );
}

class _MessageAttachmentChip extends StatelessWidget {
  const _MessageAttachmentChip({required this.attachment, this.onTap});

  final DocumentAttachment attachment;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.transparent,
    borderRadius: BorderRadius.circular(EsaRadii.field),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(EsaRadii.field),
      child: Container(
        constraints: const BoxConstraints(maxWidth: 260),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: .08),
          border: Border.all(color: Colors.white.withValues(alpha: .18)),
          borderRadius: BorderRadius.circular(EsaRadii.field),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(LucideIcons.paperclip, size: 15),
            const SizedBox(width: 7),
            Flexible(
              child: Text(
                attachment.filename,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12.5),
              ),
            ),
            const SizedBox(width: 5),
            Icon(LucideIcons.chevronRight, size: 15, color: context.n.n600),
          ],
        ),
      ),
    ),
  );
}
