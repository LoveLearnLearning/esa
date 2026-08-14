import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../models/code_editor_settings.dart';

class MonacoEditor extends StatefulWidget {
  const MonacoEditor({
    super.key,
    required this.value,
    required this.language,
    required this.dark,
    required this.indentSize,
    required this.editorTheme,
    required this.onChanged,
  });

  final String value;
  final String language;
  final bool dark;
  final int indentSize;
  final String editorTheme;
  final ValueChanged<String> onChanged;

  @override
  State<MonacoEditor> createState() => _MonacoEditorState();
}

class _MonacoEditorState extends State<MonacoEditor> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.value);
  }

  @override
  void didUpdateWidget(covariant MonacoEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != _controller.text) {
      _controller.value = TextEditingValue(
        text: widget.value,
        selection: TextSelection.collapsed(offset: widget.value.length),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final background = Color(
      codeEditorThemeBackground(widget.editorTheme, appDark: widget.dark),
    );
    final foreground = Color(
      codeEditorThemeForeground(widget.editorTheme, appDark: widget.dark),
    );
    return ColoredBox(
      color: background,
      child: TextField(
        key: const ValueKey('native-code-editor'),
        controller: _controller,
        expands: true,
        minLines: null,
        maxLines: null,
        keyboardType: TextInputType.multiline,
        inputFormatters: [_CodeEditingFormatter(widget.indentSize)],
        onChanged: widget.onChanged,
        style: TextStyle(
          color: foreground,
          fontFamily: 'JetBrainsMono',
          fontSize: 14,
          height: 1.55,
        ),
        decoration: const InputDecoration(
          filled: false,
          border: InputBorder.none,
          contentPadding: EdgeInsets.all(16),
        ),
      ),
    );
  }
}

class _CodeEditingFormatter extends TextInputFormatter {
  const _CodeEditingFormatter(this.indentSize);

  final int indentSize;

  static const _pairs = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"};

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    if (!newValue.selection.isCollapsed ||
        newValue.text.length != oldValue.text.length + 1) {
      return newValue;
    }
    final offset = newValue.selection.extentOffset;
    if (offset <= 0) return newValue;
    final inserted = newValue.text[offset - 1];
    final closing = _pairs[inserted];
    if (closing != null) {
      return TextEditingValue(
        text: newValue.text.replaceRange(offset, offset, closing),
        selection: TextSelection.collapsed(offset: offset),
      );
    }
    if (inserted != '\n') return newValue;

    final lineStart = newValue.text.lastIndexOf('\n', offset - 2) + 1;
    final previous = newValue.text.substring(lineStart, offset - 1);
    final indent = RegExp(r'^\s*').firstMatch(previous)?.group(0) ?? '';
    final extra = RegExp(r'[\{\[\(:]\s*$').hasMatch(previous)
        ? ' ' * indentSize
        : '';
    final padding = '$indent$extra';
    if (padding.isEmpty) return newValue;
    return TextEditingValue(
      text: newValue.text.replaceRange(offset, offset, padding),
      selection: TextSelection.collapsed(offset: offset + padding.length),
    );
  }
}
