import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/api/api_client.dart';
import 'package:frontend/state/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _RoleLoginApi extends ApiClient {
  _RoleLoginApi(this.actualRole) : super(baseUrl: 'http://test.invalid');

  final String actualRole;

  @override
  Future<void> login(String username, String password) async {
    sessionId = 'session';
    userId = 'user';
    this.username = username;
    accountRole = actualRole;
  }

  @override
  Future<void> logout() async {
    sessionId = null;
    userId = null;
    username = null;
  }
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test(
    'selected login role must match the server-issued account role',
    () async {
      final state = AppState(api: _RoleLoginApi('teacher'));
      addTearDown(state.dispose);

      final error = await state.login(
        'teacher@example.com',
        'password123',
        expectedAccountRole: 'student',
      );

      expect(error, '该账号是教师账号，请选择教师身份登录');
      expect(state.username, isEmpty);
      expect(state.accountRole, 'student');
      expect(state.activeWorkspace.name, 'learning');
    },
  );
}
