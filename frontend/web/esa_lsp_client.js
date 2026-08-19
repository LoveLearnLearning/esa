(function () {
  'use strict';

  const supportedLanguages = new Set([
    'c',
    'cpp',
    'python',
    'javascript',
    'typescript',
    'dart',
    'java',
    'go',
    'rust',
  ]);
  const clients = new WeakMap();
  let providersRegistered = false;

  function websocketUrl(language) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/api/lsp/${encodeURIComponent(language)}`;
  }

  function wordRange(model, position) {
    const word = model.getWordUntilPosition(position);
    return {
      startLineNumber: position.lineNumber,
      endLineNumber: position.lineNumber,
      startColumn: word.startColumn,
      endColumn: word.endColumn,
    };
  }

  function monacoRange(monaco, range) {
    if (!range || !range.start || !range.end) return null;
    return new monaco.Range(
      range.start.line + 1,
      range.start.character + 1,
      range.end.line + 1,
      range.end.character + 1,
    );
  }

  function documentation(value) {
    if (!value) return undefined;
    if (typeof value === 'string') return { value };
    if (typeof value.value === 'string') return { value: value.value };
    return undefined;
  }

  function completionKind(monaco, kind) {
    const kinds = monaco.languages.CompletionItemKind;
    const map = {
      1: kinds.Text,
      2: kinds.Method,
      3: kinds.Function,
      4: kinds.Constructor,
      5: kinds.Field,
      6: kinds.Variable,
      7: kinds.Class,
      8: kinds.Interface,
      9: kinds.Module,
      10: kinds.Property,
      11: kinds.Unit,
      12: kinds.Value,
      13: kinds.Enum,
      14: kinds.Keyword,
      15: kinds.Snippet,
      16: kinds.Color,
      17: kinds.File,
      18: kinds.Reference,
      19: kinds.Folder,
      20: kinds.EnumMember,
      21: kinds.Constant,
      22: kinds.Struct,
      23: kinds.Event,
      24: kinds.Operator,
      25: kinds.TypeParameter,
    };
    return map[kind] ?? kinds.Text;
  }

  function completionItem(monaco, model, position, item) {
    const rawLabel = typeof item.label === 'string'
      ? item.label
      : item.label?.label ?? '';
    const label = rawLabel.trim();
    const textEdit = item.textEdit;
    const editRange = textEdit?.range ?? textEdit?.replace ?? textEdit?.insert;
    const range = monacoRange(monaco, editRange) ?? wordRange(model, position);
    const insertText = textEdit?.newText ?? item.insertText ?? label;
    const suggestion = {
      label,
      kind: completionKind(monaco, item.kind),
      detail: item.detail,
      documentation: documentation(item.documentation),
      filterText: item.filterText,
      sortText: item.sortText,
      insertText,
      range,
      commitCharacters: item.commitCharacters,
    };
    if (item.insertTextFormat === 2) {
      suggestion.insertTextRules =
        monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet;
    }
    if (Array.isArray(item.additionalTextEdits)) {
      suggestion.additionalTextEdits = item.additionalTextEdits
        .map((edit) => {
          const range = monacoRange(monaco, edit.range);
          return range ? { range, text: edit.newText ?? '' } : null;
        })
        .filter(Boolean);
    }
    return suggestion;
  }

  function hoverContents(contents) {
    const values = Array.isArray(contents) ? contents : [contents];
    return values.flatMap((item) => {
      if (typeof item === 'string') return [{ value: item }];
      if (typeof item?.value !== 'string') return [];
      if (item.language) {
        return [{ value: `\`\`\`${item.language}\n${item.value}\n\`\`\`` }];
      }
      return [{ value: item.value }];
    });
  }

  function markerSeverity(monaco, severity) {
    const markers = monaco.MarkerSeverity;
    return {
      1: markers.Error,
      2: markers.Warning,
      3: markers.Info,
      4: markers.Hint,
    }[severity] ?? markers.Info;
  }

  class LspClient {
    constructor(monaco, model, language, token, onStatus) {
      this.monaco = monaco;
      this.model = model;
      this.language = language;
      this.token = token;
      this.onStatus = onStatus;
      this.socket = null;
      this.ready = false;
      this.disposed = false;
      this.requestId = 0;
      this.version = 1;
      this.pending = new Map();
      this.documentUri = '';
      this.rootUri = '';
      this.changeSubscription = model.onDidChangeContent((event) => {
        if (!this.ready) return;
        this.version += 1;
        this.notify('textDocument/didChange', {
          textDocument: { uri: this.documentUri, version: this.version },
          contentChanges: event.changes.map((change) => ({
            range: {
              start: {
                line: change.range.startLineNumber - 1,
                character: change.range.startColumn - 1,
              },
              end: {
                line: change.range.endLineNumber - 1,
                character: change.range.endColumn - 1,
              },
            },
            rangeLength: change.rangeLength,
            text: change.text,
          })),
        });
      });
    }

    start() {
      this.onStatus('connecting');
      try {
        this.socket = new WebSocket(websocketUrl(this.language));
      } catch (_) {
        this.fail('fallback');
        return;
      }
      this.socket.addEventListener('open', () => {
        this.socket.send(JSON.stringify({ type: 'esa/auth', token: this.token }));
      });
      this.socket.addEventListener('message', (event) => this.handle(event.data));
      this.socket.addEventListener('error', () => this.fail('fallback'));
      this.socket.addEventListener('close', () => {
        if (!this.disposed && !this.ready) this.fail('fallback');
        if (!this.disposed && this.ready) this.fail('disconnected');
      });
    }

    async handle(raw) {
      let message;
      try {
        message = JSON.parse(raw);
      } catch (_) {
        return;
      }
      if (message.type === 'esa/lsp-ready') {
        this.rootUri = message.root_uri;
        this.documentUri = message.document_uri;
        await this.initialize();
        return;
      }
      if (message.type === 'esa/lsp-error') {
        this.fail('fallback');
        return;
      }
      if (Object.prototype.hasOwnProperty.call(message, 'id')) {
        const pending = this.pending.get(message.id);
        if (pending) {
          this.pending.delete(message.id);
          clearTimeout(pending.timer);
          if (message.error) pending.reject(message.error);
          else pending.resolve(message.result);
          return;
        }
        if (message.method) {
          this.respondToServerRequest(message);
          return;
        }
      }
      if (message.method === 'textDocument/publishDiagnostics') {
        this.publishDiagnostics(message.params);
      }
    }

    async initialize() {
      try {
        await this.request('initialize', {
          processId: null,
          clientInfo: { name: 'ESA Monaco', version: '1.0' },
          rootUri: this.rootUri,
          workspaceFolders: [{ uri: this.rootUri, name: 'ESA Code' }],
          capabilities: {
            workspace: { configuration: true, workspaceFolders: true },
            textDocument: {
              synchronization: { didSave: false, dynamicRegistration: false },
              completion: {
                dynamicRegistration: false,
                completionItem: {
                  snippetSupport: true,
                  documentationFormat: ['markdown', 'plaintext'],
                },
              },
              hover: { contentFormat: ['markdown', 'plaintext'] },
              signatureHelp: {
                signatureInformation: {
                  documentationFormat: ['markdown', 'plaintext'],
                  parameterInformation: { labelOffsetSupport: true },
                },
              },
              definition: { linkSupport: true },
              publishDiagnostics: { relatedInformation: true, versionSupport: true },
            },
          },
        }, 12000);
        if (this.disposed) return;
        this.notify('initialized', {});
        this.notify('textDocument/didOpen', {
          textDocument: {
            uri: this.documentUri,
            languageId: this.language,
            version: this.version,
            text: this.model.getValue(),
          },
        });
        this.ready = true;
        this.onStatus('connected');
      } catch (_) {
        this.fail('fallback');
      }
    }

    request(method, params, timeoutMs = 5000) {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        return Promise.reject(new Error('LSP socket is not connected'));
      }
      const id = ++this.requestId;
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this.pending.delete(id);
          reject(new Error(`LSP request timed out: ${method}`));
        }, timeoutMs);
        this.pending.set(id, { resolve, reject, timer });
        this.socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }));
      });
    }

    notify(method, params) {
      if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;
      this.socket.send(JSON.stringify({ jsonrpc: '2.0', method, params }));
    }

    respondToServerRequest(message) {
      let result = null;
      if (message.method === 'workspace/configuration') {
        result = (message.params?.items ?? []).map(() => null);
      } else if (message.method === 'workspace/workspaceFolders') {
        result = [{ uri: this.rootUri, name: 'ESA Code' }];
      }
      this.socket?.send(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }));
    }

    publishDiagnostics(params) {
      if (params?.uri !== this.documentUri) return;
      const markers = (params.diagnostics ?? []).flatMap((diagnostic) => {
        const range = monacoRange(this.monaco, diagnostic.range);
        if (!range) return [];
        return [{
          ...range,
          severity: markerSeverity(this.monaco, diagnostic.severity),
          message: diagnostic.message ?? '',
          code: diagnostic.code?.toString(),
          source: diagnostic.source ?? `LSP ${this.language}`,
        }];
      });
      this.monaco.editor.setModelMarkers(this.model, `esa-lsp-${this.language}`, markers);
    }

    fail(status) {
      if (this.disposed) return;
      this.ready = false;
      this.onStatus(status);
    }

    dispose() {
      if (this.disposed) return;
      this.disposed = true;
      this.changeSubscription.dispose();
      this.monaco.editor.setModelMarkers(this.model, `esa-lsp-${this.language}`, []);
      if (this.ready) {
        this.notify('textDocument/didClose', {
          textDocument: { uri: this.documentUri },
        });
        this.request('shutdown', null, 1000)
          .catch(() => null)
          .finally(() => {
            this.notify('exit', null);
            this.socket?.close(1000, 'editor closed');
          });
      } else {
        this.socket?.close(1000, 'editor closed');
      }
      for (const pending of this.pending.values()) {
        clearTimeout(pending.timer);
        pending.reject(new Error('LSP client disposed'));
      }
      this.pending.clear();
    }
  }

  function registerProviders(monaco) {
    if (providersRegistered) return;
    providersRegistered = true;
    for (const language of supportedLanguages) {
      monaco.languages.registerCompletionItemProvider(language, {
        triggerCharacters: ['.', ':', '>', '(', ',', '_'],
        async provideCompletionItems(model, position, context) {
          const client = clients.get(model);
          if (!client?.ready) return { suggestions: [] };
          try {
            const result = await client.request('textDocument/completion', {
              textDocument: { uri: client.documentUri },
              position: {
                line: position.lineNumber - 1,
                character: position.column - 1,
              },
              context: {
                triggerKind: context.triggerKind === 1 ? 1 : 2,
                triggerCharacter: context.triggerCharacter,
              },
            });
            const items = Array.isArray(result) ? result : result?.items ?? [];
            return {
              suggestions: items.map((item) =>
                completionItem(monaco, model, position, item)),
              incomplete: Boolean(result?.isIncomplete),
            };
          } catch (_) {
            return { suggestions: [] };
          }
        },
      });

      monaco.languages.registerHoverProvider(language, {
        async provideHover(model, position) {
          const client = clients.get(model);
          if (!client?.ready) return null;
          try {
            const result = await client.request('textDocument/hover', {
              textDocument: { uri: client.documentUri },
              position: {
                line: position.lineNumber - 1,
                character: position.column - 1,
              },
            });
            if (!result?.contents) return null;
            return {
              contents: hoverContents(result.contents),
              range: monacoRange(monaco, result.range) ?? undefined,
            };
          } catch (_) {
            return null;
          }
        },
      });

      monaco.languages.registerSignatureHelpProvider(language, {
        signatureHelpTriggerCharacters: ['(', ','],
        signatureHelpRetriggerCharacters: [','],
        async provideSignatureHelp(model, position, _token, context) {
          const client = clients.get(model);
          if (!client?.ready) return null;
          try {
            const value = await client.request('textDocument/signatureHelp', {
              textDocument: { uri: client.documentUri },
              position: {
                line: position.lineNumber - 1,
                character: position.column - 1,
              },
              context: {
                triggerKind: context.triggerKind,
                triggerCharacter: context.triggerCharacter,
                isRetrigger: context.isRetrigger,
              },
            });
            return value ? { value, dispose() {} } : null;
          } catch (_) {
            return null;
          }
        },
      });

      monaco.languages.registerDefinitionProvider(language, {
        async provideDefinition(model, position) {
          const client = clients.get(model);
          if (!client?.ready) return null;
          try {
            const result = await client.request('textDocument/definition', {
              textDocument: { uri: client.documentUri },
              position: {
                line: position.lineNumber - 1,
                character: position.column - 1,
              },
            });
            const locations = Array.isArray(result) ? result : result ? [result] : [];
            return locations.flatMap((location) => {
              const uri = location.targetUri ?? location.uri;
              const range = monacoRange(
                monaco,
                location.targetSelectionRange ?? location.range,
              );
              return uri && range ? [{ uri: monaco.Uri.parse(uri), range }] : [];
            });
          } catch (_) {
            return null;
          }
        },
      });
    }
  }

  function attach(monaco, model, language, token, onStatus) {
    detach(model);
    if (!supportedLanguages.has(language) || !token || !window.WebSocket) {
      onStatus('fallback');
      return null;
    }
    const client = new LspClient(monaco, model, language, token, onStatus);
    clients.set(model, client);
    client.start();
    return client;
  }

  function detach(model) {
    const client = clients.get(model);
    if (!client) return;
    clients.delete(model);
    client.dispose();
  }

  window.esaLsp = { attach, detach, registerProviders };
})();
