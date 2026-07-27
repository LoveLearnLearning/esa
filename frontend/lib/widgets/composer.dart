// 输入区 —— 固定底部 顶部 1px 分割线 内容最大宽 820
// Enter 发送 Shift+Enter 换行 发送按钮胶囊 无内容或生成中时禁用

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

class Composer extends StatefulWidget {
  const Composer({super.key, required this.busy, required this.onSend});

  final bool busy;
  final ValueChanged<String> onSend;

  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  final _controller = TextEditingController();
  final _focus = FocusNode();
  String? _attachment; // 模拟附件文件名

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  bool get _canSend => !widget.busy && _controller.text.trim().isNotEmpty;

  void _send() {
    if (!_canSend) return;
    widget.onSend(_controller.text);
    _controller.clear();
    setState(() => _attachment = null);
    _focus.requestFocus();
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is KeyDownEvent &&
        event.logicalKey == LogicalKeyboardKey.enter &&
        !HardwareKeyboard.instance.isShiftPressed) {
      _send();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
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
                    Focus(
                      onKeyEvent: _onKey,
                      child: TextField(
                        controller: _controller,
                        focusNode: _focus,
                        minLines: 2,
                        maxLines: 6,
                        onChanged: (_) => setState(() {}),
                        decoration: const InputDecoration(
                          isCollapsed: true,
                          filled: false,
                          border: InputBorder.none,
                          enabledBorder: InputBorder.none,
                          focusedBorder: InputBorder.none,
                          hintText: '问点什么…',
                        ),
                      ),
                    ),
                    const SizedBox(height: EsaSpace.sm),
                    Row(
                      children: [
                        _attachButton(context),
                        const SizedBox(width: EsaSpace.md),
                        Text(
                          'Enter 发送 · Shift + Enter 换行',
                          style:
                              TextStyle(fontSize: 11.5, color: context.n.n600),
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
            Text(_attachment!,
                style: TextStyle(fontSize: 12.5, color: context.scheme.onSurface)),
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
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: const [
                Text('发送',
                    style: TextStyle(
                        color: EsaColors.onAccent,
                        fontSize: 13,
                        fontWeight: FontWeight.w800)),
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
