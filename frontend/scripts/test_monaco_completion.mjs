import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const providers = new Map();
let didType;
let keydownListener;
let pointerdownListener;
let suggestionFocused = false;
let editorFocusCount = 0;
const editorTriggers = [];
const executedEdits = [];
let editorOptions;
const source = [
  'ListNode* reverseListRecursive(ListNode* head) {',
  '  // 请尝试实现',
  '  ListNo',
  '}',
].join('\n');

const model = {
  getValue: () => source,
  getWordUntilPosition(position) {
    const line = source.split('\n')[position.lineNumber - 1] ?? '';
    const beforeCursor = line.slice(0, position.column - 1);
    const word = beforeCursor.match(/[A-Za-z_$][\w$]*$/)?.[0] ?? '';
    return {
      word,
      startColumn: position.column - word.length,
      endColumn: position.column,
    };
  },
  getOptions: () => ({ tabSize: 2 }),
  getLineContent: (lineNumber) => source.split('\n')[lineNumber - 1] ?? '',
  onDidChangeContent: () => ({ dispose() {} }),
};

const editor = {
  executeEdits: (_source, edits) => executedEdits.push(...edits),
  focus() {
    editorFocusCount += 1;
  },
  getSelection: () => ({
    startLineNumber: 3,
    startColumn: 9,
    endLineNumber: 3,
    endColumn: 9,
  }),
  hasTextFocus: () => true,
  layout() {},
  onDidType(listener) {
    didType = listener;
    return { dispose() {} };
  },
  pushUndoStop() {},
  trigger(sourceName, command, payload) {
    editorTriggers.push({ sourceName, command, payload });
  },
};

const monaco = {
  Range: class Range {},
  editor: {
    create: (_host, options) => {
      editorOptions = options;
      return editor;
    },
    createModel: () => model,
    defineTheme() {},
    remeasureFonts() {},
    setTheme() {},
  },
  languages: {
    CompletionItemInsertTextRule: { InsertAsSnippet: 1 },
    CompletionItemKind: {
      Class: 1,
      Function: 2,
      Module: 3,
      Snippet: 4,
      Variable: 5,
    },
    registerCompletionItemProvider(language, provider) {
      const items = providers.get(language) ?? [];
      items.push(provider);
      providers.set(language, items);
      return { dispose() {} };
    },
  },
};

globalThis.window = {
  monaco,
  addEventListener(type, listener) {
    if (type === 'keydown') keydownListener = listener;
  },
  removeEventListener() {},
};
globalThis.document = {
  getElementById: () => null,
};
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  disconnect() {}
};
globalThis.requestAnimationFrame = (callback) => {
  queueMicrotask(callback);
  return 1;
};
globalThis.cancelAnimationFrame = () => {};

const script = fs.readFileSync(new URL('../web/esa_monaco.js', import.meta.url), 'utf8');
vm.runInThisContext(script, { filename: 'esa_monaco.js' });

const eventTarget = {};
const host = {
  isConnected: true,
  clientWidth: 800,
  style: {},
  addEventListener(type, listener) {
    if (type === 'pointerdown') pointerdownListener = listener;
  },
  contains: (target) => target === eventTarget,
  querySelector(selector) {
    if (selector === '.suggest-widget.visible:not(.message)' && suggestionFocused) {
      return {
        querySelector: (childSelector) =>
          childSelector === '.monaco-list-row.focused' ? {} : null,
      };
    }
    return null;
  },
  removeEventListener() {},
};

window.esaMonaco.create(
  host,
  'completion-smoke-test',
  source,
  'cpp',
  true,
  2,
  'vs-dark',
  '',
  () => {},
  () => {},
);

await new Promise((resolve) => setImmediate(resolve));

const focusCountBeforePointer = editorFocusCount;
pointerdownListener();
await new Promise((resolve) => setImmediate(resolve));
assert(
  editorFocusCount > focusCountBeforePointer,
  'pointer interaction must focus Monaco text input directly',
);

const position = { lineNumber: 3, column: 9 };
const suggestions = (providers.get('cpp') ?? []).flatMap((provider) =>
  provider.provideCompletionItems(model, position).suggestions,
);
const labels = suggestions.map((item) => item.label);

assert(labels.includes('ListNode'), `ListNode missing from: ${labels.join(', ')}`);
assert(labels.includes('reverseListRecursive'));
assert(labels.includes('head'));
assert.equal(
  editorOptions.fixedOverflowWidgets,
  false,
  'suggestions must stay inside Flutter HtmlElementView coordinates',
);

didType('o');
await new Promise((resolve) => setImmediate(resolve));
assert.deepEqual(editorTriggers.at(-1), {
  sourceName: 'esa.document-symbols',
  command: 'editor.action.triggerSuggest',
  payload: { auto: true },
});

const tabEvent = () => ({
  key: 'Tab',
  keyCode: 9,
  target: eventTarget,
  shiftKey: false,
  preventDefault() {},
  stopImmediatePropagation() {},
});

const arrowEvent = (key, { shiftKey = false } = {}) => ({
  key,
  keyCode: {
    ArrowLeft: 37,
    ArrowUp: 38,
    ArrowRight: 39,
    ArrowDown: 40,
  }[key],
  target: eventTarget,
  shiftKey,
  preventDefault() {},
  stopImmediatePropagation() {},
});

suggestionFocused = true;
keydownListener(tabEvent());
assert.deepEqual(editorTriggers.at(-1), {
  sourceName: 'keyboard',
  command: 'acceptSelectedSuggestion',
  payload: {},
});
assert.equal(executedEdits.length, 0, 'accepting completion must not indent');

suggestionFocused = false;
keydownListener(tabEvent());
assert.equal(executedEdits.length, 1, 'Tab without a completion must indent');
assert.equal(executedEdits[0].text, '  ');

const arrowCommands = {
  ArrowLeft: 'cursorLeft',
  ArrowRight: 'cursorRight',
  ArrowUp: 'cursorUp',
  ArrowDown: 'cursorDown',
};
for (const [key, command] of Object.entries(arrowCommands)) {
  const focusCountBeforeArrow = editorFocusCount;
  keydownListener(arrowEvent(key));
  assert.deepEqual(editorTriggers.at(-1), {
    sourceName: 'keyboard',
    command,
    payload: {},
  });
  assert.equal(
    editorFocusCount,
    focusCountBeforeArrow + 1,
    `${key} must restore Monaco text focus`,
  );

  keydownListener(arrowEvent(key, { shiftKey: true }));
  assert.deepEqual(editorTriggers.at(-1), {
    sourceName: 'keyboard',
    command: `${command}Select`,
    payload: {},
  });
}

suggestionFocused = true;
keydownListener(arrowEvent('ArrowDown'));
assert.deepEqual(editorTriggers.at(-1), {
  sourceName: 'keyboard',
  command: 'selectNextSuggestion',
  payload: {},
});
keydownListener(arrowEvent('ArrowUp'));
assert.deepEqual(editorTriggers.at(-1), {
  sourceName: 'keyboard',
  command: 'selectPrevSuggestion',
  payload: {},
});

console.log('Monaco completion, Tab, and arrow-key smoke test passed.');
