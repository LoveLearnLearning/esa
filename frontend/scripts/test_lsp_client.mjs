import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const completionProviders = new Map();
const statuses = [];
let socket;

class FakeWebSocket {
  static OPEN = 1;

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.listeners = new Map();
    socket = this;
  }

  addEventListener(name, callback) {
    const listeners = this.listeners.get(name) ?? [];
    listeners.push(callback);
    this.listeners.set(name, listeners);
  }

  send(message) {
    this.sent.push(JSON.parse(message));
  }

  close() {
    this.readyState = 3;
  }

  dispatch(name, value = {}) {
    for (const listener of this.listeners.get(name) ?? []) listener(value);
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatch('open');
  }

  message(value) {
    this.dispatch('message', { data: JSON.stringify(value) });
  }
}

const completionKinds = {
  Text: 1,
  Method: 2,
  Function: 3,
  Constructor: 4,
  Field: 5,
  Variable: 6,
  Class: 7,
  Interface: 8,
  Module: 9,
  Property: 10,
  Unit: 11,
  Value: 12,
  Enum: 13,
  Keyword: 14,
  Snippet: 15,
  Color: 16,
  File: 17,
  Reference: 18,
  Folder: 19,
  EnumMember: 20,
  Constant: 21,
  Struct: 22,
  Event: 23,
  Operator: 24,
  TypeParameter: 25,
};

const monaco = {
  Range: class Range {
    constructor(startLineNumber, startColumn, endLineNumber, endColumn) {
      Object.assign(this, {
        startLineNumber,
        startColumn,
        endLineNumber,
        endColumn,
      });
    }
  },
  Uri: { parse: (value) => value },
  MarkerSeverity: { Error: 8, Warning: 4, Info: 2, Hint: 1 },
  editor: { setModelMarkers() {} },
  languages: {
    CompletionItemKind: completionKinds,
    CompletionItemInsertTextRule: { InsertAsSnippet: 4 },
    registerCompletionItemProvider(language, provider) {
      completionProviders.set(language, provider);
    },
    registerHoverProvider() {},
    registerSignatureHelpProvider() {},
    registerDefinitionProvider() {},
  },
};

const source = 'ListNode* head;\nListNo';
const model = {
  getValue: () => source,
  getWordUntilPosition: () => ({
    word: 'ListNo',
    startColumn: 1,
    endColumn: 7,
  }),
  onDidChangeContent: () => ({ dispose() {} }),
};

globalThis.WebSocket = FakeWebSocket;
globalThis.window = {
  WebSocket: FakeWebSocket,
  location: { protocol: 'https:', host: 'www.example.test' },
};

const script = fs.readFileSync(
  new URL('../web/esa_lsp_client.js', import.meta.url),
  'utf8',
);
vm.runInThisContext(script, { filename: 'esa_lsp_client.js' });

window.esaLsp.registerProviders(monaco);
window.esaLsp.attach(monaco, model, 'cpp', 'session-token', (status) => {
  statuses.push(status);
});

assert.equal(socket.url, 'wss://www.example.test/api/lsp/cpp');
socket.open();
assert.deepEqual(socket.sent.shift(), {
  type: 'esa/auth',
  token: 'session-token',
});

socket.message({
  type: 'esa/lsp-ready',
  language: 'cpp',
  root_uri: 'file:///tmp/esa-lsp',
  document_uri: 'file:///tmp/esa-lsp/main.cpp',
});
await new Promise((resolve) => setImmediate(resolve));

const initialize = socket.sent.shift();
assert.equal(initialize.method, 'initialize');
socket.message({ jsonrpc: '2.0', id: initialize.id, result: { capabilities: {} } });
await new Promise((resolve) => setImmediate(resolve));

assert(statuses.includes('connected'));
assert(socket.sent.some((message) => message.method === 'textDocument/didOpen'));

const completionPromise = completionProviders.get('cpp').provideCompletionItems(
  model,
  { lineNumber: 2, column: 7 },
  { triggerKind: 1 },
);
await new Promise((resolve) => setImmediate(resolve));
const completionRequest = socket.sent.find(
  (message) => message.method === 'textDocument/completion',
);
assert(completionRequest);
socket.message({
  jsonrpc: '2.0',
  id: completionRequest.id,
  result: [
    {
      label: 'ListNode',
      kind: 7,
      detail: 'struct ListNode',
      insertText: 'ListNode',
    },
  ],
});

const completion = await completionPromise;
assert.equal(completion.suggestions[0].label, 'ListNode');
assert.equal(completion.suggestions[0].kind, completionKinds.Class);
assert.equal(completion.suggestions[0].insertText, 'ListNode');

console.log('Monaco LSP handshake and completion test passed.');
