// 界面 4 —— 用户资料 + 设置(居中弹层)
// 资料区 + 统计三宫格 + 字段 + 设置区 + 底部 退出登录 / 保存

import 'package:flutter/material.dart';
import 'package:lucide_icons/lucide_icons.dart';

import '../state/app_state.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import 'esa_segmented.dart';

Future<void> showProfileSheet(BuildContext context) {
  return showDialog(
    context: context,
    barrierColor: const Color(0x80201E1D), // rgba(32,30,29,0.5)
    builder: (_) => const _ProfileSheet(),
  );
}

class _ProfileSheet extends StatefulWidget {
  const _ProfileSheet();

  @override
  State<_ProfileSheet> createState() => _ProfileSheetState();
}

class _ProfileSheetState extends State<_ProfileSheet> {
  late final TextEditingController _name;
  late final TextEditingController _email;
  late String _role;
  bool _init = false;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (!_init) {
      _name = TextEditingController(text: app.username);
      _email = TextEditingController(text: app.email);
      _role = app.role;
      _init = true;
    }

    final maxH = MediaQuery.of(context).size.height * 0.88;

    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: EsaSpace.dialogWidth,
          maxHeight: maxH,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _header(context),
            Flexible(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(EsaSpace.xl),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _profileRow(context, app),
                    const SizedBox(height: EsaSpace.xl),
                    _stats(context, app),
                    const SizedBox(height: EsaSpace.xl),
                    _labeledField(context, 'DISPLAY NAME', _name),
                    const SizedBox(height: EsaSpace.lg),
                    _labeledField(context, 'EMAIL', _email),
                    const SizedBox(height: EsaSpace.lg),
                    _roleField(context),
                    const SizedBox(height: EsaSpace.xl),
                    Divider(color: context.n.divider, thickness: 1),
                    const SizedBox(height: EsaSpace.lg),
                    Text(
                      'SETTINGS · 设置',
                      style: context.texts.labelSmall?.copyWith(
                        color: EsaColors.accent,
                      ),
                    ),
                    const SizedBox(height: EsaSpace.md),
                    _settings(context, app),
                  ],
                ),
              ),
            ),
            _footer(context, app),
          ],
        ),
      ),
    );
  }

  Widget _header(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 18, 14, 18),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: context.n.divider)),
      ),
      child: Row(
        children: [
          Text(
            'PROFILE · 个人资料',
            style: context.texts.labelSmall?.copyWith(color: EsaColors.accent),
          ),
          const Spacer(),
          InkWell(
            onTap: () => Navigator.of(context).pop(),
            borderRadius: BorderRadius.circular(EsaRadii.iconButton),
            child: SizedBox(
              width: 30,
              height: 30,
              child: Icon(LucideIcons.x, size: 18, color: context.n.n600),
            ),
          ),
        ],
      ),
    );
  }

  Widget _profileRow(BuildContext context, AppState app) {
    final initial = app.username.isEmpty ? 'U' : app.username.characters.first;
    return Row(
      children: [
        Container(
          width: 66,
          height: 66,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: EsaColors.accent,
            borderRadius: BorderRadius.circular(EsaRadii.sheet),
          ),
          child: Text(
            initial.toUpperCase(),
            style: const TextStyle(
              color: EsaColors.onAccent,
              fontSize: 28,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        const SizedBox(width: EsaSpace.lg),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(app.username, style: context.texts.headlineSmall),
              const SizedBox(height: 2),
              Text(
                app.email,
                style: TextStyle(fontSize: 12.5, color: context.n.n600),
              ),
            ],
          ),
        ),
        OutlinedButton(onPressed: () {}, child: const Text('更换头像')),
      ],
    );
  }

  Widget _stats(BuildContext context, AppState app) {
    final pinned = app.conversations.where((c) => c.pinned).length;
    Widget cell(String number, String cn, String en) => Expanded(
      child: Column(
        children: [
          Text(
            number,
            style: context.texts.headlineSmall?.copyWith(fontSize: 22),
          ),
          const SizedBox(height: 4),
          Text(
            '$cn $en',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              letterSpacing: 1.0,
              color: context.n.n600,
            ),
          ),
        ],
      ),
    );
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 18),
      decoration: BoxDecoration(
        border: Border.symmetric(
          horizontal: BorderSide(color: context.n.divider),
        ),
      ),
      child: IntrinsicHeight(
        child: Row(
          children: [
            cell('${app.conversations.length}', '对话', 'CHATS'),
            VerticalDivider(width: 1, color: context.n.divider),
            cell('$pinned', '收藏', 'PINNED'),
            VerticalDivider(width: 1, color: context.n.divider),
            cell('7', '天连续', 'STREAK'),
          ],
        ),
      ),
    );
  }

  Widget _fieldLabel(BuildContext context, String en) {
    return Padding(
      padding: const EdgeInsets.only(bottom: EsaSpace.sm),
      child: Text(
        en,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          letterSpacing: 1.2,
          color: context.n.n700,
        ),
      ),
    );
  }

  Widget _labeledField(
    BuildContext context,
    String en,
    TextEditingController c,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(context, en),
        TextField(controller: c),
      ],
    );
  }

  Widget _roleField(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(context, 'ROLE'),
        EsaSegmented<String>(
          value: _role,
          onChanged: (v) => setState(() => _role = v),
          segments: const [EsaSegment('学生', '学生'), EsaSegment('教师', '教师')],
        ),
      ],
    );
  }

  Widget _settings(BuildContext context, AppState app) {
    return Column(
      children: [
        _settingRow(
          context,
          title: '外观',
          sub: '浅色或深色主题',
          control: SizedBox(
            width: 180,
            child: EsaSegmented<ThemeMode>(
              value: app.themeMode,
              height: 36,
              onChanged: app.setThemeMode,
              segments: const [
                EsaSegment(ThemeMode.light, '浅色'),
                EsaSegment(ThemeMode.dark, '深色'),
              ],
            ),
          ),
        ),
        _divider(context),
        _settingRow(
          context,
          title: '流式输出',
          sub: '逐字显示助手回复',
          control: Switch(value: app.streamOn, onChanged: app.setStreamOn),
        ),
        _divider(context),
        _settingRow(
          context,
          title: '工具调用详情',
          sub: '显示检索等工具的执行块',
          control: Switch(value: app.toolsOn, onChanged: app.setToolsOn),
        ),
        _divider(context),
        _settingRow(
          context,
          title: '登录密码',
          sub: '修改后所有设备需要重新登录',
          control: TextButton(
            onPressed: () async {
              final changed = await showDialog<bool>(
                context: context,
                builder: (_) => const _ChangePasswordDialog(),
              );
              if (changed == true && context.mounted) {
                Navigator.of(context).pop();
              }
            },
            child: const Text(
              '修改 →',
              style: TextStyle(
                color: EsaColors.accent,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ),
        _divider(context),
        _settingRow(
          context,
          title: '数据与隐私',
          sub: '管理你的对话与课件数据',
          control: TextButton(
            onPressed: () {},
            child: const Text(
              '管理 →',
              style: TextStyle(
                color: EsaColors.accent,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _divider(BuildContext context) =>
      Divider(height: 1, color: context.n.divider);

  Widget _settingRow(
    BuildContext context, {
    required String title,
    required String sub,
    required Widget control,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: context.texts.titleMedium?.copyWith(fontSize: 14),
                ),
                const SizedBox(height: 2),
                Text(
                  sub,
                  style: TextStyle(fontSize: 11.5, color: context.n.n600),
                ),
              ],
            ),
          ),
          const SizedBox(width: EsaSpace.md),
          control,
        ],
      ),
    );
  }

  Widget _footer(BuildContext context, AppState app) {
    return Container(
      padding: const EdgeInsets.all(EsaSpace.lg),
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: context.n.divider)),
      ),
      child: Row(
        children: [
          OutlinedButton.icon(
            onPressed: () {
              Navigator.of(context).pop(); // 关闭弹层
              app.logout(); // 回到登录页(root 根据 username 切换)
            },
            icon: const Icon(LucideIcons.logOut, size: 16),
            style: OutlinedButton.styleFrom(
              foregroundColor: EsaColors.accent,
              side: const BorderSide(color: EsaColors.accent),
            ),
            label: const Text('退出登录'),
          ),
          const Spacer(),
          FilledButton(
            onPressed: () {
              app.updateProfile(
                name: _name.text,
                mail: _email.text,
                roleValue: _role,
              );
              Navigator.of(context).pop();
            },
            child: const Text('保存'),
          ),
        ],
      ),
    );
  }
}

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog();

  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _oldPassword = TextEditingController();
  final _newPassword = TextEditingController();
  final _confirmPassword = TextEditingController();
  bool _hideOld = true;
  bool _hideNew = true;
  bool _hideConfirm = true;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _oldPassword.dispose();
    _newPassword.dispose();
    _confirmPassword.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting) return;

    final oldPassword = _oldPassword.text;
    final newPassword = _newPassword.text;
    final confirmPassword = _confirmPassword.text;

    if (oldPassword.length < 8) {
      setState(() => _error = '旧密码至少需要 8 位');
      return;
    }
    if (newPassword.length < 8) {
      setState(() => _error = '新密码至少需要 8 位');
      return;
    }
    if (newPassword.length > 128) {
      setState(() => _error = '新密码不能超过 128 位');
      return;
    }
    if (newPassword != confirmPassword) {
      setState(() => _error = '两次输入的新密码不一致');
      return;
    }
    if (oldPassword == newPassword) {
      setState(() => _error = '新密码不能与旧密码相同');
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });

    final app = AppScope.of(context);
    final error = await app.changePassword(oldPassword, newPassword);
    if (!mounted) return;

    if (error == null) {
      Navigator.of(context).pop(true);
      return;
    }

    setState(() {
      _submitting = false;
      _error = error;
    });
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('修改密码'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 380),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '修改成功后，所有已登录设备都需要使用新密码重新登录。',
              style: TextStyle(fontSize: 12.5, color: context.n.n600),
            ),
            const SizedBox(height: EsaSpace.lg),
            _passwordField(
              controller: _oldPassword,
              label: '旧密码',
              obscure: _hideOld,
              onToggle: () => setState(() => _hideOld = !_hideOld),
            ),
            const SizedBox(height: EsaSpace.md),
            _passwordField(
              controller: _newPassword,
              label: '新密码',
              obscure: _hideNew,
              onToggle: () => setState(() => _hideNew = !_hideNew),
            ),
            const SizedBox(height: EsaSpace.md),
            _passwordField(
              controller: _confirmPassword,
              label: '确认新密码',
              obscure: _hideConfirm,
              onToggle: () => setState(() => _hideConfirm = !_hideConfirm),
              onSubmitted: (_) => _submit(),
            ),
            if (_error != null) ...[
              const SizedBox(height: EsaSpace.md),
              Text(
                _error!,
                style: const TextStyle(color: EsaColors.accent, fontSize: 12.5),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting
              ? null
              : () => Navigator.of(context).pop(false),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('确认修改'),
        ),
      ],
    );
  }

  Widget _passwordField({
    required TextEditingController controller,
    required String label,
    required bool obscure,
    required VoidCallback onToggle,
    ValueChanged<String>? onSubmitted,
  }) {
    return TextField(
      controller: controller,
      obscureText: obscure,
      enabled: !_submitting,
      textInputAction: onSubmitted == null
          ? TextInputAction.next
          : TextInputAction.done,
      onSubmitted: onSubmitted,
      decoration: InputDecoration(
        labelText: label,
        suffixIcon: IconButton(
          onPressed: onToggle,
          tooltip: obscure ? '显示密码' : '隐藏密码',
          icon: Icon(obscure ? LucideIcons.eye : LucideIcons.eyeOff, size: 18),
        ),
      ),
    );
  }
}
