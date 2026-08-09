import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../../models/models.dart';
import '../../theme/esa_context.dart';
import '../../theme/esa_theme.dart';

class KnowledgePointPanel extends StatelessWidget {
  const KnowledgePointPanel({
    super.key,
    required this.node,
    required this.detail,
    required this.onExplain,
  });

  final KnowledgeMapNode node;
  final KnowledgePointDetail detail;
  final VoidCallback onExplain;

  String _ratio(dynamic value) =>
      value is num ? '${(value.toDouble() * 100).round()}%' : '暂无';

  @override
  Widget build(BuildContext context) {
    final state = detail.state;
    final evidence = detail.evidence;
    final weak = detail.weakPrerequisites;
    final mastery = (state['mastery_level'] as num?)?.toDouble();
    final misconceptions =
        (evidence['recent_misconceptions'] as List? ?? const [])
            .map((item) => item.toString())
            .where((item) => item.isNotEmpty)
            .toList();
    return FractionallySizedBox(
      heightFactor: 0.86,
      child: Material(
        color: context.scheme.surface,
        borderRadius: const BorderRadius.vertical(
          top: Radius.circular(EsaRadii.sheet),
        ),
        child: ListView(
          padding: const EdgeInsets.all(EsaSpace.xl),
          children: [
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(node.name, style: context.texts.headlineSmall),
                      const SizedBox(height: 5),
                      Text(node.course, style: context.texts.bodySmall),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: '关闭',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(LucideIcons.x),
                ),
              ],
            ),
            const SizedBox(height: EsaSpace.xl),
            _Metric(
              label: '掌握水平',
              value: mastery == null ? '未评估' : '${mastery.round()}%',
            ),
            _Metric(label: '记忆状态', value: _ratio(state['retention'])),
            _Metric(
              label: '判断可信度',
              value: _ratio(state['evidence_confidence']),
            ),
            _Metric(label: '练习次数', value: '${state['practice_count'] ?? 0}'),
            const SizedBox(height: EsaSpace.lg),
            Text('学习证据', style: context.texts.titleMedium),
            const SizedBox(height: EsaSpace.sm),
            Text('有效记录：${evidence['evidence_count'] ?? 0} 条'),
            Text('正确率：${_ratio(evidence['correct_rate'])}'),
            Text('平均提示等级：${evidence['avg_hint_level'] ?? '暂无'}'),
            Text('独立完成率：${_ratio(evidence['independent_rate'])}'),
            if (misconceptions.isNotEmpty) ...[
              const SizedBox(height: EsaSpace.lg),
              Text('最近误解', style: context.texts.titleMedium),
              const SizedBox(height: EsaSpace.sm),
              for (final item in misconceptions)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    LucideIcons.alertCircle,
                    size: 18,
                    color: context.scheme.error,
                  ),
                  title: Text(item),
                ),
            ],
            if (weak.isNotEmpty) ...[
              const SizedBox(height: EsaSpace.lg),
              Text('薄弱前置', style: context.texts.titleMedium),
              const SizedBox(height: EsaSpace.sm),
              for (final item in weak)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(LucideIcons.gitBranch, size: 18),
                  title: Text(
                    item['name']?.toString() ??
                        item['kp_id']?.toString() ??
                        '未知知识点',
                  ),
                  trailing: Text(
                    item['mastery_level'] is num
                        ? '${(item['mastery_level'] as num).round()}%'
                        : '未评估',
                  ),
                ),
            ],
            const SizedBox(height: EsaSpace.xl),
            FilledButton.icon(
              onPressed: onExplain,
              icon: const Icon(LucideIcons.messageCircle, size: 18),
              label: const Text('让 ESA 讲解'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: EsaSpace.sm),
    child: Row(
      children: [
        Expanded(
          child: Text(label, style: TextStyle(color: context.n.n600)),
        ),
        Text(value, style: context.texts.titleMedium),
      ],
    ),
  );
}
