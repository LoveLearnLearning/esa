import 'dart:async';
import 'dart:js_interop';
import 'dart:typed_data';

import 'package:flutter/widgets.dart';
import 'package:web/web.dart' as web;

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

class _WebAttachmentPasteListener implements AttachmentPasteListener {
  _WebAttachmentPasteListener({
    required this.focusNode,
    required this.onAttachment,
  }) {
    _listener = ((web.Event event) {
      if (!focusNode.hasFocus) return;
      // This listener is registered specifically for the `paste` event.
      final files = (event as web.ClipboardEvent).clipboardData?.files;
      if (files == null || files.length == 0) return;
      final file = files.item(0);
      if (file != null) unawaited(_read(file));
    }).toJS;
    web.document.addEventListener('paste', _listener);
  }

  final FocusNode focusNode;
  final PastedAttachmentHandler onAttachment;
  late final web.EventListener _listener;
  bool _disposed = false;

  Future<void> _read(web.File file) async {
    try {
      final buffer = await file.arrayBuffer().toDart;
      if (_disposed) return;
      final bytes = Uint8List.view(buffer.toDart);
      final filename = file.name.trim().isEmpty
          ? 'clipboard-${DateTime.now().millisecondsSinceEpoch}${_extensionFor(file.type)}'
          : file.name;
      await onAttachment(
        PastedAttachment(
          filename: filename,
          bytes: bytes,
          mediaType: file.type,
        ),
      );
    } catch (_) {
      // The composer reports failed uploads in the same path as file picker.
    }
  }

  @override
  void dispose() {
    _disposed = true;
    web.document.removeEventListener('paste', _listener);
  }
}

AttachmentPasteListener listenForPastedAttachment({
  required FocusNode focusNode,
  required PastedAttachmentHandler onAttachment,
}) => _WebAttachmentPasteListener(
  focusNode: focusNode,
  onAttachment: onAttachment,
);

String _extensionFor(String mediaType) => switch (mediaType.toLowerCase()) {
  'image/png' => '.png',
  'image/jpeg' => '.jpg',
  'image/webp' => '.webp',
  'image/gif' => '.gif',
  'application/pdf' => '.pdf',
  'text/plain' => '.txt',
  'text/csv' => '.csv',
  _ => '.bin',
};
