import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../api/api_client.dart';
import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

const _weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
const _courseColors = <int>[
  0xFF2563EB,
  0xFF7C3AED,
  0xFF059669,
  0xFFD97706,
  0xFFDC2626,
  0xFF0891B2,
  0xFFDB2777,
];

class SchedulePage extends StatefulWidget {
  const SchedulePage({super.key});

  @override
  State<SchedulePage> createState() => _SchedulePageState();
}

class _SchedulePageState extends State<SchedulePage> {
  bool _requestedSchedule = false;
  bool _resolvedCalendarWeek = false;
  // 周切换方向：1 = 切到下一周（新内容从右滑入），-1 = 上一周
  int _weekSlideDirection = 1;
  bool _importing = false;
  int _week = 1;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedSchedule) return;
    _requestedSchedule = true;
    final app = AppScope.of(context);
    _week = app.userProfile.currentWeek.clamp(1, 30);
    app.loadSchedule();
  }

  void _changeWeek(int week, int totalWeeks) {
    final clamped = week.clamp(1, totalWeeks);
    if (clamped == _week) return;
    setState(() {
      _weekSlideDirection = clamped > _week ? 1 : -1;
      _week = clamped;
    });
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final totalWeeks = app.userProfile.totalWeeks.clamp(1, 30);
    if (app.scheduleLoaded && !_resolvedCalendarWeek) {
      _resolvedCalendarWeek = true;
      _week = app.scheduleSettings
          .weekForDate(DateTime.now())
          .clamp(1, totalWeeks);
    }
    if (_week > totalWeeks) _week = totalWeeks;
    final narrow = MediaQuery.sizeOf(context).width < 760;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            _header(context, app, totalWeeks, narrow),
            Expanded(
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onHorizontalDragEnd: narrow
                    ? (details) {
                        final velocity = details.primaryVelocity ?? 0;
                        if (velocity < -250) {
                          _changeWeek(_week + 1, totalWeeks);
                        } else if (velocity > 250) {
                          _changeWeek(_week - 1, totalWeeks);
                        }
                      }
                    : null,
                child: !app.scheduleLoaded
                    ? const Center(child: CircularProgressIndicator())
                    : AnimatedSwitcher(
                        duration: const Duration(milliseconds: 240),
                        switchInCurve: Curves.easeOutCubic,
                        switchOutCurve: Curves.easeInCubic,
                        transitionBuilder: (child, animation) {
                          // 新周从切换方向一侧滑入，旧周向另一侧滑出并淡出
                          final incoming =
                              child.key == ValueKey<int>(_week);
                          final begin = Offset(
                            (incoming ? 0.08 : -0.08) * _weekSlideDirection,
                            0,
                          );
                          return FadeTransition(
                            opacity: animation,
                            child: SlideTransition(
                              position: Tween(
                                begin: begin,
                                end: Offset.zero,
                              ).animate(animation),
                              child: child,
                            ),
                          );
                        },
                        child: KeyedSubtree(
                          key: ValueKey<int>(_week),
                          child: _weekSchedule(
                            context,
                            app,
                            compactLayout: narrow,
                          ),
                        ),
                      ),
              ),
            ),
          ],
        ),
      ),
      floatingActionButton: narrow
          ? FloatingActionButton(
              tooltip: '添加课程',
              onPressed: () => _openEditor(app, totalWeeks),
              child: const Icon(LucideIcons.plus),
            )
          : null,
    );
  }

  Widget _header(
    BuildContext context,
    AppState app,
    int totalWeeks,
    bool narrow,
  ) {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: narrow ? 14 : 20, vertical: 10),
      decoration: BoxDecoration(
        color: context.scheme.surface,
        border: Border(bottom: BorderSide(color: context.n.divider)),
      ),
      child: Row(
        children: [
          if (!narrow) ...[
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                color: EsaColors.accent.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(EsaRadii.button),
              ),
              child: const Icon(
                LucideIcons.calendarDays,
                size: 19,
                color: EsaColors.accent,
              ),
            ),
            const SizedBox(width: 10),
          ],
          PopupMenuButton<String>(
            key: const ValueKey('schedule-table-menu'),
            tooltip: '切换或管理课程表',
            onSelected: (value) => _onTableMenuSelected(app, value),
            itemBuilder: (_) => [
              for (final table in app.scheduleTables)
                PopupMenuItem(
                  value: table.id,
                  child: Row(
                    children: [
                      SizedBox(
                        width: 22,
                        child: table.id == app.activeScheduleTableId
                            ? const Icon(LucideIcons.check, size: 15)
                            : null,
                      ),
                      Flexible(
                        child: Text(table.name, overflow: TextOverflow.ellipsis),
                      ),
                    ],
                  ),
                ),
              const PopupMenuDivider(),
              const PopupMenuItem(
                value: '__create__',
                child: Row(
                  children: [
                    Icon(LucideIcons.plus, size: 15),
                    SizedBox(width: 7),
                    Text('新建课程表'),
                  ],
                ),
              ),
              const PopupMenuItem(
                value: '__rename__',
                child: Row(
                  children: [
                    Icon(LucideIcons.pencil, size: 15),
                    SizedBox(width: 7),
                    Text('重命名当前课程表'),
                  ],
                ),
              ),
              if (app.scheduleTables.length > 1)
                const PopupMenuItem(
                  value: '__delete__',
                  child: Row(
                    children: [
                      Icon(LucideIcons.trash2, size: 15),
                      SizedBox(width: 7),
                      Text('删除当前课程表'),
                    ],
                  ),
                ),
            ],
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child: Text(
                    app.activeScheduleTable?.name ?? '课表',
                    overflow: TextOverflow.ellipsis,
                    style: context.texts.titleMedium?.copyWith(fontSize: 16),
                  ),
                ),
                const SizedBox(width: 3),
                const Icon(LucideIcons.chevronDown, size: 14),
              ],
            ),
          ),
          if (!narrow) ...[
            const SizedBox(width: 8),
            Text('共 $totalWeeks 周', style: context.texts.bodySmall),
            if (app.scheduleSettings.parsedTermStartDate != null) ...[
              const SizedBox(width: 10),
              Text(
                '今天：第 ${app.scheduleSettings.weekForDate(DateTime.now()).clamp(1, totalWeeks)} 周 · '
                '${_weekdays[DateTime.now().weekday - 1]}',
                style: context.texts.bodySmall,
              ),
            ],
          ],
          const Spacer(),
          IconButton(
            tooltip: '上一周',
            visualDensity: VisualDensity.compact,
            onPressed: _week <= 1
                ? null
                : () => _changeWeek(_week - 1, totalWeeks),
            icon: const Icon(LucideIcons.chevronLeft, size: 18),
          ),
          PopupMenuButton<int>(
            tooltip: '选择教学周',
            onSelected: (week) => _changeWeek(week, totalWeeks),
            itemBuilder: (_) => [
              for (var week = 1; week <= totalWeeks; week++)
                PopupMenuItem(value: week, child: Text('第 $week 周')),
            ],
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 8),
              decoration: BoxDecoration(
                color: context.n.n100,
                border: Border.all(color: context.n.divider),
                borderRadius: BorderRadius.circular(EsaRadii.pill),
              ),
              child: Text('第 $_week 周', style: context.texts.titleMedium),
            ),
          ),
          IconButton(
            tooltip: '下一周',
            visualDensity: VisualDensity.compact,
            onPressed: _week >= totalWeeks
                ? null
                : () => _changeWeek(_week + 1, totalWeeks),
            icon: const Icon(LucideIcons.chevronRight, size: 18),
          ),
          IconButton(
            key: const ValueKey('schedule-import-button'),
            tooltip: '从文件导入课表',
            visualDensity: VisualDensity.compact,
            onPressed: _importing ? null : () => _importSchedule(app),
            icon: _importing
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(LucideIcons.fileUp, size: 18),
          ),
          IconButton(
            key: const ValueKey('schedule-settings-button'),
            tooltip: '课表设置',
            visualDensity: VisualDensity.compact,
            onPressed: () => _openScheduleSettings(app),
            icon: const Icon(LucideIcons.settings2, size: 18),
          ),
          if (!narrow) ...[
            const SizedBox(width: 8),
            FilledButton.icon(
              onPressed: () => _openEditor(app, totalWeeks),
              icon: const Icon(LucideIcons.plus, size: 16),
              label: const Text('添加课程'),
            ),
          ],
        ],
      ),
    );
  }

  Widget _weekSchedule(
    BuildContext context,
    AppState app, {
    required bool compactLayout,
  }) {
    final periodHeight = compactLayout ? 62.0 : 76.0;
    final headerHeight = compactLayout ? 38.0 : 46.0;
    final totalPeriods = app.scheduleSettings.totalPeriods;
    final totalHeight = headerHeight + periodHeight * totalPeriods;
    final courses = <ScheduleCourse>[];
    final otherWeeks = <ScheduleCourse>[];
    for (final course in app.scheduleCourses) {
      if (course.occursInWeek(_week)) {
        courses.add(course);
      } else if (course.startWeek > _week) {
        // 只有还没开课的课程显示"非本周"占位；已结课的不再显示
        otherWeeks.add(course);
      }
    }
    // 非本周课程半透明显示，但不与本周课或已放置的其他非本周课叠格
    bool cellOverlaps(ScheduleCourse a, ScheduleCourse b) =>
        a.weekday == b.weekday &&
        a.startPeriod <= b.endPeriod &&
        b.startPeriod <= a.endPeriod;
    final placed = List.of(courses);
    final ghostCourses = <ScheduleCourse>[];
    for (final course in otherWeeks) {
      if (placed.any((item) => cellOverlaps(item, course))) continue;
      placed.add(course);
      ghostCourses.add(course);
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final horizontalMargin = compactLayout
            ? 6.0
            : constraints.maxWidth < 1000
            ? 18.0
            : 32.0;
        final cardPadding = compactLayout
            ? 5.0
            : constraints.maxWidth < 1000
            ? 10.0
            : 12.0;
        final cardWidth = constraints.maxWidth - horizontalMargin * 2;

        // 周切换动画期间 AnimatedSwitcher 会同时挂载新旧两棵子树，
        // 滚动控制器必须由每棵子树自持，不能用共享的 State 字段
        return _OwnScrollbarScrollView(
          builder: (context, controller) => Scrollbar(
            controller: controller,
            thumbVisibility: true,
            child: SingleChildScrollView(
              controller: controller,
              primary: false,
            padding: EdgeInsets.fromLTRB(
              horizontalMargin,
              compactLayout ? 10 : 24,
              horizontalMargin,
              compactLayout ? 92 : 28,
            ),
            child: Container(
              key: const ValueKey('schedule-week-card'),
              width: cardWidth,
              padding: EdgeInsets.all(cardPadding),
              decoration: BoxDecoration(
                color: context.scheme.surface,
                border: Border.all(color: context.n.divider),
                borderRadius: BorderRadius.circular(compactLayout ? 16 : 22),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(
                      alpha: Theme.of(context).brightness == Brightness.dark
                          ? 0.28
                          : 0.1,
                    ),
                    blurRadius: 24,
                    spreadRadius: 1,
                    offset: const Offset(0, 8),
                  ),
                ],
              ),
              child: LayoutBuilder(
                builder: (context, gridConstraints) {
                  final gridWidth = gridConstraints.maxWidth;
                  final labelWidth = compactLayout
                      ? (gridWidth * 0.13).clamp(42.0, 52.0)
                      : (gridWidth * 0.105).clamp(72.0, 88.0);
                  final dayWidth = (gridWidth - labelWidth) / 7;
                  final compactTiles = dayWidth < 118;
                  final ultraCompactTiles = dayWidth < 64;
                  final tileInset = ultraCompactTiles ? 2.0 : 4.0;
                  return SizedBox(
                    key: const ValueKey('schedule-week-grid'),
                    width: gridWidth,
                    height: totalHeight,
                    child: Stack(
                      children: [
                        Positioned.fill(
                          child: CustomPaint(
                            painter: _ScheduleGridPainter(
                              divider: context.n.divider,
                              surface: context.n.n100,
                              labelWidth: labelWidth,
                              headerHeight: headerHeight,
                              dayWidth: dayWidth,
                              periodHeight: periodHeight,
                              periodCount: totalPeriods,
                            ),
                          ),
                        ),
                        for (var day = 0; day < 7; day++)
                          Positioned(
                            left: labelWidth + day * dayWidth,
                            top: 0,
                            width: dayWidth,
                            height: headerHeight,
                            child: Center(
                              key: ValueKey('schedule-weekday-${day + 1}'),
                              child: Text(
                                _weekdays[day],
                                maxLines: 1,
                                style: context.texts.titleMedium?.copyWith(
                                  fontSize: compactLayout ? 10 : null,
                                ),
                              ),
                            ),
                          ),
                        for (var period = 1; period <= totalPeriods; period++)
                          Positioned(
                            left: 0,
                            top: headerHeight + (period - 1) * periodHeight,
                            width: labelWidth,
                            height: periodHeight,
                            child: Center(
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(
                                    '第 $period 节',
                                    style: context.texts.bodySmall?.copyWith(
                                      fontSize: compactLayout ? 9 : null,
                                      fontWeight: FontWeight.w700,
                                      color: context.scheme.onSurface,
                                    ),
                                  ),
                                  SizedBox(height: compactLayout ? 1 : 2),
                                  Text(
                                    app.scheduleSettings.periodStartLabel(
                                      period,
                                    ),
                                    style: context.texts.bodySmall?.copyWith(
                                      fontSize: compactLayout ? 8 : 10,
                                    ),
                                  ),
                                  Text(
                                    app.scheduleSettings.periodEndLabel(period),
                                    style: context.texts.bodySmall?.copyWith(
                                      fontSize: compactLayout ? 8 : 10,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        for (final course in courses)
                          Positioned(
                            left:
                                labelWidth +
                                (course.weekday - 1) * dayWidth +
                                tileInset,
                            top:
                                headerHeight +
                                (course.startPeriod - 1) * periodHeight +
                                tileInset,
                            width: dayWidth - tileInset * 2,
                            height:
                                (course.endPeriod - course.startPeriod + 1) *
                                    periodHeight -
                                tileInset * 2,
                            child: _courseTile(
                              context,
                              app,
                              course,
                              compact: compactTiles,
                              ultraCompact: ultraCompactTiles,
                            ),
                          ),
                        for (final course in ghostCourses)
                          Positioned(
                            left:
                                labelWidth +
                                (course.weekday - 1) * dayWidth +
                                tileInset,
                            top:
                                headerHeight +
                                (course.startPeriod - 1) * periodHeight +
                                tileInset,
                            width: dayWidth - tileInset * 2,
                            height:
                                (course.endPeriod - course.startPeriod + 1) *
                                    periodHeight -
                                tileInset * 2,
                            child: _courseTile(
                              context,
                              app,
                              course,
                              compact: compactTiles,
                              ultraCompact: ultraCompactTiles,
                              dimmed: true,
                            ),
                          ),
                      ],
                    ),
                  );
                },
              ),
            ),
          ),
        ),
        );
      },
    );
  }

  Widget _courseTile(
    BuildContext context,
    AppState app,
    ScheduleCourse course, {
    required bool compact,
    required bool ultraCompact,
    bool dimmed = false,
  }) {
    final color = Color(course.colorValue);
    final tile = DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(EsaRadii.card),
        boxShadow: dimmed
            ? const []
            : [
                BoxShadow(
                  color: color.withValues(alpha: 0.16),
                  blurRadius: 10,
                  offset: const Offset(0, 3),
                ),
              ],
      ),
      child: Material(
        color: color.withValues(alpha: 0.2),
        borderRadius: BorderRadius.circular(EsaRadii.card),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => _openEditor(app, app.userProfile.totalWeeks, course),
          child: Container(
            padding: EdgeInsets.all(
              ultraCompact
                  ? 3
                  : compact
                  ? 7
                  : 10,
            ),
            decoration: BoxDecoration(
              border: Border.all(
                color: color.withValues(alpha: 0.6),
                style: dimmed ? BorderStyle.none : BorderStyle.solid,
              ),
              borderRadius: BorderRadius.circular(EsaRadii.card),
            ),
            // 超窄课块也要完整展示信息：字体缩小、允许多行，
            // 超出部分裁剪而不是报 overflow
            child: ClipRect(
              child: SingleChildScrollView(
                physics: const NeverScrollableScrollPhysics(),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (dimmed)
                      Text(
                        '非本周',
                        maxLines: 1,
                        style: context.texts.bodySmall?.copyWith(
                          fontSize: ultraCompact
                              ? 7
                              : compact
                              ? 8.5
                              : 9.5,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    Text(
                      course.name,
                      maxLines: ultraCompact ? 4 : 2,
                      overflow: TextOverflow.ellipsis,
                      style: context.texts.titleMedium?.copyWith(
                        fontSize: ultraCompact
                            ? 8.5
                            : compact
                            ? 11.5
                            : 12.5,
                        height: ultraCompact ? 1.12 : null,
                      ),
                    ),
                    SizedBox(height: ultraCompact ? 1 : 3),
                    Text(
                      compact
                          ? '${course.startPeriod}-${course.endPeriod} 节'
                          : '${course.startPeriod}-${course.endPeriod} 节 · '
                                '${app.scheduleSettings.courseTimeLabel(course.startPeriod, course.endPeriod)}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.texts.bodySmall?.copyWith(
                        fontSize: ultraCompact
                            ? 7.5
                            : compact
                            ? 9.5
                            : 10.5,
                      ),
                    ),
                    if (course.location.isNotEmpty)
                      Text(
                        course.location,
                        maxLines: ultraCompact ? 2 : 1,
                        overflow: TextOverflow.ellipsis,
                        style: context.texts.bodySmall?.copyWith(
                          fontSize: ultraCompact
                              ? 7.5
                              : compact
                              ? 9.5
                              : 10.5,
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
    return dimmed ? Opacity(opacity: 0.38, child: tile) : tile;
  }

  Future<void> _onTableMenuSelected(AppState app, String value) async {
    try {
      switch (value) {
        case '__create__':
          final name = await _promptTableName(title: '新建课程表');
          if (name == null || name.isEmpty) return;
          await app.createScheduleTable(name);
        case '__rename__':
          final current = app.activeScheduleTable;
          if (current == null) return;
          final name = await _promptTableName(
            title: '重命名课程表',
            initial: current.name,
          );
          if (name == null || name.isEmpty || name == current.name) return;
          await app.renameScheduleTable(current.id, name);
        case '__delete__':
          final current = app.activeScheduleTable;
          if (current == null) return;
          final confirmed = await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('删除课程表'),
              content: Text('确定删除「${current.name}」吗？其中的课程会一并删除。'),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('取消'),
                ),
                FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('删除'),
                ),
              ],
            ),
          );
          if (confirmed != true) return;
          await app.deleteScheduleTable(current.id);
        default:
          await app.switchScheduleTable(value);
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.detail)));
    }
  }

  Future<String?> _promptTableName({
    required String title,
    String initial = '',
  }) {
    return showDialog<String>(
      context: context,
      builder: (context) => _TableNameDialog(title: title, initial: initial),
    );
  }

  /// 返回 null 表示取消；(false, null) 导入当前课程表；(true, name) 导入新课程表
  Future<(bool, String?)?> _askImportTarget(AppState app) async {
    final currentName = app.activeScheduleTable?.name ?? '当前课程表';
    final choice = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('导入到哪个课程表？'),
        children: [
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, 'current'),
            child: Row(
              children: [
                const Icon(LucideIcons.calendarCheck, size: 17),
                const SizedBox(width: 9),
                Expanded(child: Text('添加到「$currentName」')),
              ],
            ),
          ),
          SimpleDialogOption(
            onPressed: () => Navigator.pop(context, 'new'),
            child: const Row(
              children: [
                Icon(LucideIcons.calendarPlus, size: 17),
                SizedBox(width: 9),
                Expanded(child: Text('创建新课程表')),
              ],
            ),
          ),
        ],
      ),
    );
    if (choice == null || !mounted) return null;
    if (choice == 'current') return (false, null);
    final name = await _promptTableName(title: '新课程表名称');
    if (name == null) return null;
    return (true, name.isEmpty ? null : name);
  }

  Future<void> _importSchedule(AppState app) async {
    try {
      final result = await FilePicker.pickFiles(
        type: FileType.custom,
        allowedExtensions: const [
          'pdf',
          'png',
          'jpg',
          'jpeg',
          'webp',
          'html',
          'htm',
        ],
        withData: true,
        cancelUploadOnWindowBlur: false,
      );
      final file = result?.files.singleOrNull;
      if (file == null) return;
      final target = await _askImportTarget(app);
      if (target == null || !mounted) return;
      final (toNewTable, newTableName) = target;
      setState(() => _importing = true);
      final bytes = await file.xFile.readAsBytes();
      final importResult = await app.importScheduleFile(
        filename: file.name,
        bytes: bytes,
        toNewTable: toNewTable,
        newTableName: newTableName,
      );
      if (!mounted) return;
      final count = importResult.courses.length;
      final skipped = importResult.skippedCount;
      final destination =
          toNewTable ? '「${app.activeScheduleTable?.name ?? '新课程表'}」' : '';
      final message = count == 0
          ? (skipped > 0
              ? '识别到 $skipped 条课程与现有课表时间冲突，未导入'
              : '没有发现新的课程，已有课程不会重复导入')
          : (skipped > 0
              ? '已导入 $count 条课程安排到$destination，另有 $skipped 条因时间冲突被跳过'
              : '已识别并导入 $count 条课程安排${destination.isEmpty ? '' : '到$destination'}');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message)),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.detail)));
    } on PlatformException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.message ?? '文件读取失败')));
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  Future<void> _openEditor(
    AppState app,
    int totalWeeks, [
    ScheduleCourse? course,
  ]) async {
    final result = await showModalBottomSheet<_CourseEditorResult>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _CourseEditor(
        course: course,
        totalWeeks: totalWeeks.clamp(1, 30),
        maxPeriods: app.scheduleSettings.totalPeriods,
      ),
    );
    if (result == null) return;
    try {
      if (result.deleteId != null) {
        await app.deleteScheduleCourse(result.deleteId!);
      } else if (result.course != null) {
        await app.saveScheduleCourse(result.course!);
      }
    } on ApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(error.detail)));
    }
  }

  Future<void> _openScheduleSettings(AppState app) async {
    final settings = await showModalBottomSheet<ScheduleSettings>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _ScheduleSettingsSheet(
        initialSettings: app.scheduleSettings,
        minimumTotalPeriods: app.scheduleCourses.fold<int>(
          1,
          (maximum, course) =>
              course.endPeriod > maximum ? course.endPeriod : maximum,
        ),
      ),
    );
    if (settings != null) {
      try {
        await app.saveScheduleSettings(settings);
        if (mounted) setState(() => _resolvedCalendarWeek = false);
      } on ApiException catch (error) {
        if (!mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(error.detail)));
      }
    }
  }
}

class _ScheduleSettingsSheet extends StatefulWidget {
  const _ScheduleSettingsSheet({
    required this.initialSettings,
    required this.minimumTotalPeriods,
  });

  final ScheduleSettings initialSettings;
  final int minimumTotalPeriods;

  @override
  State<_ScheduleSettingsSheet> createState() => _ScheduleSettingsSheetState();
}

class _ScheduleSettingsSheetState extends State<_ScheduleSettingsSheet> {
  final _formKey = GlobalKey<FormState>();
  late TimeOfDay _morningStart;
  late TimeOfDay _afternoonStart;
  late TimeOfDay _eveningStart;
  late final TextEditingController _morningCount;
  late final TextEditingController _afternoonCount;
  late final TextEditingController _eveningCount;
  late final TextEditingController _duration;
  late final TextEditingController _breakDuration;
  DateTime? _termStartDate;

  @override
  void initState() {
    super.initState();
    final settings = widget.initialSettings;
    _morningStart = _timeOfDay(settings.morningStartMinutes);
    _afternoonStart = _timeOfDay(settings.afternoonStartMinutes);
    _eveningStart = _timeOfDay(settings.eveningStartMinutes);
    _morningCount = TextEditingController(
      text: settings.morningPeriodCount.toString(),
    );
    _afternoonCount = TextEditingController(
      text: settings.afternoonPeriodCount.toString(),
    );
    _eveningCount = TextEditingController(
      text: settings.eveningPeriodCount.toString(),
    );
    _duration = TextEditingController(
      text: settings.periodDurationMinutes.toString(),
    );
    _breakDuration = TextEditingController(
      text: settings.breakDurationMinutes.toString(),
    );
    _termStartDate = settings.parsedTermStartDate;
  }

  @override
  void dispose() {
    _morningCount.dispose();
    _afternoonCount.dispose();
    _eveningCount.dispose();
    _duration.dispose();
    _breakDuration.dispose();
    super.dispose();
  }

  TimeOfDay _timeOfDay(int minutes) =>
      TimeOfDay(hour: minutes ~/ 60, minute: minutes % 60);

  int _minutesOfDay(TimeOfDay time) => time.hour * 60 + time.minute;

  String _dateValue(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}-'
      '${date.month.toString().padLeft(2, '0')}-'
      '${date.day.toString().padLeft(2, '0')}';

  Future<void> _pickTermStartDate() async {
    final now = DateTime.now();
    final currentMonday = now.subtract(Duration(days: now.weekday - 1));
    final value = await showDatePicker(
      context: context,
      initialDate: _termStartDate ?? currentMonday,
      firstDate: DateTime(now.year - 2),
      lastDate: DateTime(now.year + 2),
      helpText: '选择第一教学周的周一',
      cancelText: '取消',
      confirmText: '确定',
    );
    if (value != null) setState(() => _termStartDate = value);
  }

  Future<void> _pickStartTime(
    TimeOfDay initialTime,
    ValueChanged<TimeOfDay> onSelected,
    String periodName,
  ) async {
    final value = await showTimePicker(
      context: context,
      initialTime: initialTime,
      helpText: '设置$periodName第一节开始时间',
      cancelText: '取消',
      confirmText: '确定',
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(alwaysUse24HourFormat: true),
        child: child!,
      ),
    );
    if (value != null) setState(() => onSelected(value));
  }

  String? _validateCount(String? raw) =>
      _validateMinutes(raw, minimum: 0, maximum: 8, unit: '节');

  String? _validateMinutes(
    String? raw, {
    required int minimum,
    required int maximum,
    String unit = '分钟',
  }) {
    final value = int.tryParse(raw ?? '');
    if (value == null) return '请输入整数';
    if (value < minimum || value > maximum) {
      return '范围 $minimum–$maximum $unit';
    }
    return null;
  }

  void _save() {
    if (!_formKey.currentState!.validate()) return;
    final settings = _currentSettings();
    if (settings.totalPeriods < widget.minimumTotalPeriods) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('已有课程使用到第 ${widget.minimumTotalPeriods} 节，总节数不能更少'),
        ),
      );
      return;
    }
    if (!_sessionsDoNotOverlap(settings)) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('上午、下午、晚上的上课时间不能互相重叠')));
      return;
    }
    Navigator.pop(context, settings);
  }

  ScheduleSettings _currentSettings() => ScheduleSettings(
    morningPeriodCount: int.tryParse(_morningCount.text) ?? 0,
    afternoonPeriodCount: int.tryParse(_afternoonCount.text) ?? 0,
    eveningPeriodCount: int.tryParse(_eveningCount.text) ?? 0,
    morningStartMinutes: _minutesOfDay(_morningStart),
    afternoonStartMinutes: _minutesOfDay(_afternoonStart),
    eveningStartMinutes: _minutesOfDay(_eveningStart),
    periodDurationMinutes: int.tryParse(_duration.text) ?? 45,
    breakDurationMinutes: int.tryParse(_breakDuration.text) ?? 10,
    termStartDate: _termStartDate == null ? '' : _dateValue(_termStartDate!),
  );

  bool _sessionsDoNotOverlap(ScheduleSettings settings) {
    final sessions = <(int, int)>[
      if (settings.morningPeriodCount > 0)
        (settings.morningStartMinutes, settings.morningPeriodCount),
      if (settings.afternoonPeriodCount > 0)
        (settings.afternoonStartMinutes, settings.afternoonPeriodCount),
      if (settings.eveningPeriodCount > 0)
        (settings.eveningStartMinutes, settings.eveningPeriodCount),
    ];
    for (var index = 0; index < sessions.length - 1; index++) {
      final current = sessions[index];
      final next = sessions[index + 1];
      final currentEnd =
          current.$1 +
          current.$2 * settings.periodDurationMinutes +
          (current.$2 - 1) * settings.breakDurationMinutes;
      if (currentEnd > next.$1) return false;
    }
    return true;
  }

  String _sessionSummary(int startMinutes, int count, ScheduleSettings value) {
    if (count == 0) return '无课';
    final endMinutes =
        startMinutes +
        count * value.periodDurationMinutes +
        (count - 1) * value.breakDurationMinutes;
    return '${formatClockMinutes(startMinutes)}–${formatClockMinutes(endMinutes)}';
  }

  Widget _sessionRow(
    BuildContext context, {
    required String title,
    required String keyPrefix,
    required TextEditingController countController,
    required TimeOfDay startTime,
    required ValueChanged<TimeOfDay> onTimeChanged,
  }) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.n.n100,
        borderRadius: BorderRadius.circular(EsaRadii.card),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 44,
            child: Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text(title, style: context.texts.titleMedium),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 92,
            child: TextFormField(
              key: ValueKey('schedule-$keyPrefix-count'),
              controller: countController,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '节数',
                suffixText: '节',
              ),
              validator: _validateCount,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: InkWell(
              key: ValueKey('schedule-$keyPrefix-start-time'),
              onTap: () => _pickStartTime(startTime, onTimeChanged, title),
              borderRadius: BorderRadius.circular(EsaRadii.field),
              child: InputDecorator(
                decoration: const InputDecoration(
                  labelText: '第一节开始',
                  suffixIcon: Icon(LucideIcons.clock3, size: 18),
                ),
                child: Text(formatClockMinutes(_minutesOfDay(startTime))),
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    final preview = _currentSettings();
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(12, 12, 12, bottom + 12),
        child: Align(
          alignment: Alignment.bottomCenter,
          child: Container(
            width: double.infinity,
            constraints: BoxConstraints(
              maxWidth: 520,
              maxHeight: MediaQuery.sizeOf(context).height - bottom - 36,
            ),
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: context.scheme.surface,
              border: Border.all(color: context.n.divider),
              borderRadius: BorderRadius.circular(EsaRadii.sheet),
            ),
            child: Form(
              key: _formKey,
              onChanged: () => setState(() {}),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        const Icon(LucideIcons.settings2, size: 19),
                        const SizedBox(width: 9),
                        Text('课表设置', style: context.texts.headlineSmall),
                        const Spacer(),
                        IconButton(
                          onPressed: () => Navigator.pop(context),
                          icon: const Icon(LucideIcons.x),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    InkWell(
                      key: const ValueKey('schedule-term-start-date'),
                      onTap: _pickTermStartDate,
                      borderRadius: BorderRadius.circular(EsaRadii.card),
                      child: Container(
                        padding: const EdgeInsets.all(13),
                        decoration: BoxDecoration(
                          color: context.n.n100,
                          borderRadius: BorderRadius.circular(EsaRadii.card),
                        ),
                        child: Row(
                          children: [
                            const Icon(LucideIcons.calendarRange, size: 18),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    '第一周日期',
                                    style: context.texts.titleMedium,
                                  ),
                                  Text(
                                    _termStartDate == null
                                        ? '未设置（点击选择第一周周一）'
                                        : '${_dateValue(_termStartDate!)} · 系统将自动计算当前教学周',
                                    style: context.texts.bodySmall,
                                  ),
                                ],
                              ),
                            ),
                            const Icon(LucideIcons.chevronRight, size: 17),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    _sessionRow(
                      context,
                      title: '上午',
                      keyPrefix: 'morning',
                      countController: _morningCount,
                      startTime: _morningStart,
                      onTimeChanged: (value) => _morningStart = value,
                    ),
                    const SizedBox(height: 8),
                    _sessionRow(
                      context,
                      title: '下午',
                      keyPrefix: 'afternoon',
                      countController: _afternoonCount,
                      startTime: _afternoonStart,
                      onTimeChanged: (value) => _afternoonStart = value,
                    ),
                    const SizedBox(height: 8),
                    _sessionRow(
                      context,
                      title: '晚上',
                      keyPrefix: 'evening',
                      countController: _eveningCount,
                      startTime: _eveningStart,
                      onTimeChanged: (value) => _eveningStart = value,
                    ),
                    const SizedBox(height: 14),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: TextFormField(
                            key: const ValueKey('schedule-period-duration'),
                            controller: _duration,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                              labelText: '每节课时长',
                              suffixText: '分钟',
                            ),
                            validator: (value) => _validateMinutes(
                              value,
                              minimum: 20,
                              maximum: 180,
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: TextFormField(
                            key: const ValueKey('schedule-break-duration'),
                            controller: _breakDuration,
                            keyboardType: TextInputType.number,
                            decoration: const InputDecoration(
                              labelText: '课间间隔',
                              suffixText: '分钟',
                            ),
                            validator: (value) => _validateMinutes(
                              value,
                              minimum: 0,
                              maximum: 120,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: context.n.n100,
                        borderRadius: BorderRadius.circular(EsaRadii.card),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            LucideIcons.clock,
                            size: 17,
                            color: context.n.n600,
                          ),
                          const SizedBox(width: 9),
                          Expanded(
                            child: Text(
                              '共 ${preview.totalPeriods} 节\n'
                              '上午 ${_sessionSummary(preview.morningStartMinutes, preview.morningPeriodCount, preview)} · '
                              '下午 ${_sessionSummary(preview.afternoonStartMinutes, preview.afternoonPeriodCount, preview)} · '
                              '晚上 ${_sessionSummary(preview.eveningStartMinutes, preview.eveningPeriodCount, preview)}',
                              style: context.texts.bodySmall,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 18),
                    Row(
                      children: [
                        const Spacer(),
                        TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('取消'),
                        ),
                        const SizedBox(width: 8),
                        FilledButton(
                          key: const ValueKey('save-schedule-settings'),
                          onPressed: _save,
                          child: const Text('保存设置'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ScheduleGridPainter extends CustomPainter {
  const _ScheduleGridPainter({
    required this.divider,
    required this.surface,
    required this.labelWidth,
    required this.headerHeight,
    required this.dayWidth,
    required this.periodHeight,
    required this.periodCount,
  });

  final Color divider;
  final Color surface;
  final double labelWidth;
  final double headerHeight;
  final double dayWidth;
  final double periodHeight;
  final int periodCount;

  @override
  void paint(Canvas canvas, Size size) {
    final background = Paint()..color = surface;
    final line = Paint()
      ..color = divider
      ..strokeWidth = 1;
    canvas.drawRRect(
      RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(14)),
      background,
    );
    canvas.drawLine(
      Offset(0, headerHeight),
      Offset(size.width, headerHeight),
      line,
    );
    canvas.drawLine(
      Offset(labelWidth, 0),
      Offset(labelWidth, size.height),
      line,
    );
    for (var day = 1; day <= 7; day++) {
      final x = labelWidth + day * dayWidth;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), line);
    }
    for (var period = 1; period <= periodCount; period++) {
      final y = headerHeight + period * periodHeight;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), line);
    }
  }

  @override
  bool shouldRepaint(covariant _ScheduleGridPainter oldDelegate) =>
      oldDelegate.divider != divider || oldDelegate.surface != surface;
}

class _CourseEditorResult {
  const _CourseEditorResult.course(this.course) : deleteId = null;
  const _CourseEditorResult.delete(this.deleteId) : course = null;

  final ScheduleCourse? course;
  final String? deleteId;
}

class _CourseEditor extends StatefulWidget {
  const _CourseEditor({
    required this.totalWeeks,
    required this.maxPeriods,
    this.course,
  });

  final int totalWeeks;
  final int maxPeriods;
  final ScheduleCourse? course;

  @override
  State<_CourseEditor> createState() => _CourseEditorState();
}

class _CourseEditorState extends State<_CourseEditor> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _teacher;
  late final TextEditingController _location;
  late int _weekday;
  late int _startPeriod;
  late int _endPeriod;
  late int _startWeek;
  late int _endWeek;
  late int _colorValue;

  @override
  void initState() {
    super.initState();
    final course = widget.course;
    _name = TextEditingController(text: course?.name ?? '');
    _teacher = TextEditingController(text: course?.teacher ?? '');
    _location = TextEditingController(text: course?.location ?? '');
    _weekday = course?.weekday ?? 1;
    _startPeriod = (course?.startPeriod ?? 1).clamp(1, widget.maxPeriods);
    _endPeriod = (course?.endPeriod ?? 2).clamp(1, widget.maxPeriods);
    _startWeek = course?.startWeek ?? 1;
    _endWeek = (course?.endWeek ?? widget.totalWeeks).clamp(
      1,
      widget.totalWeeks,
    );
    _colorValue = course?.colorValue ?? _courseColors.first;
  }

  @override
  void dispose() {
    _name.dispose();
    _teacher.dispose();
    _location.dispose();
    super.dispose();
  }

  void _save() {
    if (!_formKey.currentState!.validate()) return;
    if (_endPeriod < _startPeriod || _endWeek < _startWeek) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('结束节次/周数不能早于开始值')));
      return;
    }
    Navigator.pop(
      context,
      _CourseEditorResult.course(
        ScheduleCourse(
          id:
              widget.course?.id ??
              DateTime.now().microsecondsSinceEpoch.toString(),
          name: _name.text.trim(),
          teacher: _teacher.text.trim(),
          location: _location.text.trim(),
          weekday: _weekday,
          startPeriod: _startPeriod,
          endPeriod: _endPeriod,
          startWeek: _startWeek,
          endWeek: _endWeek,
          colorValue: _colorValue,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(12, 12, 12, bottom + 12),
        child: Align(
          alignment: Alignment.bottomCenter,
          child: Container(
            width: double.infinity,
            constraints: const BoxConstraints(maxWidth: 620, maxHeight: 720),
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: context.scheme.surface,
              border: Border.all(color: context.n.divider),
              borderRadius: BorderRadius.circular(EsaRadii.sheet),
            ),
            child: Form(
              key: _formKey,
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Text(
                          widget.course == null ? '添加课程' : '编辑课程',
                          style: context.texts.headlineSmall,
                        ),
                        const Spacer(),
                        IconButton(
                          onPressed: () => Navigator.pop(context),
                          icon: const Icon(LucideIcons.x),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      key: const ValueKey('schedule-course-name'),
                      controller: _name,
                      decoration: const InputDecoration(labelText: '课程名称'),
                      validator: (value) =>
                          value == null || value.trim().isEmpty
                          ? '请输入课程名称'
                          : null,
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: TextFormField(
                            controller: _teacher,
                            decoration: const InputDecoration(labelText: '教师'),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: TextFormField(
                            controller: _location,
                            decoration: const InputDecoration(labelText: '教室'),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    DropdownButtonFormField<int>(
                      initialValue: _weekday,
                      decoration: const InputDecoration(labelText: '星期'),
                      items: [
                        for (var day = 1; day <= 7; day++)
                          DropdownMenuItem(
                            value: day,
                            child: Text(_weekdays[day - 1]),
                          ),
                      ],
                      onChanged: (value) => _weekday = value ?? _weekday,
                    ),
                    const SizedBox(height: 10),
                    _rangeRow(
                      context,
                      '节次',
                      _startPeriod,
                      _endPeriod,
                      widget.maxPeriods,
                      (value) => setState(() => _startPeriod = value),
                      (value) => setState(() => _endPeriod = value),
                    ),
                    const SizedBox(height: 10),
                    _rangeRow(
                      context,
                      '教学周',
                      _startWeek,
                      _endWeek,
                      widget.totalWeeks,
                      (value) => setState(() => _startWeek = value),
                      (value) => setState(() => _endWeek = value),
                    ),
                    const SizedBox(height: 14),
                    Text('课程颜色', style: context.texts.titleMedium),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 10,
                      children: [
                        for (final value in _courseColors)
                          InkWell(
                            onTap: () => setState(() => _colorValue = value),
                            customBorder: const CircleBorder(),
                            child: Container(
                              width: 34,
                              height: 34,
                              decoration: BoxDecoration(
                                color: Color(value),
                                shape: BoxShape.circle,
                                border: Border.all(
                                  color: value == _colorValue
                                      ? context.scheme.onSurface
                                      : Colors.transparent,
                                  width: 3,
                                ),
                              ),
                              child: value == _colorValue
                                  ? const Icon(
                                      LucideIcons.check,
                                      size: 17,
                                      color: Colors.white,
                                    )
                                  : null,
                            ),
                          ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    Row(
                      children: [
                        if (widget.course != null)
                          TextButton.icon(
                            onPressed: () => Navigator.pop(
                              context,
                              _CourseEditorResult.delete(widget.course!.id),
                            ),
                            icon: const Icon(LucideIcons.trash2, size: 16),
                            label: const Text('删除'),
                          ),
                        const Spacer(),
                        TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('取消'),
                        ),
                        const SizedBox(width: 8),
                        FilledButton(onPressed: _save, child: const Text('保存')),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _rangeRow(
    BuildContext context,
    String label,
    int start,
    int end,
    int max,
    ValueChanged<int> onStart,
    ValueChanged<int> onEnd,
  ) {
    return Row(
      children: [
        SizedBox(
          width: 62,
          child: Text(label, style: context.texts.titleMedium),
        ),
        Expanded(
          child: DropdownButtonFormField<int>(
            initialValue: start,
            decoration: const InputDecoration(labelText: '开始'),
            items: [
              for (var value = 1; value <= max; value++)
                DropdownMenuItem(value: value, child: Text('$value')),
            ],
            onChanged: (value) {
              if (value != null) onStart(value);
            },
          ),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 8),
          child: Text('至'),
        ),
        Expanded(
          child: DropdownButtonFormField<int>(
            initialValue: end,
            decoration: const InputDecoration(labelText: '结束'),
            items: [
              for (var value = 1; value <= max; value++)
                DropdownMenuItem(value: value, child: Text('$value')),
            ],
            onChanged: (value) {
              if (value != null) onEnd(value);
            },
          ),
        ),
      ],
    );
  }
}

/// 自持 ScrollController 的滚动容器。周切换动画期间新旧两棵子树
/// 同时存在，各自持有控制器才能同时挂 Scrollbar。
class _OwnScrollbarScrollView extends StatefulWidget {
  const _OwnScrollbarScrollView({required this.builder});

  final Widget Function(BuildContext, ScrollController) builder;

  @override
  State<_OwnScrollbarScrollView> createState() =>
      _OwnScrollbarScrollViewState();
}

class _OwnScrollbarScrollViewState extends State<_OwnScrollbarScrollView> {
  final ScrollController _controller = ScrollController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(context, _controller);
}

/// 课程表名称输入对话框。控制器由本组件持有，随组件生命周期在
/// 关闭动画结束后才释放，避免"controller used after being disposed"。
class _TableNameDialog extends StatefulWidget {
  const _TableNameDialog({required this.title, required this.initial});

  final String title;
  final String initial;

  @override
  State<_TableNameDialog> createState() => _TableNameDialogState();
}

class _TableNameDialogState extends State<_TableNameDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initial);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: TextField(
        controller: _controller,
        autofocus: true,
        maxLength: 40,
        decoration: const InputDecoration(hintText: '课程表名称'),
        onSubmitted: (value) => Navigator.pop(context, value.trim()),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text.trim()),
          child: const Text('确定'),
        ),
      ],
    );
  }
}
