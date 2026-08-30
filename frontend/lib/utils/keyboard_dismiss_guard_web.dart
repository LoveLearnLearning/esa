import 'dart:js_interop';

import 'package:flutter/foundation.dart';
import 'package:web/web.dart' as web;

/// 监听浏览器 `visualViewport` 的高度变化，检测软键盘直接收起（不点发送）。
///
/// 手机浏览器直接收起软键盘时，输入框焦点仍可能保留，导致 Flutter 的
/// `viewInsets` 未归零、页面底部残留键盘高度的黑屏。`visualViewport` 的
/// `resize` 事件比 Flutter 的 `didChangeMetrics` 更早、更可靠地反映真实
/// 视口高度，这里直接以视口高度回升作为键盘收起的信号。
class KeyboardDismissGuard {
  web.EventListener? _listener;
  VoidCallback? _onDismiss;
  double _lastHeight = 0;
  bool _hasBaseline = false;

  void install(VoidCallback onDismiss) {
    final viewport = web.window.visualViewport;
    if (viewport == null) return;
    _onDismiss = onDismiss;
    _lastHeight = viewport.height;
    _hasBaseline = true;
    _listener = ((web.Event _) {
      final height = viewport.height;
      final previous = _hasBaseline ? _lastHeight : height;
      _lastHeight = height;
      // 视口高度回升说明软键盘已收起，通知调用方释放焦点。
      if (height > previous + 1) {
        _onDismiss?.call();
      }
    }).toJS;
    viewport.addEventListener('resize', _listener!);
  }

  void dispose() {
    final viewport = web.window.visualViewport;
    if (viewport != null && _listener != null) {
      viewport.removeEventListener('resize', _listener!);
    }
    _listener = null;
    _onDismiss = null;
    _hasBaseline = false;
  }
}
