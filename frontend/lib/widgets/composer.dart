// 输入区 —— 固定底部 顶部 1px 分割线 内容最大宽 820
// Enter 发送 Shift+Enter 换行 发送按钮胶囊 无内容或生成中时禁用

import 'dart:async';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../models/task_mode.dart';
import '../models/models.dart';
import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import '../utils/paste_attachment.dart';
import 'esa_markdown.dart';
import 'latex_formula_picker.dart';

class Composer extends StatefulWidget {
  const Composer({
    super.key,
    required this.busy,
    required this.onSend,
    this.taskMode,
    this.onClearTaskMode,
    this.conversationId,
    this.onUploadAttachment,
    this.onRemoveAttachment,
    this.onSendWithAttachment,
    this.onOpenCodeEditor,
    this.onCodeBlockChanged,
    this.onSelectedAttachmentsChanged,
    this.courseNames = const [],
    this.toolsOn = true,
    this.onToolsOnChanged,
  });

  final bool busy;
  final void Function(String text, bool markdown) onSend;
  final TaskMode? taskMode;
  final VoidCallback? onClearTaskMode;
  final String? conversationId;
  final Future<DocumentAttachment> Function(
    String filename,
    Stream<List<int>> stream,
    int length,
  )?
  onUploadAttachment;
  final Future<void> Function(
    DocumentAttachment attachment,
    String conversationId,
  )?
  onRemoveAttachment;
  final void Function(
    String text,
    bool markdown,
    DocumentAttachment attachment,
  )?
  onSendWithAttachment;
  final void Function(String blockId, String code, String language)?
  onOpenCodeEditor;
  final void Function(String blockId, String code, String language)?
  onCodeBlockChanged;
  final ValueChanged<List<DocumentAttachment>>? onSelectedAttachmentsChanged;
  final List<String> courseNames;
  final bool toolsOn;
  final ValueChanged<bool>? onToolsOnChanged;

  @override
  State<Composer> createState() => ComposerState();
}

class ComposerState extends State<Composer> {
  static const _newConversationDraftKey = '__new_conversation__';

  final _controller = TextEditingController();
  final _focus = FocusNode();
  final Map<String, _ComposerDraft> _drafts = {};
  DocumentAttachment? _attachment;
  String? _attachmentConversationId;
  bool _uploadingAttachment = false;
  bool _markdownMode = false;
  bool _memoryEnabled = true;
  String _resourceScope = '课程资料';
  String? _selectedCourse;
  AttachmentPasteListener? _pasteListener;

  List<_ComposerCodeBlock> get _codeBlocks =>
      _parseComposerCodeBlocks(_controller.text);

  void _handleTextChanged(String value) {
    _saveCurrentDraft();
    setState(() {});
    final callback = widget.onCodeBlockChanged;
    if (callback == null) return;
    final blocks = _parseComposerCodeBlocks(value);
    for (var index = 0; index < blocks.length; index++) {
      final block = blocks[index];
      callback(
        'composer:$index',
        value.substring(block.contentStart, block.contentEnd).trimRight(),
        block.language,
      );
    }
  }

  @override
  void initState() {
    super.initState();
    _pasteListener = listenForPastedAttachment(
      focusNode: _focus,
      onAttachment: _uploadPastedAttachment,
    );
  }

  void replaceCodeBlock(String blockId, String code, {String? language}) {
    final index = int.tryParse(blockId.split(':').last);
    final blocks = _codeBlocks;
    if (index == null || index < 0 || index >= blocks.length) return;
    final block = blocks[index];
    final normalized = code.trimRight();
    final replacement = normalized.isEmpty ? '' : '$normalized\n';
    final nextText = _controller.text.replaceRange(
      block.contentStart,
      block.contentEnd,
      replacement,
    );
    _controller.value = TextEditingValue(
      text: nextText,
      selection: TextSelection.collapsed(
        offset: block.contentStart + replacement.length,
      ),
    );
    _saveCurrentDraft(markdownMode: true);
    setState(() => _markdownMode = true);
  }

  @override
  void dispose() {
    _pasteListener?.dispose();
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  bool get _canSend =>
      !widget.busy &&
      !_uploadingAttachment &&
      (_controller.text.trim().isNotEmpty || _attachment != null);

  @override
  void didUpdateWidget(covariant Composer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.conversationId == widget.conversationId) return;

    _drafts[_draftKey(oldWidget.conversationId)] = _currentDraft();
    final nextKey = _draftKey(widget.conversationId);
    // Pressing "new conversation" must open a genuinely empty composer.
    if (widget.conversationId == null && oldWidget.conversationId != null) {
      _drafts.remove(nextKey);
    }
    final nextDraft = _drafts[nextKey] ?? const _ComposerDraft();
    _controller.value = TextEditingValue(
      text: nextDraft.text,
      selection: TextSelection.collapsed(
        offset: nextDraft.selectionOffset.clamp(0, nextDraft.text.length),
      ),
    );
    _markdownMode = nextDraft.markdownMode;
    if (_attachment != null) _removeAttachment();
    widget.onSelectedAttachmentsChanged?.call(const []);
  }

  String _draftKey(String? conversationId) =>
      conversationId ?? _newConversationDraftKey;

  _ComposerDraft _currentDraft({bool? markdownMode}) {
    final selection = _controller.selection;
    final offset = selection.isValid
        ? selection.extentOffset.clamp(0, _controller.text.length)
        : _controller.text.length;
    return _ComposerDraft(
      text: _controller.text,
      selectionOffset: offset,
      markdownMode: markdownMode ?? _markdownMode,
    );
  }

  void _saveCurrentDraft({bool? markdownMode}) {
    _drafts[_draftKey(widget.conversationId)] = _currentDraft(
      markdownMode: markdownMode,
    );
  }

  /// 手机浏览器上软键盘行为与桌面不同：软键盘的回车会以 Enter KeyEvent
  /// 到达（且没有 Shift 可按），应当换行而不是发送；发送后应收起键盘看
  /// 回答。原生 App 的软键盘回车不走 KeyEvent，不需要该分支。
  bool get _mobileBrowser =>
      kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);

  void _send() {
    if (!_canSend) return;
    final text = _controller.text.trim().isEmpty
        ? '请分析这个附件，并给出结构化结论。'
        : _controller.text;
    final attachment = _attachment;
    if (attachment != null && widget.onSendWithAttachment != null) {
      widget.onSendWithAttachment!(text, _markdownMode, attachment);
    } else {
      widget.onSend(text, _markdownMode);
    }
    _controller.clear();
    _drafts[_draftKey(widget.conversationId)] = const _ComposerDraft();
    setState(() {
      _attachment = null;
      _attachmentConversationId = null;
    });
    widget.onSelectedAttachmentsChanged?.call(const []);
    if (_mobileBrowser) {
      // 收起键盘，把屏幕留给流式回答
      _focus.unfocus();
    } else {
      _focus.requestFocus();
    }
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is KeyDownEvent &&
        event.logicalKey == LogicalKeyboardKey.enter &&
        !HardwareKeyboard.instance.isShiftPressed) {
      // 手机浏览器软键盘的回车插入换行；发送只走按钮
      if (_mobileBrowser) return KeyEventResult.ignored;
      final composing = _controller.value.composing;
      if (composing.isValid && !composing.isCollapsed) {
        // Enter is being used to confirm an IME candidate (for example,
        // committing Latin text from a Chinese input method). Let the text
        // input system handle it instead of treating it as message submit.
        return KeyEventResult.ignored;
      }
      _send();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    final narrow = MediaQuery.sizeOf(context).width < 600;
    final inputStyle = (context.texts.bodyLarge ?? const TextStyle()).copyWith(
      color: context.scheme.onSurface,
      fontSize: 15,
      height: 1.45,
    );

    final codeBlocks = _codeBlocks;
    final showMarkdownPreview =
        _controller.text.isNotEmpty && (_markdownMode || codeBlocks.isNotEmpty);
    return Container(
      padding: EdgeInsets.fromLTRB(narrow ? 0 : 18, 12, narrow ? 0 : 18, 14),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (widget.taskMode != null) ...[
                _taskModeCard(context, widget.taskMode!),
                const SizedBox(height: EsaSpace.sm),
              ],
              if (_attachment != null || _uploadingAttachment) ...[
                _attachmentChip(context),
                const SizedBox(height: EsaSpace.sm),
              ],
              Container(
                decoration: BoxDecoration(
                  color: context.n.n100,
                  border: Border.all(color: context.n.divider),
                  borderRadius: BorderRadius.circular(EsaRadii.composer),
                ),
                padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _contextControls(context),
                    Padding(
                      padding: const EdgeInsets.only(top: 10, bottom: 10),
                      child: Divider(height: 1, color: context.n.divider),
                    ),
                    if (showMarkdownPreview) ...[
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxHeight: 180),
                        child: SingleChildScrollView(
                          child: EsaMarkdown(
                            data: _controller.text,
                            codeBlockPrefix: 'composer',
                            onOpenCodeEditorWithId: widget.onOpenCodeEditor,
                          ),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 10),
                        child: Divider(height: 1, color: context.n.divider),
                      ),
                    ],
                    Focus(
                      onKeyEvent: _onKey,
                      child: ListenableBuilder(
                        listenable: _focus,
                        builder: (context, _) => TextField(
                          key: const ValueKey('composer-input'),
                          controller: _controller,
                          focusNode: _focus,
                          minLines: narrow ? 1 : 2,
                          maxLines: 6,
                          onChanged: _handleTextChanged,
                          style: inputStyle,
                          textAlignVertical: TextAlignVertical.top,
                          cursorWidth: 2,
                          decoration: InputDecoration(
                            isCollapsed: true,
                            filled: false,
                            border: InputBorder.none,
                            enabledBorder: InputBorder.none,
                            focusedBorder: InputBorder.none,
                            contentPadding: EdgeInsets.zero,
                            // Flutter Web 会让空字段的光标和 hint 从同一个
                            // x 坐标开始绘制，光标会盖住首字形成“重影”。
                            hintText: _focus.hasFocus
                                ? null
                                : widget.taskMode?.hint ?? '向 ESA 提问，或输入学习任务……',
                            hintStyle: inputStyle.copyWith(
                              color: context.n.n600,
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: EsaSpace.sm),
                    LayoutBuilder(
                      builder: (context, constraints) {
                        final compactActions =
                            narrow || constraints.maxWidth < 710;
                        if (compactActions) {
                          return Row(
                            children: [
                              Expanded(child: _attachButton(context)),
                              const SizedBox(width: 4),
                              Expanded(child: _markdownButton(context)),
                              const SizedBox(width: 4),
                              Expanded(child: _formulaButton(context)),
                              const SizedBox(width: 8),
                              _sendButton(context),
                            ],
                          );
                        }
                        return Row(
                          children: [
                            _attachButton(context),
                            const SizedBox(width: EsaSpace.sm),
                            _markdownButton(context),
                            const SizedBox(width: EsaSpace.sm),
                            _formulaButton(context),
                            const SizedBox(width: EsaSpace.md),
                            Text(
                              'Shift + Enter 换行 · Enter 发送',
                              style: TextStyle(
                                fontSize: 11.5,
                                color: context.n.n600,
                              ),
                            ),
                            const Spacer(),
                            _sendButton(context),
                          ],
                        );
                      },
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _attachmentChip(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: context.n.n100,
          border: Border.all(color: context.n.divider),
          borderRadius: BorderRadius.circular(EsaRadii.pill),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(LucideIcons.file, size: 14, color: context.n.n600),
            const SizedBox(width: 8),
            if (_uploadingAttachment) ...[
              const SizedBox.square(
                dimension: 14,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              const SizedBox(width: 8),
              const Text('正在保存附件…'),
            ] else ...[
              Flexible(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _attachment!.filename,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 12.5,
                        color: context.scheme.onSurface,
                      ),
                    ),
                    Text(
                      _attachment!.mode == 'pending'
                          ? _attachment!.modeLabel
                          : '${_attachment!.modeLabel} · ${_attachment!.elementCount} 个元素',
                      style: TextStyle(fontSize: 10.5, color: context.n.n600),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(width: 8),
            if (!_uploadingAttachment)
              GestureDetector(
                onTap: _removeAttachment,
                child: Icon(LucideIcons.x, size: 14, color: context.n.n600),
              ),
          ],
        ),
      ),
    );
  }

  Widget _taskModeCard(BuildContext context, TaskMode mode) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: EsaColors.accent.withValues(alpha: 0.08),
        border: Border.all(color: EsaColors.accent.withValues(alpha: 0.45)),
        borderRadius: BorderRadius.circular(EsaRadii.toolCard),
      ),
      child: Row(
        children: [
          const Icon(LucideIcons.sparkles, size: 15, color: EsaColors.accent),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(mode.title, style: context.texts.titleMedium),
                Text(
                  mode.description,
                  style: TextStyle(fontSize: 11.5, color: context.n.n600),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: '退出任务模式',
            onPressed: widget.onClearTaskMode,
            icon: const Icon(LucideIcons.x, size: 16),
          ),
        ],
      ),
    );
  }

  Widget _attachButton(BuildContext context) {
    return _composerActionButton(
      context,
      onPressed: widget.busy || _uploadingAttachment ? null : _pickAttachment,
      icon: const Icon(LucideIcons.paperclip, size: 15),
      label: const Text('附件'),
    );
  }

  Future<void> _pickAttachment() async {
    if (widget.onUploadAttachment == null) return;
    try {
      final result = await FilePicker.pickFiles(
        type: FileType.custom,
        allowedExtensions: const [
          'pdf',
          'docx',
          'pptx',
          'xlsx',
          'png',
          'jpg',
          'jpeg',
          'webp',
          'bmp',
          'gif',
          'tif',
          'tiff',
        ],
        withData: false,
        // file_picker 的 Web 端在 withData=false 时不会填充 bytes；此时
        // 再通过 file.xFile.openRead() 会在插件内部对 bytes 使用 `!` 并崩溃。
        // 直接请求分块流既能避免空值，也不会把大附件一次性读入内存。
        withReadStream: kIsWeb,
        cancelUploadOnWindowBlur: false,
      );
      final file = result?.files.singleOrNull;
      if (file == null || !mounted) return;
      final stream = file.readStream ?? file.xFile.openRead();
      await _uploadAttachment(file.name, stream, file.size);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('附件解析失败：$error')));
    }
  }

  Future<void> _uploadPastedAttachment(PastedAttachment file) =>
      _uploadAttachment(
        file.filename,
        Stream<List<int>>.value(file.bytes),
        file.bytes.length,
      );

  Future<void> _uploadAttachment(
    String filename,
    Stream<List<int>> stream,
    int length,
  ) async {
    if (widget.onUploadAttachment == null ||
        _uploadingAttachment ||
        widget.busy) {
      return;
    }
    if (length > 200 * 1024 * 1024) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('文件不能超过 200 MB')));
      }
      return;
    }
    setState(() => _uploadingAttachment = true);
    try {
      final attachment = await widget.onUploadAttachment!(
        filename,
        stream,
        length,
      );
      if (!mounted) return;
      setState(() {
        _attachment = attachment;
        _attachmentConversationId = widget.conversationId;
      });
      widget.onSelectedAttachmentsChanged?.call([attachment]);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('附件解析失败：$error')));
    } finally {
      if (mounted) setState(() => _uploadingAttachment = false);
    }
  }

  void _removeAttachment() {
    final attachment = _attachment;
    final conversationId = _attachmentConversationId;
    setState(() {
      _attachment = null;
      _attachmentConversationId = null;
    });
    widget.onSelectedAttachmentsChanged?.call(const []);
    if (attachment != null &&
        conversationId != null &&
        widget.onRemoveAttachment != null) {
      unawaited(widget.onRemoveAttachment!(attachment, conversationId));
    }
  }

  Widget _markdownButton(BuildContext context) {
    final active = _markdownMode;
    return Tooltip(
      message: active ? '退出 Markdown 输入' : 'Markdown 输入',
      child: _composerActionButton(
        context,
        onPressed: () => setState(() {
          _markdownMode = !_markdownMode;
          _saveCurrentDraft();
        }),
        icon: const Icon(LucideIcons.fileCode2, size: 15),
        label: const Text('Markdown'),
        active: active,
      ),
    );
  }

  Widget _composerActionButton(
    BuildContext context, {
    required VoidCallback? onPressed,
    required Widget icon,
    required Widget label,
    bool active = false,
  }) => OutlinedButton(
    onPressed: onPressed,
    style: OutlinedButton.styleFrom(
      minimumSize: const Size(0, 32),
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 7),
      foregroundColor: active ? EsaColors.accent : context.n.n700,
      side: BorderSide(color: active ? EsaColors.accent : context.n.divider),
      textStyle: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w500),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    ),
    child: FittedBox(
      fit: BoxFit.scaleDown,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [icon, const SizedBox(width: 4), label],
      ),
    ),
  );

  Widget _sendButton(BuildContext context) {
    final enabled = _canSend;
    return Semantics(
      button: true,
      label: '发送',
      enabled: enabled,
      child: Tooltip(
        message: '发送',
        child: Opacity(
          opacity: enabled ? 1 : 0.45,
          child: Material(
            color: EsaColors.accent,
            borderRadius: BorderRadius.circular(10),
            child: InkWell(
              onTap: enabled ? _send : null,
              borderRadius: BorderRadius.circular(10),
              child: Container(
                width: 42,
                height: 42,
                alignment: Alignment.center,
                child: const Icon(
                  LucideIcons.send,
                  size: 19,
                  color: EsaColors.onAccent,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _formulaButton(BuildContext context) => Tooltip(
    message: '插入公式',
    child: _composerActionButton(
      context,
      onPressed: widget.busy ? null : _openFormulaPicker,
      icon: const Icon(LucideIcons.sigma, size: 15),
      label: const Text('LaTeX'),
    ),
  );

  Future<void> _openFormulaPicker() async {
    final beforeSelection = _controller.selection;
    final result = await showLatexFormulaPicker(context);
    if (result == null || !mounted) return;

    final text = _controller.text;
    final selection = beforeSelection.isValid
        ? beforeSelection
        : TextSelection.collapsed(offset: text.length);
    final start = selection.start.clamp(0, text.length);
    final end = selection.end.clamp(start, text.length);
    final prefix = result.display ? '\n\$\$\n' : '\$';
    final suffix = result.display ? '\n\$\$\n' : '\$';
    final insertion = '$prefix${result.latex}$suffix';
    final nextText = text.replaceRange(start, end, insertion);
    final cursor = start + prefix.length + result.cursorOffset;
    _controller.value = TextEditingValue(
      text: nextText,
      selection: TextSelection.collapsed(offset: cursor),
    );
    _saveCurrentDraft(markdownMode: true);
    setState(() => _markdownMode = true);
    _focus.requestFocus();
  }

  Widget _contextControls(BuildContext context) {
    final courses = widget.courseNames.map((item) => item.trim()).toSet()
      ..removeWhere((item) => item.isEmpty);
    final course =
        _selectedCourse ?? (courses.isEmpty ? '未选择课程' : courses.first);
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _contextMenu(
            context,
            label: '当前课程：$course',
            values: courses.isEmpty ? const ['未选择课程'] : courses.toList(),
            onSelected: (value) => setState(() => _selectedCourse = value),
          ),
          const SizedBox(width: 6),
          _contextMenu(
            context,
            label: '资料库：$_resourceScope',
            values: const ['课程资料', '全部资料'],
            onSelected: (value) => setState(() => _resourceScope = value),
          ),
          const SizedBox(width: 6),
          _contextMenu(
            context,
            label: '长期记忆：${_memoryEnabled ? '开启' : '关闭'}',
            values: const ['开启', '关闭'],
            onSelected: (value) =>
                setState(() => _memoryEnabled = value == '开启'),
          ),
          const SizedBox(width: 6),
          _contextMenu(
            context,
            label: '工具：${widget.toolsOn ? '自动' : '关闭'}',
            values: const ['自动', '关闭'],
            onSelected: (value) => widget.onToolsOnChanged?.call(value == '自动'),
          ),
        ],
      ),
    );
  }

  Widget _contextMenu(
    BuildContext context, {
    required String label,
    required List<String> values,
    required ValueChanged<String> onSelected,
  }) => PopupMenuButton<String>(
    onSelected: onSelected,
    itemBuilder: (context) => [
      for (final value in values)
        PopupMenuItem<String>(value: value, child: Text(value)),
    ],
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label, style: TextStyle(fontSize: 11.5, color: context.n.n700)),
          const SizedBox(width: 4),
          Icon(LucideIcons.chevronDown, size: 13, color: context.n.n600),
        ],
      ),
    ),
  );

  Future<void> pickAttachment() => _pickAttachment();

  Future<void> removeSelectedAttachment() async {
    if (_attachment != null) _removeAttachment();
  }
}

class _ComposerDraft {
  const _ComposerDraft({
    this.text = '',
    this.selectionOffset = 0,
    this.markdownMode = false,
  });

  final String text;
  final int selectionOffset;
  final bool markdownMode;
}

class _ComposerCodeBlock {
  const _ComposerCodeBlock({
    required this.contentStart,
    required this.contentEnd,
    required this.language,
  });

  final int contentStart;
  final int contentEnd;
  final String language;
}

List<_ComposerCodeBlock> _parseComposerCodeBlocks(String source) {
  final blocks = <_ComposerCodeBlock>[];
  final lines = RegExp(r'.*(?:\n|$)').allMatches(source).toList();
  String? marker;
  var language = 'plaintext';
  var contentStart = 0;
  for (final match in lines) {
    final raw = match.group(0) ?? '';
    if (raw.isEmpty) continue;
    final line = raw.endsWith('\n') ? raw.substring(0, raw.length - 1) : raw;
    final trimmed = line.trimLeft();
    if (marker == null) {
      final opening = RegExp(r'^(`{3,}|~{3,})').firstMatch(trimmed);
      if (opening == null) continue;
      marker = opening.group(1)!;
      final info = trimmed.substring(opening.end).trim();
      language = info.isEmpty ? 'plaintext' : info.split(RegExp(r'\s+')).first;
      contentStart = match.end;
      continue;
    }
    final closing = RegExp(
      '^${RegExp.escape(marker[0])}{${marker.length},}\\s*\$',
    );
    if (!closing.hasMatch(trimmed)) continue;
    blocks.add(
      _ComposerCodeBlock(
        contentStart: contentStart,
        contentEnd: match.start,
        language: language,
      ),
    );
    marker = null;
    language = 'plaintext';
  }
  return blocks;
}
