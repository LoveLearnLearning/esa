import 'dart:math' as math;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
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
  final TransformationController _transform = TransformationController();
  Offset? _cursor;
  Offset? _pendingCursor;
  String? _hoveredId;
  String? _selectedId;
  bool _cursorFramePending = false;
  int? _lastFitSignature;
  Size _viewportSize = Size.zero;
  Size _canvasSize = Size.zero;

  @override
  void dispose() {
    _transform.dispose();
    super.dispose();
  }

  void _open(KnowledgeMapNode node) {
    setState(() => _selectedId = node.id);
    widget.onNodeTap(node);
  }

  void _handleHover(PointerHoverEvent event) {
    _pendingCursor = event.localPosition;
    if (_cursorFramePending) return;
    _cursorFramePending = true;
    SchedulerBinding.instance.scheduleFrameCallback((_) {
      if (!mounted) return;
      setState(() {
        _cursor = _pendingCursor;
        _cursorFramePending = false;
      });
    });
  }

  void _clearCursor(PointerExitEvent _) {
    _pendingCursor = null;
    setState(() {
      _cursor = null;
      _cursorFramePending = false;
    });
  }

  Offset _interactivePosition(Offset point) {
    final cursor = _cursor;
    if (cursor == null) return point;
    final delta = cursor - point;
    final distance = delta.distance;
    const influenceRadius = 190.0;
    if (distance <= 0.1 || distance >= influenceRadius) return point;
    final strength = math.pow(1 - distance / influenceRadius, 2).toDouble();
    return point + delta / distance * (13 * strength);
  }

  void _scheduleInitialFit(_MindMapLayout layout, Size viewport) {
    final signature = Object.hash(
      layout.size.width.round(),
      layout.size.height.round(),
      viewport.width.round(),
      viewport.height.round(),
      Object.hashAll(widget.visibleNodes.map((node) => node.id)),
    );
    _viewportSize = viewport;
    _canvasSize = layout.size;
    if (_lastFitSignature == signature) return;
    _lastFitSignature = signature;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _fitGraph();
    });
  }

  void _fitGraph() {
    if (_viewportSize.isEmpty || _canvasSize.isEmpty) return;
    final scale = math
        .min(
          (_viewportSize.width - 28) / _canvasSize.width,
          (_viewportSize.height - 28) / _canvasSize.height,
        )
        .clamp(.18, 1.0)
        .toDouble();
    final dx = (_viewportSize.width - _canvasSize.width * scale) / 2;
    final dy = (_viewportSize.height - _canvasSize.height * scale) / 2;
    _transform.value = Matrix4.identity()
      ..translateByDouble(dx, dy, 0, 1)
      ..scaleByDouble(scale, scale, scale, 1);
  }

  void _setScale(double requested) {
    if (_viewportSize.isEmpty) return;
    final oldScale = _transform.value.getMaxScaleOnAxis();
    final newScale = requested.clamp(.18, 2.2).toDouble();
    final translation = _transform.value.getTranslation();
    final focal = Offset(_viewportSize.width / 2, _viewportSize.height / 2);
    final worldFocal = Offset(
      (focal.dx - translation.x) / oldScale,
      (focal.dy - translation.y) / oldScale,
    );
    final nextTranslation = focal - worldFocal * newScale;
    _transform.value = Matrix4.identity()
      ..translateByDouble(nextTranslation.dx, nextTranslation.dy, 0, 1)
      ..scaleByDouble(newScale, newScale, newScale, 1);
  }

  @override
  Widget build(BuildContext context) {
    if (widget.visibleNodes.isEmpty) {
      return const Center(child: Text('当前筛选条件下没有知识点'));
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 600;
        final viewport = Size(
          constraints.maxWidth,
          constraints.maxHeight.isFinite ? constraints.maxHeight : 560,
        );
        final layout = _MindMapLayout.calculate(
          nodes: widget.visibleNodes,
          edges: widget.edges,
          minimumSize: viewport,
          compact: compact,
        );
        _scheduleInitialFit(layout, viewport);
        final positions = <String, Offset>{
          for (final entry in layout.positions.entries)
            entry.key: _interactivePosition(entry.value),
        };
        return ClipRect(
          child: Stack(
            children: [
              Positioned.fill(
                child: CustomPaint(
                  painter: _DotBackgroundPainter(cursor: _cursor),
                ),
              ),
              InteractiveViewer(
                transformationController: _transform,
                constrained: false,
                minScale: .18,
                maxScale: 2.2,
                boundaryMargin: const EdgeInsets.all(260),
                trackpadScrollCausesScale: true,
                child: MouseRegion(
                  opaque: false,
                  onHover: _handleHover,
                  onExit: _clearCursor,
                  child: SizedBox(
                    width: layout.size.width,
                    height: layout.size.height,
                    child: Stack(
                      clipBehavior: Clip.none,
                      children: [
                        Positioned.fill(
                          child: CustomPaint(
                            painter: _MindMapEdgePainter(
                              positions: positions,
                              nodes: {
                                for (final node in widget.visibleNodes)
                                  node.id: node,
                              },
                              edges: widget.edges,
                              rootId: layout.rootId,
                              hoveredId: _hoveredId,
                            ),
                          ),
                        ),
                        for (final node in widget.visibleNodes)
                          _nodeAt(
                            node,
                            positions[node.id]!,
                            root: node.id == layout.rootId,
                            compact: compact,
                          ),
                      ],
                    ),
                  ),
                ),
              ),
              if (!compact)
                const Positioned(left: 14, bottom: 14, child: _GraphLegend()),
              Positioned(
                left: 0,
                right: 0,
                bottom: 12,
                child: Center(
                  child: AnimatedBuilder(
                    animation: _transform,
                    builder: (context, _) => _ZoomBar(
                      value: _transform.value.getMaxScaleOnAxis(),
                      onChanged: _setScale,
                      onFit: _fitGraph,
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _nodeAt(
    KnowledgeMapNode node,
    Offset point, {
    required bool root,
    required bool compact,
  }) {
    final width = root ? (compact ? 132.0 : 174.0) : (compact ? 112.0 : 152.0);
    final height = root ? (compact ? 58.0 : 68.0) : (compact ? 46.0 : 54.0);
    return Positioned(
      left: point.dx - width / 2,
      top: point.dy - height / 2,
      width: width,
      height: height,
      child: MouseRegion(
        cursor: SystemMouseCursors.click,
        onEnter: (_) => setState(() => _hoveredId = node.id),
        onExit: (_) {
          if (_hoveredId == node.id) setState(() => _hoveredId = null);
        },
        child: _MindMapNode(
          node: node,
          root: root,
          hovered: _hoveredId == node.id,
          selected: _selectedId == node.id,
          onTap: () => _open(node),
        ),
      ),
    );
  }
}

class _MindMapLayout {
  const _MindMapLayout({
    required this.size,
    required this.positions,
    required this.rootId,
  });

  final Size size;
  final Map<String, Offset> positions;
  final String rootId;

  static _MindMapLayout calculate({
    required List<KnowledgeMapNode> nodes,
    required List<KnowledgeMapEdge> edges,
    required Size minimumSize,
    required bool compact,
  }) {
    final byId = {for (final node in nodes) node.id: node};
    final degree = {for (final node in nodes) node.id: 0};
    final adjacency = {for (final node in nodes) node.id: <String>{}};
    for (final edge in edges) {
      if (!byId.containsKey(edge.from) || !byId.containsKey(edge.to)) continue;
      adjacency[edge.from]!.add(edge.to);
      adjacency[edge.to]!.add(edge.from);
      degree[edge.from] = degree[edge.from]! + 1;
      degree[edge.to] = degree[edge.to]! + 1;
    }
    final minimumLevel = nodes.map((node) => node.level).reduce(math.min);
    final rootCandidates = nodes.where((node) => node.level == minimumLevel);
    final root = rootCandidates.reduce(
      (a, b) => degree[a.id]! >= degree[b.id]! ? a : b,
    );

    final depths = <String, int>{root.id: 0};
    final queue = <String>[root.id];
    for (var index = 0; index < queue.length; index++) {
      final current = queue[index];
      final neighbors = adjacency[current]!.toList()
        ..sort((a, b) => byId[a]!.name.compareTo(byId[b]!.name));
      for (final neighbor in neighbors) {
        if (depths.containsKey(neighbor)) continue;
        depths[neighbor] = depths[current]! + 1;
        queue.add(neighbor);
      }
    }
    for (final node in nodes) {
      depths.putIfAbsent(
        node.id,
        () => math.max(1, node.level - minimumLevel + 1),
      );
    }

    final groups = <(int, int), List<KnowledgeMapNode>>{};
    final sorted = nodes.where((node) => node.id != root.id).toList()
      ..sort((a, b) {
        final depth = depths[a.id]!.compareTo(depths[b.id]!);
        if (depth != 0) return depth;
        final category = a.category.compareTo(b.category);
        return category != 0 ? category : a.name.compareTo(b.name);
      });
    final depthIndexes = <int, int>{};
    for (final node in sorted) {
      final depth = depths[node.id]!;
      final index = depthIndexes.update(
        depth,
        (value) => value + 1,
        ifAbsent: () => 0,
      );
      final side = index.isEven ? 1 : -1;
      groups.putIfAbsent((depth, side), () => []).add(node);
    }

    final maxDepth = depths.values.reduce(math.max);
    final largestColumn = groups.values.fold<int>(
      1,
      (value, group) => math.max(value, group.length),
    );
    final horizontalGap = compact ? 152.0 : 208.0;
    final verticalGap = compact ? 66.0 : 78.0;
    final sidePadding = compact ? 100.0 : 145.0;
    final verticalPadding = compact ? 84.0 : 110.0;
    final size = Size(
      math.max(
        minimumSize.width,
        sidePadding * 2 + maxDepth * horizontalGap * 2,
      ),
      math.max(
        minimumSize.height,
        verticalPadding * 2 + (largestColumn - 1) * verticalGap,
      ),
    );
    final center = Offset(size.width / 2, size.height / 2);
    final positions = <String, Offset>{root.id: center};
    for (final entry in groups.entries) {
      final depth = entry.key.$1;
      final side = entry.key.$2;
      final column = entry.value;
      final top = center.dy - (column.length - 1) * verticalGap / 2;
      for (var index = 0; index < column.length; index++) {
        positions[column[index].id] = Offset(
          center.dx + side * depth * horizontalGap,
          top + index * verticalGap,
        );
      }
    }
    return _MindMapLayout(size: size, positions: positions, rootId: root.id);
  }
}

class _DotBackgroundPainter extends CustomPainter {
  const _DotBackgroundPainter({this.cursor});

  final Offset? cursor;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFF030B15),
    );
    final dotPaint = Paint()
      ..color = const Color(0xFF1458B8).withValues(alpha: .24);
    for (double x = 14; x < size.width; x += 28) {
      for (double y = 14; y < size.height; y += 28) {
        canvas.drawCircle(Offset(x, y), .72, dotPaint);
      }
    }
    if (cursor case final point?) {
      final halo = Paint()
        ..shader = RadialGradient(
          colors: [
            const Color(0xFF3478F6).withValues(alpha: .12),
            Colors.transparent,
          ],
        ).createShader(Rect.fromCircle(center: point, radius: 150));
      canvas.drawCircle(point, 150, halo);
    }
  }

  @override
  bool shouldRepaint(covariant _DotBackgroundPainter oldDelegate) =>
      oldDelegate.cursor != cursor;
}

class _MindMapEdgePainter extends CustomPainter {
  const _MindMapEdgePainter({
    required this.positions,
    required this.nodes,
    required this.edges,
    required this.rootId,
    required this.hoveredId,
  });

  final Map<String, Offset> positions;
  final Map<String, KnowledgeMapNode> nodes;
  final List<KnowledgeMapEdge> edges;
  final String rootId;
  final String? hoveredId;

  @override
  void paint(Canvas canvas, Size size) {
    for (final edge in edges) {
      final start = positions[edge.from];
      final end = positions[edge.to];
      if (start == null || end == null) continue;
      final highlighted = hoveredId == edge.from || hoveredId == edge.to;
      final target = nodes[edge.to];
      final color = _nodeColor(target?.status ?? 'unseen');
      final direction = end.dx >= start.dx ? 1.0 : -1.0;
      final bend = math.max(34.0, (end.dx - start.dx).abs() * .46);
      final path = Path()
        ..moveTo(start.dx, start.dy)
        ..cubicTo(
          start.dx + bend * direction,
          start.dy,
          end.dx - bend * direction,
          end.dy,
          end.dx,
          end.dy,
        );
      canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeWidth = highlighted ? 2.7 : 1.35
          ..color = color.withValues(alpha: highlighted ? .92 : .44),
      );
      if (highlighted) {
        canvas.drawCircle(end, 3.2, Paint()..color = color);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _MindMapEdgePainter oldDelegate) =>
      oldDelegate.positions != positions ||
      oldDelegate.hoveredId != hoveredId ||
      oldDelegate.edges != edges;
}

Color _nodeColor(String status) => switch (status) {
  'mastered' || 'good' => const Color(0xFF66C65A),
  'weak' => const Color(0xFFFF981F),
  'learning' => const Color(0xFF3478F6),
  _ => const Color(0xFF8793A5),
};

class _MindMapNode extends StatelessWidget {
  const _MindMapNode({
    required this.node,
    required this.root,
    required this.hovered,
    required this.selected,
    required this.onTap,
  });

  final KnowledgeMapNode node;
  final bool root;
  final bool hovered;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = _nodeColor(node.status);
    final detail = node.masteryLevel == null
        ? '未评估'
        : '${node.masteryLevel!.round()}%';
    return AnimatedScale(
      scale: hovered ? 1.08 : 1,
      duration: const Duration(milliseconds: 130),
      curve: Curves.easeOutCubic,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(root ? 20 : 14),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 150),
            padding: EdgeInsets.symmetric(
              horizontal: root ? 16 : 12,
              vertical: 7,
            ),
            decoration: BoxDecoration(
              color: hovered
                  ? const Color(0xFF10233A)
                  : const Color(0xFF081624),
              borderRadius: BorderRadius.circular(root ? 20 : 14),
              border: Border.all(
                color: selected || hovered
                    ? color
                    : color.withValues(alpha: .72),
                width: root || selected ? 2.1 : 1.25,
              ),
              boxShadow: [
                BoxShadow(
                  color: color.withValues(
                    alpha: hovered
                        ? .40
                        : root
                        ? .24
                        : .12,
                  ),
                  blurRadius: hovered ? 24 : 14,
                  spreadRadius: hovered ? 2 : 0,
                ),
              ],
            ),
            child: Row(
              children: [
                Container(
                  width: root ? 11 : 8,
                  height: root ? 11 : 8,
                  decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 9),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        node.name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: root ? 15 : 12.5,
                          fontWeight: root ? FontWeight.w700 : FontWeight.w600,
                          height: 1.12,
                        ),
                      ),
                      if (root || hovered) ...[
                        const SizedBox(height: 3),
                        Text(
                          detail,
                          style: TextStyle(fontSize: 9.5, color: color),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _GraphLegend extends StatelessWidget {
  const _GraphLegend();

  @override
  Widget build(BuildContext context) => Container(
    width: 124,
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: const Color(0xE60B1724),
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(12),
    ),
    child: const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('图例', style: TextStyle(fontSize: 12)),
        SizedBox(height: 8),
        _LegendDot(color: Color(0xFF66C65A), label: '已掌握'),
        _LegendDot(color: Color(0xFF3478F6), label: '掌握中'),
        _LegendDot(color: Color(0xFFFF981F), label: '薄弱'),
        _LegendDot(color: Color(0xFF8793A5), label: '未评估'),
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
  const _ZoomBar({
    required this.value,
    required this.onChanged,
    required this.onFit,
  });

  final double value;
  final ValueChanged<double> onChanged;
  final VoidCallback onFit;

  @override
  Widget build(BuildContext context) => Container(
    height: 42,
    padding: const EdgeInsets.symmetric(horizontal: 9),
    decoration: BoxDecoration(
      color: const Color(0xE60B1724),
      border: Border.all(color: context.n.divider),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          tooltip: '缩小',
          onPressed: () => onChanged(value - .1),
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
          tooltip: '放大',
          onPressed: () => onChanged(value + .1),
          icon: const Icon(LucideIcons.zoomIn, size: 16),
        ),
        IconButton(
          tooltip: '显示全部',
          onPressed: onFit,
          icon: const Icon(LucideIcons.scan, size: 16),
        ),
      ],
    ),
  );
}
