// 便捷访问主题 token 的扩展 让页面代码更短

import 'package:flutter/material.dart';

import 'esa_theme.dart';

extension EsaContext on BuildContext {
  EsaNeutrals get n => Theme.of(this).extension<EsaNeutrals>()!;
  ColorScheme get scheme => Theme.of(this).colorScheme;
  TextTheme get texts => Theme.of(this).textTheme;
  bool get isDark => Theme.of(this).brightness == Brightness.dark;

  /// 当前亮度下的强调色：深色用浅灰、浅色用深灰，保证文字与图标在两种模式下都可读。
  Color get accent => isDark ? EsaColors.accent : EsaColors.accent600;
}
