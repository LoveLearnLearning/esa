import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../theme/esa_context.dart';
import '../theme/esa_theme.dart';
import 'esa_markdown.dart';

class LatexInsert {
  const LatexInsert({
    required this.latex,
    required this.display,
    required this.cursorOffset,
  });

  final String latex;
  final bool display;
  final int cursorOffset;
}

class _FormulaTemplate {
  const _FormulaTemplate(this.name, this.latex, this.category, this.keywords);

  final String name;
  final String latex;
  final String category;
  final String keywords;
}

const _cursorMarker = '|cursor|';

const _templates = <_FormulaTemplate>[
  _FormulaTemplate('分数', r'\frac{|cursor|}{}', '常用', 'fraction frac 分式'),
  _FormulaTemplate('平方根', r'\sqrt{|cursor|}', '常用', 'sqrt root 根式'),
  _FormulaTemplate('上标', r'x^{|cursor|}', '常用', 'power superscript 次方'),
  _FormulaTemplate('下标', r'x_{|cursor|}', '常用', 'subscript index'),
  _FormulaTemplate('求和', r'\sum_{i=1}^{n} |cursor|', '常用', 'sum sigma 累加'),
  _FormulaTemplate('极限', r'\lim_{x \to |cursor|} f(x)', '常用', 'limit lim'),
  _FormulaTemplate('积分', r'\int_{a}^{b} |cursor|\,dx', '微积分', 'integral 定积分'),
  _FormulaTemplate(
    '偏导',
    r'\frac{\partial |cursor|}{\partial x}',
    '微积分',
    'partial derivative',
  ),
  _FormulaTemplate('导数', r'\frac{d|cursor|}{dx}', '微积分', 'derivative diff'),
  _FormulaTemplate('二重积分', r'\iint_{D} |cursor|\,dA', '微积分', 'double integral'),
  _FormulaTemplate('向量', r'\vec{|cursor|}', '代数', 'vector arrow'),
  _FormulaTemplate('绝对值', r'\left| |cursor| \right|', '代数', 'absolute norm'),
  _FormulaTemplate(
    '方程组',
    r'\begin{cases}|cursor| \\ \\ \end{cases}',
    '代数',
    'cases equations',
  ),
  _FormulaTemplate('二项式', r'\binom{n}{|cursor|}', '代数', 'binomial choose'),
  _FormulaTemplate(
    '圆括号矩阵',
    r'\begin{pmatrix}|cursor| & \\ \\ & \end{pmatrix}',
    '矩阵',
    'matrix pmatrix',
  ),
  _FormulaTemplate(
    '方括号矩阵',
    r'\begin{bmatrix}|cursor| & \\ \\ & \end{bmatrix}',
    '矩阵',
    'matrix bmatrix',
  ),
  _FormulaTemplate(
    '行列式',
    r'\begin{vmatrix}|cursor| & \\ \\ & \end{vmatrix}',
    '矩阵',
    'det determinant',
  ),
  _FormulaTemplate(
    '希腊字母',
    r'\alpha,\ \beta,\ \gamma,\ |cursor|',
    '符号',
    'greek alpha beta gamma',
  ),
  _FormulaTemplate(
    '集合',
    r'\{x \in \mathbb{R} \mid |cursor|\}',
    '符号',
    'set real belongs',
  ),
  _FormulaTemplate(
    '逻辑关系',
    r'P \Rightarrow Q \Leftrightarrow |cursor|',
    '符号',
    'logic implies iff',
  ),
  _FormulaTemplate('无穷', r'|cursor| \to \infty', '符号', 'infinity'),
  _FormulaTemplate(
    '期望',
    r'\mathbb{E}[|cursor|]',
    '统计',
    'expectation probability',
  ),
  _FormulaTemplate('方差', r'\operatorname{Var}(|cursor|)', '统计', 'variance'),
  _FormulaTemplate(
    '正态分布',
    r'X \sim \mathcal{N}(|cursor|,\sigma^2)',
    '统计',
    'normal distribution',
  ),
  _FormulaTemplate(
    '波函数',
    r'i\hbar\frac{\partial}{\partial t}|cursor|=\hat{H}\psi',
    '物理',
    'schrodinger quantum',
  ),
  _FormulaTemplate(
    '麦克斯韦',
    r'\nabla \cdot \mathbf{E}=\frac{|cursor|}{\varepsilon_0}',
    '物理',
    'maxwell electric',
  ),
];

const _categories = ['常用', '微积分', '代数', '矩阵', '符号', '统计', '物理'];

Future<LatexInsert?> showLatexFormulaPicker(BuildContext context) {
  final compact = MediaQuery.sizeOf(context).width < 680;
  if (compact) {
    return showModalBottomSheet<LatexInsert>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.transparent,
      builder: (context) => const FractionallySizedBox(
        heightFactor: .9,
        child: _FormulaPickerSurface(compact: true),
      ),
    );
  }
  return showDialog<LatexInsert>(
    context: context,
    builder: (context) => const Dialog(
      clipBehavior: Clip.antiAlias,
      child: SizedBox(width: 780, height: 650, child: _FormulaPickerSurface()),
    ),
  );
}

class _FormulaPickerSurface extends StatefulWidget {
  const _FormulaPickerSurface({this.compact = false});

  final bool compact;

  @override
  State<_FormulaPickerSurface> createState() => _FormulaPickerSurfaceState();
}

class _FormulaPickerSurfaceState extends State<_FormulaPickerSurface> {
  final _search = TextEditingController();
  final _editor = TextEditingController();
  final _editorFocus = FocusNode();
  String _category = '常用';
  bool _display = false;

  @override
  void initState() {
    super.initState();
  }

  @override
  void dispose() {
    _search.dispose();
    _editor.dispose();
    _editorFocus.dispose();
    super.dispose();
  }

  List<_FormulaTemplate> get _filtered {
    final query = _search.text.trim().toLowerCase();
    return _templates.where((item) {
      if (query.isEmpty) return item.category == _category;
      return '${item.name} ${item.latex} ${item.keywords}'
          .toLowerCase()
          .contains(query);
    }).toList();
  }

  void _insertTemplate(_FormulaTemplate item) {
    final marker = item.latex.indexOf(_cursorMarker);
    final template = item.latex.replaceFirst(_cursorMarker, '');
    final current = _editor.text;
    final selection = _editor.selection.isValid
        ? _editor.selection
        : TextSelection.collapsed(offset: current.length);
    final start = selection.start.clamp(0, current.length);
    final end = selection.end.clamp(start, current.length);
    final latex = current.replaceRange(start, end, template);
    final templateCursor = marker < 0 ? template.length : marker;
    _editor.value = TextEditingValue(
      text: latex,
      selection: TextSelection.collapsed(offset: start + templateCursor),
    );
    setState(() {});
    _editorFocus.requestFocus();
  }

  void _insert() {
    final latex = _editor.text.trim();
    if (latex.isEmpty) return;
    final rawOffset = _editor.selection.isValid
        ? _editor.selection.extentOffset
        : latex.length;
    Navigator.of(context).pop(
      LatexInsert(
        latex: latex,
        display: _display,
        cursorOffset: rawOffset.clamp(0, latex.length),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Material(
      color: context.scheme.surface,
      child: Column(
        children: [
          _header(context),
          Divider(height: 1, color: context.n.divider),
          Expanded(
            child: Padding(
              padding: EdgeInsets.all(widget.compact ? 14 : 18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _searchField(context),
                  const SizedBox(height: 12),
                  _categoryTabs(context),
                  const SizedBox(height: 12),
                  Expanded(child: _formulaGrid(context)),
                  const SizedBox(height: 12),
                  _editorArea(context),
                ],
              ),
            ),
          ),
          Divider(height: 1, color: context.n.divider),
          _footer(context),
        ],
      ),
    );
  }

  Widget _header(BuildContext context) => SizedBox(
    height: 56,
    child: Padding(
      padding: const EdgeInsets.only(left: 18, right: 8),
      child: Row(
        children: [
          const Icon(LucideIcons.sigma, size: 19, color: EsaColors.accent),
          const SizedBox(width: 10),
          Expanded(
            child: Text('插入 LaTeX 公式', style: context.texts.titleMedium),
          ),
          IconButton(
            tooltip: '关闭',
            onPressed: () => Navigator.of(context).pop(),
            icon: const Icon(LucideIcons.x, size: 19),
          ),
        ],
      ),
    ),
  );

  Widget _searchField(BuildContext context) => TextField(
    key: const ValueKey('latex-search'),
    controller: _search,
    onChanged: (_) => setState(() {}),
    decoration: InputDecoration(
      prefixIcon: const Icon(LucideIcons.search, size: 17),
      hintText: '搜索公式或命令',
      suffixIcon: _search.text.isEmpty
          ? null
          : IconButton(
              tooltip: '清空搜索',
              onPressed: () {
                _search.clear();
                setState(() {});
              },
              icon: const Icon(LucideIcons.x, size: 16),
            ),
    ),
  );

  Widget _categoryTabs(BuildContext context) => SizedBox(
    height: 34,
    child: ListView.separated(
      scrollDirection: Axis.horizontal,
      itemCount: _categories.length,
      separatorBuilder: (_, _) => const SizedBox(width: 6),
      itemBuilder: (context, index) {
        final item = _categories[index];
        final selected = _search.text.isEmpty && item == _category;
        return ChoiceChip(
          label: Text(item),
          selected: selected,
          onSelected: (_) {
            _search.clear();
            setState(() => _category = item);
          },
        );
      },
    ),
  );

  Widget _formulaGrid(BuildContext context) {
    final formulas = _filtered;
    if (formulas.isEmpty) {
      return Center(
        child: Text('没有匹配的公式', style: TextStyle(color: context.n.n600)),
      );
    }
    return GridView.builder(
      itemCount: formulas.length,
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: widget.compact ? 2 : 4,
        crossAxisSpacing: 8,
        mainAxisSpacing: 8,
        mainAxisExtent: 78,
      ),
      itemBuilder: (context, index) {
        final formula = formulas[index];
        final latex = formula.latex.replaceFirst(_cursorMarker, '');
        return InkWell(
          key: ValueKey('latex-template-${formula.name}'),
          onTap: () => _insertTemplate(formula),
          borderRadius: BorderRadius.circular(EsaRadii.toolCard),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 8),
            decoration: BoxDecoration(
              color: context.n.n100,
              border: Border.all(color: context.n.divider),
              borderRadius: BorderRadius.circular(EsaRadii.toolCard),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  formula.name,
                  style: context.texts.labelSmall?.copyWith(fontSize: 11),
                ),
                const Spacer(),
                Text(
                  latex,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontFamily: 'JetBrainsMono',
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _editorArea(BuildContext context) {
    final editor = TextField(
      key: const ValueKey('latex-editor'),
      controller: _editor,
      focusNode: _editorFocus,
      maxLines: widget.compact ? 4 : 7,
      minLines: widget.compact ? 3 : 5,
      onChanged: (_) => setState(() {}),
      style: const TextStyle(fontFamily: 'JetBrainsMono', fontSize: 13),
      decoration: const InputDecoration(
        labelText: 'LaTeX 公式编辑区',
        hintText: r'点击上方模板连续插入，或直接输入，例如：\frac{a}{b}',
      ),
    );
    final preview = Container(
      height: widget.compact ? 54 : 78,
      padding: const EdgeInsets.all(10),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: context.scheme.surface,
        borderRadius: BorderRadius.circular(6),
      ),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: EsaMarkdown(
          data: _display
              ? '\$\$\n${_editor.text}\n\$\$'
              : '\$${_editor.text}\$',
        ),
      ),
    );
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.n.n100,
        border: Border.all(color: context.n.divider),
        borderRadius: BorderRadius.circular(EsaRadii.toolCard),
      ),
      child: widget.compact
          ? Column(children: [editor, const SizedBox(height: 8), preview])
          : Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: editor),
                const SizedBox(width: 12),
                Expanded(child: preview),
              ],
            ),
    );
  }

  Widget _footer(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
    child: Row(
      children: [
        SegmentedButton<bool>(
          segments: const [
            ButtonSegment(value: false, label: Text('行内公式')),
            ButtonSegment(value: true, label: Text('独立公式')),
          ],
          selected: {_display},
          onSelectionChanged: (value) => setState(() => _display = value.first),
          showSelectedIcon: false,
        ),
        const Spacer(),
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        const SizedBox(width: 8),
        FilledButton.icon(
          key: const ValueKey('insert-latex'),
          onPressed: _editor.text.trim().isEmpty ? null : _insert,
          icon: const Icon(LucideIcons.cornerDownLeft, size: 16),
          label: const Text('插入到输入框'),
        ),
      ],
    ),
  );
}
