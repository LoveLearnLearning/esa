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
  String _category = 'general';
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
      final items = await AppScope.of(context).api.listCoreMemories();
      if (mounted) setState(() => _items = items);
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

  Future<void> _delete(String key) async {
    setState(() => _loading = true);
    try {
      await AppScope.of(context).api.deleteCoreMemory(key);
      await _load();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

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
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _items.isEmpty
                ? const Center(child: Text('还没有长期记忆'))
                : ListView.builder(
                    itemCount: _items.length,
                    itemBuilder: (_, index) {
                      final item = _items[index];
                      return ListTile(
                        title: Text(item.key),
                        subtitle: Text(
                          '${_categories[item.category] ?? item.category} · ${item.content}',
                        ),
                        trailing: IconButton(
                          tooltip: '删除记忆',
                          onPressed: () => _delete(item.key),
                          icon: const Icon(LucideIcons.trash2),
                        ),
                      );
                    },
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
