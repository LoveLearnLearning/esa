import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../theme/esa_context.dart';
import '../../theme/esa_theme.dart';
import '../../utils/clipboard.dart';
import 'monaco_editor.dart';

const codeEditorLanguages = <String>[
  'plaintext',
  'python',
  'javascript',
  'typescript',
  'dart',
  'java',
  'cpp',
  'c',
  'csharp',
  'go',
  'rust',
  'html',
  'css',
  'json',
  'yaml',
  'markdown',
  'shell',
  'sql',
];

String normalizeCodeLanguage(String language) {
  final value = language.trim().toLowerCase();
  return switch (value) {
    'js' || 'jsx' || 'node' => 'javascript',
    'ts' || 'tsx' => 'typescript',
    'py' => 'python',
    'sh' || 'bash' || 'zsh' => 'shell',
    'c++' || 'cc' => 'cpp',
    'cs' || 'c#' => 'csharp',
    'htm' => 'html',
    'md' => 'markdown',
    'yml' => 'yaml',
    _ when codeEditorLanguages.contains(value) => value,
    _ => 'plaintext',
  };
}

String codeFilename(String language) =>
    switch (normalizeCodeLanguage(language)) {
      'python' => 'main.py',
      'javascript' => 'main.js',
      'typescript' => 'main.ts',
      'dart' => 'main.dart',
      'java' => 'Main.java',
      'cpp' => 'main.cpp',
      'c' => 'main.c',
      'csharp' => 'Program.cs',
      'go' => 'main.go',
      'rust' => 'main.rs',
      'html' => 'index.html',
      'css' => 'styles.css',
      'json' => 'data.json',
      'yaml' => 'config.yaml',
      'markdown' => 'notes.md',
      'shell' => 'script.sh',
      'sql' => 'query.sql',
      _ => 'untitled.txt',
    };

class CodeEditorPane extends StatefulWidget {
  const CodeEditorPane({
    super.key,
    required this.value,
    required this.originalValue,
    required this.language,
    required this.onChanged,
    required this.onLanguageChanged,
    required this.onClose,
    this.onSendToAgent,
    this.compact = false,
    this.indentSize = 2,
    this.editorTheme = 'vs-dark',
  });

  final String value;
  final String originalValue;
  final String language;
  final ValueChanged<String> onChanged;
  final ValueChanged<String> onLanguageChanged;
  final VoidCallback onClose;
  final VoidCallback? onSendToAgent;
  final bool compact;
  final int indentSize;
  final String editorTheme;

  @override
  State<CodeEditorPane> createState() => _CodeEditorPaneState();
}

class _CodeEditorPaneState extends State<CodeEditorPane> {
  bool _copied = false;
  Timer? _copiedTimer;

  @override
  void dispose() {
    _copiedTimer?.cancel();
    super.dispose();
  }

  Future<void> _copy() async {
    if (!await copyText(widget.value) || !mounted) return;
    setState(() => _copied = true);
    _copiedTimer?.cancel();
    _copiedTimer = Timer(const Duration(milliseconds: 1200), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final language = normalizeCodeLanguage(widget.language);
    final modified = widget.value != widget.originalValue;
    return ColoredBox(
      color: dark ? const Color(0xFF181818) : const Color(0xFFF8F8F8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: 52,
            padding: const EdgeInsets.only(left: 14, right: 6),
            decoration: BoxDecoration(
              color: dark ? const Color(0xFF181818) : const Color(0xFFF3F3F3),
              border: Border(bottom: BorderSide(color: context.n.divider)),
            ),
            child: Row(
              children: [
                Icon(LucideIcons.fileCode2, size: 17, color: EsaColors.accent),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    codeFilename(language),
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontFamily: 'JetBrainsMono',
                      fontSize: 12.5,
                    ),
                  ),
                ),
                if (!widget.compact)
                  Text(
                    modified ? '草稿已保存' : '原始内容',
                    style: TextStyle(fontSize: 11, color: context.n.n600),
                  ),
                const SizedBox(width: 4),
                if (widget.onSendToAgent != null)
                  Tooltip(
                    message: modified ? '将修改后的代码发送给 Agent' : '修改代码后可发送给 Agent',
                    child: IconButton(
                      onPressed: modified ? widget.onSendToAgent : null,
                      style: IconButton.styleFrom(
                        backgroundColor: modified
                            ? EsaColors.accent
                            : context.n.n200,
                        foregroundColor: modified
                            ? EsaColors.onAccent
                            : context.n.n600,
                      ),
                      icon: const Icon(LucideIcons.send, size: 16),
                    ),
                  ),
                _action(
                  context,
                  _copied ? LucideIcons.check : LucideIcons.copy,
                  _copied ? '已复制' : '复制代码',
                  _copy,
                ),
                _action(
                  context,
                  LucideIcons.rotateCcw,
                  '重置为模型生成内容',
                  modified
                      ? () => widget.onChanged(widget.originalValue)
                      : null,
                ),
                _action(context, LucideIcons.x, '关闭编辑器', widget.onClose),
              ],
            ),
          ),
          Container(
            height: 38,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            alignment: Alignment.centerLeft,
            decoration: BoxDecoration(
              color: dark ? const Color(0xFF1F1F1F) : const Color(0xFFFAFAFA),
              border: Border(bottom: BorderSide(color: context.n.divider)),
            ),
            child: Row(
              children: [
                const Icon(LucideIcons.braces, size: 14),
                const SizedBox(width: 7),
                DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: language,
                    isDense: true,
                    borderRadius: BorderRadius.circular(6),
                    style: TextStyle(
                      color: context.scheme.onSurface,
                      fontFamily: 'JetBrainsMono',
                      fontSize: 11.5,
                    ),
                    items: [
                      for (final item in codeEditorLanguages)
                        DropdownMenuItem(value: item, child: Text(item)),
                    ],
                    onChanged: (value) {
                      if (value != null) widget.onLanguageChanged(value);
                    },
                  ),
                ),
                const Spacer(),
              ],
            ),
          ),
          Expanded(
            child: MonacoEditor(
              value: widget.value,
              language: language,
              dark: dark,
              indentSize: widget.indentSize,
              editorTheme: widget.editorTheme,
              onChanged: widget.onChanged,
            ),
          ),
          Container(
            height: 24,
            padding: const EdgeInsets.symmetric(horizontal: 10),
            alignment: Alignment.centerRight,
            color: EsaColors.accent,
            child: Text(
              'ESA EDITOR  ·  ${language.toUpperCase()}',
              style: const TextStyle(
                color: Colors.white,
                fontFamily: 'JetBrainsMono',
                fontSize: 9.5,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _action(
    BuildContext context,
    IconData icon,
    String tooltip,
    VoidCallback? onPressed,
  ) => IconButton(
    tooltip: tooltip,
    onPressed: onPressed,
    icon: Icon(icon, size: 16, color: context.n.n700),
  );
}
