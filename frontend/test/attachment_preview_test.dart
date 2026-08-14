import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/models/models.dart';
import 'package:frontend/theme/esa_theme.dart';
import 'package:frontend/widgets/attachment_preview/attachment_preview.dart';

void main() {
  const attachment = DocumentAttachment(
    id: 'attachment-1',
    filename: 'research-notes.md',
    mode: 'pending',
    tokenCount: 0,
    elementCount: 0,
    pageCount: 0,
    validationStatus: 'ready',
    qualityIssueCount: 0,
    mediaType: 'text/markdown',
    sizeBytes: 24,
  );

  Widget app(Widget child) => MaterialApp(
    theme: esaTheme(brightness: Brightness.dark),
    home: Scaffold(body: child),
  );

  testWidgets('text attachment is rendered in the preview pane', (
    tester,
  ) async {
    await tester.pumpWidget(
      app(
        AttachmentPreviewPane(
          attachment: attachment,
          content: AttachmentContent(
            bytes: Uint8List.fromList(utf8.encode('# 研究结论\n\n有效内容')),
            mediaType: 'text/markdown',
            filename: attachment.filename,
          ),
          loading: false,
          onClose: () {},
          onRetry: () {},
        ),
      ),
    );

    expect(find.text('research-notes.md'), findsOneWidget);
    expect(find.textContaining('研究结论'), findsOneWidget);
    expect(find.byTooltip('下载附件'), findsOneWidget);
    expect(find.byTooltip('关闭预览'), findsOneWidget);
  });

  testWidgets('failed attachment preview offers retry', (tester) async {
    var retried = false;
    await tester.pumpWidget(
      app(
        AttachmentPreviewPane(
          attachment: attachment,
          content: null,
          loading: false,
          error: '请求失败',
          onClose: () {},
          onRetry: () => retried = true,
        ),
      ),
    );

    await tester.tap(find.text('重新加载'));
    expect(retried, isTrue);
  });
}
