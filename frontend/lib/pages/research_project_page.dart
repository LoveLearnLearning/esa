import 'dart:convert';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/esa_markdown.dart';

class ResearchProjectPage extends StatefulWidget {
  const ResearchProjectPage({
    super.key,
    required this.project,
    required this.onOpenChat,
    this.embedded = false,
    this.onBack,
    this.onProjectUpdated,
  });

  final ResearchProject project;
  final VoidCallback onOpenChat;
  final bool embedded;
  final VoidCallback? onBack;
  final ValueChanged<ResearchProject>? onProjectUpdated;

  @override
  State<ResearchProjectPage> createState() => _ResearchProjectPageState();
}

class _ResearchProjectPageState extends State<ResearchProjectPage> {
  final _frontierQuery = TextEditingController();
  final _writingInstruction = TextEditingController();
  final _documentContent = TextEditingController();
  final _projectName = TextEditingController();
  final _projectDescription = TextEditingController();
  final _groupColumn = TextEditingController();
  final _metricColumn = TextEditingController();
  final _textColumn = TextEditingController();
  final _profileInstructions = TextEditingController();
  List<FrontierTrackingJob> _frontierJobs = const [];
  List<ResearchDocument> _documents = const [];
  List<ResearchDataset> _datasets = const [];
  ResearchDocument? _selectedDocument;
  ResearchDataset? _selectedDataset;
  ResearchAnalysisJob? _analysisJob;
  ResearchProjectProfile? _projectProfile;
  late ResearchProject _project;
  String _writingOperation = 'outline';
  String _analysisType = 'descriptive';
  bool _loading = true;
  bool _submitting = false;
  bool _documentSaving = false;
  bool _documentDirty = false;
  bool _projectSaving = false;
  String? _error;

  ApiClient get _api => AppScope.of(context).api;

  @override
  void initState() {
    super.initState();
    _project = widget.project;
    _projectName.text = _project.name;
    _projectDescription.text = _project.description;
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  void didUpdateWidget(covariant ResearchProjectPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.project.id != widget.project.id ||
        oldWidget.project.updatedAt != widget.project.updatedAt) {
      _project = widget.project;
      _projectName.text = _project.name;
      _projectDescription.text = _project.description;
    }
  }

  @override
  void dispose() {
    _frontierQuery.dispose();
    _writingInstruction.dispose();
    _documentContent.dispose();
    _projectName.dispose();
    _projectDescription.dispose();
    _groupColumn.dispose();
    _metricColumn.dispose();
    _textColumn.dispose();
    _profileInstructions.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final values = await Future.wait([
        _api.listFrontierJobs(_project.id),
        _api.listResearchDocuments(_project.id),
        _api.listResearchDatasets(_project.id),
        _api.getResearchProjectProfile(_project.id),
      ]);
      if (!mounted) return;
      setState(() {
        _frontierJobs = values[0] as List<FrontierTrackingJob>;
        _documents = values[1] as List<ResearchDocument>;
        _datasets = values[2] as List<ResearchDataset>;
        _projectProfile = values[3] as ResearchProjectProfile;
        _profileInstructions.text = _projectProfile!.instructions;
        _selectedDocument = _documents.firstOrNull;
        _documentContent.text = _selectedDocument?.content ?? '';
        _documentDirty = false;
        _selectedDataset = _datasets.firstOrNull;
        _loading = false;
        _error = null;
      });
    } on ApiException catch (error) {
      _showError(error.detail);
    } catch (_) {
      _showError('无法加载科研项目，请检查网络连接。');
    }
  }

  void _showError(String message) {
    if (!mounted) return;
    setState(() {
      _error = message;
      _loading = false;
      _submitting = false;
    });
  }

  Future<void> _startFrontier() async {
    final query = _frontierQuery.text.trim();
    if (query.length < 2 || _submitting) return;
    setState(() => _submitting = true);
    try {
      final job = await _api.createFrontierJob(_project.id, query);
      if (!mounted) return;
      setState(() {
        _frontierJobs = [job, ..._frontierJobs];
        _submitting = false;
      });
      await _pollFrontier(job.id);
    } on ApiException catch (error) {
      _showError(error.detail);
    }
  }

  Future<void> _pollFrontier(String jobId) async {
    for (var attempt = 0; attempt < 90 && mounted; attempt++) {
      await Future<void>.delayed(const Duration(seconds: 2));
      if (!mounted) return;
      final job = await _api.getFrontierJob(jobId);
      if (!mounted) return;
      setState(() {
        _frontierJobs = [
          job,
          ..._frontierJobs.where((item) => item.id != job.id),
        ];
      });
      if (job.isFinished) return;
    }
  }

  Future<void> _createDocument() async {
    final title = TextEditingController();
    var type = 'outline';
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('新建科研文档'),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: title,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: '文档标题'),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: type,
                  decoration: const InputDecoration(labelText: '文档类型'),
                  items: const [
                    DropdownMenuItem(value: 'outline', child: Text('论文大纲')),
                    DropdownMenuItem(
                      value: 'literature_review',
                      child: Text('文献综述'),
                    ),
                    DropdownMenuItem(value: 'paper', child: Text('论文正文')),
                    DropdownMenuItem(value: 'notes', child: Text('研究笔记')),
                  ],
                  onChanged: (value) => setDialogState(() => type = value!),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () =>
                  Navigator.pop(context, title.text.trim().isNotEmpty),
              child: const Text('创建'),
            ),
          ],
        ),
      ),
    );
    if (accepted == true && mounted) {
      try {
        final document = await _api.createResearchDocument(
          projectId: _project.id,
          title: title.text.trim(),
          type: type,
        );
        if (mounted) {
          setState(() {
            _documents = [document, ..._documents];
            _selectedDocument = document;
            _documentContent.text = document.content;
            _documentDirty = false;
          });
        }
      } on ApiException catch (error) {
        _showError(error.detail);
      }
    }
    title.dispose();
  }

  Future<void> _startWriting() async {
    final document = _selectedDocument;
    if (document == null || _submitting) return;
    setState(() => _submitting = true);
    try {
      final job = await _api.createWritingJob(
        documentId: document.id,
        operation: _writingOperation,
        instruction: _writingInstruction.text.trim(),
        sourceText: _documentContent.text.trim(),
      );
      for (var attempt = 0; attempt < 90 && mounted; attempt++) {
        await Future<void>.delayed(const Duration(seconds: 2));
        final current = await _api.getWritingJob(job.id);
        if (!current.isFinished) continue;
        if (current.status == 'failed') {
          throw ApiException(422, current.error ?? '写作任务失败');
        }
        final refreshed = await _api.getResearchDocument(document.id);
        if (!mounted) return;
        setState(() {
          _selectedDocument = refreshed;
          _documentContent.text = refreshed.content;
          _documentDirty = false;
          _documents = [
            refreshed,
            ..._documents.where((item) => item.id != refreshed.id),
          ];
          _submitting = false;
        });
        return;
      }
      throw ApiException(408, '写作任务仍在后台运行，请稍后刷新。');
    } on ApiException catch (error) {
      _showError(error.detail);
    }
  }

  Future<void> _uploadDataset() async {
    final picked = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['csv', 'json', 'txt'],
      withData: true,
    );
    final file = picked?.files.singleOrNull;
    if (file == null || file.bytes == null) return;
    setState(() => _submitting = true);
    try {
      final dataset = await _api.uploadResearchDataset(
        projectId: _project.id,
        name: file.name,
        filename: file.name,
        bytes: file.bytes!,
      );
      if (!mounted) return;
      setState(() {
        _datasets = [dataset, ..._datasets];
        _selectedDataset = dataset;
        _submitting = false;
      });
    } on ApiException catch (error) {
      _showError(error.detail);
    }
  }

  Future<void> _startAnalysis() async {
    final dataset = _selectedDataset;
    if (dataset == null || _submitting) return;
    final parameters = <String, String>{};
    if (_analysisType == 'group_compare') {
      parameters['group_column'] = _groupColumn.text.trim();
      parameters['metric_column'] = _metricColumn.text.trim();
    } else if (_analysisType == 'text_frequency' &&
        _textColumn.text.trim().isNotEmpty) {
      parameters['text_column'] = _textColumn.text.trim();
    }
    setState(() => _submitting = true);
    try {
      var job = await _api.createAnalysisJob(
        datasetId: dataset.id,
        type: _analysisType,
        parameters: parameters,
      );
      if (mounted) setState(() => _analysisJob = job);
      for (var attempt = 0; attempt < 90 && mounted; attempt++) {
        await Future<void>.delayed(const Duration(seconds: 2));
        job = await _api.getAnalysisJob(job.id);
        if (mounted) setState(() => _analysisJob = job);
        if (!job.isFinished) continue;
        if (job.status == 'failed') {
          throw ApiException(422, job.error ?? '分析任务失败');
        }
        if (mounted) setState(() => _submitting = false);
        return;
      }
      throw ApiException(408, '分析任务仍在后台运行，请稍后刷新。');
    } on ApiException catch (error) {
      _showError(error.detail);
    }
  }

  Future<void> _openChat() async {
    await AppScope.of(context).openResearchProject(_project);
    if (!mounted) return;
    if (!widget.embedded) Navigator.pop(context);
    widget.onOpenChat();
  }

  Future<void> _saveProjectProfile() async {
    final current = _projectProfile;
    if (current == null || _submitting) return;
    setState(() => _submitting = true);
    try {
      final saved = await _api.saveResearchProjectProfile(
        _project.id,
        instructions: _profileInstructions.text.trim(),
        expectedRevision: current.revision,
      );
      if (!mounted) return;
      setState(() {
        _projectProfile = saved;
        _submitting = false;
        _error = null;
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('项目画像已保存')));
    } on ApiException catch (error) {
      _showError(error.statusCode == 409 ? '项目画像已被更新，请刷新后重试。' : error.detail);
    }
  }

  Future<void> _saveDocument() async {
    final document = _selectedDocument;
    if (document == null || _documentSaving || !_documentDirty) return;
    setState(() => _documentSaving = true);
    try {
      final saved = await _api.updateResearchDocument(
        documentId: document.id,
        content: _documentContent.text,
      );
      if (!mounted) return;
      setState(() {
        _selectedDocument = saved;
        _documents = [
          saved,
          ..._documents.where((item) => item.id != saved.id),
        ];
        _documentDirty = false;
        _documentSaving = false;
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('文档已保存')));
    } on ApiException catch (error) {
      _showError(error.detail);
    } finally {
      if (mounted && _documentSaving) {
        setState(() => _documentSaving = false);
      }
    }
  }

  Future<void> _saveProjectSettings() async {
    final name = _projectName.text.trim();
    if (name.isEmpty || _projectSaving) return;
    setState(() => _projectSaving = true);
    try {
      final saved = await AppScope.of(context).updateResearchProject(
        _project.id,
        name: name,
        description: _projectDescription.text,
      );
      if (!mounted) return;
      setState(() {
        _project = saved;
        _projectSaving = false;
      });
      widget.onProjectUpdated?.call(saved);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('项目设置已保存')));
    } on ApiException catch (error) {
      _showError(error.detail);
    } finally {
      if (mounted && _projectSaving) {
        setState(() => _projectSaving = false);
      }
    }
  }

  Future<void> _archiveProject() async {
    if (_projectSaving) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('归档科研项目'),
        content: Text('归档后“${_project.name}”将不能再创建项目对话或任务。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton.icon(
            onPressed: () => Navigator.pop(dialogContext, true),
            icon: const Icon(LucideIcons.archive, size: 16),
            label: const Text('归档项目'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _projectSaving = true);
    try {
      await AppScope.of(context).archiveResearchProject(_project.id);
      if (!mounted) return;
      widget.onBack?.call();
    } on ApiException catch (error) {
      _showError(error.detail);
    } finally {
      if (mounted && _projectSaving) {
        setState(() => _projectSaving = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final content = DefaultTabController(
      length: 6,
      child: Column(
        children: [
          _projectHeader(),
          if (_error != null)
            MaterialBanner(
              content: Text(_error!),
              actions: [
                TextButton(
                  onPressed: () => setState(() => _error = null),
                  child: const Text('关闭'),
                ),
              ],
            ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : TabBarView(
                    children: [
                      _overviewTab(),
                      _frontierTab(),
                      _writingTab(),
                      _experimentsTab(),
                      _dataTab(),
                      _settingsTab(),
                    ],
                  ),
          ),
        ],
      ),
    );
    return widget.embedded ? content : Scaffold(body: SafeArea(child: content));
  }

  Widget _projectHeader() => Container(
    padding: const EdgeInsets.fromLTRB(18, 14, 18, 0),
    decoration: BoxDecoration(
      border: Border(bottom: BorderSide(color: context.n.divider)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            if (widget.onBack != null) ...[
              IconButton(
                tooltip: '返回项目列表',
                onPressed: widget.onBack,
                icon: const Icon(LucideIcons.arrowLeft, size: 18),
              ),
              const SizedBox(width: 4),
            ],
            Container(
              width: 34,
              height: 34,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: EsaColors.accent.withValues(alpha: .15),
                borderRadius: BorderRadius.circular(9),
              ),
              child: const Icon(LucideIcons.brainCircuit, size: 19),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(_project.name, style: context.texts.headlineSmall),
                  Text(
                    _project.description.isEmpty
                        ? '独立科研项目工作空间'
                        : _project.description,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: context.texts.bodySmall,
                  ),
                ],
              ),
            ),
            TextButton.icon(
              onPressed: _openChat,
              icon: const Icon(LucideIcons.messageCircle, size: 17),
              label: const Text('项目对话'),
            ),
          ],
        ),
        const SizedBox(height: 8),
        const TabBar(
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: [
            Tab(icon: Icon(LucideIcons.gauge, size: 16), text: 'Overview'),
            Tab(icon: Icon(LucideIcons.bookOpen, size: 16), text: 'Papers'),
            Tab(icon: Icon(LucideIcons.notebookPen, size: 16), text: 'Notes'),
            Tab(
              icon: Icon(LucideIcons.flaskConical, size: 16),
              text: 'Experiments',
            ),
            Tab(icon: Icon(LucideIcons.database, size: 16), text: 'Data'),
            Tab(icon: Icon(LucideIcons.settings, size: 16), text: 'Settings'),
          ],
        ),
      ],
    ),
  );

  Widget _overviewTab() {
    final compact = MediaQuery.sizeOf(context).width < 680;
    final keyItems = <String>[
      ..._frontierJobs.take(3).map((job) => job.query),
      ..._documents.take(3).map((document) => document.title),
    ];
    return ListView(
      padding: EdgeInsets.all(compact ? 14 : 18),
      children: [
        _ResearchPanel(
          icon: LucideIcons.target,
          title: '项目目标',
          trailing: _ProjectProgress(project: _project),
          child: Text(
            _project.description.isEmpty
                ? '暂无项目描述'
                : _project.description,
            style: context.texts.bodyMedium?.copyWith(color: context.n.n600),
          ),
        ),
        const SizedBox(height: 12),
        _ResearchPanel(
          icon: LucideIcons.bookMarked,
          title: '关键文献',
          child: keyItems.isEmpty
              ? Text('还没有关键文献，前往 Papers 开始检索。', style: context.texts.bodySmall)
              : Column(
                  children: [
                    for (final item in keyItems) _PaperRow(title: item),
                  ],
                ),
        ),
        const SizedBox(height: 12),
        _ResearchPanel(
          icon: LucideIcons.clipboardList,
          title: '项目上下文',
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _Tag(text: '研究主题  ${_project.name}'),
              _Tag(
                text: '项目状态  ${_researchStatusLabel(_project.status)}',
              ),
              _Tag(
                text: '最近更新  ${_researchDateLabel(_project.updatedAt)}',
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _ResearchPanel(
          icon: LucideIcons.database,
          title: '数据集',
          child: _datasets.isEmpty
              ? Text('还没有数据集，前往 Data 上传。', style: context.texts.bodySmall)
              : Column(
                  children: [
                    for (final dataset in _datasets.take(4))
                      _DataRow(dataset: dataset),
                  ],
                ),
        ),
        const SizedBox(height: 12),
        const _ResearchPanel(
          icon: LucideIcons.lightbulb,
          title: '当前假设',
          child: Text('后端暂未提供结构化研究假设记录。'),
        ),
        const SizedBox(height: 12),
        _ResearchPanel(
          icon: LucideIcons.files,
          title: '文件',
          child: _documents.isEmpty
              ? Text('还没有项目文件，前往 Notes 新建文档。', style: context.texts.bodySmall)
              : Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final document in _documents.take(4))
                      _FileChip(document: document),
                  ],
                ),
        ),
      ],
    );
  }

  Widget _experimentsTab() =>
      const Center(child: _EmptyState(text: '实验记录将在这里关联数据、方法与评价结果。'));

  Widget _settingsTab() => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _ResearchPanel(
                icon: LucideIcons.settings2,
                title: '项目资料',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Text('当前状态', style: context.texts.bodySmall),
                        const SizedBox(width: 10),
                        _Tag(text: _researchStatusLabel(_project.status)),
                        const Spacer(),
                        Text(
                          '更新于 ${_researchDateLabel(_project.updatedAt)}',
                          style: context.texts.bodySmall,
                        ),
                      ],
                    ),
                    const SizedBox(height: 18),
                    TextField(
                      key: const ValueKey('research-project-settings-name'),
                      controller: _projectName,
                      maxLength: 80,
                      decoration: const InputDecoration(labelText: '项目名称'),
                    ),
                    const SizedBox(height: 10),
                    TextField(
                      key: const ValueKey('research-project-settings-description'),
                      controller: _projectDescription,
                      minLines: 3,
                      maxLines: 6,
                      maxLength: 1000,
                      decoration: const InputDecoration(
                        labelText: '研究目标与项目说明',
                        alignLabelWithHint: true,
                      ),
                    ),
                    Align(
                      alignment: Alignment.centerRight,
                      child: FilledButton.icon(
                        key: const ValueKey('save-research-project-settings'),
                        onPressed: _projectSaving ? null : _saveProjectSettings,
                        icon: const Icon(LucideIcons.save, size: 17),
                        label: Text(_projectSaving ? '保存中…' : '保存项目资料'),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              _ResearchPanel(
                icon: LucideIcons.brainCircuit,
                title: '项目画像',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      '这些约束只用于当前项目的研究对话与写作任务。',
                      style: context.texts.bodySmall?.copyWith(
                        color: context.n.n600,
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      key: const ValueKey('research-project-profile'),
                      controller: _profileInstructions,
                      minLines: 6,
                      maxLines: 12,
                      maxLength: 12000,
                      decoration: const InputDecoration(
                        labelText: '研究背景、术语、方法约束与写作偏好',
                        alignLabelWithHint: true,
                      ),
                    ),
                    Align(
                      alignment: Alignment.centerRight,
                      child: FilledButton.icon(
                        key: const ValueKey('save-research-project-profile'),
                        onPressed: _submitting || _projectProfile == null
                            ? null
                            : _saveProjectProfile,
                        icon: const Icon(LucideIcons.save, size: 17),
                        label: const Text('保存项目画像'),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  border: Border.all(color: const Color(0xFFE45858)),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  children: [
                    const Icon(LucideIcons.archive, color: Color(0xFFE45858)),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('归档项目', style: context.texts.titleMedium),
                          const SizedBox(height: 3),
                          Text(
                            '项目资料会保留，但不能继续创建对话或任务。',
                            style: context.texts.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    OutlinedButton.icon(
                      onPressed: _projectSaving ? null : _archiveProject,
                      icon: const Icon(LucideIcons.archive, size: 16),
                      label: const Text('归档'),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    ],
  );

  Widget _frontierTab() => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      _IntroCard(
        title: '领域前沿追踪',
        description: '检索 arXiv 真实论文，归纳年度分布、热点词和新兴信号。结果用于筛选，不替代正式文献计量。',
        child: Row(
          children: [
            Expanded(
              child: TextField(
                key: const ValueKey('frontier-query'),
                controller: _frontierQuery,
                decoration: const InputDecoration(
                  labelText: '研究主题或检索词',
                  hintText: '例如：multimodal agent memory',
                ),
                onSubmitted: (_) => _startFrontier(),
              ),
            ),
            const SizedBox(width: 12),
            FilledButton.icon(
              onPressed: _submitting ? null : _startFrontier,
              icon: const Icon(LucideIcons.search, size: 17),
              label: const Text('开始追踪'),
            ),
          ],
        ),
      ),
      const SizedBox(height: 16),
      if (_frontierJobs.isEmpty) const _EmptyState(text: '还没有前沿追踪任务。'),
      for (final job in _frontierJobs) _FrontierResult(job: job),
    ],
  );

  Widget _writingTab() => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      Row(
        children: [
          Expanded(child: Text('科研文档', style: context.texts.titleLarge)),
          FilledButton.icon(
            onPressed: _createDocument,
            icon: const Icon(LucideIcons.plus, size: 17),
            label: const Text('新建文档'),
          ),
        ],
      ),
      const SizedBox(height: 12),
      if (_documents.isEmpty)
        const _EmptyState(text: '先建立论文大纲、文献综述或研究笔记。')
      else ...[
        DropdownButtonFormField<String>(
          initialValue: _selectedDocument?.id,
          decoration: const InputDecoration(labelText: '当前文档'),
          items: _documents
              .map(
                (document) => DropdownMenuItem(
                  value: document.id,
                  child: Text('${document.title} · v${document.version}'),
                ),
              )
              .toList(),
          onChanged: (id) => setState(() {
            _selectedDocument = _documents.firstWhere((item) => item.id == id);
            _documentContent.text = _selectedDocument!.content;
          }),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _documentContent,
          minLines: 5,
          maxLines: 12,
          decoration: const InputDecoration(
            labelText: '原始材料或待处理正文',
            hintText: '粘贴可靠材料、已有正文或带引用的笔记。材料不足处会标记为 [待补来源]。',
            alignLabelWithHint: true,
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.end,
          children: [
            SizedBox(
              width: 220,
              child: DropdownButtonFormField<String>(
                initialValue: _writingOperation,
                decoration: const InputDecoration(labelText: '写作操作'),
                items: const [
                  DropdownMenuItem(value: 'outline', child: Text('搭建大纲')),
                  DropdownMenuItem(
                    value: 'literature_review',
                    child: Text('生成综述'),
                  ),
                  DropdownMenuItem(value: 'polish', child: Text('语言润色')),
                  DropdownMenuItem(value: 'format_check', child: Text('规范检查')),
                ],
                onChanged: (value) =>
                    setState(() => _writingOperation = value!),
              ),
            ),
            SizedBox(
              width: 420,
              child: TextField(
                controller: _writingInstruction,
                decoration: const InputDecoration(labelText: '补充要求（可选）'),
              ),
            ),
            FilledButton.icon(
              onPressed: _submitting ? null : _startWriting,
              icon: const Icon(LucideIcons.sparkles, size: 17),
              label: Text(_submitting ? '处理中…' : '执行并保存新版本'),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: SelectableText(
              _selectedDocument?.content.isNotEmpty == true
                  ? _selectedDocument!.content
                  : '文档当前为空。运行“大纲”或粘贴材料后开始。',
            ),
          ),
        ),
      ],
    ],
  );

  Widget _dataTab() => ListView(
    padding: const EdgeInsets.all(24),
    children: [
      Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('科研数据分析', style: context.texts.titleLarge),
                const Text('支持 CSV、JSON、TXT，单文件最多 15 MB；文件保存在本机服务器。'),
              ],
            ),
          ),
          FilledButton.icon(
            onPressed: _submitting ? null : _uploadDataset,
            icon: const Icon(LucideIcons.upload, size: 17),
            label: const Text('上传数据'),
          ),
        ],
      ),
      const SizedBox(height: 16),
      if (_datasets.isEmpty)
        const _EmptyState(text: '上传数据后将自动生成字段画像。')
      else ...[
        DropdownButtonFormField<String>(
          initialValue: _selectedDataset?.id,
          decoration: const InputDecoration(labelText: '当前数据集'),
          items: _datasets
              .map(
                (dataset) => DropdownMenuItem(
                  value: dataset.id,
                  child: Text(
                    '${dataset.name} · ${dataset.rowCount} 行 × ${dataset.columnCount} 列',
                  ),
                ),
              )
              .toList(),
          onChanged: (id) => setState(
            () => _selectedDataset = _datasets.firstWhere(
              (item) => item.id == id,
            ),
          ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          crossAxisAlignment: WrapCrossAlignment.end,
          children: [
            SizedBox(
              width: 220,
              child: DropdownButtonFormField<String>(
                initialValue: _analysisType,
                decoration: const InputDecoration(labelText: '分析类型'),
                items: const [
                  DropdownMenuItem(value: 'descriptive', child: Text('描述统计')),
                  DropdownMenuItem(value: 'correlation', child: Text('相关分析')),
                  DropdownMenuItem(value: 'group_compare', child: Text('分组比较')),
                  DropdownMenuItem(
                    value: 'text_frequency',
                    child: Text('文本词频'),
                  ),
                ],
                onChanged: (value) => setState(() => _analysisType = value!),
              ),
            ),
            if (_analysisType == 'group_compare') ...[
              SizedBox(
                width: 180,
                child: TextField(
                  controller: _groupColumn,
                  decoration: const InputDecoration(labelText: '分组字段'),
                ),
              ),
              SizedBox(
                width: 180,
                child: TextField(
                  controller: _metricColumn,
                  decoration: const InputDecoration(labelText: '数值字段'),
                ),
              ),
            ],
            if (_analysisType == 'text_frequency')
              SizedBox(
                width: 200,
                child: TextField(
                  controller: _textColumn,
                  decoration: const InputDecoration(labelText: '文本字段（可选）'),
                ),
              ),
            FilledButton.icon(
              onPressed: _submitting ? null : _startAnalysis,
              icon: const Icon(LucideIcons.play, size: 17),
              label: const Text('开始分析'),
            ),
          ],
        ),
        const SizedBox(height: 18),
        _JsonCard(
          title: _analysisJob?.result == null ? '字段画像' : '分析结果',
          value: _analysisJob?.result ?? _selectedDataset!.profile,
          visual: true,
        ),
      ],
    ],
  );
}

class _IntroCard extends StatelessWidget {
  const _IntroCard({
    required this.title,
    required this.description,
    required this.child,
  });
  final String title;
  final String description;
  final Widget child;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: context.texts.titleLarge),
          const SizedBox(height: 6),
          Text(description),
          const SizedBox(height: 18),
          child,
        ],
      ),
    ),
  );
}

class _ResearchPanel extends StatelessWidget {
  const _ResearchPanel({
    required this.icon,
    required this.title,
    required this.child,
    this.trailing,
  });
  final IconData icon;
  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: const Color(0xFF0B1724),
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 20, color: const Color(0xFF4B8DFF)),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: context.texts.titleLarge),
              const SizedBox(height: 12),
              child,
            ],
          ),
        ),
        if (trailing != null) ...[const SizedBox(width: 16), trailing!],
      ],
    ),
  );
}

class _ProjectProgress extends StatelessWidget {
  const _ProjectProgress({required this.project});

  final ResearchProject project;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 150,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('项目状态', style: context.texts.bodySmall),
        const SizedBox(height: 3),
        Text(
          _researchStatusLabel(project.status),
          style: const TextStyle(fontSize: 22),
        ),
        const SizedBox(height: 10),
        Text(
          '最近更新\n${_researchDateLabel(project.updatedAt)}',
          style: context.texts.bodySmall,
        ),
      ],
    ),
  );
}

String _researchStatusLabel(String status) => switch (status) {
  'active' => '进行中',
  'archived' => '已归档',
  'completed' => '已完成',
  _ => status.isEmpty ? '未设置' : status,
};

String _researchDateLabel(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-'
    '${value.month.toString().padLeft(2, '0')}-'
    '${value.day.toString().padLeft(2, '0')}';

class _PaperRow extends StatelessWidget {
  const _PaperRow({required this.title});
  final String title;

  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 8),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(9),
    ),
    child: Row(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
          decoration: BoxDecoration(
            color: const Color(0xFF15A66A).withValues(alpha: .16),
            borderRadius: BorderRadius.circular(6),
          ),
          child: const Text(
            '高相关',
            style: TextStyle(color: Color(0xFF34D399), fontSize: 11),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Text(title, maxLines: 2, overflow: TextOverflow.ellipsis),
        ),
        Icon(LucideIcons.bookmark, size: 18, color: context.n.n600),
      ],
    ),
  );
}

class _Tag extends StatelessWidget {
  const _Tag({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Text(text, style: context.texts.bodySmall),
  );
}

class _DataRow extends StatelessWidget {
  const _DataRow({required this.dataset});
  final ResearchDataset dataset;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: const BoxDecoration(
            color: Color(0xFF2ECC71),
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 9),
        Expanded(child: Text(dataset.name)),
        Text('${dataset.rowCount} 行', style: context.texts.bodySmall),
      ],
    ),
  );
}

class _FileChip extends StatelessWidget {
  const _FileChip({required this.document});
  final ResearchDocument document;

  @override
  Widget build(BuildContext context) => Container(
    width: 220,
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(
      color: context.n.n100,
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      children: [
        const Icon(LucideIcons.fileText, size: 18, color: Color(0xFF548EFF)),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            document.title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    ),
  );
}

class _FrontierResult extends StatelessWidget {
  const _FrontierResult({required this.job});
  final FrontierTrackingJob job;

  @override
  Widget build(BuildContext context) {
    final result = job.result;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ExpansionTile(
        initiallyExpanded: result != null,
        leading: job.isFinished
            ? Icon(
                job.status == 'succeeded'
                    ? LucideIcons.circleCheck
                    : LucideIcons.circleAlert,
              )
            : const SizedBox.square(
                dimension: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
        title: Text(job.query),
        subtitle: Text(job.error ?? _statusLabel(job.status)),
        children: [
          if (result != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: _FrontierSummary(result: result),
            ),
        ],
      ),
    );
  }

  static String _statusLabel(String status) => switch (status) {
    'queued' => '等待后台处理',
    'running' => '正在检索与归纳',
    'succeeded' => '已完成',
    'failed' => '处理失败',
    _ => status,
  };
}

class _JsonCard extends StatelessWidget {
  const _JsonCard({
    required this.title,
    required this.value,
    this.visual = false,
  });
  final String title;
  final Map<String, dynamic> value;
  final bool visual;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: context.texts.titleMedium),
          const SizedBox(height: 10),
          if (visual)
            _AnalysisSummary(value: value)
          else
            SelectableText(const JsonEncoder.withIndent('  ').convert(value)),
        ],
      ),
    ),
  );
}

class _FrontierSummary extends StatelessWidget {
  const _FrontierSummary({required this.result});
  final Map<String, dynamic> result;

  List<Map<String, dynamic>> _items(String key) =>
      (result[key] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();

  @override
  Widget build(BuildContext context) {
    final years = _items('year_distribution');
    final hotspots = _items('hotspots');
    final papers = _items('papers');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            Chip(label: Text('${result['paper_count'] ?? 0} 篇论文')),
            Chip(label: Text('${result['source'] ?? 'arXiv'}')),
            for (final year in years.take(6))
              Chip(label: Text('${year['year']}: ${year['paper_count']} 篇')),
          ],
        ),
        if (hotspots.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text('热点信号', style: context.texts.titleMedium),
          const SizedBox(height: 8),
          for (final item in hotspots.take(8))
            _MetricBar(
              label: '${item['term']}',
              value: (item['share'] as num?)?.toDouble() ?? 0,
              trailing: '${item['paper_count']} 篇',
            ),
        ],
        if (papers.isNotEmpty) ...[
          const SizedBox(height: 16),
          Text('代表论文', style: context.texts.titleMedium),
          const SizedBox(height: 6),
          for (final paper in papers.take(8))
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: const Icon(LucideIcons.fileText, size: 18),
              title: Text('${paper['title'] ?? ''}'),
              subtitle: SelectableText(
                '${paper['published'] ?? ''}  ${paper['arxiv_url'] ?? ''}',
              ),
            ),
        ],
        if (result['method_note'] case final String note) ...[
          const SizedBox(height: 10),
          Text(note, style: context.texts.bodySmall),
        ],
      ],
    );
  }
}

class _AnalysisSummary extends StatelessWidget {
  const _AnalysisSummary({required this.value});
  final Map<String, dynamic> value;

  List<Map<String, dynamic>> _items(String key) =>
      (value[key] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();

  @override
  Widget build(BuildContext context) {
    final type = value['analysis_type']?.toString();
    if (type == 'correlation') {
      final pairs = _items('pairs');
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (pairs.isEmpty) const Text('没有足够的数值字段可计算相关系数。'),
          for (final pair in pairs.take(20))
            _MetricBar(
              label: '${pair['left']} × ${pair['right']}',
              value: ((pair['pearson_r'] as num?)?.toDouble() ?? 0).abs(),
              trailing: 'r = ${pair['pearson_r']} · n=${pair['sample_size']}',
            ),
          _MethodNote(value: value),
        ],
      );
    }
    if (type == 'group_compare') {
      final groups = _items('groups');
      final maxMean = groups.fold<double>(
        0,
        (current, item) => ((item['mean'] as num?)?.toDouble() ?? 0) > current
            ? (item['mean'] as num).toDouble()
            : current,
      );
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final group in groups)
            _MetricBar(
              label: '${group['group']}',
              value: maxMean == 0
                  ? 0
                  : ((group['mean'] as num?)?.toDouble() ?? 0) / maxMean,
              trailing: '均值 ${group['mean']} · n=${group['count']}',
            ),
          _MethodNote(value: value),
        ],
      );
    }
    if (type == 'text_frequency') {
      final terms = _items('terms');
      final maxCount = terms.isEmpty
          ? 1
          : (terms.first['count'] as num?)?.toDouble() ?? 1;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final term in terms.take(25))
            _MetricBar(
              label: '${term['term']}',
              value: ((term['count'] as num?)?.toDouble() ?? 0) / maxCount,
              trailing: '${term['count']} 次',
            ),
          _MethodNote(value: value),
        ],
      );
    }
    final profile = type == 'descriptive' && value['profile'] is Map
        ? Map<String, dynamic>.from(value['profile'] as Map)
        : value;
    final columns = (profile['columns'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          '${profile['row_count'] ?? 0} 行 × ${profile['column_count'] ?? 0} 列',
        ),
        const SizedBox(height: 8),
        for (final column in columns)
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            leading: Icon(
              column['type'] == 'numeric' ? LucideIcons.hash : LucideIcons.type,
              size: 18,
            ),
            title: Text('${column['name']} · ${column['type']}'),
            subtitle: Text(
              column['type'] == 'numeric'
                  ? '均值 ${column['mean']} · 中位数 ${column['median']} · 范围 ${column['min']}–${column['max']}'
                  : '唯一值 ${column['unique_count']} · 缺失 ${column['missing_count']}',
            ),
          ),
      ],
    );
  }
}

class _MetricBar extends StatelessWidget {
  const _MetricBar({
    required this.label,
    required this.value,
    required this.trailing,
  });
  final String label;
  final double value;
  final String trailing;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      children: [
        SizedBox(
          width: 160,
          child: Text(label, overflow: TextOverflow.ellipsis),
        ),
        Expanded(
          child: LinearProgressIndicator(
            value: value.clamp(0, 1),
            minHeight: 8,
            borderRadius: BorderRadius.circular(4),
          ),
        ),
        const SizedBox(width: 10),
        SizedBox(width: 130, child: Text(trailing)),
      ],
    ),
  );
}

class _MethodNote extends StatelessWidget {
  const _MethodNote({required this.value});
  final Map<String, dynamic> value;

  @override
  Widget build(BuildContext context) => value['method_note'] is String
      ? Padding(
          padding: const EdgeInsets.only(top: 12),
          child: Text(
            '${value['method_note']}',
            style: context.texts.bodySmall,
          ),
        )
      : const SizedBox.shrink();
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 48),
    child: Center(child: Text(text)),
  );
}
