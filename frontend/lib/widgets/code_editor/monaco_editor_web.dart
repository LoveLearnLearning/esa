import 'dart:js_interop';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

import '../../models/code_editor_settings.dart';

String _cssColor(int argb) =>
    '#${(argb & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}';

@JS('esaMonaco.create')
external void _createEditor(
  web.HTMLElement host,
  String id,
  String value,
  String language,
  bool dark,
  int indentSize,
  String editorTheme,
  JSFunction onChanged,
);

@JS('esaMonaco.setValue')
external void _setEditorValue(String id, String value);

@JS('esaMonaco.focus')
external void _focusEditor(String id);

@JS('esaMonaco.setLanguage')
external void _setEditorLanguage(String id, String language);

@JS('esaMonaco.setTheme')
external void _setEditorTheme(String id, bool dark);

@JS('esaMonaco.setOptions')
external void _setEditorOptions(String id, int indentSize, String editorTheme);

@JS('esaMonaco.dispose')
external void _disposeEditor(String id);

class MonacoEditor extends StatefulWidget {
  const MonacoEditor({
    super.key,
    required this.value,
    required this.language,
    required this.dark,
    required this.indentSize,
    required this.editorTheme,
    required this.onChanged,
  });

  final String value;
  final String language;
  final bool dark;
  final int indentSize;
  final String editorTheme;
  final ValueChanged<String> onChanged;

  @override
  State<MonacoEditor> createState() => _MonacoEditorState();
}

class _MonacoEditorState extends State<MonacoEditor> {
  static int _nextId = 0;
  late final String _editorId;
  late final String _viewType;
  late final JSFunction _onChanged;

  @override
  void initState() {
    super.initState();
    _editorId = 'esa-code-editor-${_nextId++}';
    _viewType = 'esa-monaco-view-$_editorId';
    _onChanged = ((JSString value) {
      widget.onChanged(value.toDart);
    }).toJS;
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      final element = web.HTMLDivElement()
        ..id = _editorId
        ..className = 'esa-monaco-host'
        ..tabIndex = 0
        ..style.width = '100%'
        ..style.height = '100%'
        ..style.pointerEvents = 'auto'
        ..style.backgroundColor = _cssColor(
          codeEditorThemeBackground(widget.editorTheme, appDark: widget.dark),
        );
      _createEditor(
        element,
        _editorId,
        widget.value,
        widget.language,
        widget.dark,
        widget.indentSize,
        widget.editorTheme,
        _onChanged,
      );
      return element;
    });
  }

  @override
  void didUpdateWidget(covariant MonacoEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.value != widget.value) {
      _setEditorValue(_editorId, widget.value);
    }
    if (oldWidget.language != widget.language) {
      _setEditorLanguage(_editorId, widget.language);
    }
    if (oldWidget.dark != widget.dark && widget.editorTheme == 'system') {
      _setEditorTheme(_editorId, widget.dark);
    }
    if (oldWidget.indentSize != widget.indentSize ||
        oldWidget.editorTheme != widget.editorTheme) {
      _setEditorOptions(_editorId, widget.indentSize, widget.editorTheme);
    }
  }

  @override
  void dispose() {
    _disposeEditor(_editorId);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Listener(
    behavior: HitTestBehavior.opaque,
    onPointerDown: (_) => _focusEditor(_editorId),
    child: HtmlElementView(viewType: _viewType),
  );
}
