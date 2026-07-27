// ESA 星知智链 — Flutter theme tokens generated from the HTML design reference.
// Drop into lib/theme/esa_theme.dart. Values are final; do not improvise.

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class EsaColors {
  // dark (default)
  static const dBg = Color(0xFF1B1A19);
  static const dSurface = Color(0xFF232120);
  static const dText = Color(0xFFF0EEEC);
  static const dDivider = Color(0x29F0EEEC); // 16%
  static const dN100 = Color(0xFF252322);
  static const dN200 = Color(0xFF302D2C);
  static const dN300 = Color(0xFF454241);
  static const dN500 = Color(0xFF8B8787);
  static const dN600 = Color(0xFFA8A4A1);
  static const dN700 = Color(0xFFC7C3C0);

  // light
  static const lBg = Color(0xFFF3F2F2);
  static const lSurface = Color(0xFFEAE9E9);
  static const lText = Color(0xFF201E1D);
  static const lDivider = Color(0x66201E1D); // 40%
  static const lN100 = Color(0xFFF8F4F4);
  static const lN200 = Color(0xFFEAE7E7);
  static const lN300 = Color(0xFFD7D3D3);
  static const lN500 = Color(0xFF9B9797);
  static const lN600 = Color(0xFF7D7979);
  static const lN700 = Color(0xFF605D5D);

  // shared
  static const accent = Color(0xFFEC3013);
  static const accent100 = Color(0xFFFFF2EF);
  static const accent600 = Color(0xFFDD2B0F);
  static const accent700 = Color(0xFFAE1800);
  static const onAccent = Color(0xFFF3F2F2);
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
    n100: EsaColors.dN100, n200: EsaColors.dN200, n300: EsaColors.dN300,
    n500: EsaColors.dN500, n600: EsaColors.dN600, n700: EsaColors.dN700,
    divider: EsaColors.dDivider,
  );
  static const light = EsaNeutrals(
    n100: EsaColors.lN100, n200: EsaColors.lN200, n300: EsaColors.lN300,
    n500: EsaColors.lN500, n600: EsaColors.lN600, n700: EsaColors.lN700,
    divider: EsaColors.lDivider,
  );

  @override
  EsaNeutrals copyWith() => this;
  @override
  EsaNeutrals lerp(ThemeExtension<EsaNeutrals>? other, double t) =>
      t < 0.5 ? this : (other as EsaNeutrals? ?? this);
}

class EsaRadii {
  static const bubble = 18.0;      // user message
  static const composer = 18.0;    // input container
  static const sheet = 18.0;       // profile dialog, big avatar
  static const button = 11.0;      // buttons, small avatar, drawer new-chat
  static const buttonLg = 12.0;    // auth submit
  static const field = 10.0;       // inputs, list rows, segmented control
  static const iconButton = 9.0;   // 30px icon buttons
  static const toolCard = 12.0;
  static const card = 14.0;        // suggestion cards
  static const pill = 999.0;       // send button, attachment chip, switches
}

class EsaSpace {
  static const xs = 4.0, sm = 8.0, md = 12.0, lg = 16.0, xl = 24.0, xxl = 32.0;
  static const contentMaxWidth = 820.0;
  static const drawerWidth = 340.0;   // min(340, 88% of width)
  static const dialogWidth = 560.0;
  static const headerHeight = 60.0;
  static const messageGap = 26.0;
}

class EsaMotion {
  static const drawer = Duration(milliseconds: 200);
  static const fade = Duration(milliseconds: 160);
  static const messageIn = Duration(milliseconds: 200);
  static const replyDelay = Duration(milliseconds: 420);
  static const streamTick = Duration(milliseconds: 26); // + 3~4 chars per tick
  static const curve = Curves.easeOut;
}

TextTheme _esaText(Color text, Color muted) {
  final base = GoogleFonts.archivoTextTheme();
  // google_fonts 8.x 的单字体方法不再接受 fontFamilyFallback 这里用 copyWith 补上
  // 中文回退到系统字体
  const fallback = <String>['PingFang SC', 'Microsoft YaHei', 'Noto Sans SC'];
  TextStyle f(TextStyle s) => s.copyWith(fontFamilyFallback: fallback);
  return base.copyWith(
    displayLarge: f(GoogleFonts.archivo(fontSize: 68, height: 0.98, fontWeight: FontWeight.w800, letterSpacing: -1.2, color: text)),
    headlineMedium: f(GoogleFonts.archivo(fontSize: 36, height: 1.12, fontWeight: FontWeight.w800, color: text)),
    headlineSmall: f(GoogleFonts.archivo(fontSize: 24, height: 1.12, fontWeight: FontWeight.w800, color: text)),
    titleMedium: f(GoogleFonts.archivo(fontSize: 14, fontWeight: FontWeight.w800, color: text)),
    bodyLarge: f(GoogleFonts.archivo(fontSize: 15, height: 1.75, color: text)),   // assistant reply
    bodyMedium: f(GoogleFonts.archivo(fontSize: 15, height: 1.65, color: text)),  // user bubble
    bodySmall: f(GoogleFonts.archivo(fontSize: 12.5, height: 1.5, color: muted)),
    labelSmall: f(GoogleFonts.archivo(fontSize: 11, fontWeight: FontWeight.w600, letterSpacing: 1.4, color: muted)), // UPPERCASE kickers
  );
}

ThemeData esaTheme({required Brightness brightness}) {
  final dark = brightness == Brightness.dark;
  final bg = dark ? EsaColors.dBg : EsaColors.lBg;
  final surface = dark ? EsaColors.dSurface : EsaColors.lSurface;
  final text = dark ? EsaColors.dText : EsaColors.lText;
  final n = dark ? EsaNeutrals.dark : EsaNeutrals.light;

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    scaffoldBackgroundColor: bg,
    dividerColor: n.divider,
    extensions: [n],
    colorScheme: ColorScheme.fromSeed(
      seedColor: EsaColors.accent,
      brightness: brightness,
    ).copyWith(
      primary: EsaColors.accent,
      onPrimary: EsaColors.onAccent,
      surface: surface,
      onSurface: text,
      outline: n.divider,
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
        borderSide: const BorderSide(color: EsaColors.accent, width: 2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: EsaColors.accent,
        foregroundColor: EsaColors.onAccent,
        textStyle: GoogleFonts.archivo(fontSize: 13, fontWeight: FontWeight.w800),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(EsaRadii.buttonLg)),
        // NOTE: wide buttons align their label LEFT — use Row(mainAxisAlignment: start).
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: text,
        side: BorderSide(color: n.divider),
        textStyle: GoogleFonts.archivo(fontSize: 13, fontWeight: FontWeight.w800),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(EsaRadii.button)),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        foregroundColor: n.n600,
        hoverColor: n.n200,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(EsaRadii.iconButton)),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(EsaRadii.sheet),
        side: BorderSide(color: n.divider),
      ),
    ),
    drawerTheme: DrawerThemeData(
      backgroundColor: bg,
      surfaceTintColor: Colors.transparent,
      scrimColor: const Color(0x73201E1D), // rgba(32,30,29,.45)
      shape: const RoundedRectangleBorder(),
      width: EsaSpace.drawerWidth,
    ),
    switchTheme: SwitchThemeData(
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? EsaColors.accent : Colors.transparent),
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? EsaColors.onAccent : text),
      trackOutlineColor: WidgetStateProperty.all(n.divider),
    ),
  );
}
