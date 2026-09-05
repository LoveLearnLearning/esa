// ESA 星知智链 — Flutter theme tokens generated from the HTML design reference.
// Drop into lib/theme/esa_theme.dart. Values are final; do not improvise.

import 'package:flutter/material.dart';

class EsaColors {
  // dark (default)
  // Dark surfaces are a deliberately neutral black/graphite ramp. Material 3
  // container colours are overridden below so the blue seed cannot tint large
  // areas of the interface.
  static const dBg = Color(0xFF000000);
  static const dSurface = Color(0xFF070708);
  static const dText = Color(0xFFF2F5F9);
  static const dDivider = Color(0xFF29292D);
  static const dN100 = Color(0xFF111113);
  static const dN200 = Color(0xFF19191C);
  static const dN300 = Color(0xFF242428);
  static const dN500 = Color(0xFF6C6C74);
  static const dN600 = Color(0xFFA3A3AA);
  static const dN700 = Color(0xFFD8D8DD);

  // light
  static const lBg = Color(0xFFF3F2F2);
  static const lSurface = Color(0xFFEAE9E9);
  static const lText = Color.fromARGB(255, 0, 0, 0);
  static const lDivider = Color(0x66201E1D); // 40%
  static const lN100 = Color(0xFFF8F4F4);
  static const lN200 = Color(0xFFEAE7E7);
  static const lN300 = Color(0xFFD7D3D3);
  static const lN500 = Color.fromARGB(255, 164, 158, 158);
  static const lN600 = Color.fromARGB(255, 48, 46, 46);
  static const lN700 = Color.fromARGB(255, 0, 0, 0);

  // shared —— 中性主色阶。所有平台复用同一套黑灰配色，避免桌面端
  // 组件绕过 surface token 后重新出现蓝色选中块或蓝黑卡片。
  static const accent50 = Color(0xFFF4F4F5);
  static const accent100 = Color(0xFFE7E7EA);
  static const accent300 = Color(0xFF8A8A92);
  static const accent = Color(0xFFA3A3AA);
  static const accent600 = Color(0xFF29292D);
  static const accent700 = Color(0xFF202024);
  static const accent900 = Color(0xFF111113);
  static const onAccent = Color(0xFF080808);

  // 语义色必须同时配合图标或文字，不能仅靠颜色表达状态。
  static const success = Color(0xFF4FAE83);
  static const warning = Color(0xFFD6A457);
  static const error = Color(0xFFE07178);
  static const info = Color(0xFFA3A3AA);
}

/// Neutral ramp resolved for the current brightness.
class EsaNeutrals extends ThemeExtension<EsaNeutrals> {
  const EsaNeutrals({
    required this.n100,
    required this.n200,
    required this.n300,
    required this.n500,
    required this.n600,
    required this.n700,
    required this.divider,
  });

  final Color n100, n200, n300, n500, n600, n700, divider;

  static const dark = EsaNeutrals(
    n100: EsaColors.dN100,
    n200: EsaColors.dN200,
    n300: EsaColors.dN300,
    n500: EsaColors.dN500,
    n600: EsaColors.dN600,
    n700: EsaColors.dN700,
    divider: EsaColors.dDivider,
  );
  static const light = EsaNeutrals(
    n100: EsaColors.lN100,
    n200: EsaColors.lN200,
    n300: EsaColors.lN300,
    n500: EsaColors.lN500,
    n600: EsaColors.lN600,
    n700: EsaColors.lN700,
    divider: EsaColors.lDivider,
  );

  @override
  EsaNeutrals copyWith() => this;
  @override
  EsaNeutrals lerp(ThemeExtension<EsaNeutrals>? other, double t) =>
      t < 0.5 ? this : (other as EsaNeutrals? ?? this);
}

class EsaRadii {
  static const bubble = 18.0; // user message
  static const composer = 8.0; // input container
  static const sheet = 18.0; // profile dialog, big avatar
  static const button = 10.0; // buttons, small avatar, drawer new-chat
  static const buttonLg = 10.0; // auth submit
  static const field = 8.0; // inputs, list rows, segmented control
  static const iconButton = 9.0; // 30px icon buttons
  static const toolCard = 8.0;
  static const card = 8.0; // suggestion cards
  static const pill = 999.0; // send button, attachment chip, switches
}

class EsaSpace {
  static const xs = 4.0, sm = 8.0, md = 12.0, lg = 16.0, xl = 24.0, xxl = 32.0;
  static const contentMaxWidth = 820.0;
  static const drawerWidth = 340.0; // min(340, 88% of width)
  static const dialogWidth = 560.0;
  static const headerHeight = 60.0;
  static const messageGap = 26.0;
}

class EsaMotion {
  static const drawer = Duration(milliseconds: 200);
  static const fade = Duration(milliseconds: 160);
  static const messageIn = Duration(milliseconds: 200);
  static const replyDelay = Duration(milliseconds: 420);
  static const streamTick = Duration(milliseconds: 18); // 流式回复逐字显示
  static const curve = Curves.easeOut;
}

TextTheme _esaText(Color text, Color muted) {
  const fallback = <String>[
    'PingFang SC',
    'Microsoft YaHei',
    'Noto Sans SC',
    'Arial',
    'sans-serif',
  ];
  TextStyle style({
    required double size,
    required Color color,
    double? height,
    FontWeight? weight,
    double? spacing,
  }) => TextStyle(
    fontSize: size,
    height: height,
    fontWeight: weight,
    letterSpacing: 0,
    color: color,
    fontFamily: 'NotoSansSC',
    fontFamilyFallback: fallback,
  );
  return TextTheme(
    displayLarge: style(
      size: 48,
      height: 1.05,
      weight: FontWeight.w800,
      color: text,
    ),
    headlineMedium: style(
      size: 28,
      height: 1.12,
      weight: FontWeight.w800,
      color: text,
    ),
    headlineSmall: style(
      size: 22,
      height: 1.12,
      weight: FontWeight.w800,
      color: text,
    ),
    titleMedium: style(size: 14, weight: FontWeight.w800, color: text),
    bodyLarge: style(size: 16, height: 1.5, color: text),
    bodyMedium: style(size: 16, height: 1.5, color: text),
    bodySmall: style(size: 13, height: 1.45, color: muted),
    labelSmall: style(
      size: 12,
      weight: FontWeight.w600,
      spacing: 0,
      color: muted,
    ),
  );
}

ThemeData esaTheme({required Brightness brightness}) {
  final dark = brightness == Brightness.dark;
  final bg = dark ? EsaColors.dBg : EsaColors.lBg;
  final surface = dark ? EsaColors.dSurface : EsaColors.lSurface;
  final text = dark ? EsaColors.dText : EsaColors.lText;
  final n = dark ? EsaNeutrals.dark : EsaNeutrals.light;
  final primary = dark ? EsaColors.dText : EsaColors.accent700;
  final onPrimary = dark ? const Color(0xFF080809) : EsaColors.dText;
  final containerLowest = dark ? EsaColors.dBg : const Color(0xFFFFFFFF);
  final containerLow = dark ? EsaColors.dSurface : const Color(0xFFF1F0F0);
  final container = dark ? EsaColors.dN100 : const Color(0xFFEAE9E9);
  final containerHigh = dark ? EsaColors.dN200 : const Color(0xFFE1DFDF);
  final containerHighest = dark ? EsaColors.dN300 : const Color(0xFFD7D3D3);

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    scaffoldBackgroundColor: bg,
    fontFamily: 'NotoSansSC',
    dividerColor: n.divider,
    extensions: [n],
    colorScheme:
        ColorScheme.fromSeed(
          seedColor: EsaColors.accent,
          brightness: brightness,
        ).copyWith(
          primary: primary,
          onPrimary: onPrimary,
          primaryContainer: containerHigh,
          onPrimaryContainer: text,
          secondary: n.n700,
          onSecondary: onPrimary,
          secondaryContainer: container,
          onSecondaryContainer: text,
          tertiary: n.n600,
          onTertiary: onPrimary,
          tertiaryContainer: containerHigh,
          onTertiaryContainer: text,
          surface: surface,
          onSurface: text,
          surfaceDim: dark ? EsaColors.dBg : EsaColors.lN300,
          surfaceBright: dark ? EsaColors.dN300 : const Color(0xFFFFFFFF),
          surfaceContainerLowest: containerLowest,
          surfaceContainerLow: containerLow,
          surfaceContainer: container,
          surfaceContainerHigh: containerHigh,
          surfaceContainerHighest: containerHighest,
          surfaceTint: Colors.transparent,
          outline: n.divider,
          outlineVariant: n.divider,
          inverseSurface: dark ? EsaColors.dText : EsaColors.dN100,
          onInverseSurface: dark ? const Color(0xFF141416) : EsaColors.dText,
          inversePrimary: dark ? EsaColors.dN300 : EsaColors.accent300,
          shadow: Colors.black,
          scrim: Colors.black,
        ),
    textTheme: _esaText(text, n.n600),
    dividerTheme: DividerThemeData(color: n.divider, thickness: 1, space: 1),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: n.n100,
      hintStyle: TextStyle(color: n.n600, fontSize: 15),
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(EsaRadii.field),
        borderSide: BorderSide(color: n.divider),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(EsaRadii.field),
        borderSide: BorderSide(color: n.divider),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(EsaRadii.field),
        borderSide: BorderSide(color: primary, width: 2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: primary,
        foregroundColor: onPrimary,
        textStyle: const TextStyle(
          fontFamily: 'NotoSansSC',
          fontSize: 13,
          fontWeight: FontWeight.w800,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(EsaRadii.buttonLg),
        ),
        // NOTE: wide buttons align their label LEFT — use Row(mainAxisAlignment: start).
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: text,
        side: BorderSide(color: n.divider),
        textStyle: const TextStyle(
          fontFamily: 'NotoSansSC',
          fontSize: 13,
          fontWeight: FontWeight.w800,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(EsaRadii.button),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        foregroundColor: n.n600,
        hoverColor: n.n200,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(EsaRadii.iconButton),
        ),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: surface,
      surfaceTintColor: Colors.transparent,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(EsaRadii.sheet),
        side: BorderSide(color: n.divider),
      ),
    ),
    cardTheme: CardThemeData(
      color: surface,
      surfaceTintColor: Colors.transparent,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(EsaRadii.card),
        side: BorderSide(color: n.divider),
      ),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(EsaRadii.card),
        side: BorderSide(color: n.divider),
      ),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(EsaRadii.sheet),
        ),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(EsaRadii.card),
      ),
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(
        color: n.n200,
        borderRadius: BorderRadius.circular(EsaRadii.field),
        border: Border.all(color: n.divider),
      ),
      textStyle: TextStyle(color: text, fontSize: 12),
    ),
    drawerTheme: DrawerThemeData(
      backgroundColor: bg,
      surfaceTintColor: Colors.transparent,
      scrimColor: const Color(0x73201E1D), // rgba(32,30,29,.45)
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.horizontal(
          right: Radius.circular(EsaRadii.sheet),
        ),
      ),
      width: EsaSpace.drawerWidth,
    ),
    switchTheme: SwitchThemeData(
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? primary : Colors.transparent,
      ),
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? onPrimary : text,
      ),
      trackOutlineColor: WidgetStateProperty.all(n.divider),
    ),
    checkboxTheme: CheckboxThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
      side: BorderSide(color: n.n600, width: 1.5),
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? primary
            : Colors.transparent,
      ),
      checkColor: WidgetStateProperty.all(onPrimary),
    ),
  );
}
