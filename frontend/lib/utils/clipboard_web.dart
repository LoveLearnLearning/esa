import 'dart:js_interop';

import 'package:web/web.dart' as web;

/// 在 HTTPS 下优先使用 Clipboard API；裸 IP HTTP 下退回 execCommand。
Future<bool> copyText(String text) async {
  if (web.window.isSecureContext) {
    try {
      await web.window.navigator.clipboard.writeText(text).toDart;
      return true;
    } catch (_) {
      // 用户拒绝剪贴板权限时，继续尝试兼容方案。
    }
  }

  // execCommand 已被废弃，但仍是裸 IP HTTP 部署可用的兼容路径。
  // iOS Safari 注意事项：
  // - readonly + select() 不会真正建立选区，必须显式 setSelectionRange
  // - 隐藏输入框字号 <16px 会触发聚焦自动放大页面
  final textarea = web.HTMLTextAreaElement()
    ..value = text
    ..setAttribute('readonly', '')
    ..style.position = 'fixed'
    ..style.left = '-9999px'
    ..style.top = '0'
    ..style.opacity = '0'
    ..style.fontSize = '16px';

  final body = web.document.body;
  if (body == null) return false;

  body.append(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, text.length);
  final copied = web.document.execCommand('copy');
  textarea.remove();
  return copied;
}
