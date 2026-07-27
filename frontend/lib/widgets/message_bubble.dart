// 用户消息 —— 右对齐气泡 最大宽 78% 底色 neutral-200 圆角 18

import 'package:flutter/material.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

class UserBubble extends StatelessWidget {
  const UserBubble({super.key, required this.text});

  final String text;

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
          child: Text(
            text,
            style: context.texts.bodyMedium, // 15 / 1.65 保留换行
          ),
        ),
      ),
    );
  }
}
