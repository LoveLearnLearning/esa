import 'dart:typed_data';

import 'package:flutter/widgets.dart';

class PastedAttachment {
  const PastedAttachment({
    required this.filename,
    required this.bytes,
    this.mediaType = '',
  });

  final String filename;
  final Uint8List bytes;
  final String mediaType;
}

typedef PastedAttachmentHandler = Future<void> Function(PastedAttachment file);

abstract class AttachmentPasteListener {
  void dispose();
}

class _NoopAttachmentPasteListener implements AttachmentPasteListener {
  @override
  void dispose() {}
}

AttachmentPasteListener listenForPastedAttachment({
  required FocusNode focusNode,
  required PastedAttachmentHandler onAttachment,
}) => _NoopAttachmentPasteListener();
