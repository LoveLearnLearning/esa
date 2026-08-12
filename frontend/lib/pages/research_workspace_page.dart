import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../theme/esa_context.dart';
import 'research_project_page.dart';

class ResearchWorkspacePage extends StatefulWidget {
  const ResearchWorkspacePage({super.key, required this.onOpenChat});

  final VoidCallback onOpenChat;

  @override
  State<ResearchWorkspacePage> createState() => _ResearchWorkspacePageState();
}

class _ResearchWorkspacePageState extends State<ResearchWorkspacePage> {
  bool _requestedInitialLoad = false;

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
