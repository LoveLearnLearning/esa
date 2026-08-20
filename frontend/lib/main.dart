// ESA 星知智链 —— 应用入口
// AppScope 置于 MaterialApp 之上 弹层等路由也能访问全局状态
// 主题深色为默认 设置里可实时切换

import 'dart:async';

import 'package:flutter/material.dart';

import 'pages/login_page.dart';
import 'pages/role_shell.dart';
import 'state/app_state.dart';
import 'theme/esa_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState(restoringSession: true);
  runApp(EsaApp(state: state));
  unawaited(state.restoreSession());
}

class EsaApp extends StatefulWidget {
  const EsaApp({super.key, this.state});

  final AppState? state;

  @override
  State<EsaApp> createState() => _EsaAppState();
}

class _EsaAppState extends State<EsaApp> {
  late final AppState _app;

  @override
  void initState() {
    super.initState();
    _app = widget.state ?? AppState();
  }

  @override
  void dispose() {
    // Callers that inject an AppState own its lifecycle (tests and embedded
    // shells); EsaApp only owns the state it creates itself.
    if (widget.state == null) _app.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: _app,
      child: ListenableBuilder(
        listenable: _app,
        builder: (context, _) {
          return MaterialApp(
            title: '星知智链',
            debugShowCheckedModeBanner: false,
            theme: esaTheme(brightness: Brightness.light),
            darkTheme: esaTheme(brightness: Brightness.dark),
            themeMode: _app.themeMode,
            home: _app.restoringSession
                ? const _StartupPage()
                : _app.username.isEmpty
                ? const LoginPage()
                : const RoleShell(),
          );
        },
      ),
    );
  }
}

class _StartupPage extends StatelessWidget {
  const _StartupPage();

  @override
  Widget build(BuildContext context) => const Scaffold(
    body: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '星知智链',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
          ),
          SizedBox(height: 20),
          SizedBox.square(
            dimension: 22,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ],
      ),
    ),
  );
}
