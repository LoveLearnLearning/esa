import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

Future<void> showLearningDashboard(BuildContext context) => showDialog<void>(
  context: context,
  builder: (_) => const _LearningDashboard(),
);

class _LearningDashboard extends StatefulWidget {
  const _LearningDashboard();

  @override
  State<_LearningDashboard> createState() => _LearningDashboardState();
}

class _LearningDashboardState extends State<_LearningDashboard> {
  final _course = TextEditingController();
  MasteryReport? _report;
  String? _error;
  bool _loading = true;
  bool _started = false;

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
    _course.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final report = await AppScope.of(
        context,
      ).api.getMasteryReport(course: _course.text);
      if (mounted) setState(() => _report = report);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.detail);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720, maxHeight: 720),
        child: Padding(
          padding: const EdgeInsets.all(EsaSpace.xl),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Icon(LucideIcons.barChart3, color: EsaColors.accent),
                  const SizedBox(width: 10),
                  Text('学习情况', style: context.texts.headlineSmall),
                  const Spacer(),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(LucideIcons.x),
                  ),
                ],
              ),
              const SizedBox(height: EsaSpace.md),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _course,
                      decoration: const InputDecoration(
                        labelText: '课程（留空查看全部）',
                      ),
                      onSubmitted: (_) => _load(),
                    ),
                  ),
                  const SizedBox(width: EsaSpace.sm),
                  FilledButton(
                    onPressed: _loading ? null : _load,
                    child: const Text('查询'),
                  ),
                ],
              ),
              const SizedBox(height: EsaSpace.lg),
              Expanded(child: _content(context)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _content(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return Center(child: Text(_error!));
    final report = _report;
    if (report == null || report.totalPoints == 0) {
      return const Center(child: Text('还没有答题记录，可先让 ESA 批改并记录练习结果。'));
    }
    return ListView(
      children: [
        Row(
          children: [
            _metric(context, '${report.totalPoints}', '知识点'),
            const SizedBox(width: EsaSpace.sm),
            _metric(
              context,
              '${report.averageMastery.toStringAsFixed(1)}%',
              '平均掌握度',
            ),
          ],
        ),
        const SizedBox(height: EsaSpace.lg),
        _section(context, '薄弱知识点', report.weakPoints),
        _section(context, '优势知识点', report.strongPoints),
        _section(context, '需要复习', report.stalePoints),
      ],
    );
  }

  Widget _metric(BuildContext context, String value, String label) => Expanded(
    child: Container(
      padding: const EdgeInsets.all(EsaSpace.lg),
      decoration: BoxDecoration(
        color: context.n.n100,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.card),
      ),
      child: Column(
        children: [
          Text(value, style: context.texts.headlineMedium),
          Text(label),
        ],
      ),
    ),
  );

  Widget _section(
    BuildContext context,
    String title,
    List<MasteryPoint> points,
  ) {
    if (points.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: EsaSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(title, style: context.texts.titleMedium),
          const SizedBox(height: EsaSpace.sm),
          for (final point in points)
            ListTile(
              dense: true,
              title: Text(point.name),
              trailing: Text('${point.masteryLevel.toStringAsFixed(1)}%'),
            ),
        ],
      ),
    );
  }
}
