import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../api/api_client.dart';
import '../../models/models.dart';
import '../../theme/esa_context.dart';
import '../../theme/esa_theme.dart';
import '../../utils/download_attachment.dart';
import 'pdf_attachment_viewer.dart';

class AttachmentPreviewPane extends StatefulWidget {
  const AttachmentPreviewPane({
    super.key,
    required this.attachment,
    required this.content,
    required this.loading,
    required this.onClose,
    required this.onRetry,
    this.error,
    this.compact = false,
  });

  final DocumentAttachment attachment;
  final AttachmentContent? content;
  final bool loading;
  final String? error;
  final bool compact;
  final VoidCallback onClose;
  final VoidCallback onRetry;

  @override
  State<AttachmentPreviewPane> createState() => _AttachmentPreviewPaneState();
}

class _AttachmentPreviewPaneState extends State<AttachmentPreviewPane> {
  bool _downloading = false;

  Future<void> _download() async {
    final content = widget.content;
    if (content == null || _downloading) return;
    setState(() => _downloading = true);
    final saved = await downloadAttachment(
      bytes: content.bytes,
      filename: content.filename,
      mediaType: content.mediaType,
    );
    if (!mounted) return;
    setState(() => _downloading = false);
    if (!saved) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('无法开始下载，请重试。')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final content = widget.content;
    return ColoredBox(
      color: context.scheme.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _PreviewHeader(
            attachment: widget.attachment,
            onClose: widget.onClose,
            onDownload: content == null || _downloading ? null : _download,
            downloading: _downloading,
          ),
          Expanded(
            child: widget.loading
                ? const Center(child: CircularProgressIndicator())
                : widget.error != null
                ? _PreviewFailure(error: widget.error!, onRetry: widget.onRetry)
                : content == null
                ? const SizedBox.shrink()
                : _PreviewContent(
                    content: content,
                    attachment: widget.attachment,
                  ),
          ),
          Container(
            height: 28,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            alignment: Alignment.centerRight,
            color: context.n.n100,
            child: Text(
              _attachmentMeta(widget.attachment),
              style: TextStyle(fontSize: 10.5, color: context.n.n600),
            ),
          ),
        ],
      ),
    );
  }
}

class _PreviewHeader extends StatelessWidget {
  const _PreviewHeader({
    required this.attachment,
    required this.onClose,
    required this.onDownload,
    required this.downloading,
  });

  final DocumentAttachment attachment;
  final VoidCallback onClose;
  final VoidCallback? onDownload;
  final bool downloading;

  @override
  Widget build(BuildContext context) => Container(
    height: 54,
    padding: const EdgeInsets.only(left: 14, right: 6),
    decoration: BoxDecoration(
      border: Border(bottom: BorderSide(color: context.n.divider)),
    ),
    child: Row(
      children: [
        Icon(_attachmentIcon(attachment), size: 18, color: EsaColors.accent),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                attachment.filename,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.texts.titleSmall,
              ),
              Text(
                attachment.modeLabel,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 10.5, color: context.n.n600),
              ),
            ],
          ),
        ),
        IconButton(
          tooltip: '下载附件',
          onPressed: onDownload,
          icon: downloading
              ? const SizedBox.square(
                  dimension: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(LucideIcons.download, size: 18),
        ),
        IconButton(
          tooltip: '关闭预览',
          onPressed: onClose,
          icon: const Icon(LucideIcons.x, size: 18),
        ),
      ],
    ),
  );
}

class _PreviewContent extends StatelessWidget {
  const _PreviewContent({required this.content, required this.attachment});

  final AttachmentContent content;
  final DocumentAttachment attachment;

  bool get _image => content.mediaType.startsWith('image/');
  bool get _pdf =>
      content.mediaType == 'application/pdf' || attachment.extension == 'pdf';
  bool get _text =>
      content.mediaType.startsWith('text/') ||
      const {
        'md',
        'markdown',
        'txt',
        'csv',
        'json',
        'xml',
        'yaml',
        'yml',
        'py',
        'js',
        'ts',
        'dart',
        'java',
        'c',
        'cpp',
        'h',
        'html',
        'css',
        'sql',
        'sh',
      }.contains(attachment.extension);

  @override
  Widget build(BuildContext context) {
    if (_image) {
      return InteractiveViewer(
        minScale: .5,
        maxScale: 4,
        child: Center(
          child: Image.memory(
            content.bytes,
            fit: BoxFit.contain,
            errorBuilder: (_, _, _) => const _UnsupportedPreview(),
          ),
        ),
      );
    }
    if (_pdf) {
      return PdfAttachmentViewer(
        bytes: content.bytes,
        mediaType: content.mediaType,
      );
    }
    if (_text) {
      final text = utf8.decode(content.bytes, allowMalformed: true);
      return SelectionArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: SelectableText(
            text,
            style: const TextStyle(
              fontFamily: 'JetBrainsMono',
              fontSize: 12.5,
              height: 1.55,
            ),
          ),
        ),
      );
    }
    return const _UnsupportedPreview();
  }
}

class _PreviewFailure extends StatelessWidget {
  const _PreviewFailure({required this.error, required this.onRetry});

  final String error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(LucideIcons.triangleAlert, size: 30),
          const SizedBox(height: 12),
          Text(error, textAlign: TextAlign.center),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: onRetry,
            icon: const Icon(LucideIcons.rotateCw, size: 16),
            label: const Text('重新加载'),
          ),
        ],
      ),
    ),
  );
}

class _UnsupportedPreview extends StatelessWidget {
  const _UnsupportedPreview();

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(LucideIcons.file, size: 34),
          const SizedBox(height: 12),
          Text('此文件格式暂不支持在线预览。', style: context.texts.titleSmall),
          const SizedBox(height: 6),
          Text('可使用右上角下载按钮在本地打开。', style: context.texts.bodySmall),
        ],
      ),
    ),
  );
}

IconData _attachmentIcon(DocumentAttachment attachment) =>
    attachment.mediaType.startsWith('image/')
    ? LucideIcons.image
    : attachment.extension == 'pdf'
    ? LucideIcons.fileText
    : attachment.extension == 'csv' || attachment.extension == 'xlsx'
    ? LucideIcons.sheet
    : attachment.extension == 'docx'
    ? LucideIcons.fileText
    : attachment.extension == 'pptx'
    ? LucideIcons.presentation
    : LucideIcons.file;

String _attachmentMeta(DocumentAttachment attachment) {
  final mb = attachment.sizeBytes / (1024 * 1024);
  final size = attachment.sizeBytes <= 0
      ? ''
      : mb >= 1
      ? '${mb.toStringAsFixed(1)} MB'
      : '${(attachment.sizeBytes / 1024).ceil()} KB';
  final pages = attachment.pageCount > 0 ? '${attachment.pageCount} 页' : '';
  return [
    attachment.extension.toUpperCase(),
    size,
    pages,
  ].where((part) => part.isNotEmpty).join(' · ');
}
