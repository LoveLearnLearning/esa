const codeEditorThemeLabels = <String, String>{
  'system': '跟随应用',
  'vs-dark': 'VS Code 深色',
  'vs': 'VS Code 浅色',
  'esa-one-dark': 'One Dark',
  'esa-dracula': 'Dracula',
  'esa-monokai': 'Monokai',
  'esa-github-dark': 'GitHub 深色',
  'esa-github-light': 'GitHub 浅色',
  'esa-solarized-dark': 'Solarized 深色',
  'esa-solarized-light': 'Solarized 浅色',
  'hc-black': '高对比度深色',
  'hc-light': '高对比度浅色',
};

const codeEditorLightThemes = <String>{
  'vs',
  'esa-github-light',
  'esa-solarized-light',
  'hc-light',
};

bool isCodeEditorTheme(String? value) =>
    value != null && codeEditorThemeLabels.containsKey(value);

bool codeEditorThemeIsDark(String theme, {required bool appDark}) =>
    theme == 'system' ? appDark : !codeEditorLightThemes.contains(theme);

int codeEditorThemeBackground(String theme, {required bool appDark}) {
  final resolved = theme == 'system' ? (appDark ? 'vs-dark' : 'vs') : theme;
  return switch (resolved) {
    'vs' => 0xFFFFFFFF,
    'esa-one-dark' => 0xFF282C34,
    'esa-dracula' => 0xFF282A36,
    'esa-monokai' => 0xFF272822,
    'esa-github-dark' => 0xFF0D1117,
    'esa-github-light' => 0xFFFFFFFF,
    'esa-solarized-dark' => 0xFF002B36,
    'esa-solarized-light' => 0xFFFDF6E3,
    'hc-light' => 0xFFFFFFFF,
    _ => 0xFF1E1E1E,
  };
}

int codeEditorThemeForeground(String theme, {required bool appDark}) =>
    codeEditorThemeIsDark(theme, appDark: appDark) ? 0xFFD4D4D4 : 0xFF1F2328;
