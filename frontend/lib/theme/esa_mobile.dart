import 'package:flutter/material.dart';

/// ESA 移动端的结构尺寸。页面不再各自声明近似但不同的高度与间距。
abstract final class EsaMobile {
  static const unit = 8.0;
  static const pagePadding = 16.0;
  static const touchTarget = 44.0;
  static const topBarHeight = 52.0;
  static const primaryTabsHeight = 42.0;
  static const secondaryTabsHeight = 40.0;
  static const bottomBarContentHeight = 56.0;
  static const composerMinHeight = 56.0;
  static const radius = 8.0;

  static EdgeInsets pageInsets({double top = 16, double bottom = 24}) =>
      EdgeInsets.fromLTRB(pagePadding, top, pagePadding, bottom);

  static bool compact(BuildContext context) =>
      MediaQuery.sizeOf(context).width < 600;

  static bool reduceMotion(BuildContext context) =>
      MediaQuery.disableAnimationsOf(context);

  static Duration motion(
    BuildContext context, {
    Duration duration = const Duration(milliseconds: 180),
  }) => reduceMotion(context) ? Duration.zero : duration;
}
