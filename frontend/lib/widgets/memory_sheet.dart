import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

Future<void> showMemorySheet(BuildContext context) =>
    showDialog<void>(context: context, builder: (_) => const _MemorySheet());

class _MemorySheet extends StatefulWidget {
  const _MemorySheet();
  @override
  State<_MemorySheet> createState() => _MemorySheetState();
}

class _MemorySheetState extends State<_MemorySheet> {
  final _key = TextEditingController();
  final _content = TextEditingController();
  List<CoreMemoryItem> _items = const [];
  List<MemoryCandidateItem> _candidates = const [];
  String _category = 'general';
  String _scopeType = 'global';
  String? _error;
  bool _loading = true;
  bool _started = false;

  static const _categories = {
    'general': '通用',
    'profile': '个人资料',
    'preference': '偏好',
    'learning': '学习',
    'project': '项目',
    'constraint': '约束',
  };

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_started) {
      _started = true;
      _load();
    }
  }

  @override
  void dispose() {
    _key.dispose();
    _content.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final values = await Future.wait([
        AppScope.of(context).api.listCoreMemories(),
        AppScope.of(context).api.listMemoryCandidates(),
      ]);
      if (mounted) {
        setState(() {
          _items = values[0] as List<CoreMemoryItem>;
          _candidates = values[1] as List<MemoryCandidateItem>;
        });
      }
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save() async {
    if (_key.text.trim().isEmpty || _content.text.trim().isEmpty) {
      setState(() => _error = '名称和内容不能为空');
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await AppScope.of(context).api.saveCoreMemory(
        key: _key.text.trim(),
        content: _content.text.trim(),
        category: _category,
        scopeType: _scopeType,
        workspaceType: AppScope.of(context).activeWorkspace,
      );
      _key.clear();
      _content.clear();
      await _load();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _forget(CoreMemoryItem item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('彻底遗忘'),
        content: Text('将永久删除“${item.key}”及其所有历史版本。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('遗忘'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _loading = true);
    try {
      await AppScope.of(context).api.forgetCoreMemory(item.id);
      await _load();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    }
  }

  Future<void> _toggleSuppressed(CoreMemoryItem item) async {
    setState(() => _loading = true);
    try {
      await AppScope.of(context).api.setCoreMemorySuppressed(
        item.id,
        suppressed: item.status == 'active',
      );
      await _load();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    }
  }

  Future<void> _showVersions(CoreMemoryItem item) async {
    final versions = await AppScope.of(
      context,
    ).api.listCoreMemoryVersions(item.id);
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${item.key} · 版本'),
        content: SizedBox(
          width: 520,
          child: ListView(
            shrinkWrap: true,
            children: [
              for (final version in versions)
                ListTile(
                  title: Text('修订 ${version['revision']}'),
                  subtitle: Text('${version['content']}'),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
  }

  Future<void> _decideCandidate(
    MemoryCandidateItem item,
    bool accept, {
    String? content,
    String? category,
    String? scopeType,
  }) async {
    setState(() => _loading = true);
    try {
      await AppScope.of(context).api.decideMemoryCandidate(
        item.id,
        accept: accept,
        content: content,
        category: category,
        scopeType: scopeType,
        workspaceType: AppScope.of(context).activeWorkspace,
      );
      await _load();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _editCandidate(MemoryCandidateItem item) async {
    final content = TextEditingController(text: item.content);
    var category = item.category;
    var scopeType = item.scopeType;
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('编辑候选记忆'),
          content: SizedBox(
            width: 520,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: content,
                  minLines: 3,
                  maxLines: 6,
                  maxLength: 1000,
                  decoration: const InputDecoration(labelText: '记忆内容'),
                ),
                const SizedBox(height: EsaSpace.sm),
                Row(
                  children: [
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        initialValue: category,
                        decoration: const InputDecoration(labelText: '分类'),
                        items: _categories.entries
                            .map(
                              (entry) => DropdownMenuItem(
                                value: entry.key,
                                child: Text(entry.value),
                              ),
                            )
                            .toList(),
                        onChanged: (value) => setDialogState(
                          () => category = value ?? item.category,
                        ),
                      ),
                    ),
                    const SizedBox(width: EsaSpace.sm),
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        initialValue: scopeType,
                        decoration: const InputDecoration(labelText: '范围'),
                        items: [
                          const DropdownMenuItem(
                            value: 'global',
                            child: Text('全局'),
                          ),
                          DropdownMenuItem(
                            value: 'workspace',
                            child: Text(
                              AppScope.of(context).activeWorkspace.label,
                            ),
                          ),
                        ],
                        onChanged: (value) => setDialogState(
                          () => scopeType = value ?? item.scopeType,
                        ),
                      ),
                    ),
                  ],
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
              onPressed: () => Navigator.pop(context, true),
              child: const Text('接受修改'),
            ),
          ],
        ),
      ),
    );
    final editedContent = content.text.trim();
    content.dispose();
    if (accepted != true || editedContent.isEmpty || !mounted) return;
    await _decideCandidate(
      item,
      true,
      content: editedContent,
      category: category,
      scopeType: scopeType,
    );
  }

  List<CoreMemoryItem> _visibleItems(BuildContext context, String scopeType) {
    final workspace = AppScope.of(context).activeWorkspace.wireName;
    return _items
        .where(
          (item) =>
              item.scopeType == scopeType &&
              (scopeType == 'global' || item.workspaceType == workspace),
        )
        .toList();
  }

  List<MemoryCandidateItem> _visibleCandidates(BuildContext context) {
    final workspace = AppScope.of(context).activeWorkspace.wireName;
    return _candidates
        .where(
          (item) =>
              item.scopeType == 'global' || item.workspaceType == workspace,
        )
        .toList();
  }

  Widget _memoryTile(CoreMemoryItem item) => ListTile(
    title: Text(item.key),
    subtitle: Text(
      '${_categories[item.category] ?? item.category} · ${item.content}',
    ),
    trailing: PopupMenuButton<String>(
      tooltip: '记忆操作',
      onSelected: (action) {
        if (action == 'versions') _showVersions(item);
        if (action == 'suppress') _toggleSuppressed(item);
        if (action == 'forget') _forget(item);
      },
      itemBuilder: (_) => [
        const PopupMenuItem(value: 'versions', child: Text('查看版本')),
        PopupMenuItem(
          value: 'suppress',
          child: Text(item.status == 'active' ? '暂停使用' : '恢复使用'),
        ),
        const PopupMenuItem(value: 'forget', child: Text('彻底遗忘')),
      ],
    ),
  );

  Widget _memoryGroup(String title, List<CoreMemoryItem> items) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
        child: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
      ),
      if (items.isEmpty)
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 8, 16, 12),
          child: Text('暂无记忆'),
        )
      else
        for (final item in items) _memoryTile(item),
    ],
  );

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Row(
      children: [
        Icon(LucideIcons.brain, color: EsaColors.accent),
        SizedBox(width: 10),
        Text('长期记忆管理'),
      ],
    ),
    content: SizedBox(
      width: 680,
      height: 560,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('这里的内容会作为长期信息提供给 ESA。', style: context.texts.bodySmall),
          const SizedBox(height: EsaSpace.md),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _key,
                  maxLength: 64,
                  decoration: const InputDecoration(labelText: '记忆名称'),
                ),
              ),
              const SizedBox(width: EsaSpace.sm),
              SizedBox(
                width: 160,
                child: DropdownButtonFormField<String>(
                  initialValue: _category,
                  borderRadius: BorderRadius.circular(EsaRadii.card),
                  decoration: const InputDecoration(labelText: '分类'),
                  items: _categories.entries
                      .map(
                        (item) => DropdownMenuItem(
                          value: item.key,
                          child: Text(item.value),
                        ),
                      )
                      .toList(),
                  onChanged: (value) =>
                      setState(() => _category = value ?? 'general'),
                ),
              ),
              const SizedBox(width: EsaSpace.sm),
              SizedBox(
                width: 150,
                child: DropdownButtonFormField<String>(
                  initialValue: _scopeType,
                  decoration: const InputDecoration(labelText: '范围'),
                  items: [
                    const DropdownMenuItem(value: 'global', child: Text('全局')),
                    DropdownMenuItem(
                      value: 'workspace',
                      child: Text(AppScope.of(context).activeWorkspace.label),
                    ),
                  ],
                  onChanged: (value) =>
                      setState(() => _scopeType = value ?? 'global'),
                ),
              ),
            ],
          ),
          TextField(
            controller: _content,
            minLines: 2,
            maxLines: 3,
            maxLength: 1000,
            decoration: const InputDecoration(labelText: '记忆内容'),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton(
              onPressed: _loading ? null : _save,
              child: const Text('保存记忆'),
            ),
          ),
          if (_error != null)
            Text(_error!, style: const TextStyle(color: EsaColors.accent)),
          const Divider(height: EsaSpace.xl),
          if (_visibleCandidates(context).isNotEmpty) ...[
            Text('待确认', style: context.texts.titleSmall),
            for (final candidate in _visibleCandidates(context))
              ListTile(
                dense: true,
                title: Text(candidate.key),
                subtitle: Text(candidate.content),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      tooltip: '拒绝',
                      onPressed: () => _decideCandidate(candidate, false),
                      icon: const Icon(LucideIcons.x),
                    ),
                    IconButton(
                      tooltip: '编辑后接受',
                      onPressed: () => _editCandidate(candidate),
                      icon: const Icon(LucideIcons.pencil),
                    ),
                    IconButton(
                      tooltip: '接受',
                      onPressed: () => _decideCandidate(candidate, true),
                      icon: const Icon(LucideIcons.check),
                    ),
                  ],
                ),
              ),
            const Divider(height: EsaSpace.lg),
          ],
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _items.isEmpty
                ? const Center(child: Text('还没有长期记忆'))
                : ListView(
                    children: [
                      _memoryGroup('全局', _visibleItems(context, 'global')),
                      const Divider(),
                      _memoryGroup(
                        AppScope.of(context).activeWorkspace.label,
                        _visibleItems(context, 'workspace'),
                      ),
                    ],
                  ),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('关闭'),
      ),
    ],
  );
}
