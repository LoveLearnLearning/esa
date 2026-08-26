import 'dart:async';

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/learning/knowledge_graph_canvas.dart';
import '../widgets/learning/knowledge_map_legend.dart';
import '../widgets/learning/knowledge_point_panel.dart';

class KnowledgeMapPage extends StatefulWidget {
  const KnowledgeMapPage({
    super.key,
    required this.onOpenChat,
    this.onConversationCreated,
    this.onOpenSchedule,
    this.api,
    this.embedded = false,
  });

  final VoidCallback onOpenChat;

  /// Called after the explanation message has created a real conversation.
  ///
  /// `AppState.newConversation()` intentionally creates a local blank state;
  /// the server conversation is created lazily by `AppState.send()`.  The
  /// callback lets the owning shell bind navigation to that server id once it
  /// exists.
  final Future<void> Function(String conversationId)? onConversationCreated;
  final VoidCallback? onOpenSchedule;
  final ApiClient? api;
  final bool embedded;

  @override
  State<KnowledgeMapPage> createState() => _KnowledgeMapPageState();
}

class _KnowledgeMapPageState extends State<KnowledgeMapPage> {
  bool _started = false;
  bool _loading = true;
  String? _error;
  List<LearningCourseSummary> _courses = const [];
  String? _course;
  KnowledgeMapData? _map;
  String _statusFilter = 'all';
  bool _weakOnly = false;
  bool _bannerDismissed = true; // 读取到持久化状态前先不显示，避免闪烁

  ApiClient get _api => widget.api ?? AppScope.of(context).api;

  String get _bannerDismissKey =>
      'esa.knowledge_map.banner_dismissed.${_api.userId ?? _api.username ?? 'guest'}';

  Future<void> _loadBannerDismissed() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (!mounted) return;
      setState(
        () => _bannerDismissed = prefs.getBool(_bannerDismissKey) ?? false,
      );
    } catch (_) {
      // 插件不可用（如 Web hot-restart）时按未关闭处理
      if (mounted) setState(() => _bannerDismissed = false);
    }
  }

  Future<void> _dismissBanner() async {
    setState(() => _bannerDismissed = true);
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_bannerDismissKey, true);
    } catch (_) {
      // 插件不可用时无持久化，仅本次会话隐藏
    }
  }

  LearningCourseSummary? get _selectedCourse {
    for (final item in _courses) {
      if (item.name == _course) return item;
    }
    return null;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_started) {
      _started = true;
      unawaited(_loadCourses());
      unawaited(_loadBannerDismissed());
    }
  }

  Future<void> _loadCourses({String? select}) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final courses = await _api.getLearningCourses();
      if (!mounted) return;
      final selected =
          select != null && courses.any((item) => item.name == select)
          ? select
          : courses.any((item) => item.name == _course)
          ? _course
          : courses.firstOrNull?.name;
      setState(() {
        _courses = courses;
        _course = selected;
        _map = null;
      });
      if (selected == null || _selectedCourse?.supported != true) {
        setState(() => _loading = false);
      } else {
        await _loadMap();
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.detail;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = '暂时无法加载知识地图，请检查网络后重试';
        _loading = false;
      });
    }
  }

  Future<void> _loadMap() async {
    final selected = _selectedCourse;
    if (selected == null || !selected.supported) return;
    setState(() {
      _loading = true;
      _error = null;
      _map = null;
    });
    try {
      final result = await _api.getKnowledgeMap(
        selected.canonicalCourse ?? selected.name,
      );
      if (!mounted) return;
      setState(() {
        _map = result;
        _loading = false;
      });
    } on ApiException {
      if (!mounted) return;
      setState(() {
        _error = '这门课程的知识地图暂时无法加载';
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = '知识地图加载失败，请稍后重试';
        _loading = false;
      });
    }
  }

  List<KnowledgeMapNode> _visibleNodes() {
    final data = _map;
    if (data == null) return const [];
    var nodes = data.nodes.where((node) => !node.isCourse).toList();
    if (_statusFilter != 'all') {
      nodes = nodes.where((node) => node.status == _statusFilter).toList();
    }
    if (!_weakOnly && _statusFilter == 'all') {
      return data.nodes;
    }
    if (!_weakOnly) {
      return _withCoursePaths(nodes.map((node) => node.id).toSet());
    }
    final targets = nodes
        .where((node) => node.status == 'weak' || node.needsReview)
        .map((node) => node.id)
        .toSet();
    if (targets.isEmpty) return const [];
    final visible = {...targets};
    for (final edge in data.edges) {
      if (targets.contains(edge.from) || targets.contains(edge.to)) {
        visible.add(edge.from);
        visible.add(edge.to);
      }
    }
    return _withCoursePaths(visible);
  }

  List<KnowledgeMapNode> _withCoursePaths(Set<String> visible) {
    final data = _map;
    if (data == null || visible.isEmpty) return const [];
    var changed = true;
    while (changed) {
      changed = false;
      for (final edge in data.edges) {
        if (visible.contains(edge.to) && visible.add(edge.from)) {
          changed = true;
        }
      }
    }
    return data.nodes
        .where((node) => node.isCourse || visible.contains(node.id))
        .toList();
  }

  Future<void> _openNode(KnowledgeMapNode node) async {
    if (node.isCourse) {
      await _showCourseOverview(node);
      return;
    }
    try {
      final app = AppScope.of(context);
      final detail = await _api.getKnowledgePointDetail(node.id);
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        backgroundColor: Colors.transparent,
        builder: (sheetContext) => KnowledgePointPanel(
          node: node,
          detail: detail,
          onExplain: () {
            Navigator.pop(sheetContext);
            unawaited(_startLearningPoint(app, node));
          },
        ),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.detail)));
    }
  }

  Future<void> _showCourseOverview(KnowledgeMapNode node) {
    final data = _map;
    final points = data?.nodes.where((item) => !item.isCourse).toList() ?? [];
    final roots = data?.edges
        .where((edge) => edge.from == node.id && edge.type == 'course_root')
        .length;
    final evaluated = points.where((item) => item.hasRecord).length;
    final weak = points
        .where((item) => item.status == 'weak' || item.needsReview)
        .length;
    return showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 4, 24, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                node.name,
                style: context.texts.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text('课程概览', style: TextStyle(color: context.n.n500)),
              const SizedBox(height: 20),
              Row(
                children: [
                  _courseMetric('${points.length}', '知识点'),
                  _courseMetric('${roots ?? 0}', '知识子树'),
                  _courseMetric('$evaluated', '已评估'),
                  _courseMetric('$weak', '需关注'),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _courseMetric(String value, String label) => Expanded(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          value,
          style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 3),
        Text(label, style: TextStyle(fontSize: 12, color: context.n.n500)),
      ],
    ),
  );

  Future<void> _startLearningPoint(AppState app, KnowledgeMapNode node) async {
    final createConversation = app.newConversation();
    widget.onOpenChat();
    await createConversation;
    await app.send('请针对“${node.name}”结合我的掌握度、记忆状态、学习证据和薄弱前置进行讲解，并给我一道检验理解的小题。');
    final conversationId = app.activeId;
    if (conversationId != null && widget.onConversationCreated != null) {
      await widget.onConversationCreated!(conversationId);
    }
  }

  Future<void> _showAddMenu() async {
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '添加课程',
                style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 12),
              _addChoice(
                icon: LucideIcons.calendarPlus,
                title: '从课表添加',
                subtitle: '同步已经维护好的课程，不需要重复输入',
                onTap: () {
                  Navigator.pop(sheetContext);
                  unawaited(_addFromSchedule());
                },
              ),
              const SizedBox(height: 8),
              _addChoice(
                icon: LucideIcons.search,
                title: '手动添加',
                subtitle: '搜索 ESA 已支持的课程知识地图',
                onTap: () {
                  Navigator.pop(sheetContext);
                  unawaited(_addManually());
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _addChoice({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) => Material(
    color: context.n.n100,
    borderRadius: BorderRadius.circular(EsaRadii.card),
    child: ListTile(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(EsaRadii.card),
      ),
      leading: Icon(icon, color: context.scheme.primary),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(subtitle),
      trailing: const Icon(LucideIcons.chevronRight),
      onTap: onTap,
    ),
  );

  Future<void> _addFromSchedule() async {
    final app = AppScope.of(context);
    await app.loadSchedule();
    if (!mounted) return;
    final existing = _courses.map((item) => item.name).toSet();
    final names =
        app.scheduleCourses
            .map((item) => item.name.trim())
            .where((name) => name.isNotEmpty && !existing.contains(name))
            .toSet()
            .toList()
          ..sort();
    if (names.isEmpty) {
      await _showNoTimetableCourses();
      return;
    }
    final selected = <String>{...names};
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('从课表添加课程'),
          content: SizedBox(
            width: 440,
            height: 340,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('选择需要建立知识地图的课程：'),
                const SizedBox(height: 8),
                Expanded(
                  child: ListView(
                    children: [
                      for (final name in names)
                        CheckboxListTile(
                          value: selected.contains(name),
                          title: Text(name),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(EsaRadii.field),
                          ),
                          onChanged: (value) => setDialogState(() {
                            value == true
                                ? selected.add(name)
                                : selected.remove(name);
                          }),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: selected.isEmpty
                  ? null
                  : () => Navigator.pop(dialogContext, true),
              child: Text('添加 ${selected.length} 门课程'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true || !mounted) return;
    await _saveCourses(selected, source: 'timetable');
  }

  Future<void> _showNoTimetableCourses() => showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('课表中没有可添加的课程'),
      content: const Text('请先在课表页面添加课程，之后就可以一键同步到知识地图。'),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(dialogContext),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () {
            Navigator.pop(dialogContext);
            widget.onOpenSchedule?.call();
          },
          child: const Text('去课表添加'),
        ),
      ],
    ),
  );

  Future<void> _addManually() async {
    try {
      final catalog = await _api.getLearningCourseCatalog();
      if (!mounted) return;
      var query = '';
      final selected = <String>{};
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => StatefulBuilder(
          builder: (context, setDialogState) {
            final visible = catalog.where((item) {
              return !item.added &&
                  item.name.toLowerCase().contains(query.trim().toLowerCase());
            }).toList();
            return AlertDialog(
              title: const Text('手动添加课程'),
              content: SizedBox(
                width: 440,
                height: 360,
                child: Column(
                  children: [
                    TextField(
                      autofocus: true,
                      decoration: const InputDecoration(
                        hintText: '搜索课程，例如：数据结构',
                        prefixIcon: Icon(LucideIcons.search),
                      ),
                      onChanged: (value) => setDialogState(() => query = value),
                    ),
                    const SizedBox(height: 10),
                    Expanded(
                      child: visible.isEmpty
                          ? const Padding(
                              padding: EdgeInsets.all(24),
                              child: Text('没有找到可添加的课程'),
                            )
                          : ListView(
                              children: [
                                for (final item in visible)
                                  CheckboxListTile(
                                    value: selected.contains(item.name),
                                    title: Text(item.name),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(
                                        EsaRadii.field,
                                      ),
                                    ),
                                    onChanged: (value) => setDialogState(() {
                                      value == true
                                          ? selected.add(item.name)
                                          : selected.remove(item.name);
                                    }),
                                  ),
                              ],
                            ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext, false),
                  child: const Text('取消'),
                ),
                FilledButton(
                  onPressed: selected.isEmpty
                      ? null
                      : () => Navigator.pop(dialogContext, true),
                  child: Text('添加 ${selected.length} 门课程'),
                ),
              ],
            );
          },
        ),
      );
      if (confirmed == true && mounted) {
        await _saveCourses(selected, source: 'manual');
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.detail)));
    }
  }

  Future<void> _saveCourses(
    Iterable<String> courses, {
    required String source,
  }) async {
    try {
      final values = courses.toList();
      await _api.addLearningCourses(values, source: source);
      if (!mounted) return;
      await _loadCourses(select: values.firstOrNull);
      if (widget.api == null && mounted) {
        await AppScope.of(context).loadLearningOverview();
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.detail)));
    }
  }

  Future<void> _matchSelectedCourse() async {
    final sourceName = _course;
    if (sourceName == null) return;
    try {
      final catalog = await _api.getLearningCourseCatalog();
      if (!mounted) return;
      var query = '';
      final canonical = await showDialog<String>(
        context: context,
        builder: (dialogContext) => StatefulBuilder(
          builder: (context, setDialogState) {
            final visible = catalog.where((item) {
              return item.name.toLowerCase().contains(
                query.trim().toLowerCase(),
              );
            }).toList();
            return AlertDialog(
              title: Text('“$sourceName”对应哪门课程？'),
              content: SizedBox(
                width: 440,
                height: 360,
                child: Column(
                  children: [
                    TextField(
                      autofocus: true,
                      decoration: const InputDecoration(
                        hintText: '搜索 ESA 已支持的课程',
                        prefixIcon: Icon(LucideIcons.search),
                      ),
                      onChanged: (value) => setDialogState(() => query = value),
                    ),
                    const SizedBox(height: 10),
                    Expanded(
                      child: visible.isEmpty
                          ? const Center(child: Text('没有找到匹配课程'))
                          : ListView.builder(
                              itemCount: visible.length,
                              itemBuilder: (context, index) {
                                final item = visible[index];
                                return ListTile(
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(
                                      EsaRadii.field,
                                    ),
                                  ),
                                  title: Text(item.name),
                                  trailing: const Icon(
                                    LucideIcons.chevronRight,
                                    size: 18,
                                  ),
                                  onTap: () =>
                                      Navigator.pop(dialogContext, item.name),
                                );
                              },
                            ),
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(dialogContext),
                  child: const Text('取消'),
                ),
              ],
            );
          },
        ),
      );
      if (canonical == null || !mounted) return;
      await _api.bindLearningCourse(
        name: sourceName,
        canonicalCourse: canonical,
      );
      if (!mounted) return;
      await _loadCourses(select: sourceName);
      if (widget.api == null && mounted) {
        await AppScope.of(context).loadLearningOverview();
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.detail)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final desktop = MediaQuery.sizeOf(context).width >= 1040;
    final content = Column(
      children: [
        if (widget.embedded)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 14, 6),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    _course == null ? '个人知识地图' : '$_course 知识地图',
                    style: context.texts.headlineSmall,
                  ),
                ),
                IconButton(
                  tooltip: '刷新',
                  onPressed: _loading ? null : _loadCourses,
                  icon: const Icon(LucideIcons.refreshCw, size: 18),
                ),
              ],
            ),
          ),
        if (!_loading && _error == null) _toolbar(),
        Expanded(
          child: desktop && widget.embedded
              ? Row(
                  children: [
                    SizedBox(
                      width: 220,
                      child: _ChapterOutline(
                        nodes: _map?.nodes ?? const [],
                        edges: _map?.edges ?? const [],
                        onNodeTap: _openNode,
                      ),
                    ),
                    VerticalDivider(width: 1, color: context.n.divider),
                    Expanded(child: _content()),
                  ],
                )
              : _content(),
        ),
      ],
    );
    if (widget.embedded) return content;
    return Scaffold(
      appBar: AppBar(
        title: const Text('个人知识地图'),
        actions: [
          IconButton(
            tooltip: '刷新',
            onPressed: _loading ? null : _loadCourses,
            icon: const Icon(LucideIcons.refreshCw),
          ),
        ],
      ),
      body: content,
    );
  }

  Widget _toolbar() {
    final hasGraph = _map?.nodes.isNotEmpty == true;
    final mobile = MediaQuery.sizeOf(context).width < 600;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 8, 14, 10),
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(bottom: BorderSide(color: context.n.divider)),
      ),
      child: Wrap(
        spacing: EsaSpace.sm,
        runSpacing: EsaSpace.sm,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          if (_courses.isNotEmpty)
            _roundedDropdown(
              value: _course,
              hint: '选择课程',
              items: [for (final item in _courses) item.name],
              onChanged: (value) {
                if (value == null || value == _course) return;
                setState(() {
                  _course = value;
                  _map = null;
                  _statusFilter = 'all';
                  _weakOnly = false;
                });
                if (_selectedCourse?.supported == true) {
                  unawaited(_loadMap());
                }
              },
            ),
          OutlinedButton.icon(
            onPressed: _showAddMenu,
            icon: const Icon(LucideIcons.plus, size: 17),
            label: const Text('添加课程'),
          ),
          if (hasGraph && !mobile) ...[
            _roundedDropdown(
              value: _statusFilter,
              items: const [
                'all',
                'unseen',
                'weak',
                'learning',
                'good',
                'mastered',
              ],
              labels: const {
                'all': '全部状态',
                'unseen': '未评估',
                'weak': '需加强',
                'learning': '学习中',
                'good': '较好',
                'mastered': '稳定掌握',
              },
              onChanged: (value) {
                if (value != null) setState(() => _statusFilter = value);
              },
            ),
            FilterChip(
              selected: _weakOnly,
              avatar: const Icon(LucideIcons.filter, size: 15),
              label: const Text('只看我的问题'),
              onSelected: (value) => setState(() => _weakOnly = value),
              shape: const StadiumBorder(),
            ),
            const KnowledgeMapLegend(),
          ] else if (hasGraph) ...[
            FilterChip(
              selected: _weakOnly,
              avatar: const Icon(LucideIcons.filter, size: 15),
              label: const Text('只看问题'),
              onSelected: (value) => setState(() => _weakOnly = value),
              shape: const StadiumBorder(),
            ),
          ],
        ],
      ),
    );
  }

  Widget _roundedDropdown({
    required String? value,
    required List<String> items,
    required ValueChanged<String?> onChanged,
    String hint = '',
    Map<String, String> labels = const {},
  }) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12),
    decoration: BoxDecoration(
      color: context.n.n100,
      borderRadius: BorderRadius.circular(EsaRadii.field),
      border: Border.all(color: context.n.divider),
    ),
    child: DropdownButtonHideUnderline(
      child: DropdownButton<String>(
        value: value,
        hint: Text(hint),
        borderRadius: BorderRadius.circular(EsaRadii.field),
        items: [
          for (final item in items)
            DropdownMenuItem(value: item, child: Text(labels[item] ?? item)),
        ],
        onChanged: onChanged,
      ),
    ),
  );

  Widget _content() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) return _errorState();
    if (_courses.isEmpty) return _emptyCoursesState();
    if (_selectedCourse?.supported != true) return _unsupportedState();
    final data = _map;
    if (data == null || data.nodes.isEmpty) return _unsupportedState();
    return Column(
      children: [
        if ((_selectedCourse?.evaluatedPoints ?? 0) == 0 && !_bannerDismissed)
          _unassessedBanner(),
        Expanded(
          child: KnowledgeGraphCanvas(
            visibleNodes: _visibleNodes(),
            edges: data.edges,
            onNodeTap: _openNode,
          ),
        ),
      ],
    );
  }

  Widget _emptyCoursesState() => Center(
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(28),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(
              width: 190,
              height: 120,
              child: CustomPaint(painter: _EmptyGraphPainter()),
            ),
            const SizedBox(height: 20),
            const Text(
              '建立你的个人知识地图',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 25, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            Text(
              '添加正在学习的课程后，星知智链会把课程知识结构、练习记录和掌握状态连接起来，并随着学习持续更新。',
              textAlign: TextAlign.center,
              style: TextStyle(color: context.n.n500, height: 1.6),
            ),
            const SizedBox(height: 26),
            FilledButton.icon(
              onPressed: _addFromSchedule,
              icon: const Icon(LucideIcons.calendarPlus),
              label: const Text('从课表添加课程'),
            ),
            const SizedBox(height: 8),
            TextButton(onPressed: _addManually, child: const Text('手动添加课程')),
            const SizedBox(height: 12),
            Text(
              '已有课程？添加后可从顶部“选择课程”切换',
              style: TextStyle(color: context.n.n500, fontSize: 13),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _unsupportedState() => Center(
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(28),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              LucideIcons.mapPin,
              size: 54,
              color: context.n.n500.withValues(alpha: 0.7),
            ),
            const SizedBox(height: 18),
            const Text(
              '这门课程暂时没有可用的知识地图',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 10),
            Text(
              '“${_course ?? '当前课程'}”目前还没有匹配到 ESA 的课程知识结构。你仍然可以在学习助手中学习这门课程。',
              textAlign: TextAlign.center,
              style: TextStyle(color: context.n.n500, height: 1.55),
            ),
            const SizedBox(height: 22),
            Wrap(
              alignment: WrapAlignment.center,
              spacing: 10,
              runSpacing: 8,
              children: [
                FilledButton.icon(
                  onPressed: _matchSelectedCourse,
                  icon: const Icon(LucideIcons.link),
                  label: const Text('匹配已有课程'),
                ),
                OutlinedButton.icon(
                  onPressed: _showAddMenu,
                  icon: const Icon(LucideIcons.listRestart),
                  label: const Text('添加其他课程'),
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );

  Widget _unassessedBanner() => Container(
    width: double.infinity,
    margin: const EdgeInsets.fromLTRB(16, 14, 16, 0),
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: context.scheme.primary.withValues(alpha: 0.08),
      borderRadius: BorderRadius.circular(EsaRadii.card),
      border: Border.all(color: context.scheme.primary.withValues(alpha: 0.22)),
    ),
    child: Row(
      children: [
        IconButton(
          key: const ValueKey('knowledge-map-banner-close'),
          tooltip: '关闭提示',
          visualDensity: VisualDensity.compact,
          onPressed: () => unawaited(_dismissBanner()),
          icon: Icon(LucideIcons.x, size: 16, color: context.scheme.primary),
        ),
        const SizedBox(width: 4),
        Icon(LucideIcons.sparkles, color: context.scheme.primary, size: 20),
        const SizedBox(width: 12),
        const Expanded(
          child: Text('你的知识地图已经建立。目前还没有足够的学习记录，灰色节点表示“未评估”；完成练习后会逐步形成个人掌握状态。'),
        ),
        TextButton(
          onPressed: () {
            final app = AppScope.of(context);
            unawaited(app.newConversation());
            widget.onOpenChat();
          },
          child: const Text('开始学习'),
        ),
      ],
    ),
  );

  Widget _errorState() => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(LucideIcons.wifiOff, size: 42),
          const SizedBox(height: 14),
          Text(_error!, textAlign: TextAlign.center),
          const SizedBox(height: 14),
          OutlinedButton(onPressed: _loadCourses, child: const Text('重新加载')),
        ],
      ),
    ),
  );
}

class _ChapterOutline extends StatelessWidget {
  const _ChapterOutline({
    required this.nodes,
    required this.edges,
    required this.onNodeTap,
  });

  final List<KnowledgeMapNode> nodes;
  final List<KnowledgeMapEdge> edges;
  final ValueChanged<KnowledgeMapNode> onNodeTap;

  List<_OutlineEntry> _buildTree() {
    if (nodes.isEmpty) return const [];
    final byId = {for (final node in nodes) node.id: node};
    final candidates = <String, List<KnowledgeMapNode>>{};
    for (final edge in edges) {
      final parent = byId[edge.from];
      final child = byId[edge.to];
      if (parent == null || child == null || parent.id == child.id) continue;
      candidates.putIfAbsent(child.id, () => []).add(parent);
    }

    final parentByChild = <String, String>{};
    for (final entry in candidates.entries) {
      final child = byId[entry.key]!;
      final parents = entry.value
        ..sort((a, b) {
          final aBeforeChild = a.level < child.level ? 0 : 1;
          final bBeforeChild = b.level < child.level ? 0 : 1;
          final direction = aBeforeChild.compareTo(bBeforeChild);
          if (direction != 0) return direction;
          final distance = (child.level - a.level).abs().compareTo(
            (child.level - b.level).abs(),
          );
          return distance != 0 ? distance : a.name.compareTo(b.name);
        });
      parentByChild[child.id] = parents.first.id;
    }

    final children = <String, List<KnowledgeMapNode>>{
      for (final node in nodes) node.id: [],
    };
    for (final entry in parentByChild.entries) {
      children[entry.value]?.add(byId[entry.key]!);
    }
    for (final values in children.values) {
      values.sort((a, b) {
        final level = a.level.compareTo(b.level);
        return level != 0 ? level : a.name.compareTo(b.name);
      });
    }

    final roots =
        nodes.where((node) => !parentByChild.containsKey(node.id)).toList()
          ..sort((a, b) {
            final level = a.level.compareTo(b.level);
            return level != 0 ? level : a.name.compareTo(b.name);
          });
    final result = <_OutlineEntry>[];
    final visited = <String>{};

    void visit(
      KnowledgeMapNode node,
      int depth,
      bool isLast,
      List<bool> ancestorHasNext,
    ) {
      if (!visited.add(node.id)) return;
      result.add(
        _OutlineEntry(
          node: node,
          depth: depth,
          isLast: isLast,
          ancestorHasNext: ancestorHasNext,
        ),
      );
      final descendants = children[node.id]!;
      for (var index = 0; index < descendants.length; index++) {
        visit(descendants[index], depth + 1, index == descendants.length - 1, [
          ...ancestorHasNext,
          !isLast,
        ]);
      }
    }

    for (var index = 0; index < roots.length; index++) {
      visit(roots[index], 0, index == roots.length - 1, const []);
    }
    final remaining = nodes.where((node) => !visited.contains(node.id)).toList()
      ..sort((a, b) => a.name.compareTo(b.name));
    for (var index = 0; index < remaining.length; index++) {
      visit(remaining[index], 0, index == remaining.length - 1, const []);
    }
    return result;
  }

  @override
  Widget build(BuildContext context) {
    final tree = _buildTree();
    return Container(
      color: const Color(0xFF08131F),
      padding: const EdgeInsets.fromLTRB(12, 14, 8, 12),
      child: ListView(
        children: [
          const Text(
            '知识结构',
            style: TextStyle(fontSize: 12, color: Color(0xFFAAB5C7)),
          ),
          const SizedBox(height: 12),
          if (tree.isEmpty)
            Text('暂无知识点', style: context.texts.bodySmall)
          else
            for (final entry in tree)
              _OutlineRow(entry: entry, onTap: onNodeTap),
        ],
      ),
    );
  }
}

class _OutlineEntry {
  const _OutlineEntry({
    required this.node,
    required this.depth,
    required this.isLast,
    required this.ancestorHasNext,
  });

  final KnowledgeMapNode node;
  final int depth;
  final bool isLast;
  final List<bool> ancestorHasNext;
}

class _OutlineRow extends StatelessWidget {
  const _OutlineRow({required this.entry, required this.onTap});

  final _OutlineEntry entry;
  final ValueChanged<KnowledgeMapNode> onTap;

  @override
  Widget build(BuildContext context) {
    final node = entry.node;
    final branchWidth = 18.0 + entry.depth * 16.0;
    final color = node.isCourse
        ? const Color(0xFFF1C75B)
        : node.hasRecord
        ? const Color(0xFF5795FF)
        : context.n.n500;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: () => onTap(node),
        borderRadius: BorderRadius.circular(8),
        hoverColor: const Color(0xFF17304F).withValues(alpha: .55),
        child: Container(
          height: 36,
          decoration: BoxDecoration(
            color: node.needsReview
                ? EsaColors.accent.withValues(alpha: .10)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              SizedBox(
                width: branchWidth,
                height: 36,
                child: CustomPaint(
                  painter: _GitBranchPainter(
                    depth: entry.depth,
                    isLast: entry.isLast,
                    ancestorHasNext: entry.ancestorHasNext,
                    nodeColor: color,
                  ),
                ),
              ),
              const SizedBox(width: 5),
              Expanded(
                child: Text(
                  node.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: node.isCourse ? 12.5 : 11.5,
                    fontWeight: node.isCourse
                        ? FontWeight.w700
                        : FontWeight.normal,
                  ),
                ),
              ),
              const SizedBox(width: 6),
            ],
          ),
        ),
      ),
    );
  }
}

class _GitBranchPainter extends CustomPainter {
  const _GitBranchPainter({
    required this.depth,
    required this.isLast,
    required this.ancestorHasNext,
    required this.nodeColor,
  });

  final int depth;
  final bool isLast;
  final List<bool> ancestorHasNext;
  final Color nodeColor;

  @override
  void paint(Canvas canvas, Size size) {
    const step = 16.0;
    const origin = 9.0;
    final centerY = size.height / 2;
    final line = Paint()
      ..color = const Color(0xFF43536A)
      ..strokeWidth = 1.15
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    for (var index = 0; index < ancestorHasNext.length; index++) {
      if (!ancestorHasNext[index]) continue;
      final x = origin + index * step;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), line);
    }

    final x = origin + depth * step;
    if (depth == 0) {
      if (!isLast) {
        canvas.drawLine(Offset(x, centerY), Offset(x, size.height), line);
      }
    } else {
      final parentX = x - step;
      canvas.drawLine(Offset(parentX, 0), Offset(parentX, centerY), line);
      canvas.drawLine(Offset(parentX, centerY), Offset(x, centerY), line);
      if (!isLast) {
        canvas.drawLine(
          Offset(parentX, centerY),
          Offset(parentX, size.height),
          line,
        );
      }
    }
    canvas.drawCircle(
      Offset(x, centerY),
      4.1,
      Paint()..color = const Color(0xFF08131F),
    );
    canvas.drawCircle(Offset(x, centerY), 3.0, Paint()..color = nodeColor);
  }

  @override
  bool shouldRepaint(covariant _GitBranchPainter oldDelegate) =>
      oldDelegate.depth != depth ||
      oldDelegate.isLast != isLast ||
      oldDelegate.ancestorHasNext != ancestorHasNext ||
      oldDelegate.nodeColor != nodeColor;
}

class _EmptyGraphPainter extends CustomPainter {
  const _EmptyGraphPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final line = Paint()
      ..color = const Color(0xFF4F7FF5).withValues(alpha: 0.25)
      ..strokeWidth = 2;
    final fill = Paint()
      ..color = const Color(0xFF4F7FF5).withValues(alpha: 0.5);
    final points = [
      Offset(size.width * 0.18, size.height * 0.68),
      Offset(size.width * 0.5, size.height * 0.28),
      Offset(size.width * 0.82, size.height * 0.65),
      Offset(size.width * 0.5, size.height * 0.84),
    ];
    canvas.drawLine(points[0], points[1], line);
    canvas.drawLine(points[1], points[2], line);
    canvas.drawLine(points[0], points[3], line);
    canvas.drawLine(points[3], points[2], line);
    for (final point in points) {
      canvas.drawCircle(point, 13, fill);
      canvas.drawCircle(point, 5, Paint()..color = const Color(0xFFDCE7FF));
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
