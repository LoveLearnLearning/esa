// 输入区 —— 固定底部 顶部 1px 分割线 内容最大宽 820
// Enter 发送 Shift+Enter 换行 发送按钮胶囊 无内容或生成中时禁用

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../models/task_mode.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import 'esa_markdown.dart';

class Composer extends StatefulWidget {
  const Composer({
    super.key,
    required this.busy,
    required this.onSend,
    this.taskMode,
    this.onClearTaskMode,
  });

  final bool busy;
  final void Function(String text, bool markdown) onSend;
  final TaskMode? taskMode;
  final VoidCallback? onClearTaskMode;

  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  final _controller = TextEditingController();
  final _focus = FocusNode();
  String? _attachment; // 模拟附件文件名
  bool _markdownMode = false;

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  bool get _canSend => !widget.busy && _controller.text.trim().isNotEmpty;

  void _send() {
    if (!_canSend) return;
    widget.onSend(_controller.text, _markdownMode);
    _controller.clear();
    setState(() => _attachment = null);
    _focus.requestFocus();
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is KeyDownEvent &&
        event.logicalKey == LogicalKeyboardKey.enter &&
        !HardwareKeyboard.instance.isShiftPressed) {
      final composing = _controller.value.composing;
      if (composing.isValid && !composing.isCollapsed) {
        // Enter is being used to confirm an IME candidate (for example,
        // committing Latin text from a Chinese input method). Let the text
        // input system handle it instead of treating it as message submit.
        return KeyEventResult.ignored;
      }
      _send();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    final inputStyle = (context.texts.bodyLarge ?? const TextStyle()).copyWith(
      color: context.scheme.onSurface,
      fontSize: 15,
      height: 1.45,
    );

    return Container(
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: context.n.divider)),
      ),
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: EsaSpace.contentMaxWidth),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (widget.taskMode != null) ...[
                _taskModeCard(context, widget.taskMode!),
                const SizedBox(height: EsaSpace.sm),
              ],
              if (_attachment != null) ...[
                _attachmentChip(context),
                const SizedBox(height: EsaSpace.sm),
              ],
              Container(
                decoration: BoxDecoration(
                  color: context.n.n100,
                  border: Border.all(color: context.n.divider),
                  borderRadius: BorderRadius.circular(EsaRadii.composer),
                ),
                padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (_markdownMode && _controller.text.isNotEmpty) ...[
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxHeight: 180),
                        child: SingleChildScrollView(
                          child: EsaMarkdown(data: _controller.text),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        child: Divider(height: 1, color: context.n.divider),
                      ),
                    ],
                    Focus(
                      onKeyEvent: _onKey,
                      child: TextField(
                        controller: _controller,
                        focusNode: _focus,
                        minLines: 2,
                        maxLines: 6,
                        onChanged: (_) => setState(() {}),
                        style: inputStyle,
                        strutStyle: StrutStyle.fromTextStyle(
                          inputStyle,
                          forceStrutHeight: true,
                        ),
                        textAlignVertical: TextAlignVertical.top,
                        cursorHeight: 21.75,
                        cursorWidth: 2,
                        decoration: InputDecoration.collapsed(
                          hintText: widget.taskMode?.hint ?? '问点什么…',
                          hintStyle: inputStyle.copyWith(color: context.n.n600),
                        ),
                      ),
                    ),
                    const SizedBox(height: EsaSpace.sm),
                    Row(
                      children: [
                        _attachButton(context),
                        const SizedBox(width: EsaSpace.sm),
                        _markdownButton(context),
                        const SizedBox(width: EsaSpace.md),
                        Text(
                          'Enter 发送 · Shift + Enter 换行',
                          style: TextStyle(
                            fontSize: 11.5,
                            color: context.n.n600,
                          ),
                        ),
                        const Spacer(),
                        _sendButton(context),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _attachmentChip(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: context.n.n100,
          border: Border.all(color: context.n.divider),
          borderRadius: BorderRadius.circular(EsaRadii.pill),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(LucideIcons.file, size: 14, color: context.n.n600),
            const SizedBox(width: 8),
            Text(
              _attachment!,
              style: TextStyle(fontSize: 12.5, color: context.scheme.onSurface),
            ),
            const SizedBox(width: 8),
            GestureDetector(
              onTap: () => setState(() => _attachment = null),
              child: Icon(LucideIcons.x, size: 14, color: context.n.n600),
            ),
          ],
        ),
      ),
    );
  }

  Widget _taskModeCard(BuildContext context, TaskMode mode) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: EsaColors.accent.withValues(alpha: 0.08),
        border: Border.all(color: EsaColors.accent.withValues(alpha: 0.45)),
        borderRadius: BorderRadius.circular(EsaRadii.toolCard),
      ),
      child: Row(
        children: [
          const Icon(LucideIcons.sparkles, size: 15, color: EsaColors.accent),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(mode.title, style: context.texts.titleMedium),
                Text(
                  mode.description,
                  style: TextStyle(fontSize: 11.5, color: context.n.n600),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: '退出任务模式',
            onPressed: widget.onClearTaskMode,
            icon: const Icon(LucideIcons.x, size: 16),
          ),
        ],
      ),
    );
  }

  Widget _attachButton(BuildContext context) {
    return InkWell(
      onTap: () => setState(() => _attachment = '课堂笔记.pdf'),
      customBorder: const CircleBorder(),
      child: Container(
        width: 32,
        height: 32,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: context.n.divider),
        ),
        child: Icon(LucideIcons.paperclip, size: 16, color: context.n.n600),
      ),
    );
  }

  Widget _markdownButton(BuildContext context) {
    final active = _markdownMode;
    return Tooltip(
      message: active ? '退出 Markdown 输入' : 'Markdown 输入',
      child: InkWell(
        onTap: () => setState(() => _markdownMode = !_markdownMode),
        customBorder: const CircleBorder(),
        child: AnimatedContainer(
          duration: EsaMotion.fade,
          width: 32,
          height: 32,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: active ? EsaColors.accent : Colors.transparent,
            border: Border.all(
              color: active ? EsaColors.accent : context.n.divider,
            ),
          ),
          child: Icon(
            LucideIcons.fileCode2,
            size: 16,
            color: active ? EsaColors.onAccent : context.n.n600,
          ),
        ),
      ),
    );
  }

  Widget _sendButton(BuildContext context) {
    final enabled = _canSend;
    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: Material(
        color: EsaColors.accent,
        borderRadius: BorderRadius.circular(EsaRadii.pill),
        child: InkWell(
          onTap: enabled ? _send : null,
          borderRadius: BorderRadius.circular(EsaRadii.pill),
          child: Container(
            height: 32,
            padding: const EdgeInsets.symmetric(horizontal: 14),
            alignment: Alignment.center,
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '发送',
                  style: TextStyle(
                    color: EsaColors.onAccent,
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                SizedBox(width: 6),
                Icon(LucideIcons.arrowUp, size: 16, color: EsaColors.onAccent),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
