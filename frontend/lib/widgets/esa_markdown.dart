import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_markdown_plus_latex/flutter_markdown_plus_latex.dart';
import 'package:highlight/highlight.dart' show Node, highlight;
import 'package:markdown/markdown.dart' as md;

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

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

class EsaMarkdown extends StatelessWidget {
  const EsaMarkdown({super.key, required this.data, this.selectable = false});

  final String data;
  final bool selectable;

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
      data: normalizeMarkdownLatex(data),
      // A SelectionArea provides one continuous selection region for the
      // complete Markdown document. MarkdownBody's selectable mode creates
      // separate SelectableText widgets for individual blocks, which makes
      // drag selection across paragraphs unreliable on Flutter Web.
      selectable: false,
      builders: {
        'latex': LatexElementBuilder(textStyle: bodyStyle),
        'pre': _CodeBlockBuilder(),
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
          fontFamily: 'monospace',
          fontSize: 13,
          color: context.scheme.onSurface,
          backgroundColor: context.n.n200,
        ),
        codeblockDecoration: BoxDecoration(
          color: context.n.n100,
          border: Border.all(color: context.n.divider),
          borderRadius: BorderRadius.circular(EsaRadii.toolCard),
        ),
        a: bodyStyle?.copyWith(
          color: EsaColors.accent,
          decoration: TextDecoration.underline,
        ),
      ),
    );

    return selectable ? SelectionArea(child: markdown) : markdown;
  }
}

class _CodeBlockBuilder extends MarkdownElementBuilder {
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
    return _EditableCodeBlock(code: element.textContent, language: language);
  }
}

class _EditableCodeBlock extends StatefulWidget {
  const _EditableCodeBlock({required this.code, required this.language});

  final String code;
  final String language;

  @override
  State<_EditableCodeBlock> createState() => _EditableCodeBlockState();
}

class _EditableCodeBlockState extends State<_EditableCodeBlock> {
  late final _HighlightEditingController _controller;
  bool _editing = false;
  bool _copied = false;

  @override
  void initState() {
    super.initState();
    _controller = _HighlightEditingController(
      text: widget.code.trimRight(),
      language: widget.language,
    );
  }

  @override
  void didUpdateWidget(covariant _EditableCodeBlock oldWidget) {
    super.didUpdateWidget(oldWidget);
    _controller.language = widget.language;
    if (!_editing && widget.code != oldWidget.code) {
      final updatedCode = widget.code.trimRight();
      _controller.value = TextEditingValue(
        text: updatedCode,
        selection: TextSelection.collapsed(offset: updatedCode.length),
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
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFF171717),
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.toolCard),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.only(left: 12, right: 4),
            color: const Color(0xFF222222),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    widget.language,
                    style: const TextStyle(
                      color: Color(0xFFAAAAAA),
                      fontSize: 11,
                      fontFamily: 'JetBrainsMono',
                    ),
                  ),
                ),
                _action(
                  _editing ? Icons.visibility_outlined : Icons.edit_outlined,
                  _editing ? '预览' : '编辑',
                  () => setState(() => _editing = !_editing),
                ),
                _action(
                  _copied ? Icons.check : Icons.copy_outlined,
                  '复制',
                  () async {
                    await Clipboard.setData(
                      ClipboardData(text: _controller.text),
                    );
                    if (!mounted) return;
                    setState(() => _copied = true);
                    Future<void>.delayed(
                      const Duration(milliseconds: 1200),
                      () {
                        if (mounted) setState(() => _copied = false);
                      },
                    );
                  },
                ),
                _action(Icons.play_arrow_rounded, '运行', () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('尚未配置隔离代码执行服务，已阻止在浏览器中直接执行。')),
                  );
                }),
              ],
            ),
          ),
          if (_editing)
            TextField(
              controller: _controller,
              minLines: 4,
              maxLines: null,
              onChanged: (_) => setState(() {}),
              style: const TextStyle(
                color: Colors.white,
                fontFamily: 'JetBrainsMono',
                fontSize: 14,
                height: 1.65,
              ),
              decoration: const InputDecoration(
                border: InputBorder.none,
                contentPadding: EdgeInsets.all(14),
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
                      color: const Color(0xFF282C34),
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 14,
                      ),
                      child: SelectableText.rich(
                        TextSpan(
                          style: const TextStyle(
                            color: Color(0xFFABB2BF),
                            fontFamily: 'JetBrainsMono',
                            fontSize: 14,
                            height: 1.65,
                          ),
                          children: _highlightCode(
                            _controller.text,
                            widget.language,
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

  Widget _action(IconData icon, String tooltip, VoidCallback onPressed) {
    return IconButton(
      tooltip: tooltip,
      onPressed: onPressed,
      icon: Icon(icon, size: 16, color: const Color(0xFFCCCCCC)),
    );
  }
}

const _codeTheme = <String, TextStyle>{
  'comment': TextStyle(color: Color(0xFF7F848E), fontStyle: FontStyle.italic),
  'quote': TextStyle(color: Color(0xFF7F848E), fontStyle: FontStyle.italic),
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

List<TextSpan> _highlightCode(String source, String language) {
  final nodes =
      highlight.parse(source, language: language).nodes ?? const <Node>[];
  return _convertHighlightNodes(nodes);
}

List<TextSpan> _convertHighlightNodes(List<Node> nodes) {
  return nodes.map((node) {
    final style = node.className == null ? null : _codeTheme[node.className!];
    if (node.value != null) return TextSpan(text: node.value, style: style);
    return TextSpan(
      style: style,
      children: _convertHighlightNodes(node.children ?? const <Node>[]),
    );
  }).toList();
}

class _HighlightEditingController extends TextEditingController {
  _HighlightEditingController({required super.text, required this.language});

  String language;

  @override
  TextSpan buildTextSpan({
    required BuildContext context,
    TextStyle? style,
    required bool withComposing,
  }) {
    return TextSpan(style: style, children: _highlightCode(text, language));
  }
}
