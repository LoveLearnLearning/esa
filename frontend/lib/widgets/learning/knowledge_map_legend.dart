import 'package:flutter/material.dart';

import '../../theme/esa_context.dart';

class KnowledgeMapLegend extends StatelessWidget {
  const KnowledgeMapLegend({super.key});

  @override
  Widget build(BuildContext context) {
    const items = [
      ('未评估', Color(0xFF8B8787)),
      ('需加强', Color(0xFFEF4444)),
      ('学习中', Color(0xFFF59E0B)),
      ('较好', Color(0xFF22C55E)),
      ('稳定掌握', Color(0xFF10B981)),
    ];
    return Wrap(
      spacing: 14,
      runSpacing: 6,
      children: [
        for (final item in items)
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  color: item.$2,
                  shape: BoxShape.circle,
                ),
              ),
              const SizedBox(width: 5),
              Text(item.$1, style: context.texts.bodySmall),
            ],
          ),
      ],
    );
  }
}
