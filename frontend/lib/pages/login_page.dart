import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../state/app_state.dart';

enum AuthMode { login, register }

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage>
    with SingleTickerProviderStateMixin {
  static const _background = Color(0xFF070A11);
  static const _text = Color(0xFFF4F7FB);
  static const _muted = Color(0xFF8D9AAF);
  static const _soft = Color(0xFF66748A);
  static const _accent = Color(0xFF9BB0FF);
  static const _cyan = Color(0xFF8DDBF8);
  static const _line = Color(0x17FFFFFF);

  final _email = TextEditingController();
  final _verificationCode = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _password2 = TextEditingController();
  final _emailFocus = FocusNode();
  final _verificationCodeFocus = FocusNode();
  final _usernameFocus = FocusNode();
  final _passwordFocus = FocusNode();
  final _password2Focus = FocusNode();

  late final AnimationController _graphAnimation;
  late final ValueNotifier<Offset?> _graphPointer;
  late final _KnowledgeGraphPainter _graphPainter;
  AuthMode _mode = AuthMode.login;
  String _accountRole = 'student';
  bool _showPw = false;
  bool _rememberLogin = true;
  bool _loading = false;
  bool _sendingCode = false;
  int _codeCooldown = 0;
  Timer? _codeTimer;
  String? _error;

  bool get _isRegister => _mode == AuthMode.register;

  @override
  void initState() {
    super.initState();
    for (final focusNode in [
      _emailFocus,
      _verificationCodeFocus,
      _usernameFocus,
      _passwordFocus,
      _password2Focus,
    ]) {
      focusNode.addListener(_handleInputFocusChange);
    }
    _graphPointer = ValueNotifier<Offset?>(null);
    _graphAnimation = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 24),
    );
    _graphPainter = _KnowledgeGraphPainter(
      animation: _graphAnimation,
      pointer: _graphPointer,
    );
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final media = MediaQuery.of(context);
    final animate = media.size.width >= 600 && !media.disableAnimations;
    if (animate && !_graphAnimation.isAnimating) {
      _graphAnimation.repeat();
    } else if (!animate && _graphAnimation.isAnimating) {
      _graphAnimation.stop();
    }
  }

  void _handleInputFocusChange() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _codeTimer?.cancel();
    _graphAnimation.dispose();
    _graphPointer.dispose();
    for (final focusNode in [
      _emailFocus,
      _verificationCodeFocus,
      _usernameFocus,
      _passwordFocus,
      _password2Focus,
    ]) {
      focusNode.removeListener(_handleInputFocusChange);
    }
    _email.dispose();
    _verificationCode.dispose();
    _username.dispose();
    _password.dispose();
    _password2.dispose();
    _emailFocus.dispose();
    _verificationCodeFocus.dispose();
    _usernameFocus.dispose();
    _passwordFocus.dispose();
    _password2Focus.dispose();
    super.dispose();
  }

  bool _looksLikeEmail(String value) {
    final parts = value.trim().split('@');
    return parts.length == 2 &&
        parts.first.isNotEmpty &&
        parts.last.contains('.') &&
        !parts.last.startsWith('.') &&
        !parts.last.endsWith('.');
  }

  Future<void> _sendVerificationCode() async {
    if (_sendingCode || _codeCooldown > 0) return;
    final email = _email.text.trim();
    if (!_looksLikeEmail(email)) {
      setState(() => _error = '请输入正确的邮箱地址');
      _emailFocus.requestFocus();
      return;
    }
    setState(() {
      _error = null;
      _sendingCode = true;
    });
    final result = await AppScope.of(context).sendRegistrationCode(email);
    if (!mounted) return;
    final seconds = int.tryParse(result ?? '');
    setState(() {
      _sendingCode = false;
      _error = seconds == null ? result : null;
      if (seconds != null) _codeCooldown = seconds;
    });
    if (seconds == null) return;
    _verificationCodeFocus.requestFocus();
    _codeTimer?.cancel();
    _codeTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(() {
        if (_codeCooldown <= 1) {
          _codeCooldown = 0;
          timer.cancel();
        } else {
          _codeCooldown--;
        }
      });
    });
  }

  Future<void> _submit() async {
    if (_loading) return;

    final username = _username.text.trim();
    final email = _email.text.trim();
    final verificationCode = _verificationCode.text.trim();
    final password = _password.text;
    if (username.isEmpty || password.isEmpty) {
      setState(() => _error = _isRegister ? '请输入用户名和密码' : '请输入邮箱或用户名和密码');
      return;
    }
    if (_isRegister && !_looksLikeEmail(email)) {
      setState(() => _error = '请输入正确的邮箱地址');
      return;
    }
    if (_isRegister && !RegExp(r'^\d{6}$').hasMatch(verificationCode)) {
      setState(() => _error = '请输入邮件中的 6 位验证码');
      return;
    }
    if (username.length > 32) {
      setState(() => _error = '用户名不能超过 32 位');
      return;
    }
    if (password.length < 8) {
      setState(() => _error = '密码至少 8 位');
      return;
    }
    if (_isRegister && password != _password2.text) {
      setState(() => _error = '两次输入的密码不一致');
      return;
    }

    setState(() {
      _error = null;
      _loading = true;
    });
    final app = AppScope.of(context);
    final err = _isRegister
        ? await app.register(
            email,
            verificationCode,
            username,
            password,
            _accountRole,
          )
        : await app.login(username, password, rememberLogin: _rememberLogin);
    if (!mounted) return;
    if (err == null) TextInput.finishAutofillContext(shouldSave: true);
    setState(() {
      _loading = false;
      _error = err;
    });
  }

  void _enterAsGuest() {
    if (_loading) return;
    AppScope.of(context).enterAsGuest();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _background,
      body: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < 920;
            _graphPainter.compact = compact;
            return MouseRegion(
              opaque: false,
              onHover: constraints.maxWidth < 600
                  ? null
                  : (event) => _graphPointer.value = event.localPosition,
              onExit: (_) => _graphPointer.value = null,
              child: Stack(
                children: [
                  const Positioned.fill(child: _BackgroundWash()),
                  Positioned.fill(
                    child: RepaintBoundary(
                      child: CustomPaint(
                        painter: _graphPainter,
                        isComplex: true,
                        willChange: true,
                      ),
                    ),
                  ),
                  const Positioned(top: 26, left: 34, child: _Brand()),
                  if (compact)
                    _compactLayout(constraints)
                  else
                    _desktopLayout(constraints),
                  if (_loading) const Positioned.fill(child: _LoadingStage()),
                ],
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _desktopLayout(BoxConstraints constraints) {
    return Row(
      children: [
        Expanded(
          flex: 15,
          child: Stack(
            children: [
              const Positioned(left: 72, top: 152, child: _Metrics()),
              Positioned(
                left: 72,
                right: 50,
                bottom: math.max(72, constraints.maxHeight * 0.09),
                child: const _HeroCopy(),
              ),
              const Positioned(
                right: 0,
                top: 100,
                bottom: 100,
                child: VerticalDivider(width: 1, color: _line),
              ),
            ],
          ),
        ),
        Expanded(
          flex: 9,
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(42, 88, 54, 42),
            child: Center(child: _authPanel()),
          ),
        ),
      ],
    );
  }

  Widget _compactLayout(BoxConstraints constraints) {
    return SingleChildScrollView(
      padding: EdgeInsets.only(
        top: constraints.maxWidth < 560 ? 180 : 205,
        left: 18,
        right: 18,
        bottom: 88,
      ),
      child: Column(
        children: [
          const Align(alignment: Alignment.centerLeft, child: _CompactHero()),
          const SizedBox(height: 28),
          _authPanel(),
        ],
      ),
    );
  }

  Widget _authPanel() {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 450),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: const Color(0xE612111B),
          borderRadius: BorderRadius.circular(24),
          border: Border.all(color: _line),
          boxShadow: const [
            BoxShadow(
              color: Color(0x70000000),
              blurRadius: 70,
              offset: Offset(0, 28),
            ),
          ],
        ),
        child: Padding(
          padding: const EdgeInsets.all(30),
          child: AutofillGroup(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  _isRegister ? '创建知识空间' : '欢迎回来',
                  style: const TextStyle(
                    color: _text,
                    fontSize: 29,
                    height: 1.15,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  _isRegister ? '注册 ESA，开始构建你的学习网络。' : '继续构建你的知识世界。',
                  style: const TextStyle(
                    color: _muted,
                    fontSize: 14,
                    height: 1.6,
                  ),
                ),
                const SizedBox(height: 26),
                _modeSwitch(),
                if (!_isRegister) ...[
                  const SizedBox(height: 12),
                  _guestLoginButton(),
                ],
                const SizedBox(height: 24),
                if (_isRegister) ...[
                  _fieldLabel('账号类型'),
                  const SizedBox(height: 8),
                  _roleSwitch(),
                  const SizedBox(height: 17),
                  _field(
                    label: '邮箱',
                    hint: 'name@example.com',
                    controller: _email,
                    focusNode: _emailFocus,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    textInputAction: TextInputAction.next,
                    onSubmitted: (_) => _verificationCodeFocus.requestFocus(),
                  ),
                  const SizedBox(height: 17),
                  _verificationCodeField(),
                  const SizedBox(height: 17),
                ],
                _field(
                  label: _isRegister ? '用户名' : '邮箱或用户名',
                  hint: _isRegister ? '设置一个用户名' : 'name@example.com',
                  controller: _username,
                  focusNode: _usernameFocus,
                  autofillHints: const [AutofillHints.username],
                  textInputAction: TextInputAction.next,
                  onSubmitted: (_) => _passwordFocus.requestFocus(),
                ),
                const SizedBox(height: 17),
                _passwordField(),
                if (_isRegister) ...[
                  const SizedBox(height: 17),
                  _field(
                    label: '确认密码',
                    hint: '再次输入密码',
                    controller: _password2,
                    focusNode: _password2Focus,
                    obscure: !_showPw,
                    autofillHints: const [AutofillHints.newPassword],
                    textInputAction: TextInputAction.done,
                    onSubmitted: (_) => _submit(),
                  ),
                ] else ...[
                  const SizedBox(height: 13),
                  _rememberRow(),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 16),
                  _errorBar(_error!),
                ],
                const SizedBox(height: 22),
                _submitButton(),
                const SizedBox(height: 17),
                Text(
                  _isRegister
                      ? '验证码 10 分钟内有效 · 密码 8–128 位'
                      : '支持邮箱或用户名登录 · 会话有效期 7 天',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: _soft, fontSize: 11),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _modeSwitch() {
    return Container(
      height: 44,
      decoration: BoxDecoration(
        color: const Color(0x4D03070E),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: _line),
      ),
      padding: const EdgeInsets.all(3),
      child: Row(
        children: [
          _modeCell(AuthMode.login, '登录', 'LOG IN'),
          _modeCell(AuthMode.register, '注册', 'SIGN UP'),
        ],
      ),
    );
  }

  Widget _modeCell(AuthMode mode, String label, String sublabel) {
    final selected = _mode == mode;
    return Expanded(
      child: Material(
        color: selected ? const Color(0xFFF4F7FB) : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => setState(() {
            _mode = mode;
            _error = null;
          }),
          child: Center(
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    color: selected ? _background : _muted,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  sublabel,
                  style: TextStyle(
                    color: selected ? const Color(0xFF5E6878) : _soft,
                    fontSize: 9,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _roleSwitch() {
    return Container(
      height: 42,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: _line),
      ),
      child: Row(
        children: [_roleCell('student', '学生'), _roleCell('teacher', '教师')],
      ),
    );
  }

  Widget _roleCell(String value, String label) {
    final selected = _accountRole == value;
    return Expanded(
      child: InkWell(
        onTap: () => setState(() => _accountRole = value),
        borderRadius: BorderRadius.circular(12),
        child: Container(
          alignment: Alignment.center,
          margin: const EdgeInsets.all(3),
          decoration: BoxDecoration(
            color: selected ? const Color(0x1F9BB0FF) : Colors.transparent,
            borderRadius: BorderRadius.circular(9),
          ),
          child: Text(
            label,
            style: TextStyle(
              color: selected ? _text : _muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ),
    );
  }

  Widget _fieldLabel(String label, {Widget? trailing}) {
    final text = Text(
      label,
      style: const TextStyle(
        color: Color(0xFFB9C3D1),
        fontSize: 12,
        fontWeight: FontWeight.w500,
      ),
    );
    if (trailing == null) return text;
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [text, trailing],
    );
  }

  Widget _field({
    required String label,
    required String hint,
    required TextEditingController controller,
    FocusNode? focusNode,
    bool obscure = false,
    Iterable<String>? autofillHints,
    TextInputAction? textInputAction,
    ValueChanged<String>? onSubmitted,
    TextInputType? keyboardType,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(label),
        const SizedBox(height: 8),
        _inputShell(
          child: TextField(
            controller: controller,
            focusNode: focusNode,
            obscureText: obscure,
            autofillHints: autofillHints,
            textInputAction: textInputAction,
            keyboardType: keyboardType,
            scrollPadding: EdgeInsets.only(
              bottom: MediaQuery.viewInsetsOf(context).bottom + 24,
            ),
            onSubmitted: onSubmitted,
            style: const TextStyle(color: _text, fontSize: 14),
            cursorColor: _accent,
            decoration: _inputDecoration(
              hint,
              showHint: focusNode?.hasFocus != true,
            ),
          ),
        ),
      ],
    );
  }

  Widget _inputShell({required Widget child}) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0x7303070E),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0x18FFFFFF)),
      ),
      child: child,
    );
  }

  InputDecoration _inputDecoration(
    String hint, {
    bool showHint = true,
    Widget? suffix,
  }) {
    return InputDecoration(
      hintText: showHint ? hint : null,
      hintStyle: const TextStyle(color: Color(0xFF58657A), fontSize: 14),
      suffixIcon: suffix,
      filled: false,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 15, vertical: 15),
      border: InputBorder.none,
      enabledBorder: InputBorder.none,
      focusedBorder: InputBorder.none,
    );
  }

  Widget _verificationCodeField() {
    final disabled = _sendingCode || _codeCooldown > 0;
    final buttonText = _sendingCode
        ? '发送中…'
        : _codeCooldown > 0
        ? '${_codeCooldown}s'
        : '获取验证码';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel('邮箱验证码'),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: _inputShell(
                child: TextField(
                  controller: _verificationCode,
                  focusNode: _verificationCodeFocus,
                  keyboardType: TextInputType.number,
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                    LengthLimitingTextInputFormatter(6),
                  ],
                  autofillHints: const [AutofillHints.oneTimeCode],
                  textInputAction: TextInputAction.next,
                  onSubmitted: (_) => _usernameFocus.requestFocus(),
                  style: const TextStyle(color: _text, fontSize: 14),
                  cursorColor: _accent,
                  decoration: _inputDecoration(
                    '6 位验证码',
                    showHint: !_verificationCodeFocus.hasFocus,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 9),
            SizedBox(
              width: 110,
              height: 48,
              child: OutlinedButton(
                onPressed: disabled ? null : _sendVerificationCode,
                style: OutlinedButton.styleFrom(
                  foregroundColor: _text,
                  disabledForegroundColor: _soft,
                  side: const BorderSide(color: _line),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
                child: Text(buttonText, style: const TextStyle(fontSize: 12)),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _passwordField() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(
          '密码',
          trailing: TextButton(
            onPressed: () => setState(() => _showPw = !_showPw),
            style: TextButton.styleFrom(
              foregroundColor: _accent,
              padding: EdgeInsets.zero,
              minimumSize: const Size(44, 28),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
            child: Text(
              _showPw ? '隐藏' : '显示',
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
            ),
          ),
        ),
        const SizedBox(height: 8),
        _inputShell(
          child: TextField(
            controller: _password,
            focusNode: _passwordFocus,
            obscureText: !_showPw,
            autofillHints: [
              _isRegister ? AutofillHints.newPassword : AutofillHints.password,
            ],
            textInputAction: _isRegister
                ? TextInputAction.next
                : TextInputAction.done,
            scrollPadding: EdgeInsets.only(
              bottom: MediaQuery.viewInsetsOf(context).bottom + 24,
            ),
            onSubmitted: (_) {
              if (_isRegister) {
                _password2Focus.requestFocus();
              } else {
                _submit();
              }
            },
            style: const TextStyle(color: _text, fontSize: 14),
            cursorColor: _accent,
            decoration: _inputDecoration(
              '请输入密码',
              showHint: !_passwordFocus.hasFocus,
            ),
          ),
        ),
      ],
    );
  }

  Widget _rememberRow() {
    return InkWell(
      onTap: _loading
          ? null
          : () => setState(() => _rememberLogin = !_rememberLogin),
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            SizedBox(
              width: 22,
              height: 22,
              child: Checkbox(
                value: _rememberLogin,
                onChanged: _loading
                    ? null
                    : (value) =>
                          setState(() => _rememberLogin = value ?? false),
                activeColor: _accent,
                checkColor: _background,
                side: const BorderSide(color: Color(0xFF66748A)),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(5),
                ),
              ),
            ),
            const SizedBox(width: 11),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('记住登录', style: TextStyle(color: _text, fontSize: 12)),
                  SizedBox(height: 2),
                  Text(
                    '在这台设备上保持登录 7 天',
                    style: TextStyle(color: _soft, fontSize: 11),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _errorBar(String message) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 11),
      decoration: BoxDecoration(
        color: const Color(0x1FFF8A9B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0x3DFF8A9B)),
      ),
      child: Row(
        children: [
          const Icon(
            LucideIcons.circleAlert,
            size: 15,
            color: Color(0xFFFF9AAA),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(color: Color(0xFFFFA6B3), fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _submitButton() {
    return SizedBox(
      height: 50,
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: const LinearGradient(colors: [Color(0xFFB6C4FF), _cyan]),
          borderRadius: BorderRadius.circular(14),
          boxShadow: const [
            BoxShadow(
              color: Color(0x245680FF),
              blurRadius: 28,
              offset: Offset(0, 12),
            ),
          ],
        ),
        child: Material(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(14),
          child: InkWell(
            onTap: _loading ? null : _submit,
            borderRadius: BorderRadius.circular(14),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 17),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    _loading ? '正在连接…' : (_isRegister ? '创建知识空间' : '进入 ESA'),
                    style: const TextStyle(
                      color: Color(0xFF08101F),
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Icon(
                    LucideIcons.arrowRight,
                    size: 17,
                    color: Color(0xFF08101F),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _guestLoginButton() {
    return OutlinedButton.icon(
      onPressed: _enterAsGuest,
      style: OutlinedButton.styleFrom(
        foregroundColor: _muted,
        side: const BorderSide(color: _line),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
      icon: const Icon(LucideIcons.userRound, size: 15),
      label: const Text(
        '游客登录',
        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _BackgroundWash extends StatelessWidget {
  const _BackgroundWash();

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: const [
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Color(0xFF080B13), Color(0xFF060910)],
            ),
          ),
        ),
        DecoratedBox(
          decoration: BoxDecoration(
            gradient: RadialGradient(
              center: Alignment(-0.65, -0.05),
              radius: 1.15,
              colors: [Color(0x192F4BD6), Color(0x00070A11)],
            ),
          ),
        ),
      ],
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        _BrandMark(),
        SizedBox(width: 11),
        Text(
          'ESA',
          style: TextStyle(
            color: _LoginPageState._text,
            fontSize: 14,
            fontWeight: FontWeight.w800,
          ),
        ),
        SizedBox(width: 8),
        Text(
          'Evolving Study Agent',
          style: TextStyle(color: _LoginPageState._soft, fontSize: 11),
        ),
      ],
    );
  }
}

class _BrandMark extends StatelessWidget {
  const _BrandMark();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 34,
      height: 34,
      child: CustomPaint(painter: _BrandPainter()),
    );
  }
}

class _BrandPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    const points = [
      Offset(8, 10),
      Offset(25, 7),
      Offset(17, 27),
      Offset(29, 23),
    ];
    final edge = Paint()
      ..color = const Color(0x739EB4FF)
      ..strokeWidth = 1;
    canvas.drawLine(points[0], points[1], edge);
    canvas.drawLine(points[0], points[2], edge);
    canvas.drawLine(points[1], points[3], edge);
    canvas.drawLine(points[2], points[3], edge);
    const colors = [
      Color(0xFFC4D1FF),
      Color(0xFF91B6FF),
      Color(0xFF8EE1FF),
      Color(0xFFDCE5FF),
    ];
    for (var i = 0; i < points.length; i++) {
      canvas.drawCircle(
        points[i],
        i == 0 ? 3 : 2.5,
        Paint()..color = colors[i],
      );
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _Metrics extends StatelessWidget {
  const _Metrics();

  // Real seeded knowledge graph: 473 knowledge points and 47 courses.
  static const _conceptCount = 473;
  static const _learningPathCount = 47;

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        _Metric(value: _conceptCount, label: 'concepts'),
        SizedBox(width: 24),
        _Metric(value: _learningPathCount, label: 'learning paths'),
        SizedBox(width: 24),
        Text(
          'continuously evolving',
          style: TextStyle(color: Color(0xFF738299), fontSize: 11),
        ),
      ],
    );
  }
}

class _Metric extends StatefulWidget {
  const _Metric({required this.value, required this.label});

  final int value;
  final String label;

  @override
  State<_Metric> createState() => _MetricState();
}

class _MetricState extends State<_Metric>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _progress;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1600),
    );
    _progress = CurvedAnimation(
      parent: _controller,
      curve: Curves.easeOutCubic,
    );
    _controller.forward();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _progress,
      builder: (context, _) {
        final displayed = (_progress.value * widget.value).round();
        return Text.rich(
          TextSpan(
            children: [
              TextSpan(
                text: '$displayed  ',
                style: const TextStyle(
                  color: Color(0xFFC6D0DF),
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              TextSpan(
                text: widget.label,
                style: const TextStyle(
                  color: Color(0xFF738299),
                  fontSize: 11,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _HeroCopy extends StatelessWidget {
  const _HeroCopy();

  @override
  Widget build(BuildContext context) {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'ENTER YOUR KNOWLEDGE SPACE',
          style: TextStyle(
            color: Color(0xFF77879E),
            fontSize: 10,
            fontWeight: FontWeight.w600,
          ),
        ),
        SizedBox(height: 14),
        SizedBox(
          width: 580,
          child: Text(
            'ESA-星知智链',
            style: TextStyle(
              color: _LoginPageState._text,
              fontSize: 58,
              height: 1.12,
              fontWeight: FontWeight.w700,
              letterSpacing: 0,
            ),
          ),
        ),
        SizedBox(height: 17),
        SizedBox(
          width: 520,
          child: Text(
            'ESA 理解你已经掌握的内容、正在学习的方向，以及下一步该去哪里，并围绕你持续重建学习路径。',
            style: TextStyle(
              color: Color(0xFF8E9DB2),
              fontSize: 14,
              height: 1.75,
            ),
          ),
        ),
      ],
    );
  }
}

class _CompactHero extends StatelessWidget {
  const _CompactHero();

  @override
  Widget build(BuildContext context) {
    return const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'ENTER YOUR KNOWLEDGE SPACE',
          style: TextStyle(color: Color(0xFF77879E), fontSize: 9),
        ),
        SizedBox(height: 10),
        Text(
          'ESA-星知智链',
          style: TextStyle(
            color: _LoginPageState._text,
            fontSize: 34,
            height: 1.08,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

class _LoadingStage extends StatelessWidget {
  const _LoadingStage();

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xE8070A11),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(
              width: 54,
              height: 54,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: _LoginPageState._accent,
              ),
            ),
            const SizedBox(height: 24),
            const Text(
              'Connecting your knowledge…',
              style: TextStyle(
                color: _LoginPageState._text,
                fontSize: 17,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              '正在连接你的知识空间',
              style: TextStyle(color: _LoginPageState._soft, fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}

class _GraphNode {
  const _GraphNode(
    this.x,
    this.y,
    this.radius,
    this.label, {
    this.core = false,
  });
  final double x;
  final double y;
  final double radius;
  final String label;
  final bool core;
}

class _KnowledgeGraphPainter extends CustomPainter {
  _KnowledgeGraphPainter({required this.animation, required this.pointer})
    : super(repaint: Listenable.merge([animation, pointer])) {
    _labels = List.generate(nodes.length, (index) {
      final small = index == 3 || index == 4 || index == 5;
      return TextPainter(
        text: TextSpan(
          text: nodes[index].label,
          style: TextStyle(
            color: small ? const Color(0xFF8794A8) : const Color(0xFFDCE4F2),
            fontSize: small ? 10 : 12,
            fontWeight: FontWeight.w500,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
    }, growable: false);
  }

  final Animation<double> animation;
  final ValueListenable<Offset?> pointer;
  bool compact = false;

  late final List<TextPainter> _labels;
  final List<Offset> _points = List.filled(
    nodes.length,
    Offset.zero,
    growable: false,
  );
  Offset _smoothedPointer = Offset.zero;
  double _hoverAmount = 0;

  final Paint _edgePaint = Paint()
    ..style = PaintingStyle.stroke
    ..strokeWidth = 1;
  final Paint _ringPaint = Paint()
    ..style = PaintingStyle.stroke
    ..strokeWidth = 1;
  final Paint _haloPaint = Paint()..style = PaintingStyle.fill;
  final Paint _nodePaint = Paint()..style = PaintingStyle.fill;
  final Paint _cursorEdgePaint = Paint()
    ..color = const Color(0x6B8DDBF8)
    ..style = PaintingStyle.stroke
    ..strokeWidth = 1;

  static const nodes = <_GraphNode>[
    _GraphNode(.17, .31, 7, 'Mathematics', core: true),
    _GraphNode(.28, .23, 5, 'Calculus'),
    _GraphNode(.30, .40, 5, 'Linear Algebra'),
    _GraphNode(.39, .16, 3.5, 'Limits'),
    _GraphNode(.40, .29, 3.5, 'Derivatives'),
    _GraphNode(.40, .40, 3.5, 'Matrices'),
    _GraphNode(.46, .50, 4.5, 'Eigenvalues'),
    _GraphNode(.15, .52, 5, 'Probability'),
    _GraphNode(.06, .61, 3.5, 'Bayes'),
    _GraphNode(.50, .21, 7, 'Artificial Intelligence', core: true),
    _GraphNode(.58, .35, 5, 'Machine Learning'),
    _GraphNode(.66, .29, 4.5, 'Neural Networks'),
    _GraphNode(.68, .47, 5, 'Transformer'),
    _GraphNode(.79, .53, 3.5, 'Attention'),
    _GraphNode(.76, .40, 3.5, 'Embedding'),
    _GraphNode(.51, .60, 5, 'Data Structures'),
    _GraphNode(.61, .71, 4.5, 'Graph Theory'),
    _GraphNode(.41, .70, 4.5, 'Algorithms'),
    _GraphNode(.27, .75, 4.5, 'Operating Systems'),
    _GraphNode(.11, .78, 4.5, 'Databases'),
  ];

  static const edges = <(int, int)>[
    (0, 1),
    (0, 2),
    (0, 7),
    (1, 3),
    (1, 4),
    (2, 5),
    (2, 6),
    (7, 8),
    (9, 10),
    (10, 11),
    (10, 12),
    (12, 13),
    (12, 14),
    (10, 15),
    (15, 16),
    (15, 17),
    (17, 18),
    (17, 19),
    (2, 9),
    (7, 10),
    (5, 15),
    (16, 6),
  ];

  static const double _heroClearance = 30;

  Rect _heroProtectedRect(Size size) {
    if (compact) return Rect.zero;
    final heroWidth = math.min(580.0, size.width * (15 / 24) - 122);
    final left = 58.0;
    final right = math.min(left + math.max(heroWidth, 120), size.width - 24);
    final bottomInset = math.max(72.0, size.height * .09);
    final top = size.height - bottomInset - 136;
    return Rect.fromLTRB(
      left,
      top - 18,
      right,
      size.height - bottomInset + 10,
    );
  }

  Offset _repelFromHero(Offset point, Size size) {
    if (compact) return point;
    final rect = _heroProtectedRect(size);
    if (!rect.contains(point)) return point;
    final dxLeft = point.dx - rect.left;
    final dxRight = rect.right - point.dx;
    final dyTop = point.dy - rect.top;
    final dyBottom = rect.bottom - point.dy;
    final minX = math.min(dxLeft, dxRight);
    final minY = math.min(dyTop, dyBottom);
    if (minX < minY) {
      final shift = _heroClearance + minX;
      return point + Offset(dxLeft < dxRight ? -shift : shift, 0);
    }
    final shift = _heroClearance + minY;
    return point + Offset(0, dyTop < dyBottom ? -shift : shift);
  }

  bool _segmentIntersectsRect(Offset a, Offset b, Rect rect) {
    final guard = rect.inflate(2);
    if (guard.contains(a) || guard.contains(b)) return true;
    for (var t = .1; t < 1; t += .1) {
      final sample = Offset.lerp(a, b, t);
      if (sample != null && guard.contains(sample)) return true;
    }
    return false;
  }

  Offset _point(
    _GraphNode node,
    Size size,
    int index,
    double phase,
    Offset parallax,
  ) {
    final width = compact ? size.width * 1.45 : size.width;
    final xShift = compact ? -size.width * .13 : 0.0;
    final depth = .45 + (index % 4) * .15;
    final dx = math.sin(phase + index * .73) * 2.4;
    final dy = math.cos(phase * .83 + index * .61) * 2.4;
    return _repelFromHero(
      Offset(
        xShift + node.x * width + dx + parallax.dx * depth,
        node.y * size.height + dy + parallax.dy * depth,
      ),
      size,
    );
  }

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    final targetPointer = pointer.value;
    final targetHover = targetPointer == null ? 0.0 : 1.0;
    _hoverAmount += (targetHover - _hoverAmount) * .14;
    final fallback = Offset(size.width * .5, size.height * .45);
    final target = targetPointer ?? fallback;
    if (_smoothedPointer == Offset.zero) _smoothedPointer = target;
    _smoothedPointer = Offset.lerp(_smoothedPointer, target, .14)!;
    final phase = animation.value * math.pi * 2;
    final parallax = Offset(
      ((_smoothedPointer.dx / size.width) - .5) * 22 * _hoverAmount,
      ((_smoothedPointer.dy / size.height) - .5) * 16 * _hoverAmount,
    );
    final heroRect = compact ? null : _heroProtectedRect(size);
    final visibleCount = compact ? 13 : nodes.length;
    for (var i = 0; i < visibleCount; i++) {
      _points[i] = _point(nodes[i], size, i, phase, parallax);
    }

    for (var i = 0; i < edges.length; i++) {
      final edge = edges[i];
      if (edge.$1 >= visibleCount || edge.$2 >= visibleCount) continue;
      if (heroRect != null &&
          _segmentIntersectsRect(
            _points[edge.$1],
            _points[edge.$2],
            heroRect,
          )) {
        continue;
      }
      final proximity = math.max(
        _proximity(_points[edge.$1]),
        _proximity(_points[edge.$2]),
      );
      _edgePaint.color = Color.lerp(
        i % 5 == 0 ? const Color(0x579FB4FF) : const Color(0x2E9FB4FF),
        const Color(0xB58DDBF8),
        proximity,
      )!;
      _edgePaint.strokeWidth = 1 + proximity * .7;
      canvas.drawLine(_points[edge.$1], _points[edge.$2], _edgePaint);
    }

    var nearestIndex = -1;
    var nearestDistance = double.infinity;
    for (var i = 0; i < visibleCount; i++) {
      final node = nodes[i];
      var point = _points[i];
      final distance = (point - _smoothedPointer).distance;
      final proximity = _proximity(point);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = i;
      }
      if (proximity > 0) {
        point += (_smoothedPointer - point) * (proximity * .025);
      }
      final radius = node.radius * (1 + proximity * .38);

      _ringPaint.color = Color.lerp(
        const Color(0x479CB0FF),
        const Color(0xC98DDBF8),
        proximity,
      )!;
      _ringPaint.strokeWidth = 1 + proximity;
      canvas.drawCircle(
        point,
        radius + (node.core ? 10 : 6) + proximity * 3,
        _ringPaint,
      );
      if (node.core) {
        _haloPaint.color = Color.lerp(
          const Color(0x2492A8FF),
          const Color(0x568DDBF8),
          proximity,
        )!;
        canvas.drawCircle(point, radius + 8, _haloPaint);
        _haloPaint.color = const Color(0x1A92A8FF);
        canvas.drawCircle(
          point,
          radius + 15 + math.sin(phase + i) * 2,
          _haloPaint,
        );
      }
      _nodePaint.color = Color.lerp(
        node.core ? const Color(0xFFA9BBFF) : const Color(0xFFDDE5F5),
        const Color(0xFFB9F0FF),
        proximity,
      )!;
      canvas.drawCircle(point, radius, _nodePaint);
      if (!compact || i < 8) {
        _labels[i].paint(canvas, point + Offset(radius + 10, -7));
      }
    }

    if (_hoverAmount > .05 && nearestIndex >= 0 && nearestDistance < 190) {
      _cursorEdgePaint.color = const Color(
        0x6B8DDBF8,
      ).withValues(alpha: .42 * _hoverAmount * (1 - nearestDistance / 190));
      canvas.drawLine(
        _smoothedPointer,
        _points[nearestIndex],
        _cursorEdgePaint,
      );
    }
  }

  double _proximity(Offset point) {
    if (_hoverAmount <= .01) return 0;
    final distance = (point - _smoothedPointer).distance;
    return (1 - distance / 175).clamp(0.0, 1.0) * _hoverAmount;
  }

  @override
  bool shouldRepaint(covariant _KnowledgeGraphPainter oldDelegate) => false;
}
