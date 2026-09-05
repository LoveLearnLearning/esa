import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/theme/esa_theme.dart';

void main() {
  test('dark surfaces and primary controls stay neutral and readable', () {
    final theme = esaTheme(brightness: Brightness.dark);
    final scheme = theme.colorScheme;
    for (final color in [
      theme.scaffoldBackgroundColor,
      scheme.surface,
      scheme.surfaceContainerLow,
      scheme.surfaceContainer,
      scheme.surfaceContainerHigh,
      scheme.surfaceContainerHighest,
      scheme.primaryContainer,
      scheme.secondaryContainer,
      EsaColors.accent,
    ]) {
      expect((color.r - color.b).abs(), lessThan(.035));
      expect((color.g - color.b).abs(), lessThan(.035));
    }
    double contrast(Color a, Color b) {
      final first = a.computeLuminance();
      final second = b.computeLuminance();
      return first > second
          ? (first + .05) / (second + .05)
          : (second + .05) / (first + .05);
    }

    expect(contrast(scheme.primary, scheme.onPrimary), greaterThan(4.5));
    expect(contrast(EsaColors.accent, EsaColors.onAccent), greaterThan(4.5));
    expect(contrast(EsaColors.accent, scheme.surface), greaterThan(4.5));
  });
}
