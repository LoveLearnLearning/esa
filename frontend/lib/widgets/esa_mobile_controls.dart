import 'package:flutter/material.dart';

import '../theme/esa_context.dart';
import '../theme/esa_mobile.dart';

class EsaMobileIconButton extends StatelessWidget {
  const EsaMobileIconButton({
    super.key,
    required this.icon,
    required this.tooltip,
    required this.onPressed,
    this.selected = false,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  final bool selected;

  @override
  Widget build(BuildContext context) => Semantics(
    button: true,
    label: tooltip,
    enabled: onPressed != null,
    selected: selected,
    child: Tooltip(
      message: tooltip,
      child: IconButton(
        onPressed: onPressed,
        constraints: const BoxConstraints.tightFor(
          width: EsaMobile.touchTarget,
          height: EsaMobile.touchTarget,
        ),
        padding: EdgeInsets.zero,
        style: IconButton.styleFrom(
          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
          foregroundColor: selected ? context.scheme.primary : context.n.n600,
          backgroundColor: selected ? context.n.n200 : Colors.transparent,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(EsaMobile.radius),
          ),
        ),
        icon: Icon(icon, size: 20),
      ),
    ),
  );
}

class EsaMobileTabEntry<T> {
  const EsaMobileTabEntry(this.value, this.label, {this.key});

  final T value;
  final String label;
  final Key? key;
}

class EsaMobileTabStrip<T> extends StatelessWidget {
  const EsaMobileTabStrip({
    super.key,
    required this.value,
    required this.entries,
    required this.onChanged,
    this.height = EsaMobile.primaryTabsHeight,
    this.minItemWidth = 70,
    this.padding = const EdgeInsets.symmetric(horizontal: 8),
    this.itemPadding = const EdgeInsets.symmetric(horizontal: 12),
  });

  final T value;
  final List<EsaMobileTabEntry<T>> entries;
  final ValueChanged<T> onChanged;
  final double height;
  final double minItemWidth;
  final EdgeInsets padding;
  final EdgeInsets itemPadding;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final availableWidth = constraints.maxWidth - padding.horizontal;
      final naturalWidth = minItemWidth * entries.length;
      final itemWidth = availableWidth.isFinite && availableWidth > naturalWidth
          ? availableWidth / entries.length
          : minItemWidth;
      final stripWidth = itemWidth * entries.length;
      return SizedBox(
        width: double.infinity,
        height: height,
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: padding,
          child: SizedBox(
            width: stripWidth,
            child: Row(
              children: [
                for (final entry in entries)
                  SizedBox(
                    width: itemWidth,
                    height: height,
                    child: Semantics(
                      button: true,
                      selected: value == entry.value,
                      label: entry.label,
                      child: Material(
                        color: Colors.transparent,
                        child: InkWell(
                          key: entry.key,
                          onTap: () => onChanged(entry.value),
                          borderRadius: BorderRadius.circular(EsaMobile.radius),
                          child: Container(
                            margin: const EdgeInsets.symmetric(
                              horizontal: 2,
                              vertical: 4,
                            ),
                            alignment: Alignment.center,
                            padding: itemPadding,
                            decoration: BoxDecoration(
                              color: value == entry.value
                                  ? context.n.n200
                                  : Colors.transparent,
                              borderRadius: BorderRadius.circular(
                                EsaMobile.radius,
                              ),
                            ),
                            child: Text(
                              entry.label,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: context.texts.bodySmall?.copyWith(
                                fontSize: 13,
                                color: value == entry.value
                                    ? context.scheme.primary
                                    : context.n.n600,
                                fontWeight: value == entry.value
                                    ? FontWeight.w700
                                    : FontWeight.w500,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      );
    },
  );
}
