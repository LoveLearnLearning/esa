import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';

class ToolCallCard extends StatefulWidget {
  const ToolCallCard({
    super.key,
    required this.name,
    required this.output,
    this.durationMs,
    this.running = false,
  });

  final String name;
  final String output;
  final int? durationMs;
  final bool running;

  @override
  State<ToolCallCard> createState() => _ToolCallCardState();
}

class _ToolCallCardState extends State<ToolCallCard> {
  bool _expanded = false;

  @override
  void initState() {
    super.initState();
    _expanded = widget.running;
  }

  @override
  void didUpdateWidget(covariant ToolCallCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!oldWidget.running && widget.running) {
      _expanded = true;
    } else if (oldWidget.running && !widget.running) {
      _expanded = false;
    }
  }

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
          InkWell(
            onTap: widget.running
                ? null
                : () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              child: Row(
                children: [
                  const Icon(
                    LucideIcons.wrench,
                    size: 14,
                    color: EsaColors.accent,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'TOOL · ${widget.name}',
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 1,
                        color: context.n.n700,
                      ),
                    ),
                  ),
                  if (widget.running) ...[
                    Text(
                      '调用中',
                      style: TextStyle(fontSize: 11, color: context.n.n600),
                    ),
                    const SizedBox(width: 9),
                    const SizedBox.square(
                      dimension: 15,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.8,
                        color: EsaColors.accent,
                      ),
                    ),
                  ] else ...[
                    if (widget.durationMs != null) ...[
                      Text(
                        '${widget.durationMs} ms',
                        style: TextStyle(fontSize: 11, color: context.n.n600),
                      ),
                      const SizedBox(width: 8),
                    ],
                    Icon(
                      _expanded
                          ? LucideIcons.chevronUp
                          : LucideIcons.chevronDown,
                      size: 16,
                      color: context.n.n600,
                    ),
                  ],
                ],
              ),
            ),
          ),
          AnimatedSize(
            duration: EsaMotion.fade,
            alignment: Alignment.topCenter,
            child: _expanded
                ? Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 14,
                      vertical: 12,
                    ),
                    decoration: BoxDecoration(
                      border: Border(top: BorderSide(color: context.n.divider)),
                    ),
                    child: widget.running
                        ? Text(
                            '正在执行 ${widget.name}…',
                            style: TextStyle(
                              fontSize: 12,
                              color: context.n.n600,
                            ),
                          )
                        : SelectableText(
                            widget.output,
                            style: TextStyle(
                              fontSize: 12,
                              height: 1.7,
                              color: context.n.n700,
                            ),
                          ),
                  )
                : const SizedBox.shrink(),
          ),
        ],
      ),
    );
  }
}
