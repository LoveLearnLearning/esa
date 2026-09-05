import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../models/models.dart';
import '../../theme/esa_context.dart';

enum KnowledgeGraphLayoutDirection { horizontal, vertical }

class KnowledgeGraphCanvas extends StatefulWidget {
  const KnowledgeGraphCanvas({
    super.key,
    required this.visibleNodes,
    required this.edges,
    required this.onNodeTap,
    this.persistenceKey,
  });

  final List<KnowledgeMapNode> visibleNodes;
  final List<KnowledgeMapEdge> edges;
  final ValueChanged<KnowledgeMapNode> onNodeTap;
  final String? persistenceKey;

  @override
  State<KnowledgeGraphCanvas> createState() => _KnowledgeGraphCanvasState();
}

class _KnowledgeGraphCanvasState extends State<KnowledgeGraphCanvas>
    with SingleTickerProviderStateMixin {
  final TransformationController _transform = TransformationController();
  late final AnimationController _layoutAnimation = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 280),
    value: 1,
  );

  KnowledgeGraphLayoutDirection _direction =
      KnowledgeGraphLayoutDirection.horizontal;
  final Set<String> _collapsedIds = {};
  final Map<String, Offset> _manualOffsets = {};
  String? _hoveredId;
  String? _selectedId;
  Map<String, Offset> _animationFrom = const {};
  Map<String, Offset> _lastDrawnPositions = const {};
  int? _layoutSignature;
  _MindMapLayout? _cachedLayout;
  int? _lastFitSignature;
  Size _viewportSize = Size.zero;
  Size _canvasSize = Size.zero;
  Rect _contentBounds = Rect.zero;

  String get _preferencePrefix =>
      'esa.knowledge_graph.${widget.persistenceKey ?? 'default'}';

  @override
  void initState() {
    super.initState();
    _loadPreferences();
  }

  @override
  void didUpdateWidget(covariant KnowledgeGraphCanvas oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.persistenceKey != widget.persistenceKey) {
      _collapsedIds.clear();
      _manualOffsets.clear();
      _selectedId = null;
      _invalidateLayout();
      _loadPreferences();
      return;
    }
    if (oldWidget.visibleNodes != widget.visibleNodes ||
        oldWidget.edges != widget.edges) {
      final ids = widget.visibleNodes.map((node) => node.id).toSet();
      _collapsedIds.removeWhere((id) => !ids.contains(id));
      _manualOffsets.removeWhere((id, _) => !ids.contains(id));
      if (!ids.contains(_selectedId)) _selectedId = null;
      _invalidateLayout();
    }
  }

  @override
  void dispose() {
    _layoutAnimation.dispose();
    _transform.dispose();
    super.dispose();
  }

  Future<void> _loadPreferences() async {
    try {
      final preferences = await SharedPreferences.getInstance();
      final direction = preferences.getString('$_preferencePrefix.direction');
      final collapsed =
          preferences.getStringList('$_preferencePrefix.collapsed') ?? const [];
      if (!mounted) return;
      setState(() {
        _direction = direction == 'vertical'
            ? KnowledgeGraphLayoutDirection.vertical
            : KnowledgeGraphLayoutDirection.horizontal;
        _collapsedIds
          ..clear()
          ..addAll(collapsed);
        _invalidateLayout();
      });
    } catch (_) {
      // Local persistence is optional. The graph remains fully usable.
    }
  }

  Future<void> _savePreferences() async {
    try {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setString(
        '$_preferencePrefix.direction',
        _direction.name,
      );
      await preferences.setStringList(
        '$_preferencePrefix.collapsed',
        _collapsedIds.toList()..sort(),
      );
    } catch (_) {
      // Ignore unavailable platform storage during hot restart and tests.
    }
  }

  void _invalidateLayout() {
    _layoutSignature = null;
    _cachedLayout = null;
    _lastFitSignature = null;
  }

  void _beginLayoutMutation(VoidCallback mutation) {
    _animationFrom = Map<String, Offset>.from(_lastDrawnPositions);
    setState(() {
      mutation();
      _invalidateLayout();
    });
    _layoutAnimation.forward(from: 0);
  }

  void _setDirection(KnowledgeGraphLayoutDirection direction) {
    if (_direction == direction) return;
    _beginLayoutMutation(() {
      _direction = direction;
      _manualOffsets.clear();
    });
    _savePreferences();
  }

  void _autoArrange() {
    _beginLayoutMutation(_manualOffsets.clear);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _fitGraph();
    });
  }

  void _toggleCollapsed(String nodeId) {
    _beginLayoutMutation(() {
      if (!_collapsedIds.add(nodeId)) _collapsedIds.remove(nodeId);
    });
    _savePreferences();
  }

  void _dragNode(String nodeId, Offset screenDelta) {
    if (_layoutAnimation.isAnimating) _layoutAnimation.stop();
    final scale = _transform.value.getMaxScaleOnAxis();
    setState(() {
      _manualOffsets[nodeId] =
          (_manualOffsets[nodeId] ?? Offset.zero) + screenDelta / scale;
    });
  }

  void _scheduleInitialFit(_MindMapLayout layout, Size viewport) {
    final signature = Object.hash(
      layout.size.width.round(),
      layout.size.height.round(),
      viewport.width.round(),
      viewport.height.round(),
      _direction,
      Object.hashAll(layout.positions.keys),
    );
    _viewportSize = viewport;
    _canvasSize = layout.size;
    _contentBounds = layout.contentBounds;
    if (_lastFitSignature == signature) return;
    _lastFitSignature = signature;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _fitGraph();
    });
  }

  void _fitGraph() {
    if (_viewportSize.isEmpty || _canvasSize.isEmpty) return;
    final bounds = _contentBounds.isEmpty
        ? Offset.zero & _canvasSize
        : _contentBounds;
    final scale = math
        .min(
          (_viewportSize.width - 32) / bounds.width,
          (_viewportSize.height - 32) / bounds.height,
        )
        .clamp(.18, 1.0)
        .toDouble();
    final dx =
        (_viewportSize.width - bounds.width * scale) / 2 - bounds.left * scale;
    final dy =
        (_viewportSize.height - bounds.height * scale) / 2 - bounds.top * scale;
    _transform.value = Matrix4.identity()
      ..translateByDouble(dx, dy, 0, 1)
      ..scaleByDouble(scale, scale, scale, 1);
  }

  void _centerRoot(_MindMapLayout layout) {
    final root = layout.positions[layout.rootId];
    if (root == null || _viewportSize.isEmpty) return;
    final scale = _transform.value.getMaxScaleOnAxis().clamp(.5, 1.25);
    final viewportCenter = Offset(
      _viewportSize.width / 2,
      _viewportSize.height / 2,
    );
    final translation = viewportCenter - root * scale;
    _transform.value = Matrix4.identity()
      ..translateByDouble(translation.dx, translation.dy, 0, 1)
      ..scaleByDouble(scale, scale, scale, 1);
  }

  void _setScale(double requested) {
    if (_viewportSize.isEmpty) return;
    final oldScale = _transform.value.getMaxScaleOnAxis();
    final newScale = requested.clamp(.18, 2.4).toDouble();
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

  _MindMapLayout _layoutFor(
    Size viewport, {
    required bool compact,
    required _GraphProjection projection,
  }) {
    final signature = Object.hash(
      viewport.width.round(),
      viewport.height.round(),
      compact,
      _direction,
      Object.hashAll(
        projection.nodes.map(
          (node) => Object.hash(node.id, node.level, node.category, node.name),
        ),
      ),
      Object.hashAll(
        projection.edges.map(
          (edge) => Object.hash(edge.from, edge.to, edge.type),
        ),
      ),
    );
    if (_layoutSignature == signature && _cachedLayout != null) {
      return _cachedLayout!;
    }
    final layout = _MindMapLayout.calculate(
      nodes: projection.nodes,
      edges: projection.edges,
      minimumSize: viewport,
      compact: compact,
      direction: _direction,
    );
    _layoutSignature = signature;
    _cachedLayout = layout;
    return layout;
  }

  Map<String, Offset> _animatedPositions(_MindMapLayout layout) {
    final target = <String, Offset>{
      for (final entry in layout.positions.entries)
        entry.key: entry.value + (_manualOffsets[entry.key] ?? Offset.zero),
    };
    if (!_layoutAnimation.isAnimating && _layoutAnimation.value == 1) {
      _lastDrawnPositions = target;
      return target;
    }
    final t = Curves.easeInOutCubic.transform(_layoutAnimation.value);
    final positions = <String, Offset>{
      for (final entry in target.entries)
        entry.key: Offset.lerp(
          _animationFrom[entry.key] ?? entry.value,
          entry.value,
          t,
        )!,
    };
    _lastDrawnPositions = positions;
    return positions;
  }

  @override
  Widget build(BuildContext context) {
    if (widget.visibleNodes.isEmpty) {
      return const Center(child: Text('当前筛选条件下没有知识点'));
    }
    return AnimatedBuilder(
      animation: _layoutAnimation,
      builder: (context, _) => LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 700;
          final viewport = Size(
            constraints.maxWidth,
            constraints.maxHeight.isFinite ? constraints.maxHeight : 560,
          );
          final fullTree = _GraphTree.build(widget.visibleNodes, widget.edges);
          final projection = _GraphProjection.fromTree(
            nodes: widget.visibleNodes,
            edges: widget.edges,
            tree: fullTree,
            collapsedIds: _collapsedIds,
          );
          final layout = _layoutFor(
            viewport,
            compact: compact,
            projection: projection,
          );
          _scheduleInitialFit(layout, viewport);
          final positions = _animatedPositions(layout);
          final selectedNode = projection.byId[_selectedId];

          return ClipRect(
            child: Stack(
              children: [
                const Positioned.fill(
                  child: CustomPaint(painter: _DotBackgroundPainter()),
                ),
                InteractiveViewer(
                  transformationController: _transform,
                  constrained: false,
                  minScale: .18,
                  maxScale: 2.4,
                  boundaryMargin: const EdgeInsets.all(1200),
                  trackpadScrollCausesScale: true,
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: () => setState(() => _selectedId = null),
                    child: SizedBox(
                      width: layout.size.width,
                      height: layout.size.height,
                      child: Stack(
                        clipBehavior: Clip.none,
                        children: [
                          Positioned.fill(
                            child: CustomPaint(
                              key: ValueKey(
                                'knowledge-tree-edge-count-${projection.edges.length}',
                              ),
                              painter: _MindMapEdgePainter(
                                positions: positions,
                                sizes: layout.nodeSizes,
                                edges: projection.edges,
                                hoveredId: _hoveredId,
                                selectedId: _selectedId,
                                direction: _direction,
                              ),
                            ),
                          ),
                          for (final node in projection.nodes)
                            _nodeAt(
                              node,
                              positions[node.id]!,
                              size: layout.nodeSizes[node.id]!,
                              depth: layout.depths[node.id] ?? node.level,
                              childCount:
                                  fullTree.children[node.id]?.length ?? 0,
                              collapsed: _collapsedIds.contains(node.id),
                              compact: compact,
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
                Positioned(
                  left: compact ? 10 : 14,
                  top: compact ? 10 : 14,
                  child: _GraphToolbar(
                    direction: _direction,
                    onDirectionChanged: _setDirection,
                    onAutoArrange: _autoArrange,
                    onCenterRoot: () => _centerRoot(layout),
                  ),
                ),
                if (!compact)
                  const Positioned(left: 14, bottom: 14, child: _GraphLegend()),
                if (!compact && selectedNode != null)
                  Positioned(
                    key: const ValueKey('knowledge-node-inspector'),
                    right: 14,
                    top: 14,
                    child: _NodeInspector(
                      node: selectedNode,
                      depth:
                          layout.depths[selectedNode.id] ?? selectedNode.level,
                      childCount:
                          fullTree.children[selectedNode.id]?.length ?? 0,
                      onOpen: () => widget.onNodeTap(selectedNode),
                      onClose: () => setState(() => _selectedId = null),
                    ),
                  ),
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
      ),
    );
  }

  Widget _nodeAt(
    KnowledgeMapNode node,
    Offset point, {
    required Size size,
    required int depth,
    required int childCount,
    required bool collapsed,
    required bool compact,
  }) {
    return Positioned(
      key: ValueKey('knowledge-graph-node-${node.id}'),
      left: point.dx - size.width / 2,
      top: point.dy - size.height / 2,
      width: size.width,
      height: size.height,
      child: MouseRegion(
        cursor: SystemMouseCursors.move,
        onEnter: (_) => setState(() => _hoveredId = node.id),
        onExit: (_) {
          if (_hoveredId == node.id) setState(() => _hoveredId = null);
        },
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onPanUpdate: (details) => _dragNode(node.id, details.delta),
          child: _MindMapNode(
            node: node,
            depth: depth,
            hovered: _hoveredId == node.id,
            selected: _selectedId == node.id,
            childCount: childCount,
            collapsed: collapsed,
            direction: _direction,
            compact: compact,
            onTap: () {
              setState(() => _selectedId = node.id);
              widget.onNodeTap(node);
            },
            onOpen: () => widget.onNodeTap(node),
            onToggleCollapsed: childCount == 0
                ? null
                : () => _toggleCollapsed(node.id),
          ),
        ),
      ),
    );
  }
}

class _GraphProjection {
  const _GraphProjection({
    required this.nodes,
    required this.edges,
    required this.byId,
  });

  final List<KnowledgeMapNode> nodes;
  final List<KnowledgeMapEdge> edges;
  final Map<String, KnowledgeMapNode> byId;

  factory _GraphProjection.fromTree({
    required List<KnowledgeMapNode> nodes,
    required List<KnowledgeMapEdge> edges,
    required _GraphTree tree,
    required Set<String> collapsedIds,
  }) {
    final hidden = <String>{};
    void hideDescendants(String id) {
      for (final child in tree.children[id] ?? const <String>[]) {
        if (!hidden.add(child)) continue;
        hideDescendants(child);
      }
    }

    for (final id in collapsedIds) {
      if (tree.byId.containsKey(id)) hideDescendants(id);
    }
    final visibleNodes = nodes
        .where((node) => !hidden.contains(node.id))
        .toList();
    final visibleIds = visibleNodes.map((node) => node.id).toSet();
    final originalByPair = <String, KnowledgeMapEdge>{};
    for (final edge in edges) {
      originalByPair.putIfAbsent('${edge.from}\u0000${edge.to}', () => edge);
    }
    final visibleEdges = <KnowledgeMapEdge>[];
    for (final parent in tree.children.entries) {
      if (!visibleIds.contains(parent.key)) continue;
      for (final child in parent.value) {
        if (!visibleIds.contains(child)) continue;
        visibleEdges.add(
          originalByPair['${parent.key}\u0000$child'] ??
              KnowledgeMapEdge(from: parent.key, to: child, type: 'tree'),
        );
      }
    }
    return _GraphProjection(
      nodes: visibleNodes,
      edges: visibleEdges,
      byId: {for (final node in visibleNodes) node.id: node},
    );
  }
}

class _GraphTree {
  const _GraphTree({
    required this.rootId,
    required this.byId,
    required this.children,
    required this.depths,
  });

  final String rootId;
  final Map<String, KnowledgeMapNode> byId;
  final Map<String, List<String>> children;
  final Map<String, int> depths;

  factory _GraphTree.build(
    List<KnowledgeMapNode> nodes,
    List<KnowledgeMapEdge> edges,
  ) {
    final byId = {for (final node in nodes) node.id: node};
    final outgoing = {for (final node in nodes) node.id: <String>[]};
    final incomingCount = {for (final node in nodes) node.id: 0};
    for (final edge in edges) {
      if (!byId.containsKey(edge.from) || !byId.containsKey(edge.to)) continue;
      outgoing[edge.from]!.add(edge.to);
      incomingCount[edge.to] = incomingCount[edge.to]! + 1;
    }
    for (final values in outgoing.values) {
      values.sort((a, b) => byId[a]!.name.compareTo(byId[b]!.name));
    }
    final courseRoot = nodes.where((node) => node.isCourse).firstOrNull;
    final roots = nodes.where((node) => incomingCount[node.id] == 0).toList()
      ..sort((a, b) {
        final level = a.level.compareTo(b.level);
        return level != 0 ? level : a.name.compareTo(b.name);
      });
    final root = courseRoot ?? roots.firstOrNull ?? nodes.first;
    final parentIds = <String>{root.id};
    final children = {for (final node in nodes) node.id: <String>[]};
    final depths = <String, int>{root.id: 0};

    void attachComponent(String componentRoot, String? parentId) {
      if (parentId != null) {
        children[parentId]!.add(componentRoot);
        depths[componentRoot] = depths[parentId]! + 1;
      }
      final queue = <String>[componentRoot];
      for (var index = 0; index < queue.length; index++) {
        final current = queue[index];
        for (final child in outgoing[current]!) {
          if (!parentIds.add(child)) continue;
          children[current]!.add(child);
          depths[child] = depths[current]! + 1;
          queue.add(child);
        }
      }
    }

    attachComponent(root.id, null);
    for (final node in nodes) {
      if (!parentIds.add(node.id)) continue;
      attachComponent(node.id, root.id);
    }
    for (final values in children.values) {
      values.sort((a, b) => byId[a]!.name.compareTo(byId[b]!.name));
    }
    return _GraphTree(
      rootId: root.id,
      byId: byId,
      children: children,
      depths: depths,
    );
  }
}

Size _mindMapNodeSize({required int depth, required bool compact}) {
  if (depth == 0) return Size(compact ? 162 : 196, compact ? 70 : 78);
  if (depth == 1) return Size(compact ? 148 : 174, compact ? 64 : 68);
  return Size(compact ? 136 : 158, compact ? 60 : 64);
}

class _MindMapLayout {
  const _MindMapLayout({
    required this.size,
    required this.positions,
    required this.nodeSizes,
    required this.rootId,
    required this.depths,
    required this.branchRootById,
    required this.contentBounds,
  });

  final Size size;
  final Map<String, Offset> positions;
  final Map<String, Size> nodeSizes;
  final String rootId;
  final Map<String, int> depths;
  final Map<String, String> branchRootById;
  final Rect contentBounds;

  static _MindMapLayout calculate({
    required List<KnowledgeMapNode> nodes,
    required List<KnowledgeMapEdge> edges,
    required Size minimumSize,
    required bool compact,
    required KnowledgeGraphLayoutDirection direction,
  }) {
    final tree = _GraphTree.build(nodes, edges);
    final nodeSizes = <String, Size>{
      for (final node in nodes)
        node.id: _mindMapNodeSize(
          depth: tree.depths[node.id] ?? node.level,
          compact: compact,
        ),
    };
    final branchRootById = <String, String>{tree.rootId: tree.rootId};
    void assignBranch(String id, String branchRoot) {
      branchRootById[id] = branchRoot;
      for (final child in tree.children[id] ?? const <String>[]) {
        assignBranch(child, branchRoot);
      }
    }

    for (final child in tree.children[tree.rootId] ?? const <String>[]) {
      assignBranch(child, child);
    }

    final leafSpan = compact ? 76.0 : 88.0;
    final depthSpan = compact ? 224.0 : 272.0;
    final sidePadding = compact ? 112.0 : 142.0;
    final crossPadding = compact ? 94.0 : 124.0;
    var nextLeaf = 0.0;
    final cross = <String, double>{};

    double place(String id) {
      final children = tree.children[id] ?? const <String>[];
      if (children.isEmpty) {
        final value = nextLeaf;
        nextLeaf += leafSpan;
        cross[id] = value;
        return value;
      }
      final first = place(children.first);
      var last = first;
      for (final child in children.skip(1)) {
        last = place(child);
      }
      final value = (first + last) / 2;
      cross[id] = value;
      return value;
    }

    place(tree.rootId);
    final maxDepth = tree.depths.values.fold<int>(0, math.max);
    final crossExtent = math.max(0.0, nextLeaf - leafSpan);
    final positions = <String, Offset>{};
    if (direction == KnowledgeGraphLayoutDirection.horizontal) {
      for (final node in nodes) {
        positions[node.id] = Offset(
          sidePadding + (tree.depths[node.id] ?? 0) * depthSpan,
          crossPadding + (cross[node.id] ?? 0),
        );
      }
    } else {
      for (final node in nodes) {
        positions[node.id] = Offset(
          crossPadding + (cross[node.id] ?? 0),
          sidePadding + (tree.depths[node.id] ?? 0) * (compact ? 134 : 154),
        );
      }
    }
    final largestWidth = nodeSizes.values
        .map((size) => size.width)
        .fold<double>(0, math.max);
    final largestHeight = nodeSizes.values
        .map((size) => size.height)
        .fold<double>(0, math.max);
    final calculatedWidth =
        direction == KnowledgeGraphLayoutDirection.horizontal
        ? sidePadding * 2 + maxDepth * depthSpan + largestWidth
        : crossPadding * 2 + crossExtent + largestWidth;
    final calculatedHeight =
        direction == KnowledgeGraphLayoutDirection.horizontal
        ? crossPadding * 2 + crossExtent + largestHeight
        : sidePadding * 2 + maxDepth * (compact ? 134 : 154) + largestHeight;
    var contentBounds = Rect.zero;
    for (final node in nodes) {
      final bounds = Rect.fromCenter(
        center: positions[node.id]!,
        width: nodeSizes[node.id]!.width,
        height: nodeSizes[node.id]!.height,
      );
      contentBounds = contentBounds.isEmpty
          ? bounds
          : contentBounds.expandToInclude(bounds);
    }
    contentBounds = contentBounds.inflate(compact ? 22 : 30);
    return _MindMapLayout(
      size: Size(
        math.max(minimumSize.width, calculatedWidth),
        math.max(minimumSize.height, calculatedHeight),
      ),
      positions: positions,
      nodeSizes: nodeSizes,
      rootId: tree.rootId,
      depths: tree.depths,
      branchRootById: branchRootById,
      contentBounds: contentBounds,
    );
  }
}

class _DotBackgroundPainter extends CustomPainter {
  const _DotBackgroundPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xFF030303),
    );
    final paint = Paint()..color = const Color(0xFF2B2B30);
    for (double x = 14; x < size.width; x += 28) {
      for (double y = 14; y < size.height; y += 28) {
        canvas.drawCircle(Offset(x, y), .72, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DotBackgroundPainter oldDelegate) => false;
}

class _MindMapEdgePainter extends CustomPainter {
  const _MindMapEdgePainter({
    required this.positions,
    required this.sizes,
    required this.edges,
    required this.hoveredId,
    required this.selectedId,
    required this.direction,
  });

  final Map<String, Offset> positions;
  final Map<String, Size> sizes;
  final List<KnowledgeMapEdge> edges;
  final String? hoveredId;
  final String? selectedId;
  final KnowledgeGraphLayoutDirection direction;

  Offset _boundaryPoint(Offset center, Offset toward, String nodeId) {
    final delta = toward - center;
    if (delta.distanceSquared < .01) return center;
    final size = sizes[nodeId] ?? const Size(150, 64);
    final xScale = delta.dx.abs() < .001
        ? double.infinity
        : size.width / 2 / delta.dx.abs();
    final yScale = delta.dy.abs() < .001
        ? double.infinity
        : size.height / 2 / delta.dy.abs();
    return center + delta * math.min(xScale, yScale);
  }

  Path _edgePath(Offset start, Offset end) {
    if (direction == KnowledgeGraphLayoutDirection.horizontal) {
      final middleX = (start.dx + end.dx) / 2;
      final verticalDirection = end.dy >= start.dy ? 1.0 : -1.0;
      final radius = math.min(12.0, (end.dy - start.dy).abs() / 2);
      return Path()
        ..moveTo(start.dx, start.dy)
        ..lineTo(middleX - 8, start.dy)
        ..quadraticBezierTo(
          middleX,
          start.dy,
          middleX,
          start.dy + radius * verticalDirection,
        )
        ..lineTo(middleX, end.dy - radius * verticalDirection)
        ..quadraticBezierTo(middleX, end.dy, middleX + 8, end.dy)
        ..lineTo(end.dx, end.dy);
    }
    final middleY = (start.dy + end.dy) / 2;
    final horizontalDirection = end.dx >= start.dx ? 1.0 : -1.0;
    final radius = math.min(12.0, (end.dx - start.dx).abs() / 2);
    return Path()
      ..moveTo(start.dx, start.dy)
      ..lineTo(start.dx, middleY - 8)
      ..quadraticBezierTo(
        start.dx,
        middleY,
        start.dx + radius * horizontalDirection,
        middleY,
      )
      ..lineTo(end.dx - radius * horizontalDirection, middleY)
      ..quadraticBezierTo(end.dx, middleY, end.dx, middleY + 8)
      ..lineTo(end.dx, end.dy);
  }

  @override
  void paint(Canvas canvas, Size size) {
    for (final edge in edges) {
      final startCenter = positions[edge.from];
      final endCenter = positions[edge.to];
      if (startCenter == null || endCenter == null) continue;
      final start = _boundaryPoint(startCenter, endCenter, edge.from);
      final end = _boundaryPoint(endCenter, startCenter, edge.to);
      final connected =
          hoveredId == edge.from ||
          hoveredId == edge.to ||
          selectedId == edge.from ||
          selectedId == edge.to;
      final color = connected
          ? const Color(0xFFE2E2E7)
          : const Color(0xFF68686F);
      canvas.drawPath(
        _edgePath(start, end),
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeWidth = connected ? 2.2 : 1.35
          ..color = color.withValues(alpha: connected ? .94 : .58),
      );
      canvas.drawCircle(
        end,
        connected ? 3 : 2,
        Paint()..color = color.withValues(alpha: connected ? 1 : .72),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _MindMapEdgePainter oldDelegate) =>
      oldDelegate.positions != positions ||
      oldDelegate.hoveredId != hoveredId ||
      oldDelegate.selectedId != selectedId ||
      oldDelegate.edges != edges ||
      oldDelegate.direction != direction;
}

Color _nodeColor(String status) => switch (status) {
  'course' => const Color(0xFFE7E7EA),
  'mastered' || 'good' => const Color(0xFF61AA67),
  'weak' => const Color(0xFFD68A45),
  'learning' => const Color(0xFFB6B6BD),
  _ => const Color(0xFF77777F),
};

String _statusLabel(KnowledgeMapNode node) {
  if (node.isCourse) return '课程中心';
  return switch (node.status) {
    'mastered' => '稳定掌握',
    'good' => '掌握较好',
    'weak' => '需要加强',
    'learning' => '学习中',
    _ => '未评估',
  };
}

class _MindMapNode extends StatelessWidget {
  const _MindMapNode({
    required this.node,
    required this.depth,
    required this.hovered,
    required this.selected,
    required this.childCount,
    required this.collapsed,
    required this.direction,
    required this.compact,
    required this.onTap,
    required this.onOpen,
    required this.onToggleCollapsed,
  });

  final KnowledgeMapNode node;
  final int depth;
  final bool hovered;
  final bool selected;
  final int childCount;
  final bool collapsed;
  final KnowledgeGraphLayoutDirection direction;
  final bool compact;
  final VoidCallback onTap;
  final VoidCallback onOpen;
  final VoidCallback? onToggleCollapsed;

  @override
  Widget build(BuildContext context) {
    final color = _nodeColor(node.status);
    final root = depth == 0;
    final firstLevel = depth == 1;
    final foreground = root ? const Color(0xFF080808) : Colors.white;
    final surface = root
        ? const Color(0xFFE7E7EA)
        : selected || hovered
        ? const Color(0xFF18181B)
        : firstLevel
        ? const Color(0xFF111113)
        : const Color(0xFF0B0B0C);

    return Stack(
      clipBehavior: Clip.none,
      children: [
        Positioned.fill(
          child: Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: onTap,
              borderRadius: BorderRadius.circular(8),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 140),
                padding: EdgeInsets.fromLTRB(
                  root ? 16 : 12,
                  9,
                  selected && !compact ? 38 : 12,
                  9,
                ),
                decoration: BoxDecoration(
                  color: surface,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: root
                        ? const Color(0xFFE7E7EA)
                        : selected
                        ? const Color(0xFFE7E7EA)
                        : hovered
                        ? const Color(0xFF66666D)
                        : const Color(0xFF2A2A2E),
                    width: selected || root ? 2 : 1,
                  ),
                ),
                child: Row(
                  children: [
                    if (!root) ...[
                      Container(
                        width: 3,
                        height: firstLevel ? 34 : 28,
                        decoration: BoxDecoration(
                          color: color,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                      const SizedBox(width: 10),
                    ],
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
                              color: foreground,
                              fontSize: root
                                  ? 16
                                  : firstLevel
                                  ? 13.5
                                  : 12.5,
                              fontWeight: root
                                  ? FontWeight.w700
                                  : FontWeight.w600,
                              height: 1.18,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            node.masteryLevel == null
                                ? _statusLabel(node)
                                : '${_statusLabel(node)} · ${node.masteryLevel!.round()}%',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: root
                                  ? const Color(0xFF4D4D52)
                                  : color.withValues(alpha: .96),
                              fontSize: root ? 10.5 : 9.5,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        if (selected && !compact)
          Positioned(
            right: 5,
            top: 5,
            child: _NodeActionButton(
              tooltip: '查看详情',
              icon: LucideIcons.panelRightOpen,
              onPressed: onOpen,
              darkIcon: root,
            ),
          ),
        if (onToggleCollapsed != null)
          Positioned(
            key: ValueKey('knowledge-collapse-${node.id}'),
            right: direction == KnowledgeGraphLayoutDirection.horizontal
                ? 0
                : null,
            left: direction == KnowledgeGraphLayoutDirection.vertical
                ? (compact ? 55 : 66)
                : null,
            bottom: direction == KnowledgeGraphLayoutDirection.vertical
                ? 0
                : null,
            top: direction == KnowledgeGraphLayoutDirection.horizontal
                ? (compact ? 18 : 21)
                : null,
            child: Tooltip(
              message: collapsed ? '展开 $childCount 个分支' : '折叠分支',
              child: Material(
                color: const Color(0xFF171719),
                shape: const CircleBorder(
                  side: BorderSide(color: Color(0xFF3A3A3F)),
                ),
                child: InkWell(
                  customBorder: const CircleBorder(),
                  onTap: onToggleCollapsed,
                  child: SizedBox(
                    width: 26,
                    height: 26,
                    child: Icon(
                      collapsed ? LucideIcons.plus : LucideIcons.minus,
                      size: 14,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _NodeActionButton extends StatelessWidget {
  const _NodeActionButton({
    required this.tooltip,
    required this.icon,
    required this.onPressed,
    this.darkIcon = false,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback onPressed;
  final bool darkIcon;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: tooltip,
    child: Material(
      color: darkIcon ? const Color(0x22000000) : const Color(0xFF242428),
      borderRadius: BorderRadius.circular(5),
      child: InkWell(
        borderRadius: BorderRadius.circular(5),
        onTap: onPressed,
        child: SizedBox(
          width: 28,
          height: 28,
          child: Icon(
            icon,
            size: 15,
            color: darkIcon ? const Color(0xFF202024) : Colors.white,
          ),
        ),
      ),
    ),
  );
}

class _GraphToolbar extends StatelessWidget {
  const _GraphToolbar({
    required this.direction,
    required this.onDirectionChanged,
    required this.onAutoArrange,
    required this.onCenterRoot,
  });

  final KnowledgeGraphLayoutDirection direction;
  final ValueChanged<KnowledgeGraphLayoutDirection> onDirectionChanged;
  final VoidCallback onAutoArrange;
  final VoidCallback onCenterRoot;

  @override
  Widget build(BuildContext context) => Container(
    height: 42,
    padding: const EdgeInsets.all(4),
    decoration: BoxDecoration(
      color: const Color(0xF20A0A0B),
      border: Border.all(color: const Color(0xFF29292D)),
      borderRadius: BorderRadius.circular(8),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _ToolbarButton(
          key: const ValueKey('knowledge-layout-horizontal'),
          tooltip: '从左到右布局',
          icon: LucideIcons.gitBranch,
          selected: direction == KnowledgeGraphLayoutDirection.horizontal,
          onPressed: () =>
              onDirectionChanged(KnowledgeGraphLayoutDirection.horizontal),
        ),
        _ToolbarButton(
          key: const ValueKey('knowledge-layout-vertical'),
          tooltip: '从上到下布局',
          icon: LucideIcons.listTree,
          selected: direction == KnowledgeGraphLayoutDirection.vertical,
          onPressed: () =>
              onDirectionChanged(KnowledgeGraphLayoutDirection.vertical),
        ),
        const _ToolbarDivider(),
        _ToolbarButton(
          key: const ValueKey('knowledge-auto-layout'),
          tooltip: '自动整理',
          icon: LucideIcons.wandSparkles,
          onPressed: onAutoArrange,
        ),
        _ToolbarButton(
          tooltip: '定位中心主题',
          icon: LucideIcons.locateFixed,
          onPressed: onCenterRoot,
        ),
      ],
    ),
  );
}

class _ToolbarButton extends StatelessWidget {
  const _ToolbarButton({
    super.key,
    required this.tooltip,
    required this.icon,
    required this.onPressed,
    this.selected = false,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback onPressed;
  final bool selected;

  @override
  Widget build(BuildContext context) => Tooltip(
    message: tooltip,
    child: Material(
      color: selected ? const Color(0xFF29292E) : Colors.transparent,
      borderRadius: BorderRadius.circular(5),
      child: InkWell(
        borderRadius: BorderRadius.circular(5),
        onTap: onPressed,
        child: SizedBox(
          width: 34,
          height: 34,
          child: Icon(
            icon,
            size: 17,
            color: selected ? Colors.white : const Color(0xFFAAAAAF),
          ),
        ),
      ),
    ),
  );
}

class _ToolbarDivider extends StatelessWidget {
  const _ToolbarDivider();

  @override
  Widget build(BuildContext context) => const SizedBox(
    width: 9,
    height: 22,
    child: Center(child: VerticalDivider(width: 1, color: Color(0xFF303034))),
  );
}

class _NodeInspector extends StatelessWidget {
  const _NodeInspector({
    required this.node,
    required this.depth,
    required this.childCount,
    required this.onOpen,
    required this.onClose,
  });

  final KnowledgeMapNode node;
  final int depth;
  final int childCount;
  final VoidCallback onOpen;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final color = _nodeColor(node.status);
    return Container(
      width: 248,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xF20A0A0B),
        border: Border.all(color: const Color(0xFF29292D)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  depth == 0 ? '中心主题' : '已选知识点',
                  style: const TextStyle(
                    color: Color(0xFF929299),
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              InkResponse(
                radius: 18,
                onTap: onClose,
                child: const Padding(
                  padding: EdgeInsets.all(4),
                  child: Icon(
                    LucideIcons.x,
                    size: 15,
                    color: Color(0xFF929299),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            node.name,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 16,
              fontWeight: FontWeight.w700,
              height: 1.25,
            ),
          ),
          const SizedBox(height: 12),
          _InspectorRow(label: '所属课程', value: node.course),
          _InspectorRow(label: '层级', value: depth == 0 ? '根节点' : '$depth 级'),
          _InspectorRow(label: '子节点', value: '$childCount'),
          _InspectorRow(
            label: '掌握状态',
            value: node.masteryLevel == null
                ? _statusLabel(node)
                : '${node.masteryLevel!.round()}%',
            valueColor: color,
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: onOpen,
              icon: const Icon(LucideIcons.panelRightOpen, size: 16),
              label: Text(node.isCourse ? '查看课程概览' : '查看学习详情'),
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFE7E7EA),
                foregroundColor: const Color(0xFF080808),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(6),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _InspectorRow extends StatelessWidget {
  const _InspectorRow({
    required this.label,
    required this.value,
    this.valueColor,
  });

  final String label;
  final String value;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 7),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 64,
          child: Text(
            label,
            style: const TextStyle(color: Color(0xFF77777E), fontSize: 11),
          ),
        ),
        Expanded(
          child: Text(
            value,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.right,
            style: TextStyle(
              color: valueColor ?? const Color(0xFFD8D8DC),
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    ),
  );
}

class _GraphLegend extends StatelessWidget {
  const _GraphLegend();

  @override
  Widget build(BuildContext context) => Container(
    width: 124,
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: const Color(0xF20A0A0B),
      border: Border.all(color: const Color(0xFF29292D)),
      borderRadius: BorderRadius.circular(8),
    ),
    child: const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('掌握状态', style: TextStyle(fontSize: 11)),
        SizedBox(height: 8),
        _LegendDot(color: Color(0xFF61AA67), label: '已掌握'),
        _LegendDot(color: Color(0xFFB6B6BD), label: '掌握中'),
        _LegendDot(color: Color(0xFFD68A45), label: '薄弱'),
        _LegendDot(color: Color(0xFF77777F), label: '未评估'),
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
    padding: const EdgeInsets.symmetric(horizontal: 4),
    decoration: BoxDecoration(
      color: const Color(0xF20A0A0B),
      border: Border.all(color: const Color(0xFF29292D)),
      borderRadius: BorderRadius.circular(8),
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
          width: 46,
          child: Text(
            '${(value * 100).round()}%',
            textAlign: TextAlign.center,
            style: context.texts.bodySmall,
          ),
        ),
        IconButton(
          tooltip: '放大',
          onPressed: () => onChanged(value + .1),
          icon: const Icon(LucideIcons.plus, size: 16),
        ),
        IconButton(
          tooltip: '适应画布',
          onPressed: onFit,
          icon: const Icon(LucideIcons.scan, size: 16),
        ),
      ],
    ),
  );
}
