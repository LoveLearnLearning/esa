(function () {
  'use strict';

  const editors = new Map();
  const cancelled = new Set();
  let loaderPromise = null;
  let editorFontPromise = null;
  let providersReady = false;

  const supportedLanguages = [
    'plaintext',
    'python',
    'javascript',
    'typescript',
    'dart',
    'java',
    'cpp',
    'c',
    'csharp',
    'go',
    'rust',
    'html',
    'css',
    'json',
    'yaml',
    'markdown',
    'shell',
    'sql',
  ];

  const keywords = new Set((
    'abstract as async await break case catch class const continue default '
    + 'def delete do else enum export extends false final finally for from '
    + 'func function if implements import in instanceof interface is let '
    + 'new null package pass private protected public raise readonly return '
    + 'static struct super switch this throw trait true try type typeof var '
    + 'void while with yield fn fun mut self Self int long short float double '
    + 'bool boolean char string String num dynamic Object List Map Set Future '
    + 'Promise undefined keyof namespace module require of'
  ).split(/\s+/));

  const themeBackgrounds = {
    'vs': '#ffffff',
    'vs-dark': '#1e1e1e',
    'esa-one-dark': '#282c34',
    'esa-dracula': '#282a36',
    'esa-monokai': '#272822',
    'esa-github-dark': '#0d1117',
    'esa-github-light': '#ffffff',
    'esa-solarized-dark': '#002b36',
    'esa-solarized-light': '#fdf6e3',
    'hc-black': '#000000',
    'hc-light': '#ffffff',
  };

  // This script loads before Flutter, so this capture listener wins over
  // Flutter's global focus-traversal shortcut when Tab is pressed in Monaco.
  window.addEventListener(
    'keydown',
    (event) => {
      if (event.key !== 'Tab' && event.keyCode !== 9) return;
      for (const record of editors.values()) {
        if (!record.host.contains(event.target)) continue;
        event.preventDefault();
        event.stopImmediatePropagation();
        record.applyIndent(event.shiftKey);
        return;
      }
    },
    true,
  );

  function loadEditorFont() {
    if (!document.fonts || !document.fonts.load) return Promise.resolve();
    if (editorFontPromise) return editorFontPromise;

    editorFontPromise = Promise.all([
      document.fonts.load(
        '400 14px "JetBrains Mono"',
        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789(){}[]',
      ),
      document.fonts.ready,
    ]).catch((error) => {
      console.warn('JetBrains Mono failed to preload', error);
    });
    return editorFontPromise;
  }

  function loadMonaco() {
    if (window.monaco) return Promise.resolve(window.monaco);
    if (loaderPromise) return loaderPromise;

    loaderPromise = new Promise((resolve, reject) => {
      const start = () => {
        window.require.config({ paths: { vs: 'monaco/vs' } });
        window.require(
          ['vs/editor/editor.main'],
          () => resolve(window.monaco),
          reject,
        );
      };
      if (window.require && window.require.config) {
        start();
        return;
      }
      const script = document.createElement('script');
      script.src = 'monaco/vs/loader.js';
      script.onload = start;
      script.onerror = reject;
      document.head.appendChild(script);
    });
    return loaderPromise;
  }

  function defineThemes(monaco) {
    const define = (name, base, background, foreground, rules, colors = {}) => {
      monaco.editor.defineTheme(name, {
        base,
        inherit: true,
        rules,
        colors: {
          'editor.background': background,
          'editor.foreground': foreground,
          'editorLineNumber.foreground': `${foreground}66`,
          'editorLineNumber.activeForeground': foreground,
          'editor.selectionBackground': base === 'vs' ? '#add6ff' : '#264f78',
          'editor.inactiveSelectionBackground': base === 'vs' ? '#e5ebf1' : '#3a3d41',
          'editorCursor.foreground': foreground,
          ...colors,
        },
      });
    };

    define('esa-one-dark', 'vs-dark', '#282c34', '#abb2bf', [
      { token: 'comment', foreground: '5c6370', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'c678dd' },
      { token: 'string', foreground: '98c379' },
      { token: 'number', foreground: 'd19a66' },
      { token: 'type', foreground: 'e5c07b' },
      { token: 'function', foreground: '61afef' },
    ]);
    define('esa-dracula', 'vs-dark', '#282a36', '#f8f8f2', [
      { token: 'comment', foreground: '6272a4', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'ff79c6' },
      { token: 'string', foreground: 'f1fa8c' },
      { token: 'number', foreground: 'bd93f9' },
      { token: 'type', foreground: '8be9fd', fontStyle: 'italic' },
      { token: 'function', foreground: '50fa7b' },
    ], { 'editor.selectionBackground': '#44475a' });
    define('esa-monokai', 'vs-dark', '#272822', '#f8f8f2', [
      { token: 'comment', foreground: '75715e', fontStyle: 'italic' },
      { token: 'keyword', foreground: 'f92672' },
      { token: 'string', foreground: 'e6db74' },
      { token: 'number', foreground: 'ae81ff' },
      { token: 'type', foreground: '66d9ef', fontStyle: 'italic' },
      { token: 'function', foreground: 'a6e22e' },
    ]);
    define('esa-github-dark', 'vs-dark', '#0d1117', '#e6edf3', [
      { token: 'comment', foreground: '8b949e' },
      { token: 'keyword', foreground: 'ff7b72' },
      { token: 'string', foreground: 'a5d6ff' },
      { token: 'number', foreground: '79c0ff' },
      { token: 'type', foreground: 'ffa657' },
      { token: 'function', foreground: 'd2a8ff' },
    ], { 'editor.selectionBackground': '#264f78' });
    define('esa-github-light', 'vs', '#ffffff', '#1f2328', [
      { token: 'comment', foreground: '6e7781' },
      { token: 'keyword', foreground: 'cf222e' },
      { token: 'string', foreground: '0a3069' },
      { token: 'number', foreground: '0550ae' },
      { token: 'type', foreground: '953800' },
      { token: 'function', foreground: '8250df' },
    ]);
    define('esa-solarized-dark', 'vs-dark', '#002b36', '#839496', [
      { token: 'comment', foreground: '586e75', fontStyle: 'italic' },
      { token: 'keyword', foreground: '859900' },
      { token: 'string', foreground: '2aa198' },
      { token: 'number', foreground: 'd33682' },
      { token: 'type', foreground: 'b58900' },
      { token: 'function', foreground: '268bd2' },
    ]);
    define('esa-solarized-light', 'vs', '#fdf6e3', '#657b83', [
      { token: 'comment', foreground: '93a1a1', fontStyle: 'italic' },
      { token: 'keyword', foreground: '859900' },
      { token: 'string', foreground: '2aa198' },
      { token: 'number', foreground: 'd33682' },
      { token: 'type', foreground: 'b58900' },
      { token: 'function', foreground: '268bd2' },
    ]);
  }

  function completionRange(model, position) {
    const word = model.getWordUntilPosition(position);
    return {
      startLineNumber: position.lineNumber,
      endLineNumber: position.lineNumber,
      startColumn: word.startColumn,
      endColumn: word.endColumn,
    };
  }

  function documentSymbols(monaco, model, position) {
    const source = model.getValue();
    const symbols = new Map();
    const kinds = monaco.languages.CompletionItemKind;
    const add = (label, kind, detail) => {
      if (!label || !/^[A-Za-z_$][\w$]*$/.test(label) || keywords.has(label)) {
        return;
      }
      const key = `${kind}:${label}`;
      if (!symbols.has(key)) symbols.set(key, { label, kind, detail });
    };
    const addParameters = (raw) => {
      for (const entry of raw.split(',')) {
        const withoutDefault = entry.split('=')[0].trim();
        if (!withoutDefault) continue;
        const beforeType = withoutDefault.includes(':')
          ? withoutDefault.split(':')[0]
          : withoutDefault;
        const names = beforeType.match(/[A-Za-z_$][\w$]*/g) || [];
        const candidates = names.filter((name) => !keywords.has(name));
        if (candidates.length > 0) {
          add(candidates[candidates.length - 1], kinds.Variable, '参数');
        }
      }
    };
    const scan = (expression, visit) => {
      expression.lastIndex = 0;
      let match;
      while ((match = expression.exec(source)) !== null) visit(match);
    };

    scan(/\b(?:class|interface|enum|struct|trait|type)\s+([A-Za-z_$][\w$]*)/g,
      (match) => add(match[1], kinds.Class, '当前文件中的类或类型'));
    scan(/\b(?:def|function|func|fn|fun)\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)/g,
      (match) => {
        add(match[1], kinds.Function, '当前文件中的函数');
        addParameters(match[2]);
      });
    scan(/\b(?:const|let|var|final)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>/g,
      (match) => {
        add(match[1], kinds.Function, '当前文件中的函数');
        addParameters(match[2]);
      });
    scan(/^\s*(?:(?:public|private|protected|static|async|export|external|override|virtual|inline|synchronized)\s+)*(?:[\w$<>\[\],.?]+\s+)+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?:\{|=>|:|throws\b)/gm,
      (match) => {
        add(match[1], kinds.Function, '当前文件中的函数或方法');
        addParameters(match[2]);
      });

    scan(/\b(?:const|let|var|final|late|auto)\s+(?:[A-Za-z_$][\w$<>\[\],.?]*\s+)?([A-Za-z_$][\w$]*)/g,
      (match) => add(match[1], kinds.Variable, '当前文件中的变量'));
    scan(/^\s*(?:(?:public|private|protected|static|readonly|volatile)\s+)*(?:int|long|short|float|double|bool|boolean|char|string|String|num|dynamic|Object|List|Map|Set|Future|Promise)(?:<[^;=\n]+>)?\s+([A-Za-z_$][\w$]*)/gm,
      (match) => add(match[1], kinds.Variable, '当前文件中的变量'));
    scan(/^\s*([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=(?!=)/gm,
      (match) => add(match[1], kinds.Variable, '当前文件中的变量'));
    scan(/\bfor\s*(?:\(|)\s*(?:const|let|var|final)?\s*([A-Za-z_$][\w$]*)\s+(?:in|of)\b/g,
      (match) => add(match[1], kinds.Variable, '循环变量'));

    scan(/^\s*import\s+([^\n;]+)/gm, (match) => {
      const clause = match[1].replace(/\s+from\s+.+$/, '').trim();
      for (const part of clause.replace(/[{}]/g, '').split(',')) {
        const value = part.trim();
        if (!value || /^['\"]/.test(value)) continue;
        const alias = value.match(/\bas\s+([A-Za-z_$][\w$]*)$/)?.[1];
        const name = alias || value.match(/[A-Za-z_$][\w$]*/)?.[0];
        add(name, kinds.Module, '导入符号');
      }
    });
    scan(/^\s*from\s+\S+\s+import\s+([^\n;]+)/gm, (match) => {
      for (const part of match[1].replace(/[()]/g, '').split(',')) {
        const value = part.trim();
        const alias = value.match(/\bas\s+([A-Za-z_$][\w$]*)$/)?.[1];
        add(alias || value.match(/[A-Za-z_$][\w$]*/)?.[0], kinds.Module, '导入符号');
      }
    });

    const range = completionRange(model, position);
    return [...symbols.values()].map((symbol) => ({
      ...symbol,
      insertText: symbol.label,
      range,
      sortText: `0-${symbol.label.toLowerCase()}`,
    }));
  }

  function registerCompletions(monaco) {
    if (providersReady) return;
    providersReady = true;

    defineThemes(monaco);

    const snippets = {
      python: [
        ['def', 'def ${1:name}(${2:args}):\n    ${0:pass}', '定义函数'],
        ['class', 'class ${1:Name}:\n    def __init__(self, ${2:args}):\n        ${0:pass}', '定义类'],
        ['for', 'for ${1:item} in ${2:items}:\n    ${0:pass}', 'for 循环'],
        ['ifmain', "if __name__ == '__main__':\n    ${0:main()}", 'Python 入口'],
      ],
      dart: [
        ['main', 'void main() {\n  ${0}\n}', 'Dart 入口'],
        ['class', 'class ${1:Name} {\n  ${0}\n}', '定义类'],
        ['future', 'Future<${1:void}> ${2:name}() async {\n  ${0}\n}', '异步函数'],
      ],
      java: [
        ['main', 'public static void main(String[] args) {\n    ${0}\n}', 'Java 入口'],
        ['class', 'public class ${1:Name} {\n    ${0}\n}', '定义类'],
      ],
      cpp: [
        ['main', 'int main() {\n    ${0}\n    return 0;\n}', 'C++ 入口'],
        ['for', 'for (${1:int i = 0}; ${2:i < n}; ${3:++i}) {\n    ${0}\n}', 'for 循环'],
      ],
      go: [
        ['main', 'package main\n\nfunc main() {\n\t${0}\n}', 'Go 入口'],
        ['func', 'func ${1:name}(${2}) ${3:error} {\n\t${0}\n}', '定义函数'],
      ],
      rust: [
        ['main', 'fn main() {\n    ${0}\n}', 'Rust 入口'],
        ['fn', 'fn ${1:name}(${2}) -> ${3:Result<(), Error>} {\n    ${0}\n}', '定义函数'],
      ],
      sql: [
        ['select', 'SELECT ${1:*}\nFROM ${2:table}\nWHERE ${0:condition};', 'SELECT 查询'],
        ['insert', 'INSERT INTO ${1:table} (${2:columns})\nVALUES (${0:values});', 'INSERT 语句'],
      ],
    };

    for (const [language, items] of Object.entries(snippets)) {
      monaco.languages.registerCompletionItemProvider(language, {
        provideCompletionItems(model, position) {
          const range = completionRange(model, position);
          return {
            suggestions: items.map(([label, insertText, documentation]) => ({
              label,
              kind: monaco.languages.CompletionItemKind.Snippet,
              insertText,
              insertTextRules:
                monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
              documentation,
              range,
            })),
          };
        },
      });
    }

    for (const language of supportedLanguages) {
      monaco.languages.registerCompletionItemProvider(language, {
        provideCompletionItems(model, position) {
          return { suggestions: documentSymbols(monaco, model, position) };
        },
      });
    }
  }

  function resolvedTheme(editorTheme, dark) {
    return editorTheme === 'system'
      ? (dark ? 'vs-dark' : 'vs')
      : editorTheme;
  }

  function applyTheme(record) {
    const theme = resolvedTheme(record.editorTheme, record.dark);
    window.monaco.editor.setTheme(theme);
    record.host.style.backgroundColor = themeBackgrounds[theme] || '#1e1e1e';
  }

  function create(
    host,
    id,
    value,
    language,
    dark,
    indentSize,
    editorTheme,
    onChanged,
  ) {
    cancelled.delete(id);
    Promise.all([loadMonaco(), loadEditorFont()]).then(([monaco]) => {
      const mount = () => {
        if (cancelled.has(id)) return;
        if (!host.isConnected) {
          requestAnimationFrame(mount);
          return;
        }
        registerCompletions(monaco);
        const model = monaco.editor.createModel(value, language);
        const editor = monaco.editor.create(host, {
          model,
          theme: resolvedTheme(editorTheme, dark),
          automaticLayout: false,
          autoClosingBrackets: 'always',
          autoClosingQuotes: 'always',
          autoIndent: 'advanced',
          bracketPairColorization: { enabled: true },
          cursorBlinking: 'blink',
          cursorSmoothCaretAnimation: 'off',
          disableMonospaceOptimizations: true,
          fixedOverflowWidgets: true,
          folding: true,
          fontFamily: "'JetBrains Mono', monospace",
          fontLigatures: false,
          fontSize: 14,
          fontWeight: '400',
          formatOnPaste: true,
          guides: { bracketPairs: true, indentation: true },
          letterSpacing: 0,
          lineHeight: 22,
          minimap: { enabled: host.clientWidth >= 560, scale: 1 },
          mouseWheelZoom: true,
          padding: { top: 12, bottom: 12 },
          quickSuggestions: { other: true, comments: false, strings: true },
          inlineSuggest: { enabled: true },
          parameterHints: { enabled: true, cycle: true },
          scrollBeyondLastLine: false,
          smoothScrolling: true,
          snippetSuggestions: 'inline',
          stickyScroll: { enabled: true },
          suggestOnTriggerCharacters: true,
          suggest: {
            showClasses: true,
            showFunctions: true,
            showModules: true,
            showVariables: true,
            showWords: true,
          },
          tabCompletion: 'on',
          tabFocusMode: false,
          tabSize: indentSize,
          indentSize,
          insertSpaces: true,
          detectIndentation: false,
          wordWrap: 'on',
          wordBasedSuggestions: 'currentDocument',
        });
        const applyIndent = (outdent) => {
          const selection = editor.getSelection();
          if (!selection) return;
          const tabSize = Number(model.getOptions().tabSize) || 2;
          const empty =
            selection.startLineNumber === selection.endLineNumber &&
            selection.startColumn === selection.endColumn;
          let endLine = selection.endLineNumber;
          if (
            !empty &&
            selection.endColumn === 1 &&
            endLine > selection.startLineNumber
          ) {
            endLine -= 1;
          }

          const edits = [];
          if (outdent) {
            for (
              let line = selection.startLineNumber;
              line <= endLine;
              line += 1
            ) {
              const content = model.getLineContent(line);
              const leadingSpaces = content.match(/^ +/)?.[0].length ?? 0;
              const removeCount = content.startsWith('\t')
                ? 1
                : Math.min(tabSize, leadingSpaces);
              if (removeCount > 0) {
                edits.push({
                  range: new monaco.Range(line, 1, line, removeCount + 1),
                  text: '',
                  forceMoveMarkers: true,
                });
              }
            }
          } else if (!empty) {
            const indentation = ' '.repeat(tabSize);
            for (
              let line = selection.startLineNumber;
              line <= endLine;
              line += 1
            ) {
              edits.push({
                range: new monaco.Range(line, 1, line, 1),
                text: indentation,
                forceMoveMarkers: true,
              });
            }
          } else {
            const visualColumn = selection.startColumn - 1;
            const insertCount = tabSize - (visualColumn % tabSize);
            edits.push({
              range: new monaco.Range(
                selection.startLineNumber,
                selection.startColumn,
                selection.startLineNumber,
                selection.startColumn,
              ),
              text: ' '.repeat(insertCount),
              forceMoveMarkers: true,
            });
          }

          if (edits.length === 0) return;
          editor.pushUndoStop();
          editor.executeEdits('keyboard.tab', edits);
          editor.pushUndoStop();
          editor.focus();
        };

        const bubbleSpace = (event) => {
          if (
            event.code === 'Space' &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.altKey
          ) {
            // Do not preventDefault: Monaco must still insert the space.
            event.stopPropagation();
          }
        };
        const focusEditor = () => editor.focus();
        host.addEventListener('keydown', bubbleSpace);
        host.addEventListener('pointerdown', focusEditor, true);
        const recalibrate = () => {
          if (cancelled.has(id)) return;
          monaco.editor.remeasureFonts();
          editor.layout();
        };
        const resizeObserver = new ResizeObserver(recalibrate);
        resizeObserver.observe(host);
        const fontListener = () => requestAnimationFrame(recalibrate);
        document.fonts?.addEventListener?.('loadingdone', fontListener);
        window.visualViewport?.addEventListener('resize', fontListener);
        window.addEventListener('resize', fontListener);

        const record = {
          host,
          editor,
          model,
          dark,
          editorTheme,
          applying: false,
          applyIndent,
          disposeMeasurements() {
            host.removeEventListener('keydown', bubbleSpace);
            host.removeEventListener('pointerdown', focusEditor, true);
            resizeObserver.disconnect();
            document.fonts?.removeEventListener?.('loadingdone', fontListener);
            window.visualViewport?.removeEventListener('resize', fontListener);
            window.removeEventListener('resize', fontListener);
          },
        };
        record.subscription = model.onDidChangeContent(() => {
          if (!record.applying) onChanged(model.getValue());
        });
        editors.set(id, record);
        requestAnimationFrame(() => {
          recalibrate();
          editor.focus();
        });
      };
      mount();
    }).catch((error) => {
      host.textContent = '代码编辑器加载失败，请刷新页面后重试。';
      host.style.padding = '20px';
      host.style.color = dark ? '#f8fafc' : '#1f2328';
      console.error('Monaco failed to load', error);
    });
  }

  function setValue(id, value) {
    const record = editors.get(id);
    if (!record || record.model.getValue() === value) return;
    record.applying = true;
    record.model.setValue(value);
    record.applying = false;
  }

  function setLanguage(id, language) {
    const record = editors.get(id);
    if (record) window.monaco.editor.setModelLanguage(record.model, language);
  }

  function setTheme(id, dark) {
    const record = editors.get(id);
    if (!record) return;
    record.dark = dark;
    applyTheme(record);
  }

  function setOptions(id, indentSize, editorTheme) {
    const record = editors.get(id);
    if (!record) return;
    record.model.updateOptions({
      tabSize: indentSize,
      indentSize,
      insertSpaces: true,
      detectIndentation: false,
    });
    record.editor.updateOptions({ tabSize: indentSize });
    record.editorTheme = editorTheme;
    applyTheme(record);
  }

  function dispose(id) {
    cancelled.add(id);
    const record = editors.get(id);
    if (!record) return;
    record.disposeMeasurements();
    record.subscription.dispose();
    record.editor.dispose();
    record.model.dispose();
    editors.delete(id);
  }

  window.esaMonaco = {
    create,
    setValue,
    setLanguage,
    setTheme,
    setOptions,
    dispose,
  };
})();
