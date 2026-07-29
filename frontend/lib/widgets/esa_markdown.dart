import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_markdown_plus_latex/flutter_markdown_plus_latex.dart';
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

    return MarkdownBody(
      data: normalizeMarkdownLatex(data),
      selectable: selectable,
      builders: {'latex': LatexElementBuilder(textStyle: bodyStyle)},
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
  }
}
