import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

Future<void> showAgentActionSheet(BuildContext context) => showDialog<void>(
  context: context,
  builder: (_) => const _AgentActionSheet(),
);

class _AgentActionSheet extends StatefulWidget {
  const _AgentActionSheet();

  @override
  State<_AgentActionSheet> createState() => _AgentActionSheetState();
}

class _AgentActionSheetState extends State<_AgentActionSheet> {
  List<AgentActionItem> _items = const [];
  bool _loading = true;
  String? _error;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_loading && _items.isEmpty) _load();
  }

  Future<void> _load() async {
    try {
      final items = await AppScope.of(
        context,
      ).api.listAgentActions(status: 'pending');
      if (mounted) setState(() => _items = items);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _decide(AgentActionItem item, bool approve) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      await AppScope.of(
        context,
      ).api.decideAgentAction(item.id, approve: approve);
      await _load();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _title(AgentActionItem item) => switch (item.type) {
    'start_frontier_tracking' => '启动前沿追踪',
    'start_research_writing' => '启动科研写作',
    'start_dataset_analysis' => '启动数据分析',
    _ => item.type,
  };

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Row(
      children: [
        Icon(LucideIcons.shieldCheck, color: EsaColors.accent),
        SizedBox(width: 10),
        Text('待确认动作'),
      ],
    ),
    content: SizedBox(
      width: 620,
      height: 460,
      child: _loading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (_error != null) ...[
                  Text(_error!, style: TextStyle(color: context.scheme.error)),
                  const SizedBox(height: 12),
                ],
                Expanded(
                  child: _items.isEmpty
                      ? const Center(child: Text('没有待确认动作'))
                      : ListView.separated(
                          itemCount: _items.length,
                          separatorBuilder: (_, _) => const Divider(),
                          itemBuilder: (context, index) {
                            final item = _items[index];
                            final details = const JsonEncoder.withIndent(
                              '  ',
                            ).convert(item.arguments);
                            return ListTile(
                              contentPadding: const EdgeInsets.symmetric(
                                horizontal: 4,
                                vertical: 8,
                              ),
                              leading: const Icon(LucideIcons.circleAlert),
                              title: Text(_title(item)),
                              subtitle: SelectableText(details),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  IconButton(
                                    tooltip: '拒绝',
                                    onPressed: () => _decide(item, false),
                                    icon: const Icon(LucideIcons.x),
                                  ),
                                  FilledButton.icon(
                                    onPressed: () => _decide(item, true),
                                    icon: const Icon(
                                      LucideIcons.check,
                                      size: 16,
                                    ),
                                    label: const Text('批准'),
                                  ),
                                ],
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
