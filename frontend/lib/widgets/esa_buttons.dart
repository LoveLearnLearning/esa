// 主红色按钮 —— 宽按钮标签左对齐 右侧可放箭头图标 禁用时透明度 .45

import 'package:flutter/material.dart';

import '../theme/esa_theme.dart';

class EsaRedButton extends StatelessWidget {
  const EsaRedButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.leading,
    this.trailing,
    this.height = 48,
    this.radius = EsaRadii.buttonLg,
    this.alignStart = true,
    this.fontSize = 13,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? leading;
  final IconData? trailing;
  final double height;
  final double radius;
  final bool alignStart; // true 左对齐(宽按钮) false 居中
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: Material(
        color: EsaColors.accent,
        borderRadius: BorderRadius.circular(radius),
        child: InkWell(
          onTap: onPressed,
          borderRadius: BorderRadius.circular(radius),
          child: SizedBox(
            height: height,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                mainAxisAlignment:
                    alignStart ? MainAxisAlignment.start : MainAxisAlignment.center,
                children: [
                  if (leading != null) ...[
                    Icon(leading, size: 16, color: EsaColors.onAccent),
                    const SizedBox(width: 10),
                  ],
                  Text(
                    label,
                    style: const TextStyle(
                      color: EsaColors.onAccent,
                      fontWeight: FontWeight.w800,
                    ).copyWith(fontSize: fontSize),
                  ),
                  if (trailing != null) ...[
                    if (alignStart) const Spacer(),
                    if (!alignStart) const SizedBox(width: 10),
                    Icon(trailing, size: 18, color: EsaColors.onAccent),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
