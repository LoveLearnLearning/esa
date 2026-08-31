import 'package:flutter/foundation.dart';

/// 非 Web 平台无软键盘收起问题，提供空实现占位。
class KeyboardDismissGuard {
  void install(VoidCallback onDismiss) {}

  void dispose() {}
}
