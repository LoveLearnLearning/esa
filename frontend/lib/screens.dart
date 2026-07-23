import 'package:flutter/material.dart';

Widget buildChatPage({String userName = '用户'}) => ChatPage(userName: userName);

class ChatPage extends StatefulWidget {
  const ChatPage({super.key, this.userName = '用户'});

  final String userName;

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<String> _historyList = ['项目需求分析', '会议方案', '后端接口总结'];
  final List<_ChatMessage> _messages = [
    const _ChatMessage(
      text: '你好！我是你的 AI 助手。你可以直接向我提问，比如“帮我总结这个项目”或“给我写一段代码”。',
      isUser: false,
    ),
  ];

  Future<void> _sendMessageWithText(String text) async {
    final input = text.trim();
    if (input.isEmpty) {
      return;
    }

    setState(() {
      _messages.add(_ChatMessage(text: input, isUser: true));
      _controller.clear();
    });
    _scrollToBottom();

    await Future.delayed(const Duration(milliseconds: 600));
    if (!mounted) {
      return;
    }

    setState(() {
      _messages.add(_ChatMessage(text: _buildReply(input), isUser: false));
    });
    _scrollToBottom();
  }

  Future<void> _sendMessage() async {
    await _sendMessageWithText(_controller.text);
  }

  String _buildReply(String input) {
    final value = input.toLowerCase();
    if (value.contains('总结')) {
      return '可以，我可以把你的内容整理成简洁的摘要或要点清单。';
    }
    if (value.contains('代码') || value.contains('flutter')) {
      return '当然，我可以帮你生成 Flutter 示例代码、布局结构或页面逻辑。';
    }
    if (value.contains('帮助')) {
      return '我可以为你提供思路、代码、解释和项目建议。';
    }
    return '我已经收到你的消息：$input。接下来我可以继续帮你分析、写作、编程或总结内容。';
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Row(
        children: [
          Container(
            width: 260,
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerLow,
              border: Border(
                right: BorderSide(
                  color: Theme.of(context).colorScheme.outlineVariant,
                ),
              ),
            ),
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      '已结束对话',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
                Expanded(
                  child: ListView.separated(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    itemCount: _historyList.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, index) {
                      return Container(
                        decoration: BoxDecoration(
                          color: Theme.of(context).colorScheme.surface,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: ListTile(
                          leading: const Icon(Icons.history_edu_outlined),
                          title: Text(_historyList[index]),
                          dense: true,
                          onTap: () {},
                        ),
                      );
                    },
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Theme.of(context).colorScheme.surface,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Row(
                      children: [
                        CircleAvatar(
                          radius: 18,
                          backgroundColor: Colors.indigo.shade100,
                          child: const Icon(
                            Icons.person,
                            color: Colors.indigo,
                            size: 20,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            widget.userName,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.bodyMedium,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: Scaffold(
              appBar: AppBar(
                title: const Row(
                  children: [
                    CircleAvatar(
                      radius: 16,
                      backgroundColor: Colors.indigo,
                      child: Icon(
                        Icons.smart_toy,
                        color: Colors.white,
                        size: 18,
                      ),
                    ),
                    SizedBox(width: 10),
                    Text('AI 助手'),
                  ],
                ),
                centerTitle: false,
                elevation: 0,
              ),
              body: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        _SuggestionChip(
                          label: '给我一份总结',
                          onTap: () => _sendMessageWithText('给我一份总结'),
                        ),
                        _SuggestionChip(
                          label: '帮我写个代码',
                          onTap: () => _sendMessageWithText('帮我写个代码'),
                        ),
                        _SuggestionChip(
                          label: '持续更新ing',
                          onTap: () => _sendMessageWithText('持续更新ing'),
                        ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.all(16),
                      itemCount: _messages.length,
                      itemBuilder: (context, index) {
                        final message = _messages[index];
                        return Align(
                          alignment: message.isUser
                              ? Alignment.centerRight
                              : Alignment.centerLeft,
                          child: Container(
                            margin: const EdgeInsets.symmetric(vertical: 6),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 14,
                              vertical: 12,
                            ),
                            constraints: BoxConstraints(
                              maxWidth:
                                  MediaQuery.of(context).size.width * 0.78,
                            ),
                            decoration: BoxDecoration(
                              color: message.isUser
                                  ? Theme.of(context).colorScheme.primary
                                  : Theme.of(
                                      context,
                                    ).colorScheme.surfaceContainerHighest,
                              borderRadius: BorderRadius.circular(16),
                            ),
                            child: Text(
                              message.text,
                              style: TextStyle(
                                color: message.isUser
                                    ? Theme.of(context).colorScheme.onPrimary
                                    : Theme.of(context).colorScheme.onSurface,
                              ),
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                  SafeArea(
                    child: Container(
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
                      decoration: BoxDecoration(
                        color: Theme.of(context).colorScheme.surface,
                        border: Border(
                          top: BorderSide(
                            color: Theme.of(context).colorScheme.outlineVariant,
                          ),
                        ),
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: TextField(
                              controller: _controller,
                              minLines: 1,
                              maxLines: 4,
                              decoration: InputDecoration(
                                hintText: '输入消息…',
                                border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(20),
                                ),
                                contentPadding: const EdgeInsets.symmetric(
                                  horizontal: 16,
                                  vertical: 10,
                                ),
                              ),
                              onSubmitted: (_) => _sendMessage(),
                            ),
                          ),
                          const SizedBox(width: 8),
                          FloatingActionButton.small(
                            onPressed: _sendMessage,
                            child: const Icon(Icons.send),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SuggestionChip extends StatelessWidget {
  const _SuggestionChip({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ActionChip(label: Text(label), onPressed: onTap);
  }
}

class _ChatMessage {
  const _ChatMessage({required this.text, required this.isUser});

  final String text;
  final bool isUser;
}
