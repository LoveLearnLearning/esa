// 工具调用块 —— 1px 描边 圆角 12 底色 neutral-100 显示在助手正文之前

import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../models/models.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

class ToolCallCard extends StatelessWidget {
  const ToolCallCard({super.key, required this.tool});

  final ToolInvocation tool;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: context.n.n100,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.toolCard),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 头部
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: context.n.divider)),
            ),
            child: Row(
              children: [
                const Icon(LucideIcons.wrench, size: 14, color: EsaColors.accent),
                const SizedBox(width: 8),
                Text(
                  'TOOL · ${tool.name}',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 1.0,
                    color: context.n.n700,
                  ),
                ),
                const Spacer(),
                if (tool.durationMs != null)
                  Text(
                    '${tool.durationMs} ms',
                    style: TextStyle(fontSize: 11, color: context.n.n600),
                  ),
              ],
            ),
          ),
          // 内容
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Text(
              tool.output,
              style: TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                height: 1.7,
                color: context.n.n700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
