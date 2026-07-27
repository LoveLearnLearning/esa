// 便捷访问主题 token 的扩展 让页面代码更短

import 'package:flutter/material.dart';

import 'esa_theme.dart';

extension EsaContext on BuildContext {
  EsaNeutrals get n => Theme.of(this).extension<EsaNeutrals>()!;
  ColorScheme get scheme => Theme.of(this).colorScheme;
  TextTheme get texts => Theme.of(this).textTheme;
  bool get isDark => Theme.of(this).brightness == Brightness.dark;
}
