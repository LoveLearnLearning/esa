// 分段控件 —— 1px 描边容器 选中格底色为 text 字色为 bg
// 用于 登录/注册 切换 外观切换 身份切换

import 'package:flutter/material.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

class EsaSegment<T> {
  const EsaSegment(this.value, this.label, {this.sublabel});
  final T value;
  final String label;
  final String? sublabel; // 例如 LOG IN
}

class EsaSegmented<T> extends StatelessWidget {
  const EsaSegmented({
    super.key,
    required this.value,
    required this.segments,
    required this.onChanged,
    this.height = 42,
  });

  final T value;
  final List<EsaSegment<T>> segments;
  final ValueChanged<T> onChanged;
  final double height;

  @override
  Widget build(BuildContext context) {
    final bg = Theme.of(context).scaffoldBackgroundColor;
    return Container(
      height: height,
      decoration: BoxDecoration(
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.button),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(EsaRadii.button - 1),
        child: Row(
          children: [
            for (final seg in segments)
              Expanded(
                child: _Cell(
                  selected: seg.value == value,
                  bg: bg,
                  onTap: () => onChanged(seg.value),
                  child: _label(context, seg, seg.value == value, bg),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _label(BuildContext context, EsaSegment<T> seg, bool selected, Color bg) {
    final fg = selected ? bg : context.n.n600;
    if (seg.sublabel == null) {
      return Text(
        seg.label,
        style: context.texts.titleMedium?.copyWith(color: fg, fontSize: 13),
      );
    }
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      crossAxisAlignment: CrossAxisAlignment.baseline,
      textBaseline: TextBaseline.alphabetic,
      children: [
        Text(
          seg.label,
          style: context.texts.titleMedium?.copyWith(color: fg, fontSize: 13),
        ),
        const SizedBox(width: 6),
        Text(
          seg.sublabel!,
          style: TextStyle(
            color: selected ? bg.withValues(alpha: 0.7) : context.n.n500,
            fontSize: 10,
            fontWeight: FontWeight.w600,
            letterSpacing: 1.0,
          ),
        ),
      ],
    );
  }
}

class _Cell extends StatelessWidget {
  const _Cell({
    required this.selected,
    required this.bg,
    required this.onTap,
    required this.child,
  });

  final bool selected;
  final Color bg;
  final VoidCallback onTap;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        alignment: Alignment.center,
        color: selected ? context.scheme.onSurface : Colors.transparent,
        child: child,
      ),
    );
  }
}
