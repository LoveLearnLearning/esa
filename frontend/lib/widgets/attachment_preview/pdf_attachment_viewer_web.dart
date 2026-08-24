import 'dart:js_interop';
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

class PdfAttachmentViewer extends StatefulWidget {
  const PdfAttachmentViewer({
    super.key,
    required this.bytes,
    required this.mediaType,
    this.page,
  });

  final Uint8List bytes;
  final String mediaType;
  final int? page;

  @override
  State<PdfAttachmentViewer> createState() => _PdfAttachmentViewerState();
}

class _PdfAttachmentViewerState extends State<PdfAttachmentViewer> {
  static int _nextId = 0;
  late final String _viewType;
  late final String _url;

  @override
  void initState() {
    super.initState();
    _viewType = 'esa-pdf-preview-${_nextId++}';
    final blob = web.Blob(
      [widget.bytes.toJS].toJS,
      web.BlobPropertyBag(
        type: widget.mediaType.isEmpty ? 'application/pdf' : widget.mediaType,
      ),
    );
    _url = web.URL.createObjectURL(blob);
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      return web.HTMLIFrameElement()
        ..src = widget.page != null && widget.page! > 0
            ? '$_url#page=${widget.page}'
            : _url
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.border = '0';
    });
  }

  @override
  void dispose() {
    web.URL.revokeObjectURL(_url);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => HtmlElementView(viewType: _viewType);
}
