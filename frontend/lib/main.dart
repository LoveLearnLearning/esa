import 'package:flutter/material.dart';
import 'log-in.dart';
import 'screens.dart';

void main() {
  runApp(const EsaApp());
}

class EsaApp extends StatelessWidget {
  const EsaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AI Chat Demo',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: buildLoginPage(),
    );
  }
}
