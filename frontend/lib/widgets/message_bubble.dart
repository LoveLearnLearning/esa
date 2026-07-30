// 用户消息 —— 右对齐气泡 最大宽 78% 底色 neutral-200 圆角 18

import 'package:flutter/material.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import 'esa_markdown.dart';

class UserBubble extends StatelessWidget {
  const UserBubble({super.key, required this.text, this.markdown = false});

  final String text;
  final bool markdown;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.78,
        ),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: context.n.n200,
            borderRadius: BorderRadius.circular(EsaRadii.bubble),
          ),
          child: markdown
              ? EsaMarkdown(data: text, selectable: true)
              : Text(
                  text,
                  style: context.texts.bodyMedium, // 15 / 1.65 保留换行
                ),
        ),
      ),
    );
  }
}
