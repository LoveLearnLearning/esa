// 界面 1 —— 登录 / 注册
// 左右两栏 海报(红) + 表单 窄屏(<880)竖向堆叠 海报在上

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../widgets/esa_buttons.dart';
import '../widgets/esa_segmented.dart';

enum AuthMode { login, register }

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
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
  AuthMode _mode = AuthMode.login;
  bool _showPw = false;
  bool _rememberLogin = true;
  bool _loading = false;
  bool _sendingCode = false;
  int _codeCooldown = 0;
  Timer? _codeTimer;
  String? _error;

  @override
  void dispose() {
    _codeTimer?.cancel();
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

  bool get _isRegister => _mode == AuthMode.register;

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
    final password = _password.text; // 不 trim 密码
    // 校验与后端一致
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
        ? await app.register(email, verificationCode, username, password)
        : await app.login(username, password, rememberLogin: _rememberLogin);
    if (!mounted) return;
    if (err == null) TextInput.finishAutofillContext(shouldSave: true);
    setState(() {
      _loading = false;
      _error = err; // null 表示成功 root 会自动切到对话页
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      // 点击表单外空白处收起软键盘（手机浏览器上没有系统返回手势可用）
      body: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTap: () => FocusManager.instance.primaryFocus?.unfocus(),
        child: LayoutBuilder(
          builder: (context, c) {
            final stacked = c.maxWidth < 880;
            final poster = _Poster(stacked: stacked);
            final form = _buildForm(context);
            if (stacked) {
              return SingleChildScrollView(
                child: Column(children: [poster, form]),
              );
            }
            return Row(
              children: [
                Expanded(child: poster),
                Expanded(child: SingleChildScrollView(child: form)),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildForm(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 400 + 48 * 2),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 48, vertical: 56),
          child: AutofillGroup(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'ACCOUNT',
                  style: context.texts.labelSmall?.copyWith(
                    color: EsaColors.accent,
                  ),
                ),
                const SizedBox(height: EsaSpace.md),
                Text(
                  _isRegister ? '注册' : '登录',
                  style: context.texts.headlineMedium,
                ),
                const SizedBox(height: EsaSpace.sm),
                Text(
                  _isRegister ? '创建一个 ESA 账号，开始你的学习。' : '欢迎回来，登录继续你的学习。',
                  style: context.texts.bodySmall?.copyWith(fontSize: 13),
                ),
                const SizedBox(height: EsaSpace.xl),
                EsaSegmented<AuthMode>(
                  value: _mode,
                  onChanged: (m) => setState(() {
                    _mode = m;
                    _error = null;
                  }),
                  segments: const [
                    EsaSegment(AuthMode.login, '登录', sublabel: 'LOG IN'),
                    EsaSegment(AuthMode.register, '注册', sublabel: 'SIGN UP'),
                  ],
                ),
                const SizedBox(height: EsaSpace.xl),
                if (_isRegister) ...[
                  _field(
                    context,
                    label: '邮箱',
                    controller: _email,
                    focusNode: _emailFocus,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    textInputAction: TextInputAction.next,
                    onSubmitted: (_) => _verificationCodeFocus.requestFocus(),
                  ),
                  const SizedBox(height: EsaSpace.lg),
                  _verificationCodeField(context),
                  const SizedBox(height: EsaSpace.lg),
                ],
                _field(
                  context,
                  label: _isRegister ? '用户名' : '邮箱或用户名',
                  controller: _username,
                  focusNode: _usernameFocus,
                  autofillHints: const [AutofillHints.username],
                  textInputAction: TextInputAction.next,
                  onSubmitted: (_) => _passwordFocus.requestFocus(),
                ),
                const SizedBox(height: EsaSpace.lg),
                _passwordField(context),
                if (_isRegister) ...[
                  const SizedBox(height: EsaSpace.lg),
                  _field(
                    context,
                    label: '确认密码',
                    controller: _password2,
                    focusNode: _password2Focus,
                    obscure: !_showPw,
                    autofillHints: const [AutofillHints.newPassword],
                    textInputAction: TextInputAction.done,
                    onSubmitted: (_) => _submit(),
                  ),
                ],
                if (!_isRegister) ...[
                  const SizedBox(height: EsaSpace.md),
                  CheckboxListTile(
                    value: _rememberLogin,
                    onChanged: _loading
                        ? null
                        : (value) =>
                              setState(() => _rememberLogin = value ?? false),
                    controlAffinity: ListTileControlAffinity.leading,
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: const Text('记住登录'),
                    subtitle: const Text('在这台设备上保持登录 7 天'),
                  ),
                ],
                if (_error != null) ...[
                  const SizedBox(height: EsaSpace.lg),
                  _errorBar(context, _error!),
                ],
                const SizedBox(height: EsaSpace.xl),
                EsaRedButton(
                  label: _loading ? '请稍候…' : (_isRegister ? '创建账号' : '登录 ESA'),
                  trailing: LucideIcons.arrowUp,
                  onPressed: _loading ? null : _submit,
                ),
                const SizedBox(height: EsaSpace.lg),
                Text(
                  _isRegister
                      ? '验证码 10 分钟内有效 · 密码 8–128 位'
                      : '支持邮箱或用户名登录 · 会话有效期 7 天',
                  style: TextStyle(fontSize: 11.5, color: context.n.n600),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _fieldLabel(BuildContext context, String label, {Widget? trailing}) {
    final l = Text(
      label.toUpperCase(),
      style: TextStyle(
        fontSize: 11,
        fontWeight: FontWeight.w600,
        letterSpacing: 1.2,
        color: context.n.n700,
      ),
    );
    if (trailing == null) return l;
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [l, trailing],
    );
  }

  Widget _field(
    BuildContext context, {
    required String label,
    required TextEditingController controller,
    FocusNode? focusNode,
    bool obscure = false,
    Iterable<String>? autofillHints,
    TextInputAction? textInputAction,
    ValueChanged<String>? onSubmitted,
    TextInputType? keyboardType,
    int? maxLength,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(context, label),
        const SizedBox(height: EsaSpace.sm),
        TextField(
          controller: controller,
          focusNode: focusNode,
          obscureText: obscure,
          autofillHints: autofillHints,
          textInputAction: textInputAction,
          keyboardType: keyboardType,
          maxLength: maxLength,
          buildCounter: maxLength == null
              ? null
              : (_, {required currentLength, required isFocused, maxLength}) =>
                    null,
          // 竖排布局下字段靠近屏幕底部，聚焦时确保滚到键盘上方
          scrollPadding: EdgeInsets.only(
            bottom: MediaQuery.viewInsetsOf(context).bottom + 24,
          ),
          onSubmitted: onSubmitted,
        ),
      ],
    );
  }

  Widget _verificationCodeField(BuildContext context) {
    final disabled = _sendingCode || _codeCooldown > 0;
    final buttonText = _sendingCode
        ? '发送中…'
        : _codeCooldown > 0
        ? '${_codeCooldown}s'
        : '获取验证码';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(context, '邮箱验证码'),
        const SizedBox(height: EsaSpace.sm),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
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
              ),
            ),
            const SizedBox(width: EsaSpace.sm),
            SizedBox(
              width: 112,
              child: OutlinedButton(
                onPressed: disabled ? null : _sendVerificationCode,
                child: Text(buttonText),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _passwordField(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(
          context,
          '密码',
          trailing: GestureDetector(
            onTap: () => setState(() => _showPw = !_showPw),
            child: Text(
              _showPw ? '隐藏' : '显示',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                letterSpacing: 1.2,
                color: EsaColors.accent,
              ),
            ),
          ),
        ),
        const SizedBox(height: EsaSpace.sm),
        TextField(
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
        ),
      ],
    );
  }

  Widget _errorBar(BuildContext context, String message) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: EsaColors.accent100,
        borderRadius: BorderRadius.circular(EsaRadii.field),
      ),
      child: Text(
        message,
        style: const TextStyle(color: EsaColors.accent700, fontSize: 13),
      ),
    );
  }
}

class _Poster extends StatelessWidget {
  const _Poster({required this.stacked});
  final bool stacked;

  @override
  Widget build(BuildContext context) {
    const white = EsaColors.onAccent;

    final brand = Row(
      children: [
        Container(
          width: 28,
          height: 28,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: white,
            borderRadius: BorderRadius.circular(8),
          ),
          child: const Text(
            'E',
            style: TextStyle(
              color: EsaColors.accent,
              fontWeight: FontWeight.w800,
              fontSize: 16,
            ),
          ),
        ),
        const SizedBox(width: 12),
        const Text(
          'EFFICIENT STUDY AGENT',
          style: TextStyle(
            color: white,
            fontSize: 11,
            fontWeight: FontWeight.w600,
            letterSpacing: 1.54,
          ),
        ),
      ],
    );

    final titleBlock = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '星知\n智链',
          style: context.texts.displayLarge?.copyWith(
            color: white,
            fontSize: stacked ? 44 : 68,
          ),
        ),
        const SizedBox(height: 20),
        Container(
          height: 2,
          constraints: const BoxConstraints(maxWidth: 340),
          color: white.withValues(alpha: 0.55),
        ),
        if (!stacked) ...[
          const SizedBox(height: 20),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: const Text(
              '面向学生与教师的学习智能体，检索课件、记住你的进度、调用工具，一步步陪你把问题学透。',
              style: TextStyle(color: white, fontSize: 16, height: 1.6),
            ),
          ),
        ],
      ],
    );

    return Container(
      color: EsaColors.accent,
      padding: EdgeInsets.symmetric(
        horizontal: 48,
        vertical: stacked ? 28 : 56,
      ),
      // 顶部留出状态栏/刘海 避免品牌行被裁切
      child: SafeArea(
        left: false,
        right: false,
        bottom: false,
        child: stacked
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [brand, const SizedBox(height: 24), titleBlock],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  brand,
                  const SizedBox(height: 24),
                  titleBlock,
                  const Column(
                    children: [
                      _PosterRow('课件检索', 'RAG'),
                      _PosterRow('学习记忆', 'MEMORY'),
                      _PosterRow('工具调用', 'TOOLS'),
                    ],
                  ),
                ],
              ),
      ),
    );
  }
}

class _PosterRow extends StatelessWidget {
  const _PosterRow(this.cn, this.en);
  final String cn;
  final String en;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14),
      decoration: BoxDecoration(
        border: Border(
          top: BorderSide(color: EsaColors.onAccent.withValues(alpha: 0.55)),
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            cn,
            style: const TextStyle(
              color: EsaColors.onAccent,
              fontSize: 15,
              fontWeight: FontWeight.w800,
            ),
          ),
          Text(
            en,
            style: TextStyle(
              color: EsaColors.onAccent.withValues(alpha: 0.8),
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}
