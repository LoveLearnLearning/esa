// ESA 星知智链 —— 应用入口
// AppScope 置于 MaterialApp 之上 弹层等路由也能访问全局状态
// 主题深色为默认 设置里可实时切换

import 'package:flutter/material.dart';

import 'pages/chat_page.dart';
import 'pages/login_page.dart';
import 'state/app_state.dart';
import 'theme/esa_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState();
  await state.restoreSession();
  runApp(EsaApp(state: state));
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
    _app.dispose();
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
            title: 'ESA 星知智链',
            debugShowCheckedModeBanner: false,
            theme: esaTheme(brightness: Brightness.light),
            darkTheme: esaTheme(brightness: Brightness.dark),
            themeMode: _app.themeMode,
            home: _app.username.isEmpty ? const LoginPage() : const ChatPage(),
          );
        },
      ),
    );
  }
}
