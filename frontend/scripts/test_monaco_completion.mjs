import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const providers = new Map();
let didType;
let suggestRuns = 0;
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
  onDidChangeContent: () => ({ dispose() {} }),
};

const editor = {
  focus() {},
  getAction: () => ({ run: () => { suggestRuns += 1; } }),
  hasTextFocus: () => true,
  layout() {},
  onDidType(listener) {
    didType = listener;
    return { dispose() {} };
  },
};

const monaco = {
  Range: class Range {},
  editor: {
    create: () => editor,
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
  addEventListener() {},
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

window.esaMonaco.create(
  {
    isConnected: true,
    clientWidth: 800,
    style: {},
    addEventListener() {},
    removeEventListener() {},
  },
  'completion-smoke-test',
  source,
  'cpp',
  true,
  2,
  'vs-dark',
  () => {},
);

await new Promise((resolve) => setImmediate(resolve));

const position = { lineNumber: 3, column: 9 };
const suggestions = (providers.get('cpp') ?? []).flatMap((provider) =>
  provider.provideCompletionItems(model, position).suggestions,
);
const labels = suggestions.map((item) => item.label);

assert(labels.includes('ListNode'), `ListNode missing from: ${labels.join(', ')}`);
assert(labels.includes('reverseListRecursive'));
assert(labels.includes('head'));

didType('o');
await new Promise((resolve) => setImmediate(resolve));
assert.equal(suggestRuns, 1, 'typing an identifier must open suggestions');

console.log('Monaco C++ symbol completion smoke test passed.');
