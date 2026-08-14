// 界面 4 —— 用户资料 + 设置(居中弹层)
// 资料区 + 统计三宫格 + 字段 + 设置区 + 底部 退出登录 / 保存

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../state/app_state.dart';
import '../models/code_editor_settings.dart';
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
  late final TextEditingController _customInstruction;
  late final TextEditingController _grade;
  late final TextEditingController _currentWeek;
  late final TextEditingController _totalWeeks;
  late String _role;
  late String _preferredStyle;
  late String _preferredTone;
  late bool _profileEnabled;
  bool _saving = false;
  String? _saveError;
  bool _init = false;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _customInstruction.dispose();
    _grade.dispose();
    _currentWeek.dispose();
    _totalWeeks.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (!_init) {
      _name = TextEditingController(text: app.username);
      _email = TextEditingController(text: app.email);
      _customInstruction = TextEditingController(
        text: app.preferences.customInstruction,
      );
      _grade = TextEditingController(text: app.userProfile.grade);
      _currentWeek = TextEditingController(
        text: app.userProfile.currentWeek.toString(),
      );
      _totalWeeks = TextEditingController(
        text: app.userProfile.totalWeeks.toString(),
      );
      _role = app.role;
      _preferredStyle = app.preferences.preferredStyle;
      _preferredTone = app.preferences.preferredTone;
      _profileEnabled = app.userProfile.profileEnabled;
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
                    _emailField(context, app),
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
                    const SizedBox(height: EsaSpace.xl),
                    _preferencesSection(context),
                    const SizedBox(height: EsaSpace.xl),
                    _learningProfileSection(context),
                    if (_saveError != null) ...[
                      const SizedBox(height: EsaSpace.md),
                      Text(
                        _saveError!,
                        style: const TextStyle(color: EsaColors.accent),
                      ),
                    ],
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

  Widget _emailField(BuildContext context, AppState app) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(context, 'EMAIL'),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _email,
                readOnly: true,
                decoration: InputDecoration(
                  hintText: '尚未绑定邮箱',
                  prefixIcon: const Icon(LucideIcons.mail, size: 18),
                ),
              ),
            ),
            const SizedBox(width: EsaSpace.sm),
            TextButton(
              onPressed: () async {
                final bound = await showDialog<String>(
                  context: context,
                  builder: (_) => _BindEmailDialog(initialEmail: app.email),
                );
                if (bound != null && mounted) {
                  _email.text = bound;
                  setState(() {});
                }
              },
              child: Text(app.email.isEmpty ? '绑定' : '更换'),
            ),
          ],
        ),
      ],
    );
  }

  Widget _roleField(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(context, 'ROLE'),
        InputDecorator(
          decoration: const InputDecoration(helperText: '账号身份由注册入口与服务端权限决定'),
          child: Text(_role),
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
          title: '代码缩进',
          sub: 'Tab 和自动缩进使用的空格数',
          control: SizedBox(
            width: 180,
            child: EsaSegmented<int>(
              key: const ValueKey('code-editor-indent-setting'),
              value: app.codeEditorIndentSize,
              height: 36,
              onChanged: app.setCodeEditorIndentSize,
              segments: const [
                EsaSegment(2, '2'),
                EsaSegment(4, '4'),
                EsaSegment(8, '8'),
              ],
            ),
          ),
        ),
        _divider(context),
        _settingRow(
          context,
          title: '代码主题',
          sub: '独立设置代码编辑区域配色',
          control: SizedBox(
            width: 180,
            child: DropdownButtonFormField<String>(
              key: const ValueKey('code-editor-theme-setting'),
              initialValue: app.codeEditorTheme,
              isExpanded: true,
              isDense: true,
              decoration: const InputDecoration(
                contentPadding: EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 10,
                ),
              ),
              items: [
                for (final entry in codeEditorThemeLabels.entries)
                  DropdownMenuItem(value: entry.key, child: Text(entry.value)),
              ],
              onChanged: (value) {
                if (value != null) app.setCodeEditorTheme(value);
              },
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

  Widget _preferencesSection(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'OUTPUT · 输出偏好',
          style: context.texts.labelSmall?.copyWith(color: EsaColors.accent),
        ),
        const SizedBox(height: EsaSpace.md),
        _fieldLabel(context, '回答风格'),
        EsaSegmented<String>(
          value: _preferredStyle,
          onChanged: (value) => setState(() => _preferredStyle = value),
          segments: const [
            EsaSegment('concise', '简洁'),
            EsaSegment('detailed', '详细'),
            EsaSegment('socratic', '苏格拉底'),
          ],
        ),
        const SizedBox(height: EsaSpace.lg),
        _fieldLabel(context, '回答语调'),
        EsaSegmented<String>(
          value: _preferredTone,
          onChanged: (value) => setState(() => _preferredTone = value),
          segments: const [
            EsaSegment('friendly', '友好'),
            EsaSegment('formal', '正式'),
            EsaSegment('encouraging', '鼓励'),
            EsaSegment('strict', '严格'),
          ],
        ),
        const SizedBox(height: EsaSpace.lg),
        _fieldLabel(context, '自定义指令（0/500）'),
        TextField(
          controller: _customInstruction,
          minLines: 3,
          maxLines: 5,
          maxLength: 500,
          decoration: const InputDecoration(hintText: '例：解释数学概念时先给直观例子…'),
        ),
      ],
    );
  }

  Widget _learningProfileSection(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'LEARNING PROFILE · 学情档案',
                    style: context.texts.labelSmall?.copyWith(
                      color: EsaColors.accent,
                    ),
                  ),
                  Text(
                    '开启后 Agent 会结合掌握度和教学进度回答',
                    style: TextStyle(fontSize: 11.5, color: context.n.n600),
                  ),
                ],
              ),
            ),
            Switch(
              value: _profileEnabled,
              onChanged: (value) => setState(() => _profileEnabled = value),
            ),
          ],
        ),
        const SizedBox(height: EsaSpace.md),
        _fieldLabel(context, '专业'),
        const TextField(
          enabled: false,
          decoration: InputDecoration(hintText: '计算机科学（当前仅支持）'),
        ),
        const SizedBox(height: EsaSpace.lg),
        _labeledField(context, '年级', _grade),
        const SizedBox(height: EsaSpace.lg),
        Row(
          children: [
            Expanded(child: _numberField(context, '当前教学周', _currentWeek)),
            const SizedBox(width: EsaSpace.md),
            Expanded(child: _numberField(context, '学期总周数', _totalWeeks)),
          ],
        ),
      ],
    );
  }

  Widget _numberField(
    BuildContext context,
    String label,
    TextEditingController controller,
  ) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _fieldLabel(context, label),
        TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(hintText: '1 - 30'),
        ),
      ],
    );
  }

  Future<void> _save(AppState app) async {
    if (_saving) return;
    final currentWeek = int.tryParse(_currentWeek.text);
    final totalWeeks = int.tryParse(_totalWeeks.text);
    if (currentWeek == null || totalWeeks == null) {
      setState(() => _saveError = '教学周必须是数字');
      return;
    }
    if (currentWeek < 1 ||
        currentWeek > 30 ||
        totalWeeks < 1 ||
        totalWeeks > 30) {
      setState(() => _saveError = '教学周必须在 1 到 30 之间');
      return;
    }
    setState(() {
      _saving = true;
      _saveError = null;
    });
    final error = await app.savePreferencesAndProfile(
      preferredStyle: _preferredStyle,
      preferredTone: _preferredTone,
      customInstruction: _customInstruction.text,
      major: 'cs',
      grade: _grade.text.trim(),
      currentWeek: currentWeek,
      totalWeeks: totalWeeks,
      profileEnabled: _profileEnabled,
    );
    if (!mounted) return;
    if (error != null) {
      setState(() {
        _saving = false;
        _saveError = error;
      });
      return;
    }
    app.updateProfile(name: _name.text);
    Navigator.of(context).pop();
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
            onPressed: _saving ? null : () => _save(app),
            child: Text(_saving ? '保存中…' : '保存'),
          ),
        ],
      ),
    );
  }
}

class _BindEmailDialog extends StatefulWidget {
  const _BindEmailDialog({required this.initialEmail});

  final String initialEmail;

  @override
  State<_BindEmailDialog> createState() => _BindEmailDialogState();
}

class _BindEmailDialogState extends State<_BindEmailDialog> {
  late final TextEditingController _email;
  final _code = TextEditingController();
  bool _sending = false;
  bool _submitting = false;
  int _cooldown = 0;
  Timer? _timer;
  String? _error;

  @override
  void initState() {
    super.initState();
    _email = TextEditingController(text: widget.initialEmail);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _email.dispose();
    _code.dispose();
    super.dispose();
  }

  bool _validEmail(String value) {
    final parts = value.trim().split('@');
    return parts.length == 2 &&
        parts.first.isNotEmpty &&
        parts.last.contains('.') &&
        !parts.last.startsWith('.') &&
        !parts.last.endsWith('.');
  }

  Future<void> _sendCode() async {
    if (_sending || _cooldown > 0) return;
    final value = _email.text.trim();
    if (!_validEmail(value)) {
      setState(() => _error = '请输入正确的邮箱地址');
      return;
    }
    setState(() {
      _sending = true;
      _error = null;
    });
    final result = await AppScope.of(context).sendBindEmailCode(value);
    if (!mounted) return;
    final seconds = int.tryParse(result ?? '');
    setState(() {
      _sending = false;
      _error = seconds == null ? result : null;
      if (seconds != null) _cooldown = seconds;
    });
    if (seconds == null) return;
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted || _cooldown <= 1) {
        timer.cancel();
        if (mounted) setState(() => _cooldown = 0);
        return;
      }
      setState(() => _cooldown--);
    });
  }

  Future<void> _submit() async {
    if (_submitting) return;
    final value = _email.text.trim();
    if (!_validEmail(value)) {
      setState(() => _error = '请输入正确的邮箱地址');
      return;
    }
    if (!RegExp(r'^\d{6}$').hasMatch(_code.text)) {
      setState(() => _error = '请输入 6 位邮箱验证码');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    final error = await AppScope.of(context).bindEmail(value, _code.text);
    if (!mounted) return;
    if (error == null) {
      Navigator.of(context).pop(value.toLowerCase());
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
      title: Text(widget.initialEmail.isEmpty ? '绑定邮箱' : '更换邮箱'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 400),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _email,
              enabled: !_submitting,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: '邮箱',
                prefixIcon: Icon(LucideIcons.mail, size: 18),
              ),
            ),
            const SizedBox(height: EsaSpace.md),
            TextField(
              controller: _code,
              enabled: !_submitting,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.done,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              maxLength: 6,
              onSubmitted: (_) => _submit(),
              decoration: InputDecoration(
                labelText: '验证码',
                counterText: '',
                suffixIcon: TextButton(
                  onPressed: _sending || _cooldown > 0 ? null : _sendCode,
                  child: Text(
                    _sending
                        ? '发送中'
                        : _cooldown > 0
                        ? '${_cooldown}s'
                        : '发送验证码',
                  ),
                ),
              ),
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
          onPressed: _submitting ? null : () => Navigator.of(context).pop(),
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
              : const Text('确认绑定'),
        ),
      ],
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
