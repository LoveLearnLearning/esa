import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../models/models.dart';
import '../../theme/esa_context.dart';

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

  @override
  State<KnowledgeGraphCanvas> createState() => _KnowledgeGraphCanvasState();
}

class _KnowledgeGraphCanvasState extends State<KnowledgeGraphCanvas> {
  KnowledgeMapNode? _selected;
  double _scale = 1;

  KnowledgeMapNode get _center {
    if (_selected != null && widget.visibleNodes.contains(_selected)) {
      return _selected!;
    }
    final scores = <String, int>{};
    for (final edge in widget.edges) {
      scores[edge.from] = (scores[edge.from] ?? 0) + 1;
      scores[edge.to] = (scores[edge.to] ?? 0) + 1;
    }
    return widget.visibleNodes.reduce(
      (a, b) => (scores[a.id] ?? 0) >= (scores[b.id] ?? 0) ? a : b,
    );
  }

  List<KnowledgeMapNode> get _satellites {
    final center = _center;
    final adjacent = <String>{};
    for (final edge in widget.edges) {
      if (edge.from == center.id) adjacent.add(edge.to);
      if (edge.to == center.id) adjacent.add(edge.from);
    }
    final ordered = [
      ...widget.visibleNodes.where((node) => adjacent.contains(node.id)),
      ...widget.visibleNodes.where(
        (node) => node.id != center.id && !adjacent.contains(node.id),
      ),
    ];
    return ordered.take(8).toList();
  }

  void _open(KnowledgeMapNode node) {
    setState(() => _selected = node);
    widget.onNodeTap(node);
  }

  @override
  Widget build(BuildContext context) {
    if (widget.visibleNodes.isEmpty) {
      return const Center(child: Text('当前筛选条件下没有知识点'));
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 600;
        final graphSize = Size(
          compact ? constraints.maxWidth : math.max(680, constraints.maxWidth),
          compact
              ? math.max(330, constraints.maxHeight)
              : math.max(520, constraints.maxHeight),
        );
        final center = Offset(
          graphSize.width / 2,
          graphSize.height / 2 - (compact ? 2 : 12),
        );
        final radiusX = math.min(
          graphSize.width * (compact ? .34 : .34),
          compact ? 135.0 : 310.0,
        );
        final radiusY = math.min(
          graphSize.height * (compact ? .30 : .34),
          compact ? 128.0 : 205.0,
        );
        final satellitePositions = <String, Offset>{};
        final satellites = _satellites;
        for (var i = 0; i < satellites.length; i++) {
          final angle = -math.pi / 2 + i * (math.pi * 2 / satellites.length);
          satellitePositions[satellites[i].id] = Offset(
            center.dx + math.cos(angle) * radiusX,
            center.dy + math.sin(angle) * radiusY,
          );
        }
        return Stack(
          children: [
            Positioned.fill(
              child: CustomPaint(painter: const _DotBackgroundPainter()),
            ),
            ClipRect(
              child: Transform.scale(
                scale: _scale,
                child: SizedBox(
                  width: graphSize.width,
                  height: graphSize.height,
                  child: Stack(
                    children: [
                      Positioned.fill(
                        child: CustomPaint(
                          painter: _RadialEdgePainter(
                            center: center,
                            satellites: satellitePositions,
                            edges: widget.edges,
                            centerId: _center.id,
                          ),
                        ),
                      ),
                      _nodeAt(_center, center, primary: true),
                      for (final node in satellites)
                        _nodeAt(node, satellitePositions[node.id]!),
                    ],
                  ),
                ),
              ),
            ),
            if (!compact)
              Positioned(left: 14, bottom: 14, child: _GraphLegend()),
            Positioned(
              left: 0,
              right: 0,
              bottom: 12,
              child: Center(
                child: _ZoomBar(
                  value: _scale,
                  onChanged: (value) => setState(() => _scale = value),
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _nodeAt(KnowledgeMapNode node, Offset point, {bool primary = false}) {
    final compact = MediaQuery.sizeOf(context).width < 600;
    final diameter = primary
        ? (compact ? 86.0 : 112.0)
        : (compact ? 62.0 : 82.0);
    return Positioned(
      left: point.dx - diameter / 2,
      top: point.dy - diameter / 2,
      width: diameter,
      height: diameter,
      child: _RadialNode(
        node: node,
        primary: primary,
        onTap: () => _open(node),
      ),
    );
  }
}

class _DotBackgroundPainter extends CustomPainter {
  const _DotBackgroundPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFF030B15),
    );
    final paint = Paint()
      ..color = const Color(0xFF1458B8).withValues(alpha: .3);
    for (double x = 14; x < size.width; x += 28) {
      for (double y = 14; y < size.height; y += 28) {
        canvas.drawCircle(Offset(x, y), .75, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _RadialEdgePainter extends CustomPainter {
  const _RadialEdgePainter({
    required this.center,
    required this.satellites,
    required this.edges,
    required this.centerId,
  });
  final Offset center;
  final Map<String, Offset> satellites;
  final List<KnowledgeMapEdge> edges;
  final String centerId;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = const Color(0xFF6D7D91).withValues(alpha: .72)
      ..strokeWidth = 1.2;
    for (final entry in satellites.entries) {
      final edge = edges.cast<KnowledgeMapEdge?>().firstWhere(
        (item) =>
            item?.from == centerId && item?.to == entry.key ||
            item?.to == centerId && item?.from == entry.key,
        orElse: () => null,
      );
      if (edge == null) {
        paint.color = const Color(0xFF496078).withValues(alpha: .55);
      } else {
        paint.color = const Color(0xFF7D8DA0).withValues(alpha: .78);
      }
      final vector = entry.value - center;
      final start = center + vector / vector.distance * 54;
      final end = entry.value - vector / vector.distance * 42;
      canvas.drawLine(start, end, paint);
      canvas.drawCircle(end, 2.2, Paint()..color = paint.color);
    }
  }

  @override
  bool shouldRepaint(covariant _RadialEdgePainter oldDelegate) => true;
}

class _RadialNode extends StatelessWidget {
  const _RadialNode({
    required this.node,
    required this.primary,
    required this.onTap,
  });
  final KnowledgeMapNode node;
  final bool primary;
  final VoidCallback onTap;

  Color get _color => switch (node.status) {
    'mastered' || 'good' => const Color(0xFF66C65A),
    'weak' => const Color(0xFFFF981F),
    _ => const Color(0xFF3478F6),
  };

  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    customBorder: const CircleBorder(),
    child: Container(
      alignment: Alignment.center,
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: const Color(0xFF071320),
        border: Border.all(color: _color, width: primary ? 2.2 : 1.3),
        boxShadow: [
          BoxShadow(
            color: _color.withValues(alpha: primary ? .65 : .25),
            blurRadius: primary ? 28 : 14,
            spreadRadius: primary ? 4 : 1,
          ),
          BoxShadow(
            color: _color.withValues(alpha: .7),
            blurRadius: 0,
            spreadRadius: primary ? -8 : -5,
          ),
        ],
      ),
      child: FittedBox(
        fit: BoxFit.scaleDown,
        child: Text(
          node.name,
          textAlign: TextAlign.center,
          style: TextStyle(
            color: Colors.white,
            fontSize: primary ? 20 : 15,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    ),
  );
}

class _GraphLegend extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Container(
    width: 124,
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: const Color(0xE60B1724),
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(9),
    ),
    child: const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('图例', style: TextStyle(fontSize: 12)),
        SizedBox(height: 8),
        _LegendDot(color: Color(0xFF66C65A), label: '已掌握'),
        _LegendDot(color: Color(0xFF3478F6), label: '掌握中'),
        _LegendDot(color: Color(0xFFFF981F), label: '薄弱'),
        _LegendDot(color: Color(0xFF8793A5), label: '未学习'),
      ],
    ),
  );
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});
  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 6),
    child: Row(
      children: [
        Container(
          width: 7,
          height: 7,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 7),
        Text(label, style: const TextStyle(fontSize: 10.5)),
      ],
    ),
  );
}

class _ZoomBar extends StatelessWidget {
  const _ZoomBar({required this.value, required this.onChanged});
  final double value;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) => Container(
    height: 42,
    padding: const EdgeInsets.symmetric(horizontal: 9),
    decoration: BoxDecoration(
      color: const Color(0xE60B1724),
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(9),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          onPressed: () => onChanged((value - .1).clamp(.65, 1.35)),
          icon: const Icon(LucideIcons.minus, size: 16),
        ),
        SizedBox(
          width: 48,
          child: Text(
            '${(value * 100).round()}%',
            textAlign: TextAlign.center,
            style: context.texts.bodySmall,
          ),
        ),
        IconButton(
          onPressed: () => onChanged((value + .1).clamp(.65, 1.35)),
          icon: const Icon(LucideIcons.zoomIn, size: 16),
        ),
        IconButton(
          onPressed: () => onChanged(1),
          icon: const Icon(LucideIcons.locateFixed, size: 16),
        ),
      ],
    ),
  );
}
