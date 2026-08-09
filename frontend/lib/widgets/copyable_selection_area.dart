import 'dart:async';

import 'package:flutter/material.dart';

import '../utils/clipboard.dart';

/// 可跨 Markdown 节点选择，并兼容裸 IP HTTP 部署的复制区域。
///
/// Flutter Web 默认复制依赖安全上下文中的 Clipboard API。在 HTTP 页面中，
/// 这里通过可覆盖的 CopySelectionTextIntent 和自定义右键菜单改用应用自己的
/// 兼容复制实现。
class CopyableSelectionArea extends StatefulWidget {
  const CopyableSelectionArea({super.key, required this.child});

  final Widget child;

  @override
  State<CopyableSelectionArea> createState() => _CopyableSelectionAreaState();
}

class _CopyableSelectionAreaState extends State<CopyableSelectionArea> {
  String _selectedText = '';

  Future<void> _copySelection() async {
    final text = _selectedText;
    if (text.isEmpty) return;

    final copied = await copyText(text);
    if (!mounted || copied) return;
    ScaffoldMessenger.maybeOf(
      context,
    )?.showSnackBar(const SnackBar(content: Text('复制失败，请使用消息下方的复制按钮。')));
  }

  Widget _buildContextMenu(BuildContext context, SelectableRegionState region) {
    final items = region.contextMenuButtonItems.map((item) {
      if (item.type != ContextMenuButtonType.copy) return item;
      return item.copyWith(
        onPressed: () {
          region.hideToolbar();
          unawaited(_copySelection());
        },
      );
    }).toList();

    return AdaptiveTextSelectionToolbar.buttonItems(
      anchors: region.contextMenuAnchors,
      buttonItems: items,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Actions(
      actions: <Type, Action<Intent>>{
        CopySelectionTextIntent: CallbackAction<CopySelectionTextIntent>(
          onInvoke: (_) {
            unawaited(_copySelection());
            return null;
          },
        ),
      },
      child: SelectionArea(
        onSelectionChanged: (selection) {
          _selectedText = selection?.plainText ?? '';
        },
        contextMenuBuilder: _buildContextMenu,
        child: widget.child,
      ),
    );
  }
}
