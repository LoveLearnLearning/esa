// 工具调用块 —— 1px 描边 圆角 12 底色 neutral-100
// 对应后端返回的 role == "tool" 的消息 name 为工具名 content 为结果

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

class ToolCallCard extends StatelessWidget {
  const ToolCallCard({
    super.key,
    required this.name,
    required this.output,
    this.durationMs,
  });

  final String name;
  final String output;
  final int? durationMs;

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
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: context.n.divider)),
            ),
            child: Row(
              children: [
                const Icon(
                  LucideIcons.wrench,
                  size: 14,
                  color: EsaColors.accent,
                ),
                const SizedBox(width: 8),
                Text(
                  'TOOL · $name',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 1.0,
                    color: context.n.n700,
                  ),
                ),
                const Spacer(),
                if (durationMs != null)
                  Text(
                    '$durationMs ms',
                    style: TextStyle(fontSize: 11, color: context.n.n600),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: SelectableText(
              output,
              style: TextStyle(
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
