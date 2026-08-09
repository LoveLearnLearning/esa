import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../../models/models.dart';
import '../../theme/esa_context.dart';
import '../../theme/esa_theme.dart';

class KnowledgeGraphCanvas extends StatelessWidget {
  const KnowledgeGraphCanvas({
    super.key,
    required this.visibleNodes,
    required this.edges,
    required this.onNodeTap,
  });

  final List<KnowledgeMapNode> visibleNodes;
  final List<KnowledgeMapEdge> edges;
  final ValueChanged<KnowledgeMapNode> onNodeTap;

  static const nodeWidth = 172.0;
  static const nodeHeight = 88.0;
  static const horizontalGap = 92.0;
  static const verticalGap = 28.0;
  static const padding = 52.0;

  Map<String, Rect> _layout() {
    final byLevel = <int, List<KnowledgeMapNode>>{};
    for (final node in visibleNodes) {
      byLevel.putIfAbsent(node.level, () => []).add(node);
    }
    for (final nodes in byLevel.values) {
      nodes.sort((a, b) => a.name.compareTo(b.name));
    }
    final result = <String, Rect>{};
    final levels = byLevel.keys.toList()..sort();
    for (var column = 0; column < levels.length; column++) {
      final nodes = byLevel[levels[column]]!;
      for (var row = 0; row < nodes.length; row++) {
        result[nodes[row].id] = Rect.fromLTWH(
          padding + column * (nodeWidth + horizontalGap),
          padding + row * (nodeHeight + verticalGap),
          nodeWidth,
          nodeHeight,
        );
      }
    }
    return result;
  }

  @override
  Widget build(BuildContext context) {
    if (visibleNodes.isEmpty) {
      return const Center(child: Text('当前筛选条件下没有知识点'));
    }
    final rects = _layout();
    final width = rects.values.fold<double>(
      720,
      (value, rect) => math.max(value, rect.right + padding),
    );
    final height = rects.values.fold<double>(
      480,
      (value, rect) => math.max(value, rect.bottom + padding),
    );
    return InteractiveViewer(
      minScale: 0.3,
      maxScale: 2.4,
      boundaryMargin: const EdgeInsets.all(260),
      constrained: false,
      child: SizedBox(
        width: width,
        height: height,
        child: Stack(
          children: [
            Positioned.fill(
              child: CustomPaint(
                painter: _KnowledgeEdgePainter(
                  rects: rects,
                  edges: edges,
                  color: context.n.n500,
                ),
              ),
            ),
            for (final node in visibleNodes)
              Positioned.fromRect(
                rect: rects[node.id]!,
                child: _KnowledgeNodeCard(
                  node: node,
                  onTap: () => onNodeTap(node),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _KnowledgeEdgePainter extends CustomPainter {
  const _KnowledgeEdgePainter({
    required this.rects,
    required this.edges,
    required this.color,
  });

  final Map<String, Rect> rects;
  final List<KnowledgeMapEdge> edges;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;
    for (final edge in edges) {
      final source = rects[edge.from];
      final target = rects[edge.to];
      if (source == null || target == null) continue;
      final start = Offset(source.right, source.center.dy);
      final end = Offset(target.left, target.center.dy);
      final control = math.max(28.0, (end.dx - start.dx).abs() * 0.45);
      final path = Path()
        ..moveTo(start.dx, start.dy)
        ..cubicTo(
          start.dx + control,
          start.dy,
          end.dx - control,
          end.dy,
          end.dx,
          end.dy,
        );
      canvas.drawPath(path, paint);
      const arrow = 6.0;
      canvas.drawPath(
        Path()
          ..moveTo(end.dx - arrow, end.dy - arrow)
          ..lineTo(end.dx, end.dy)
          ..lineTo(end.dx - arrow, end.dy + arrow),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _KnowledgeEdgePainter oldDelegate) =>
      oldDelegate.rects != rects ||
      oldDelegate.edges != edges ||
      oldDelegate.color != color;
}

class _KnowledgeNodeCard extends StatelessWidget {
  const _KnowledgeNodeCard({required this.node, required this.onTap});

  final KnowledgeMapNode node;
  final VoidCallback onTap;

  String get _statusText => switch (node.status) {
    'weak' => '需加强',
    'learning' => '学习中',
    'good' => '较好',
    'mastered' => '稳定掌握',
    _ => '未评估',
  };

  Color _statusColor(BuildContext context) => switch (node.status) {
    'weak' => context.scheme.error,
    'learning' => const Color(0xFFF59E0B),
    'good' => const Color(0xFF22C55E),
    'mastered' => const Color(0xFF10B981),
    _ => context.n.n600,
  };

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(context);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(EsaRadii.card),
        child: Ink(
          padding: const EdgeInsets.all(13),
          decoration: BoxDecoration(
            color: context.n.n100,
            borderRadius: BorderRadius.circular(EsaRadii.card),
            border: Border.all(
              color: node.status == 'weak'
                  ? color.withValues(alpha: 0.72)
                  : context.n.divider,
            ),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.08),
                blurRadius: 12,
                offset: const Offset(0, 4),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      node.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: context.texts.titleMedium,
                    ),
                  ),
                  if (node.needsReview)
                    Icon(LucideIcons.clock3, size: 15, color: color),
                ],
              ),
              const Spacer(),
              Row(
                children: [
                  Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: color,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    _statusText,
                    style: TextStyle(
                      color: color,
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    node.masteryLevel == null
                        ? '—'
                        : '${node.masteryLevel!.round()}%',
                    style: context.texts.bodySmall,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
