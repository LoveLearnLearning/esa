import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_mobile.dart';
import '../widgets/esa_mobile_controls.dart';
import 'research_project_page.dart';

enum _ResearchFilter { all, active, archived }

class ResearchWorkspacePage extends StatefulWidget {
  const ResearchWorkspacePage({
    super.key,
    required this.onOpenChat,
    this.onOpenProject,
  });

  final VoidCallback onOpenChat;
  final ValueChanged<ResearchProject>? onOpenProject;

  @override
  State<ResearchWorkspacePage> createState() => _ResearchWorkspacePageState();
}

class _ResearchWorkspacePageState extends State<ResearchWorkspacePage> {
  bool _requestedInitialLoad = false;
  final _searchController = TextEditingController();
  _ResearchFilter _filter = _ResearchFilter.all;
  bool _searchVisible = false;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedInitialLoad) return;
    _requestedInitialLoad = true;
    final app = AppScope.of(context);
    if (app.researchProjects.isEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) app.loadResearchProjects();
      });
    }
  }

  Future<void> _createProject() async {
    final name = TextEditingController();
    final description = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('新建科研项目'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const ValueKey('research-project-name'),
                controller: name,
                autofocus: true,
                decoration: const InputDecoration(labelText: '项目名称'),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const ValueKey('research-project-description'),
                controller: description,
                maxLines: 3,
                decoration: const InputDecoration(labelText: '研究目标或说明'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            key: const ValueKey('create-research-project'),
            onPressed: () {
              if (name.text.trim().isNotEmpty) Navigator.pop(context, true);
            },
            child: const Text('创建'),
          ),
        ],
      ),
    );
    if (created == true && mounted) {
      await AppScope.of(
        context,
      ).createResearchProject(name.text, description.text);
    }
    name.dispose();
    description.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (MediaQuery.sizeOf(context).width < 700) {
      return _mobile(context, app);
    }
    return Scaffold(
      body: CustomScrollView(
        slivers: [
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(24, 30, 24, 12),
            sliver: SliverToBoxAdapter(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('科研工作空间', style: context.texts.headlineMedium),
                        const SizedBox(height: 8),
                        Text(
                          '项目隔离文献、写作、趋势追踪与数据分析上下文。',
                          style: context.texts.bodyMedium?.copyWith(
                            color: context.n.n600,
                          ),
                        ),
                      ],
                    ),
                  ),
                  FilledButton.icon(
                    key: const ValueKey('new-research-project'),
                    onPressed: _createProject,
                    icon: const Icon(LucideIcons.plus, size: 17),
                    label: const Text('新建项目'),
                  ),
                ],
              ),
            ),
          ),
          if (app.loadingResearchProjects && app.researchProjects.isEmpty)
            const SliverFillRemaining(
              child: Center(child: CircularProgressIndicator()),
            )
          else if (app.researchProjects.isEmpty)
            SliverFillRemaining(
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(LucideIcons.flaskConical, size: 42),
                    const SizedBox(height: 16),
                    Text('还没有科研项目', style: context.texts.titleLarge),
                    const SizedBox(height: 8),
                    const Text('先创建一个项目，再进入独立科研对话。'),
                  ],
                ),
              ),
            )
          else
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(24, 12, 24, 32),
              sliver: SliverGrid.builder(
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                  maxCrossAxisExtent: 430,
                  mainAxisExtent: 190,
                  crossAxisSpacing: 16,
                  mainAxisSpacing: 16,
                ),
                itemCount: app.researchProjects.length,
                itemBuilder: (context, index) => _ProjectCard(
                  project: app.researchProjects[index],
                  onOpen: () async {
                    if (widget.onOpenProject != null) {
                      widget.onOpenProject!(app.researchProjects[index]);
                      return;
                    }
                    await Navigator.of(context).push<void>(
                      MaterialPageRoute(
                        builder: (_) => AppScope(
                          state: app,
                          child: ResearchProjectPage(
                            project: app.researchProjects[index],
                            onOpenChat: widget.onOpenChat,
                          ),
                        ),
                      ),
                    );
                  },
                  onArchive: () => app.archiveResearchProject(
                    app.researchProjects[index].id,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _mobile(BuildContext context, AppState app) {
    final query = _searchController.text.trim().toLowerCase();
    final projects = app.researchProjects.where((project) {
      final archived = project.status == 'archived';
      final matchesFilter = switch (_filter) {
        _ResearchFilter.all => true,
        _ResearchFilter.active => !archived,
        _ResearchFilter.archived => archived,
      };
      final matchesQuery =
          query.isEmpty ||
          project.name.toLowerCase().contains(query) ||
          project.description.toLowerCase().contains(query);
      return matchesFilter && matchesQuery;
    }).toList();

    return Scaffold(
      body: Column(
        children: [
          Container(
            height: EsaMobile.topBarHeight,
            padding: const EdgeInsets.only(left: 16, right: 4),
            decoration: BoxDecoration(
              color: context.scheme.surface,
              border: Border(bottom: BorderSide(color: context.n.divider)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    '研究空间',
                    style: context.texts.titleLarge?.copyWith(
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                EsaMobileIconButton(
                  key: const ValueKey('research-search-toggle'),
                  tooltip: '搜索项目',
                  icon: _searchVisible ? LucideIcons.x : LucideIcons.search,
                  selected: _searchVisible,
                  onPressed: () =>
                      setState(() => _searchVisible = !_searchVisible),
                ),
                EsaMobileIconButton(
                  key: const ValueKey('new-research-project'),
                  tooltip: '新建项目',
                  icon: LucideIcons.plus,
                  onPressed: _createProject,
                ),
              ],
            ),
          ),
          AnimatedSize(
            duration: EsaMobile.motion(
              context,
              duration: const Duration(milliseconds: 160),
            ),
            child: !_searchVisible
                ? const SizedBox.shrink()
                : Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: SizedBox(
                      height: 44,
                      child: TextField(
                        key: const ValueKey('research-search-field'),
                        controller: _searchController,
                        autofocus: true,
                        onChanged: (_) => setState(() {}),
                        decoration: const InputDecoration(
                          hintText: '搜索项目',
                          prefixIcon: Icon(LucideIcons.search, size: 18),
                        ),
                      ),
                    ),
                  ),
          ),
          EsaMobileTabStrip<_ResearchFilter>(
            value: _filter,
            entries: const [
              EsaMobileTabEntry(_ResearchFilter.all, '全部'),
              EsaMobileTabEntry(_ResearchFilter.active, '进行中'),
              EsaMobileTabEntry(_ResearchFilter.archived, '已归档'),
            ],
            onChanged: (value) => setState(() => _filter = value),
            height: EsaMobile.touchTarget,
            minItemWidth: 76,
          ),
          Expanded(
            child: app.loadingResearchProjects && app.researchProjects.isEmpty
                ? const Center(child: CircularProgressIndicator())
                : projects.isEmpty
                ? _ResearchEmptyState(
                    filtered:
                        app.researchProjects.isNotEmpty || query.isNotEmpty,
                    onCreate: _createProject,
                  )
                : ListView.separated(
                    key: const ValueKey('mobile-research-project-list'),
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                    itemCount: projects.length,
                    separatorBuilder: (_, _) =>
                        Divider(height: 1, color: context.n.divider),
                    itemBuilder: (context, index) => _MobileProjectRow(
                      project: projects[index],
                      onOpen: () => _openProject(app, projects[index]),
                      onArchive: () =>
                          app.archiveResearchProject(projects[index].id),
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  Future<void> _openProject(AppState app, ResearchProject project) async {
    if (widget.onOpenProject != null) {
      widget.onOpenProject!(project);
      return;
    }
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AppScope(
          state: app,
          child: ResearchProjectPage(
            project: project,
            onOpenChat: widget.onOpenChat,
          ),
        ),
      ),
    );
  }
}

class _MobileProjectRow extends StatelessWidget {
  const _MobileProjectRow({
    required this.project,
    required this.onOpen,
    required this.onArchive,
  });

  final ResearchProject project;
  final VoidCallback onOpen;
  final VoidCallback onArchive;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.transparent,
    child: InkWell(
      key: ValueKey('mobile-research-project-${project.id}'),
      onTap: onOpen,
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 116),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 40,
                height: 40,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: context.n.n200,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  LucideIcons.flaskConical,
                  size: 20,
                  color: context.scheme.primary,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      project.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.texts.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      project.description.isEmpty
                          ? '暂无项目说明'
                          : project.description,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: context.texts.bodySmall?.copyWith(fontSize: 13),
                    ),
                    const SizedBox(height: 7),
                    Wrap(
                      spacing: 10,
                      runSpacing: 3,
                      children: [
                        Text(
                          '更新 ${_researchDate(project.updatedAt)}',
                          style: context.texts.labelSmall,
                        ),
                        Text(
                          '文献 ${project.documentCount}',
                          style: context.texts.labelSmall,
                        ),
                        Text(
                          project.status == 'archived' ? '已归档' : '进行中',
                          style: context.texts.labelSmall?.copyWith(
                            color: project.status == 'archived'
                                ? context.n.n600
                                : context.scheme.primary,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                tooltip: '项目操作',
                constraints: const BoxConstraints(minWidth: 160, maxWidth: 220),
                padding: EdgeInsets.zero,
                icon: const Icon(LucideIcons.ellipsisVertical, size: 19),
                onSelected: (value) {
                  if (value == 'archive') onArchive();
                },
                itemBuilder: (_) => [
                  PopupMenuItem(
                    value: 'archive',
                    enabled: project.status != 'archived',
                    child: const Text('归档项目'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _ResearchEmptyState extends StatelessWidget {
  const _ResearchEmptyState({required this.filtered, required this.onCreate});

  final bool filtered;
  final VoidCallback onCreate;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(LucideIcons.flaskConical, size: 32, color: context.n.n500),
          const SizedBox(height: 12),
          Text(
            filtered ? '没有匹配的项目' : '还没有研究项目',
            style: context.texts.titleMedium,
          ),
          const SizedBox(height: 6),
          Text(
            filtered ? '调整搜索词或筛选条件' : '创建项目来组织文献、写作和分析',
            style: context.texts.bodySmall,
            textAlign: TextAlign.center,
          ),
          if (!filtered) ...[
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onCreate,
              icon: const Icon(LucideIcons.plus, size: 17),
              label: const Text('新建项目'),
            ),
          ],
        ],
      ),
    ),
  );
}

String _researchDate(DateTime value) {
  final local = value.toLocal();
  return '${local.month} 月 ${local.day} 日';
}

class _ProjectCard extends StatelessWidget {
  const _ProjectCard({
    required this.project,
    required this.onOpen,
    required this.onArchive,
  });

  final ResearchProject project;
  final VoidCallback onOpen;
  final VoidCallback onArchive;

  @override
  Widget build(BuildContext context) => Card(
    child: InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onOpen,
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(LucideIcons.flaskConical, size: 19),
                const Spacer(),
                IconButton(
                  tooltip: '归档项目',
                  onPressed: onArchive,
                  icon: const Icon(LucideIcons.archive, size: 18),
                ),
              ],
            ),
            Text(project.name, style: context.texts.titleLarge),
            const SizedBox(height: 8),
            Expanded(
              child: Text(
                project.description.isEmpty ? '暂无项目说明' : project.description,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: context.texts.bodyMedium?.copyWith(
                  color: context.n.n600,
                ),
              ),
            ),
            const Row(
              children: [
                Text('进入项目'),
                SizedBox(width: 6),
                Icon(LucideIcons.arrowRight, size: 16),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}
