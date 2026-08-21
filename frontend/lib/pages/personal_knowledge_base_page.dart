import 'dart:async';
import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/attachment_preview/pdf_attachment_viewer.dart';

class PersonalKnowledgeBasePage extends StatefulWidget {
  const PersonalKnowledgeBasePage({super.key});

  @override
  State<PersonalKnowledgeBasePage> createState() =>
      _PersonalKnowledgeBasePageState();
}

class _PersonalKnowledgeBasePageState extends State<PersonalKnowledgeBasePage> {
  PersonalKnowledgeBase _snapshot = const PersonalKnowledgeBase.empty();
  KnowledgeBaseFile? _selected;
  Timer? _pollTimer;
  bool _loading = true;
  bool _uploading = false;
  String? _error;
  String _query = '';
  AttachmentContent? _previewContent;
  RequestCancellation? _previewCancellation;
  bool _previewLoading = false;
  String? _previewError;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loading && _error == null) unawaited(_load());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _previewCancellation?.cancel();
    super.dispose();
  }

  Future<void> _load({bool quiet = false}) async {
    if (!quiet && mounted) setState(() => _loading = true);
    try {
      final value = await AppScope.of(context).api.getPersonalKnowledgeBase();
      if (!mounted) return;
      setState(() {
        _snapshot = value;
        _loading = false;
        _error = null;
        if (_selected != null) {
          _selected = value.files
              .where((item) => item.id == _selected!.id)
              .firstOrNull;
        }
      });
      _schedulePolling();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.detail;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '知识库加载失败，请稍后重试';
      });
    }
  }

  void _schedulePolling() {
    _pollTimer?.cancel();
    if (!_snapshot.isBuilding) return;
    _pollTimer = Timer(const Duration(seconds: 2), () {
      if (mounted) unawaited(_load(quiet: true));
    });
  }

  Future<void> _pickFiles() async {
    if (_uploading) return;
    try {
      final result = await FilePicker.pickFiles(
        allowMultiple: true,
        type: FileType.custom,
        allowedExtensions: const [
          'pdf',
          'doc',
          'docx',
          'ppt',
          'pptx',
          'xls',
          'xlsx',
          'csv',
          'txt',
          'md',
          'json',
          'png',
          'jpg',
          'jpeg',
          'webp',
        ],
        withData: false,
        withReadStream: kIsWeb,
        cancelUploadOnWindowBlur: false,
      );
      if (result == null || result.files.isEmpty || !mounted) return;
      final files = result.files
          .map(
            (file) => KnowledgeBaseUploadFile(
              filename: file.name,
              stream: file.readStream ?? file.xFile.openRead(),
              length: file.size,
            ),
          )
          .toList();
      setState(() => _uploading = true);
      final value = await AppScope.of(
        context,
      ).api.uploadPersonalKnowledgeBaseFiles(files);
      if (!mounted) return;
      setState(() {
        _snapshot = value;
        _uploading = false;
        _error = null;
      });
      _schedulePolling();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _uploading = false);
      _showError(error.detail);
    } catch (_) {
      if (!mounted) return;
      setState(() => _uploading = false);
      _showError('文件选择或上传失败，请重试');
    }
  }

  void _selectFile(KnowledgeBaseFile file) {
    _previewCancellation?.cancel();
    final cancellation = RequestCancellation();
    setState(() {
      _selected = file;
      _previewContent = null;
      _previewError = null;
      _previewLoading = true;
      _previewCancellation = cancellation;
    });
    unawaited(_loadPreview(file, cancellation));
  }

  Future<void> _loadPreview(
    KnowledgeBaseFile file,
    RequestCancellation cancellation,
  ) async {
    try {
      final content = await AppScope.of(
        context,
      ).api.fetchPersonalKnowledgeBasePreview(file, cancellation: cancellation);
      if (!mounted || cancellation.isCancelled || _selected?.id != file.id) {
        return;
      }
      setState(() {
        _previewContent = content;
        _previewLoading = false;
        _previewError = null;
      });
    } on ApiException catch (error) {
      if (!mounted || cancellation.isCancelled || _selected?.id != file.id) {
        return;
      }
      setState(() {
        _previewLoading = false;
        _previewError = error.detail;
      });
    } catch (_) {
      if (!mounted || cancellation.isCancelled || _selected?.id != file.id) {
        return;
      }
      setState(() {
        _previewLoading = false;
        _previewError = '文件预览加载失败，请重试';
      });
    }
  }

  void _closePreview() {
    _previewCancellation?.cancel();
    setState(() {
      _selected = null;
      _previewContent = null;
      _previewError = null;
      _previewLoading = false;
      _previewCancellation = null;
    });
  }

  void _retryPreview() {
    final selected = _selected;
    if (selected == null) return;
    _selectFile(selected);
  }

  Future<void> _deleteFile(KnowledgeBaseFile file) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('移出知识库'),
        content: Text('确定移除“${file.filename}”及其索引吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('移除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await AppScope.of(context).api.deletePersonalKnowledgeBaseFile(file.id);
      if (!mounted) return;
      if (_selected?.id == file.id) {
        _previewCancellation?.cancel();
        setState(() {
          _selected = null;
          _previewContent = null;
          _previewLoading = false;
          _previewError = null;
        });
      }
      await _load(quiet: true);
    } on ApiException catch (error) {
      if (mounted) _showError(error.detail);
    }
  }

  Future<void> _rebuild() async {
    try {
      final value = await AppScope.of(
        context,
      ).api.rebuildPersonalKnowledgeBase();
      if (!mounted) return;
      setState(() => _snapshot = value);
      _schedulePolling();
    } on ApiException catch (error) {
      if (mounted) _showError(error.detail);
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  List<KnowledgeBaseFile> get _visibleFiles {
    final normalized = _query.trim().toLowerCase();
    if (normalized.isEmpty) return _snapshot.files;
    return _snapshot.files
        .where((file) => file.filename.toLowerCase().contains(normalized))
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 760;
    return ColoredBox(
      key: const ValueKey('personal-knowledge-base-page'),
      color: context.scheme.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _KnowledgeBaseHeader(
            snapshot: _snapshot,
            uploading: _uploading,
            onAdd: _pickFiles,
            onRebuild: _snapshot.files.isEmpty ? null : _rebuild,
          ),
          if (_loading) const LinearProgressIndicator(minHeight: 2),
          Expanded(
            child: _error != null && _snapshot.files.isEmpty
                ? _LoadFailure(error: _error!, onRetry: _load)
                : compact
                ? _mobileBody()
                : Row(
                    children: [
                      SizedBox(width: 340, child: _fileList()),
                      VerticalDivider(width: 1, color: context.n.divider),
                      Expanded(child: _previewPane()),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _mobileBody() {
    if (_selected != null) {
      return Column(
        children: [
          Container(
            height: 44,
            alignment: Alignment.centerLeft,
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: context.n.divider)),
            ),
            child: TextButton.icon(
              onPressed: _closePreview,
              icon: const Icon(LucideIcons.chevronLeft, size: 17),
              label: const Text('返回文件列表'),
            ),
          ),
          Expanded(child: _previewPane()),
        ],
      );
    }
    return _fileList();
  }

  Widget _fileList() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
        child: TextField(
          key: const ValueKey('knowledge-base-search'),
          onChanged: (value) => setState(() => _query = value),
          decoration: const InputDecoration(
            hintText: '搜索知识库文件',
            prefixIcon: Icon(LucideIcons.search, size: 17),
            isDense: true,
          ),
        ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 2, 16, 9),
        child: Row(
          children: [
            Expanded(child: Text('文件', style: context.texts.labelSmall)),
            Text('${_visibleFiles.length}', style: context.texts.labelSmall),
          ],
        ),
      ),
      Expanded(
        child: _visibleFiles.isEmpty
            ? _EmptyFiles(onAdd: _pickFiles, query: _query)
            : ListView.separated(
                padding: const EdgeInsets.fromLTRB(8, 0, 8, 16),
                itemCount: _visibleFiles.length,
                separatorBuilder: (_, _) => const SizedBox(height: 2),
                itemBuilder: (context, index) {
                  final file = _visibleFiles[index];
                  return _KnowledgeFileRow(
                    key: ValueKey('knowledge-file-${file.id}'),
                    file: file,
                    selected: file.id == _selected?.id,
                    onTap: () => _selectFile(file),
                    onDelete: () => _deleteFile(file),
                  );
                },
              ),
      ),
    ],
  );

  Widget _previewPane() {
    final selected = _selected;
    if (selected == null) return const _PreviewPlaceholder();
    return _PersonalPreviewPane(
      key: ValueKey('knowledge-preview-${selected.id}'),
      file: selected,
      content: _previewContent,
      loading: _previewLoading,
      error: _previewError,
      onRetry: _retryPreview,
      onClose: _closePreview,
    );
  }
}

class _PersonalPreviewPane extends StatelessWidget {
  const _PersonalPreviewPane({
    super.key,
    required this.file,
    required this.content,
    required this.loading,
    required this.error,
    required this.onRetry,
    required this.onClose,
  });

  final KnowledgeBaseFile file;
  final AttachmentContent? content;
  final bool loading;
  final String? error;
  final VoidCallback onRetry;
  final VoidCallback onClose;

  Widget _body(BuildContext context) {
    if (loading) return const Center(child: CircularProgressIndicator());
    if (error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(LucideIcons.triangleAlert, size: 30),
              const SizedBox(height: 12),
              Text(error!, textAlign: TextAlign.center),
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
    final value = content;
    if (value == null) return const SizedBox.shrink();
    if (value.mediaType.startsWith('image/')) {
      return InteractiveViewer(
        minScale: .5,
        maxScale: 4,
        child: Center(
          child: Image.memory(
            value.bytes,
            key: const ValueKey('knowledge-base-image-preview'),
            fit: BoxFit.contain,
            errorBuilder: (_, _, _) => const Center(child: Text('图片预览无法解码')),
          ),
        ),
      );
    }
    if (value.mediaType.startsWith('application/pdf')) {
      return PdfAttachmentViewer(
        bytes: value.bytes,
        mediaType: value.mediaType,
      );
    }
    final text = utf8.decode(value.bytes, allowMalformed: true);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!const {'txt', 'md', 'csv', 'json'}.contains(file.extension))
          Container(
            key: const ValueKey('knowledge-base-derived-preview-label'),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            color: context.n.n100,
            child: Text(
              '${file.extension.toUpperCase()} 解析文本预览',
              style: TextStyle(fontSize: 11, color: context.n.n600),
            ),
          ),
        Expanded(
          child: SelectionArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(18),
              child: SelectableText(
                text,
                key: const ValueKey('knowledge-base-text-preview'),
                style: const TextStyle(
                  fontFamily: 'JetBrainsMono',
                  fontSize: 12.5,
                  height: 1.55,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Container(
        height: 52,
        padding: const EdgeInsets.only(left: 14, right: 6),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: context.n.divider)),
        ),
        child: Row(
          children: [
            Icon(_fileIcon(file), size: 18, color: EsaColors.accent),
            const SizedBox(width: 9),
            Expanded(
              child: Text(
                file.filename,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: context.texts.titleSmall,
              ),
            ),
            IconButton(
              tooltip: '关闭',
              onPressed: onClose,
              icon: const Icon(LucideIcons.x, size: 18),
            ),
          ],
        ),
      ),
      Expanded(child: _body(context)),
    ],
  );
}

class _KnowledgeBaseHeader extends StatelessWidget {
  const _KnowledgeBaseHeader({
    required this.snapshot,
    required this.uploading,
    required this.onAdd,
    required this.onRebuild,
  });

  final PersonalKnowledgeBase snapshot;
  final bool uploading;
  final VoidCallback onAdd;
  final VoidCallback? onRebuild;

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 620;
    final status = switch (snapshot.status) {
      KnowledgeBaseBuildStatus.queued => '等待构建',
      KnowledgeBaseBuildStatus.building => '正在构建',
      KnowledgeBaseBuildStatus.ready => '索引就绪',
      KnowledgeBaseBuildStatus.failed => '构建失败',
      KnowledgeBaseBuildStatus.idle => snapshot.files.isEmpty ? '等待文件' : '未构建',
    };
    return Container(
      padding: EdgeInsets.fromLTRB(narrow ? 16 : 24, 18, narrow ? 12 : 20, 16),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.n.divider)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('个人知识库', style: context.texts.headlineSmall),
                    const SizedBox(height: 4),
                    Text('管理用于检索与引用的个人资料', style: context.texts.bodySmall),
                  ],
                ),
              ),
              if (onRebuild != null && !narrow)
                IconButton(
                  tooltip: '重新构建索引',
                  onPressed: snapshot.isBuilding ? null : onRebuild,
                  icon: const Icon(LucideIcons.refreshCw, size: 18),
                ),
              const SizedBox(width: 4),
              FilledButton.icon(
                key: const ValueKey('knowledge-base-add-files'),
                onPressed: uploading ? null : onAdd,
                icon: uploading
                    ? const SizedBox.square(
                        dimension: 15,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      )
                    : const Icon(LucideIcons.filePlus2, size: 17),
                label: Text(uploading ? '上传中' : '添加文件'),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Wrap(
            spacing: 28,
            runSpacing: 10,
            children: [
              _Metric(label: '文件', value: '${snapshot.fileCount}'),
              _Metric(label: 'CHUNKS', value: '${snapshot.chunkCount}'),
              _Metric(label: 'INDEX', value: '${snapshot.indexCount}'),
            ],
          ),
          const SizedBox(height: 15),
          Row(
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: LinearProgressIndicator(
                    key: const ValueKey('knowledge-base-progress'),
                    value: snapshot.isBuilding
                        ? snapshot.progress
                        : snapshot.files.isEmpty
                        ? 0
                        : 1,
                    minHeight: 5,
                    backgroundColor: context.n.n200,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              SizedBox(
                width: 72,
                child: Text(
                  status,
                  textAlign: TextAlign.right,
                  style: TextStyle(fontSize: 11, color: context.n.n600),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 86,
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(value, style: context.texts.titleLarge),
        const SizedBox(height: 2),
        Text(label, style: context.texts.labelSmall),
      ],
    ),
  );
}

class _KnowledgeFileRow extends StatelessWidget {
  const _KnowledgeFileRow({
    super.key,
    required this.file,
    required this.selected,
    required this.onTap,
    required this.onDelete,
  });

  final KnowledgeBaseFile file;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) => Material(
    color: selected
        ? EsaColors.accent.withValues(alpha: .13)
        : Colors.transparent,
    borderRadius: BorderRadius.circular(6),
    child: ListTile(
      dense: true,
      contentPadding: const EdgeInsets.only(left: 10, right: 2),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      leading: Icon(
        _fileIcon(file),
        size: 18,
        color: selected ? EsaColors.accent : context.n.n600,
      ),
      title: Text(file.filename, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(
        _fileMeta(file),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: 10.5, color: context.n.n600),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _FileStatus(status: file.status),
          PopupMenuButton<String>(
            tooltip: '文件操作',
            icon: const Icon(LucideIcons.ellipsis, size: 16),
            onSelected: (value) {
              if (value == 'delete') onDelete();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'delete', child: Text('移出知识库')),
            ],
          ),
        ],
      ),
      onTap: onTap,
    ),
  );
}

class _FileStatus extends StatelessWidget {
  const _FileStatus({required this.status});
  final KnowledgeBaseBuildStatus status;

  @override
  Widget build(BuildContext context) {
    if (status == KnowledgeBaseBuildStatus.building ||
        status == KnowledgeBaseBuildStatus.queued) {
      return const SizedBox.square(
        dimension: 14,
        child: CircularProgressIndicator(strokeWidth: 1.6),
      );
    }
    return Icon(
      status == KnowledgeBaseBuildStatus.failed
          ? LucideIcons.circleAlert
          : LucideIcons.circleCheck,
      size: 14,
      color: status == KnowledgeBaseBuildStatus.failed
          ? context.scheme.error
          : context.n.n600,
    );
  }
}

class _EmptyFiles extends StatelessWidget {
  const _EmptyFiles({required this.onAdd, required this.query});
  final VoidCallback onAdd;
  final String query;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(LucideIcons.files, size: 28, color: context.n.n500),
          const SizedBox(height: 12),
          Text(query.trim().isEmpty ? '知识库中还没有文件' : '没有匹配的文件'),
          if (query.trim().isEmpty) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: onAdd,
              icon: const Icon(LucideIcons.plus, size: 16),
              label: const Text('添加第一批文件'),
            ),
          ],
        ],
      ),
    ),
  );
}

class _PreviewPlaceholder extends StatelessWidget {
  const _PreviewPlaceholder();

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(LucideIcons.fileSearch, size: 30, color: context.n.n500),
        const SizedBox(height: 12),
        Text('选择左侧文件进行预览', style: context.texts.titleSmall),
      ],
    ),
  );
}

class _LoadFailure extends StatelessWidget {
  const _LoadFailure({required this.error, required this.onRetry});
  final String error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(LucideIcons.triangleAlert, size: 28),
        const SizedBox(height: 10),
        Text(error),
        const SizedBox(height: 12),
        OutlinedButton.icon(
          onPressed: onRetry,
          icon: const Icon(LucideIcons.rotateCw, size: 16),
          label: const Text('重新加载'),
        ),
      ],
    ),
  );
}

IconData _fileIcon(KnowledgeBaseFile file) => switch (file.extension) {
  'pdf' || 'doc' || 'docx' => LucideIcons.fileText,
  'ppt' || 'pptx' => LucideIcons.presentation,
  'xls' || 'xlsx' || 'csv' => LucideIcons.sheet,
  'png' || 'jpg' || 'jpeg' || 'webp' => LucideIcons.image,
  _ => LucideIcons.file,
};

String _fileMeta(KnowledgeBaseFile file) {
  final size = file.sizeBytes >= 1024 * 1024
      ? '${(file.sizeBytes / (1024 * 1024)).toStringAsFixed(1)} MB'
      : '${(file.sizeBytes / 1024).ceil()} KB';
  return [
    file.extension.toUpperCase(),
    size,
    '${file.chunkCount} chunks',
    '${file.indexCount} index',
  ].where((item) => item.isNotEmpty).join(' · ');
}
