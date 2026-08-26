import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

class PdfAttachmentViewer extends StatelessWidget {
  const PdfAttachmentViewer({
    super.key,
    required this.bytes,
    required this.mediaType,
    this.page,
    this.searchText,
  });

  final Uint8List bytes;
  final String mediaType;
  final int? page;
  final String? searchText;

  @override
  Widget build(BuildContext context) =>
      const Center(child: Icon(LucideIcons.fileText, size: 42));
}
