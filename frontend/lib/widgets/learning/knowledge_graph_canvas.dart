import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../models/models.dart';
import '../../theme/esa_context.dart';
import '../../theme/esa_theme.dart';

class KnowledgeGraphCanvas extends StatefulWidget {
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

  @override
  State<KnowledgeGraphCanvas> createState() => _KnowledgeGraphCanvasState();
}

class _KnowledgeGraphCanvasState extends State<KnowledgeGraphCanvas> {
  final _transformation = TransformationController();
  double _fitScale = 1.0;
  Size? _fittedViewport;

  @override
  void dispose() {
    _transformation.dispose();
    super.dispose();
  }

  Map<String, Rect> _layout() {
    final byLevel = <int, List<KnowledgeMapNode>>{};
    for (final node in widget.visibleNodes) {
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
          KnowledgeGraphCanvas.padding +
              column *
                  (KnowledgeGraphCanvas.nodeWidth +
                      KnowledgeGraphCanvas.horizontalGap),
          KnowledgeGraphCanvas.padding +
              row *
                  (KnowledgeGraphCanvas.nodeHeight +
                      KnowledgeGraphCanvas.verticalGap),
          KnowledgeGraphCanvas.nodeWidth,
          KnowledgeGraphCanvas.nodeHeight,
        );
      }
    }
    return result;
  }

  /// 首次（及视口尺寸变化时）把整张图缩放到刚好放进屏幕。
  /// 手机竖屏上多列图谱宽度轻松超过 2000px，不缩放的话只能看到左上角。
  /// 在帧后回调里改 controller，避免构建期间触发依赖方重建。
  void _scheduleFitScale(Size viewport, double width, double height) {
    if (_fittedViewport == viewport) return;
    _fittedViewport = viewport;
    final fit = math.min(
      math.min(viewport.width / width, viewport.height / height),
      1.0,
    );
    _fitScale = fit.clamp(0.3, 1.0);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _transformation.value = Matrix4.diagonal3Values(_fitScale, _fitScale, 1);
    });
  }

  @override
  Widget build(BuildContext context) {
    if (widget.visibleNodes.isEmpty) {
      return const Center(child: Text('当前筛选条件下没有知识点'));
    }
    final rects = _layout();
    final width = rects.values.fold<double>(
      720,
      (value, rect) => math.max(value, rect.right + KnowledgeGraphCanvas.padding),
    );
    final height = rects.values.fold<double>(
      480,
      (value, rect) =>
          math.max(value, rect.bottom + KnowledgeGraphCanvas.padding),
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        _scheduleFitScale(
          Size(constraints.maxWidth, constraints.maxHeight),
          width,
          height,
        );
        return InteractiveViewer(
          transformationController: _transformation,
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
                      edges: widget.edges,
                      color: context.n.n500,
                    ),
                  ),
                ),
                for (final node in widget.visibleNodes)
                  Positioned.fromRect(
                    rect: rects[node.id]!,
                    child: _KnowledgeNodeCard(
                      node: node,
                      onTap: () => widget.onNodeTap(node),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
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
