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
        .clamp(_viewportSize.width < 600 ? .60 : .68, 1.0)
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
                              compact: compact,
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
    final size = _mindMapNodeSize(root: root, compact: compact);
    return Positioned(
      key: ValueKey('knowledge-graph-node-${node.id}'),
      left: point.dx - size.width / 2,
      top: point.dy - size.height / 2,
      width: size.width,
      height: size.height,
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

Size _mindMapNodeSize({required bool root, required bool compact}) => Size(
  root ? (compact ? 132.0 : 174.0) : (compact ? 112.0 : 152.0),
  root ? (compact ? 58.0 : 68.0) : (compact ? 46.0 : 54.0),
);

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
    final courseRoot = nodes.where((node) => node.isCourse).firstOrNull;
    final root =
        courseRoot ??
        rootCandidates.reduce((a, b) => degree[a.id]! >= degree[b.id]! ? a : b);

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
    final sideByNode = <String, int>{};
    var nextRootSide = 1;
    for (final node in sorted) {
      final depth = depths[node.id]!;
      final parent = adjacency[node.id]!
          .where((id) => depths[id] == depth - 1)
          .firstOrNull;
      final side = parent == null || parent == root.id
          ? nextRootSide
          : (sideByNode[parent] ?? nextRootSide);
      if (parent == null || parent == root.id) nextRootSide *= -1;
      sideByNode[node.id] = side;
      groups.putIfAbsent((depth, side), () => []).add(node);
    }

    final maxDepth = depths.values.reduce(math.max);
    final largestColumn = groups.values.fold<int>(
      1,
      (value, group) => math.max(value, group.length),
    );
    final horizontalGap = compact ? 220.0 : 312.0;
    final verticalGap = compact ? 108.0 : 132.0;
    final sidePadding = compact ? 142.0 : 210.0;
    final verticalPadding = compact ? 126.0 : 174.0;
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
    required this.compact,
  });

  final Map<String, Offset> positions;
  final Map<String, KnowledgeMapNode> nodes;
  final List<KnowledgeMapEdge> edges;
  final String rootId;
  final String? hoveredId;
  final bool compact;

  Rect _nodeBounds(String id, Offset center, {double clearance = 0}) {
    final size = _mindMapNodeSize(root: id == rootId, compact: compact);
    return Rect.fromCenter(
      center: center,
      width: size.width + clearance * 2,
      height: size.height + clearance * 2,
    );
  }

  Offset _boundaryPoint(
    Offset center,
    Offset toward,
    String nodeId, {
    double clearance = 0,
  }) {
    final delta = toward - center;
    if (delta.distanceSquared < .01) return center;
    final bounds = _nodeBounds(nodeId, center, clearance: clearance);
    final halfWidth = bounds.width / 2;
    final halfHeight = bounds.height / 2;
    final xScale = delta.dx.abs() < .001
        ? double.infinity
        : halfWidth / delta.dx.abs();
    final yScale = delta.dy.abs() < .001
        ? double.infinity
        : halfHeight / delta.dy.abs();
    return center + delta * math.min(xScale, yScale);
  }

  bool _polylineIntersectsNode(
    List<Offset> points,
    String startId,
    String endId,
  ) {
    for (final entry in positions.entries) {
      if (entry.key == startId || entry.key == endId) continue;
      final bounds = _nodeBounds(
        entry.key,
        entry.value,
        clearance: compact ? 18 : 24,
      );
      for (var index = 1; index < points.length; index++) {
        if (_segmentIntersectsRect(points[index - 1], points[index], bounds)) {
          return true;
        }
      }
    }
    return false;
  }

  bool _segmentIntersectsRect(Offset start, Offset end, Rect rect) {
    if (rect.contains(start) || rect.contains(end)) return true;
    final delta = end - start;
    var lower = 0.0;
    var upper = 1.0;
    for (final axis in <(double, double, double, double)>[
      (start.dx, delta.dx, rect.left, rect.right),
      (start.dy, delta.dy, rect.top, rect.bottom),
    ]) {
      if (axis.$2.abs() < .001) {
        if (axis.$1 < axis.$3 || axis.$1 > axis.$4) return false;
        continue;
      }
      final first = (axis.$3 - axis.$1) / axis.$2;
      final second = (axis.$4 - axis.$1) / axis.$2;
      lower = math.max(lower, math.min(first, second));
      upper = math.min(upper, math.max(first, second));
      if (lower > upper) return false;
    }
    return upper >= 0 && lower <= 1;
  }

  Path _edgePath(Offset start, Offset end, String startId, String endId) {
    final direction = end.dx >= start.dx ? 1.0 : -1.0;
    final bend = math.max(42.0, (end.dx - start.dx).abs() * .42);
    final firstControl = Offset(start.dx + bend * direction, start.dy);
    final secondControl = Offset(end.dx - bend * direction, end.dy);
    final samples = <Offset>[
      for (var step = 0; step <= 24; step++)
        _cubicPoint(start, firstControl, secondControl, end, step / 24),
    ];
    if (!_polylineIntersectsNode(samples, startId, endId)) {
      return Path()
        ..moveTo(start.dx, start.dy)
        ..cubicTo(
          firstControl.dx,
          firstControl.dy,
          secondControl.dx,
          secondControl.dy,
          end.dx,
          end.dy,
        );
    }

    final routeAbove = (start.dy + end.dy) / 2 <= sizeCenterY;
    final outerY = routeAbove
        ? positions.values.map((point) => point.dy).reduce(math.min)
        : positions.values.map((point) => point.dy).reduce(math.max);
    final baseClearance = compact ? 48.0 : 64.0;
    final lead = compact ? 54.0 : 76.0;
    final startCorridorX = start.dx + lead * direction;
    final endCorridorX = end.dx - lead * direction;
    final midpointX = (startCorridorX + endCorridorX) / 2;
    var fallbackRouteY = outerY;
    for (final factor in const [1.0, 1.7, 2.5]) {
      final clearance = baseClearance * factor;
      final routeY = routeAbove ? outerY - clearance : outerY + clearance;
      fallbackRouteY = routeY;
      final midpoint = Offset(midpointX, routeY);
      final firstControl = Offset(start.dx + lead * direction * .72, start.dy);
      final firstRouteControl = Offset(startCorridorX, routeY);
      final secondRouteControl = Offset(endCorridorX, routeY);
      final secondControl = Offset(end.dx - lead * direction * .72, end.dy);
      final detourSamples = <Offset>[
        for (var step = 0; step <= 18; step++)
          _cubicPoint(
            start,
            firstControl,
            firstRouteControl,
            midpoint,
            step / 18,
          ),
        for (var step = 1; step <= 18; step++)
          _cubicPoint(
            midpoint,
            secondRouteControl,
            secondControl,
            end,
            step / 18,
          ),
      ];
      if (_polylineIntersectsNode(detourSamples, startId, endId)) continue;
      return Path()
        ..moveTo(start.dx, start.dy)
        ..cubicTo(
          firstControl.dx,
          firstControl.dy,
          firstRouteControl.dx,
          firstRouteControl.dy,
          midpoint.dx,
          midpoint.dy,
        )
        ..cubicTo(
          secondRouteControl.dx,
          secondRouteControl.dy,
          secondControl.dx,
          secondControl.dy,
          end.dx,
          end.dy,
        );
    }
    return _roundedPolylinePath([
      start,
      Offset(startCorridorX, start.dy),
      Offset(startCorridorX, fallbackRouteY),
      Offset(endCorridorX, fallbackRouteY),
      Offset(endCorridorX, end.dy),
      end,
    ], compact ? 22 : 30);
  }

  Path _roundedPolylinePath(List<Offset> points, double radius) {
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (var index = 1; index < points.length - 1; index++) {
      final previous = points[index - 1];
      final corner = points[index];
      final next = points[index + 1];
      final incoming = corner - previous;
      final outgoing = next - corner;
      if (incoming.distance < .01 || outgoing.distance < .01) {
        path.lineTo(corner.dx, corner.dy);
        continue;
      }
      final cornerRadius = math.min(
        radius,
        math.min(incoming.distance / 2, outgoing.distance / 2),
      );
      final before = corner - incoming / incoming.distance * cornerRadius;
      final after = corner + outgoing / outgoing.distance * cornerRadius;
      path
        ..lineTo(before.dx, before.dy)
        ..quadraticBezierTo(corner.dx, corner.dy, after.dx, after.dy);
    }
    return path..lineTo(points.last.dx, points.last.dy);
  }

  Offset _cubicPoint(
    Offset start,
    Offset firstControl,
    Offset secondControl,
    Offset end,
    double t,
  ) {
    final inverse = 1 - t;
    return start * (inverse * inverse * inverse) +
        firstControl * (3 * inverse * inverse * t) +
        secondControl * (3 * inverse * t * t) +
        end * (t * t * t);
  }

  double get sizeCenterY {
    if (positions.isEmpty) return 0;
    return positions.values.map((point) => point.dy).reduce((a, b) => a + b) /
        positions.length;
  }

  @override
  void paint(Canvas canvas, Size size) {
    for (final edge in edges) {
      final startCenter = positions[edge.from];
      final endCenter = positions[edge.to];
      if (startCenter == null || endCenter == null) continue;
      final start = _boundaryPoint(startCenter, endCenter, edge.from);
      final end = _boundaryPoint(endCenter, startCenter, edge.to);
      final highlighted = hoveredId == edge.from || hoveredId == edge.to;
      final target = nodes[edge.to];
      final color = _nodeColor(target?.status ?? 'unseen');
      final path = _edgePath(start, end, edge.from, edge.to);
      canvas.drawPath(
        path,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeWidth = highlighted ? 2.7 : 1.35
          ..color = color.withValues(alpha: highlighted ? .92 : .44),
      );
      if (highlighted) {
        canvas.drawCircle(end, 2.8, Paint()..color = color);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _MindMapEdgePainter oldDelegate) =>
      oldDelegate.positions != positions ||
      oldDelegate.hoveredId != hoveredId ||
      oldDelegate.edges != edges ||
      oldDelegate.compact != compact;
}

Color _nodeColor(String status) => switch (status) {
  'course' => const Color(0xFFF1C75B),
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
    final detail = node.isCourse
        ? '课程节点'
        : node.masteryLevel == null
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
