import 'package:flutter/material.dart';

import '../state/app_state.dart';
import 'home_shell.dart';
import 'teacher_shell.dart';

/// Selects one role-specific application shell from the server-issued role.
class RoleShell extends StatelessWidget {
  const RoleShell({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return app.isTeacher
        ? const TeacherShell(key: ValueKey('teacher-shell'))
        : const HomeShell(key: ValueKey('student-shell'));
  }
}
