import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_markdown_plus_latex/flutter_markdown_plus_latex.dart';
import 'package:highlight/highlight.dart' show Node, highlight;
import 'package:markdown/markdown.dart' as md;

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../utils/clipboard.dart';
import 'copyable_selection_area.dart';

String normalizeMarkdownLatex(String source) {
  final lines = source.split('\n');
  final output = <String>[];
  var inFence = false;

  for (final line in lines) {
    final trimmed = line.trimLeft();
    final isFence = trimmed.startsWith('```') || trimmed.startsWith('~~~');

    if (isFence) {
      inFence = !inFence;
      output.add(line);
      continue;
    }

    if (inFence || !line.contains(r'$$')) {
      output.add(line);
      continue;
    }

    // LatexBlockSyntax only recognizes $$ when it is on its own line.
    // Model output commonly places display math directly after prose.
    final normalized = line.replaceAllMapped(
      RegExp(r'(?<!\\)\$\$'),
      (_) => '\n\$\$\n',
    );
    output.add(normalized);
  }

  return output.join('\n').replaceAll(RegExp(r'\n{3,}'), '\n\n');
}

bool containsFencedCode(String source) =>
    RegExp(r'^\s*(?:```|~~~)', multiLine: true).hasMatch(source);

class EsaMarkdown extends StatelessWidget {
  const EsaMarkdown({
    super.key,
    required this.data,
    this.selectable = false,
    this.onEditCode,
    this.codeBlockPrefix,
    this.codeOverrideFor,
    this.onOpenCodeEditorWithId,
    this.onCodeChangedWithId,
    this.codeOverrideVersion = 0,
  });

  final String data;
  final bool selectable;
  final void Function(String code, String language)? onEditCode;
  final String? codeBlockPrefix;
  final String? Function(String blockId)? codeOverrideFor;
  final void Function(String blockId, String code, String language)?
  onOpenCodeEditorWithId;
  final void Function(String blockId, String code, String language)?
  onCodeChangedWithId;
  final int codeOverrideVersion;

  @override
  Widget build(BuildContext context) {
    final foreground = context.scheme.onSurface;
    final bodyStyle = context.texts.bodyLarge?.copyWith(color: foreground);
    final headingBase = bodyStyle?.copyWith(
      color: foreground,
      height: 1.4,
      fontWeight: FontWeight.w700,
    );

    final markdown = MarkdownBody(
      key: ValueKey(
        '${data.hashCode}:${codeBlockPrefix ?? ''}:$codeOverrideVersion',
      ),
      data: normalizeMarkdownLatex(data),
      // 单个 SelectableText 无法跨 Markdown 段落选择。外层统一交给
      // SelectionArea，段落内部保持普通 Text/RichText。
      selectable: false,
      builders: {
        'latex': LatexElementBuilder(textStyle: bodyStyle),
        'pre': _CodeBlockBuilder(
          onEditCode: onEditCode,
          codeBlockPrefix: codeBlockPrefix,
          codeOverrideFor: codeOverrideFor,
          onOpenCodeEditorWithId: onOpenCodeEditorWithId,
          onCodeChangedWithId: onCodeChangedWithId,
        ),
      },
      extensionSet: md.ExtensionSet(
        [LatexBlockSyntax(), ...md.ExtensionSet.gitHubFlavored.blockSyntaxes],
        [LatexInlineSyntax(), ...md.ExtensionSet.gitHubFlavored.inlineSyntaxes],
      ),
      styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
        p: bodyStyle,
        h1: headingBase?.copyWith(fontSize: 22),
        h2: headingBase?.copyWith(fontSize: 20),
        h3: headingBase?.copyWith(fontSize: 18),
        h4: headingBase?.copyWith(fontSize: 16),
        h5: headingBase?.copyWith(fontSize: 15),
        h6: headingBase?.copyWith(fontSize: 14),
        strong: bodyStyle?.copyWith(fontWeight: FontWeight.w800),
        em: bodyStyle?.copyWith(fontStyle: FontStyle.italic),
        listBullet: bodyStyle,
        tableHead: bodyStyle?.copyWith(fontWeight: FontWeight.w800),
        tableBody: bodyStyle,
        blockquote: bodyStyle?.copyWith(color: context.n.n700),
        blockquoteDecoration: BoxDecoration(
          color: context.n.n100,
          borderRadius: BorderRadius.circular(EsaRadii.toolCard),
          border: const Border(
            left: BorderSide(color: EsaColors.accent, width: 3),
          ),
        ),
        code: bodyStyle?.copyWith(
          fontFamily: 'JetBrainsMono',
          fontSize: 13,
          color: context.scheme.onSurface,
          backgroundColor: context.n.n200,
        ),
        // `pre` 已由 _EditableCodeBlock 自己绘制背景、边框和圆角。
        // 这里保持透明，避免 MarkdownBody 再套一层形成顶部横线和露底。
        codeblockDecoration: const BoxDecoration(),
        a: bodyStyle?.copyWith(
          color: EsaColors.accent,
          decoration: TextDecoration.underline,
        ),
      ),
    );

    return selectable ? CopyableSelectionArea(child: markdown) : markdown;
  }
}

class _CodeBlockBuilder extends MarkdownElementBuilder {
  _CodeBlockBuilder({
    this.onEditCode,
    this.codeBlockPrefix,
    this.codeOverrideFor,
    this.onOpenCodeEditorWithId,
    this.onCodeChangedWithId,
  });

  final void Function(String code, String language)? onEditCode;
  final String? codeBlockPrefix;
  final String? Function(String blockId)? codeOverrideFor;
  final void Function(String blockId, String code, String language)?
  onOpenCodeEditorWithId;
  final void Function(String blockId, String code, String language)?
  onCodeChangedWithId;
  var _blockIndex = 0;

  @override
  bool isBlockElement() => true;

  @override
  Widget? visitElementAfterWithContext(
    BuildContext context,
    md.Element element,
    TextStyle? preferredStyle,
    TextStyle? parentStyle,
  ) {
    final codeElement = element.children?.whereType<md.Element>().firstOrNull;
    final className = codeElement?.attributes['class'] ?? '';
    final language = className.startsWith('language-')
        ? className.substring('language-'.length)
        : 'plaintext';
    final sourceCode = element.textContent.trimRight();
    final blockId = '${codeBlockPrefix ?? 'markdown'}:${_blockIndex++}';
    final displayCode = codeOverrideFor?.call(blockId) ?? sourceCode;
    return _EditableCodeBlock(
      code: sourceCode,
      displayCode: displayCode,
      language: language,
      onOpenEditor: onEditCode,
      blockId: blockId,
      onOpenEditorWithId: onOpenCodeEditorWithId,
      onCodeChangedWithId: onCodeChangedWithId,
    );
  }
}

class _EditableCodeBlock extends StatefulWidget {
  const _EditableCodeBlock({
    required this.code,
    required this.displayCode,
    required this.language,
    required this.blockId,
    this.onOpenEditor,
    this.onOpenEditorWithId,
    this.onCodeChangedWithId,
  });

  final String code;
  final String displayCode;
  final String language;
  final String blockId;
  final void Function(String code, String language)? onOpenEditor;
  final void Function(String blockId, String code, String language)?
  onOpenEditorWithId;
  final void Function(String blockId, String code, String language)?
  onCodeChangedWithId;

  @override
  State<_EditableCodeBlock> createState() => _EditableCodeBlockState();
}

class _EditableCodeBlockState extends State<_EditableCodeBlock> {
  late final _HighlightEditingController _controller;
  late String _originalCode;
  bool _editing = false;
  bool _copied = false;

  bool get _modified => _controller.text != _originalCode;

  @override
  void initState() {
    super.initState();
    _originalCode = widget.code.trimRight();
    _controller = _HighlightEditingController(
      text: widget.displayCode.trimRight(),
      language: widget.language,
    );
  }

  @override
  void didUpdateWidget(covariant _EditableCodeBlock oldWidget) {
    super.didUpdateWidget(oldWidget);
    _controller.language = widget.language;
    final sourceChanged = widget.code != oldWidget.code;
    final displayChanged = widget.displayCode != oldWidget.displayCode;
    if (sourceChanged) _originalCode = widget.code.trimRight();
    if (sourceChanged || displayChanged) {
      _controller.value = TextEditingValue(
        text: widget.displayCode.trimRight(),
        selection: TextSelection.collapsed(
          offset: widget.displayCode.trimRight().length,
        ),
      );
    }
  }

  void _resetCode() {
    _controller.value = TextEditingValue(
      text: _originalCode,
      selection: TextSelection.collapsed(offset: _originalCode.length),
    );
    widget.onCodeChangedWithId?.call(
      widget.blockId,
      _originalCode,
      widget.language,
    );
    setState(() {});
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    _controller.dark = dark;
    final frameColor = dark ? const Color(0xFF171717) : const Color(0xFFF3F3F1);
    final headerColor = dark
        ? const Color(0xFF222222)
        : const Color(0xFFE9E9E6);
    final labelColor = dark ? const Color(0xFFAAAAAA) : const Color(0xFF75756D);
    final codeBg = dark ? const Color(0xFF282C34) : const Color(0xFFFAFAFA);
    final baseCodeColor = dark
        ? const Color(0xFFABB2BF)
        : const Color(0xFF383A42);
    final iconColor = dark ? const Color(0xFFCCCCCC) : const Color(0xFF55554F);
    final hasExternalEditor =
        widget.onOpenEditor != null || widget.onOpenEditorWithId != null;
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: frameColor,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.toolCard),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.only(left: 12, right: 4),
            color: headerColor,
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    widget.language,
                    style: TextStyle(
                      color: labelColor,
                      fontSize: 11,
                      fontFamily: 'JetBrainsMono',
                    ),
                  ),
                ),
                _action(
                  !hasExternalEditor
                      ? (_editing
                            ? Icons.visibility_outlined
                            : Icons.edit_outlined)
                      : Icons.open_in_new_rounded,
                  !hasExternalEditor ? (_editing ? '预览' : '编辑') : '在编辑器中打开',
                  iconColor,
                  !hasExternalEditor
                      ? () => setState(() => _editing = !_editing)
                      : () {
                          if (widget.onOpenEditorWithId != null) {
                            widget.onOpenEditorWithId!(
                              widget.blockId,
                              _controller.text,
                              widget.language,
                            );
                          } else {
                            widget.onOpenEditor?.call(
                              _controller.text,
                              widget.language,
                            );
                          }
                        },
                ),
                if (_modified)
                  _action(
                    Icons.restore_rounded,
                    '重置为模型生成内容',
                    iconColor,
                    _resetCode,
                  ),
                _action(
                  _copied ? Icons.check : Icons.copy_outlined,
                  '复制',
                  iconColor,
                  () async {
                    final copied = await copyText(_controller.text);
                    if (!context.mounted) return;
                    if (!copied) {
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('复制失败，请手动选择代码复制。')),
                      );
                      return;
                    }
                    setState(() => _copied = copied);
                    Future<void>.delayed(
                      const Duration(milliseconds: 1200),
                      () {
                        if (mounted) setState(() => _copied = false);
                      },
                    );
                  },
                ),
                _action(Icons.play_arrow_rounded, '运行', iconColor, () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('尚未配置隔离代码执行服务，已阻止在浏览器中直接执行。')),
                  );
                }),
              ],
            ),
          ),
          if (_editing)
            SelectionContainer.disabled(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  return Container(
                    color: codeBg,
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: ConstrainedBox(
                        constraints: BoxConstraints(
                          minWidth: constraints.maxWidth,
                        ),
                        child: IntrinsicWidth(
                          child: TextField(
                            controller: _controller,
                            minLines: 4,
                            maxLines: null,
                            keyboardType: TextInputType.multiline,
                            onChanged: (_) => setState(() {}),
                            style: TextStyle(
                              color: baseCodeColor,
                              fontFamily: 'JetBrainsMono',
                              fontSize: 14,
                              height: 1.65,
                            ),
                            cursorWidth: 2,
                            decoration: const InputDecoration(
                              isCollapsed: true,
                              filled: false,
                              border: InputBorder.none,
                              enabledBorder: InputBorder.none,
                              focusedBorder: InputBorder.none,
                              contentPadding: EdgeInsets.all(14),
                            ),
                          ),
                        ),
                      ),
                    ),
                  );
                },
              ),
            )
          else
            LayoutBuilder(
              builder: (context, constraints) {
                return SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minWidth: constraints.maxWidth),
                    child: Container(
                      color: codeBg,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 14,
                      ),
                      child: Text.rich(
                        TextSpan(
                          style: TextStyle(
                            color: baseCodeColor,
                            fontFamily: 'JetBrainsMono',
                            fontSize: 14,
                            height: 1.65,
                          ),
                          children: _highlightCode(
                            _controller.text,
                            widget.language,
                            dark: dark,
                          ),
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
        ],
      ),
    );
  }

  Widget _action(
    IconData icon,
    String tooltip,
    Color color,
    VoidCallback onPressed,
  ) {
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      icon: Icon(icon, size: 16, color: color),
    );
  }
}

const _codeTheme = <String, TextStyle>{
  // 项目只内置了 JetBrains Mono Regular。不要对 token 使用合成斜体或不同
  // 字重，否则 Flutter Web 的编辑选择层会和实际 glyph 度量发生偏移。
  'comment': TextStyle(color: Color(0xFF7F848E)),
  'quote': TextStyle(color: Color(0xFF7F848E)),
  'keyword': TextStyle(color: Color(0xFFC678DD)),
  'selector-tag': TextStyle(color: Color(0xFFE06C75)),
  'type': TextStyle(color: Color(0xFFE5C07B)),
  'literal': TextStyle(color: Color(0xFF56B6C2)),
  'number': TextStyle(color: Color(0xFFD19A66)),
  'string': TextStyle(color: Color(0xFF98C379)),
  'regexp': TextStyle(color: Color(0xFF98C379)),
  'title': TextStyle(color: Color(0xFF61AFEF)),
  'name': TextStyle(color: Color(0xFFE06C75)),
  'function': TextStyle(color: Color(0xFF61AFEF)),
  'params': TextStyle(color: Color(0xFFABB2BF)),
  'built_in': TextStyle(color: Color(0xFF56B6C2)),
  'symbol': TextStyle(color: Color(0xFF56B6C2)),
  'meta': TextStyle(color: Color(0xFF61AFEF)),
  'meta-keyword': TextStyle(color: Color(0xFFC678DD)),
  'meta-string': TextStyle(color: Color(0xFF98C379)),
  'attr': TextStyle(color: Color(0xFFD19A66)),
  'attribute': TextStyle(color: Color(0xFFD19A66)),
  'variable': TextStyle(color: Color(0xFFE06C75)),
  'template-variable': TextStyle(color: Color(0xFFE06C75)),
};

// One Light 配色，浅色主题下的代码高亮（与上表 token 一一对应）
const _codeThemeLight = <String, TextStyle>{
  'comment': TextStyle(color: Color(0xFFA0A1A7)),
  'quote': TextStyle(color: Color(0xFFA0A1A7)),
  'keyword': TextStyle(color: Color(0xFFA626A4)),
  'selector-tag': TextStyle(color: Color(0xFFE45649)),
  'type': TextStyle(color: Color(0xFFC18401)),
  'literal': TextStyle(color: Color(0xFF0184BC)),
  'number': TextStyle(color: Color(0xFF986801)),
  'string': TextStyle(color: Color(0xFF50A14F)),
  'regexp': TextStyle(color: Color(0xFF50A14F)),
  'title': TextStyle(color: Color(0xFF4078F2)),
  'name': TextStyle(color: Color(0xFFE45649)),
  'function': TextStyle(color: Color(0xFF4078F2)),
  'params': TextStyle(color: Color(0xFF383A42)),
  'built_in': TextStyle(color: Color(0xFF0184BC)),
  'symbol': TextStyle(color: Color(0xFF0184BC)),
  'meta': TextStyle(color: Color(0xFF4078F2)),
  'meta-keyword': TextStyle(color: Color(0xFFA626A4)),
  'meta-string': TextStyle(color: Color(0xFF50A14F)),
  'attr': TextStyle(color: Color(0xFF986801)),
  'attribute': TextStyle(color: Color(0xFF986801)),
  'variable': TextStyle(color: Color(0xFFE45649)),
  'template-variable': TextStyle(color: Color(0xFFE45649)),
};

List<TextSpan> _highlightCode(
  String source,
  String language, {
  required bool dark,
}) {
  final nodes =
      highlight.parse(source, language: language).nodes ?? const <Node>[];
  return _convertHighlightNodes(nodes, dark ? _codeTheme : _codeThemeLight);
}

List<TextSpan> _convertHighlightNodes(
  List<Node> nodes,
  Map<String, TextStyle> theme,
) {
  return nodes.map((node) {
    final style = node.className == null ? null : theme[node.className!];
    if (node.value != null) return TextSpan(text: node.value, style: style);
    return TextSpan(
      style: style,
      children: _convertHighlightNodes(node.children ?? const <Node>[], theme),
    );
  }).toList();
}

class _HighlightEditingController extends TextEditingController {
  _HighlightEditingController({required super.text, required this.language});

  String language;
  bool dark = true;

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    return TextSpan(
      style: style,
      children: _highlightCode(text, language, dark: dark),
    );
  }
}
