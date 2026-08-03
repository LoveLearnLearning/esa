// 界面 1 —— 登录 / 注册
// 左右两栏 海报(红) + 表单 窄屏(<880)竖向堆叠 海报在上

import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

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
  final _username = TextEditingController();
  final _password = TextEditingController();
  final _password2 = TextEditingController();
  final _usernameFocus = FocusNode();
  final _passwordFocus = FocusNode();
  final _password2Focus = FocusNode();
  AuthMode _mode = AuthMode.login;
  bool _showPw = false;
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    _password2.dispose();
    _usernameFocus.dispose();
    _passwordFocus.dispose();
    _password2Focus.dispose();
    super.dispose();
  }

  bool get _isRegister => _mode == AuthMode.register;

  Future<void> _submit() async {
    if (_loading) return;

    final username = _username.text.trim();
    final password = _password.text; // 不 trim 密码
    // 校验与后端一致
    if (username.isEmpty || password.isEmpty) {
      setState(() => _error = '请输入用户名和密码');
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
        ? await app.register(username, password)
        : await app.login(username, password);
    if (!mounted) return;
    setState(() {
      _loading = false;
      _error = err; // null 表示成功 root 会自动切到对话页
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: LayoutBuilder(
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
    );
  }

  Widget _buildForm(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 400 + 48 * 2),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 48, vertical: 56),
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
              _field(
                context,
                label: '用户名',
                controller: _username,
                focusNode: _usernameFocus,
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
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) => _submit(),
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
                '密码 8–128 位 · 会话有效期 2 小时',
                style: TextStyle(fontSize: 11.5, color: context.n.n600),
              ),
            ],
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
    TextInputAction? textInputAction,
    ValueChanged<String>? onSubmitted,
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
          textInputAction: textInputAction,
          onSubmitted: onSubmitted,
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
          textInputAction: _isRegister
              ? TextInputAction.next
              : TextInputAction.done,
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
