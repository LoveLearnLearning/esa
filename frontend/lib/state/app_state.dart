// ESA 应用状态 —— 集中式 ChangeNotifier 通过 ApiClient 调用真实后端
// 认证 / 对话列表 / 历史消息 / 发消息 均对接 API.md 定义的接口
// 置顶(pinned) 主题 设置为纯前端本地状态 后端无对应字段

import 'dart:async';
import 'dart:collection';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' show ClientException;
import 'package:shared_preferences/shared_preferences.dart';

import '../api/api_client.dart';
import '../models/code_editor_settings.dart';
import '../models/models.dart';
import '../theme/esa_theme.dart';

class AppState extends ChangeNotifier {
  AppState({ApiClient? api, this.restoringSession = false})
    : api = api ?? ApiClient();

  final ApiClient api;

  static const _rememberSessionKey = 'esa.remember.session_id';
  static const _rememberUserIdKey = 'esa.remember.user_id';
  static const _rememberUsernameKey = 'esa.remember.username';
  static const _rememberEmailKey = 'esa.remember.email';
  static const _rememberExpiresAtKey = 'esa.remember.expires_at';
  static const _scheduleStoragePrefix = 'esa.schedule.';
  static const _scheduleSettingsStoragePrefix = 'esa.schedule.settings.';
  static const _codeEditorIndentSizeKey = 'esa.editor.indent_size';
  static const _codeEditorThemeKey = 'esa.editor.theme';

  // ---- 本地设置(不落后端) ----
  ThemeMode themeMode = ThemeMode.dark;
  bool streamOn = true;
  bool toolsOn = true;
  int codeEditorIndentSize = 2;
  String codeEditorTheme = 'vs-dark';
  String accountRole = 'student';
  List<WorkspaceDescriptor> availableWorkspaces = const [
    WorkspaceDescriptor(
      type: WorkspaceType.learning,
      name: '学习空间',
      description: '',
      capabilities: ['chat'],
    ),
    WorkspaceDescriptor(
      type: WorkspaceType.research,
      name: '科研空间',
      description: '',
      capabilities: ['chat', 'research_projects'],
    ),
  ];
  WorkspaceType activeWorkspace = WorkspaceType.learning;
  final List<ResearchProject> researchProjects = [];
  bool loadingResearchProjects = false;
  bool researchProjectsLoaded = false;
  String email = '';
  String role = '学生';
  UserPreferences preferences = const UserPreferences();
  UserProfile userProfile = const UserProfile();
  bool loadingProfile = false;
  List<LearningCourseSummary> learningCourses = const [];
  MasteryReport? masteryReport;
  bool loadingLearningOverview = false;
  String? learningOverviewError;
  bool restoringSession;

  // ---- 对话数据 ----
  final List<ChatConversation> conversations = [];
  final Map<String, List<ChatMessage>> _messages = {};
  final Set<String> _pinned = {}; // 本地置顶集合
  final List<ChatGroup> groups = [];
  String? activeGroupId;
  bool loadingGroups = false;
  bool groupsLoaded = false;
  String? activeId;
  Future<void>? _conversationCreation;

  bool busy = false; // 正在发消息
  bool loadingConversations = false;
  bool loadingMessages = false;
  final List<ScheduleCourse> scheduleCourses = [];
  final List<ScheduleTable> scheduleTables = [];
  String activeScheduleTableId = '';
  ScheduleSettings scheduleSettings = const ScheduleSettings();
  bool scheduleLoaded = false;

  String get username => api.username ?? '';
  bool get isLoggedIn => api.isLoggedIn;

  List<ChatMessage> get messages =>
      activeId == null ? const [] : (_messages[activeId] ?? const []);

  ChatConversation? get activeConversation {
    if (activeId == null) return null;
    for (final c in conversations) {
      if (c.id == activeId) return c;
    }
    return null;
  }

  List<ChatConversation> get groupedConversations =>
      conversations.where((c) => c.groupId != null).toList();

  List<ChatConversation> get ungroupedConversations =>
      conversations.where((c) => c.groupId == null).toList();

  List<ChatConversation> conversationsInGroup(String groupId) =>
      conversations.where((c) => c.groupId == groupId).toList();

  ChatGroup? get activeGroup {
    if (activeGroupId == null) return null;
    for (final group in groups) {
      if (group.id == activeGroupId) return group;
    }
    return null;
  }

  // ============ 认证 ============
  /// 返回 null 表示成功 否则返回错误文案
  Future<String?> login(
    String username,
    String password, {
    bool rememberLogin = false,
  }) async {
    try {
      await api.login(username, password);
      email = api.email ?? '';
      await _afterLogin();
      if (rememberLogin) {
        await _rememberCurrentSession();
      } else {
        await _forgetRememberedSession();
      }
      return null;
    } on ApiException catch (e) {
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请检查后端是否启动';
    }
  }

  /// 注册并自动登录 返回 null 表示成功 否则返回错误文案
  Future<String?> sendRegistrationCode(String emailAddress) async {
    try {
      final seconds = await api.sendRegistrationCode(emailAddress);
      return seconds.toString();
    } on ApiException catch (e) {
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请检查后端是否启动';
    }
  }

  Future<String?> register(
    String emailAddress,
    String verificationCode,
    String username,
    String password,
    String accountRole,
  ) async {
    try {
      await api.register(
        emailAddress,
        verificationCode,
        username,
        password,
        accountRole,
      );
      await api.login(emailAddress, password);
      email = api.email ?? emailAddress;
      await _afterLogin();
      return null;
    } on ApiException catch (e) {
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请检查后端是否启动';
    }
  }

  Future<void> _afterLogin() async {
    final manifest = await api.getWorkspaceManifest();
    accountRole = manifest.accountRole;
    api.accountRole = manifest.accountRole;
    role = accountRole == 'teacher' ? '教师' : '学生';
    availableWorkspaces = manifest.workspaces;
    if (!availableWorkspaces.any((item) => item.type == activeWorkspace)) {
      activeWorkspace = manifest.defaultWorkspace;
    }
    await Future.wait([
      loadConversations(),
      loadGroups(),
      loadPreferencesAndProfile(),
      loadLearningOverview(),
    ]);
    if (conversations.isNotEmpty) {
      await setActive(conversations.first.id);
    } else {
      activeId = null;
    }
    notifyListeners();
  }

  Future<void> logout() async {
    await api.logout();
    _clearSession();
  }

  /// 游客模式：纯本地进入主界面，不创建后端会话。
  void enterAsGuest() {
    _clearSession();
    api.username = '游客';
    notifyListeners();
  }

  Future<void> restoreSession() async {
    try {
      final localPreferences = await _getLocalPreferences();
      if (localPreferences == null) return;
      _loadLocalEditorSettings(localPreferences);
      final sessionId = localPreferences.getString(_rememberSessionKey);
      final userId = localPreferences.getString(_rememberUserIdKey);
      final username = localPreferences.getString(_rememberUsernameKey);
      final rememberedEmail = localPreferences.getString(_rememberEmailKey);
      final expiresAtValue = localPreferences.getString(_rememberExpiresAtKey);
      final expiresAt = DateTime.tryParse(expiresAtValue ?? '');

      if (sessionId == null ||
          userId == null ||
          username == null ||
          expiresAt == null ||
          !expiresAt.isAfter(DateTime.now().toUtc())) {
        await _forgetRememberedSession();
        return;
      }

      api.sessionId = sessionId;
      api.userId = userId;
      api.username = username;
      api.email = rememberedEmail;
      api.sessionExpiresAt = expiresAt;
      email = rememberedEmail ?? '';

      // The local session is enough to render the application shell. Remote
      // workspace and conversation data can continue loading behind it.
      restoringSession = false;
      notifyListeners();
      try {
        await _afterLogin();
      } catch (_) {
        _clearSession();
      }
    } finally {
      if (restoringSession) {
        restoringSession = false;
        notifyListeners();
      }
    }
  }

  Future<void> _rememberCurrentSession() async {
    final sessionId = api.sessionId;
    final userId = api.userId;
    final username = api.username;
    final expiresAt = api.sessionExpiresAt;
    if (sessionId == null ||
        userId == null ||
        username == null ||
        expiresAt == null) {
      return;
    }
    final localPreferences = await _getLocalPreferences();
    if (localPreferences == null) return;
    await localPreferences.setString(_rememberSessionKey, sessionId);
    await localPreferences.setString(_rememberUserIdKey, userId);
    await localPreferences.setString(_rememberUsernameKey, username);
    if (api.email case final rememberedEmail?) {
      await localPreferences.setString(_rememberEmailKey, rememberedEmail);
    } else {
      await localPreferences.remove(_rememberEmailKey);
    }
    await localPreferences.setString(
      _rememberExpiresAtKey,
      expiresAt.toUtc().toIso8601String(),
    );
  }

  Future<void> _forgetRememberedSession() async {
    final localPreferences = await _getLocalPreferences();
    if (localPreferences == null) return;
    await Future.wait([
      localPreferences.remove(_rememberSessionKey),
      localPreferences.remove(_rememberUserIdKey),
      localPreferences.remove(_rememberUsernameKey),
      localPreferences.remove(_rememberEmailKey),
      localPreferences.remove(_rememberExpiresAtKey),
    ]);
  }

  Future<SharedPreferences?> _getLocalPreferences() async {
    try {
      return await SharedPreferences.getInstance();
    } on MissingPluginException {
      // 新增插件后仅 Hot Restart 时 Web 插件可能尚未重新注册。
      // 此时跳过会话持久化，让应用仍可正常进入登录页。
      return null;
    }
  }

  void _loadLocalEditorSettings(SharedPreferences localPreferences) {
    final indentSize = localPreferences.getInt(_codeEditorIndentSizeKey);
    if (indentSize == 2 || indentSize == 4 || indentSize == 8) {
      codeEditorIndentSize = indentSize!;
    }
    final editorTheme = localPreferences.getString(_codeEditorThemeKey);
    if (isCodeEditorTheme(editorTheme)) {
      codeEditorTheme = editorTheme!;
    }
  }

  /// 修改成功后服务端会注销全部会话，前端同步回到登录页。
  /// 返回 null 表示成功，否则返回可直接展示的错误信息。
  Future<String?> changePassword(String oldPassword, String newPassword) async {
    try {
      await api.changePassword(oldPassword, newPassword);
      _clearSession();
      return null;
    } on ApiException catch (e) {
      if (e.isUnauthorized) _clearSession();
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请稍后重试';
    }
  }

  Future<String?> sendBindEmailCode(String emailAddress) async {
    try {
      return (await api.sendBindEmailCode(emailAddress)).toString();
    } on ApiException catch (e) {
      if (e.isUnauthorized) _clearSession();
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请稍后重试';
    }
  }

  Future<String?> bindEmail(
    String emailAddress,
    String verificationCode,
  ) async {
    try {
      await api.bindEmail(emailAddress, verificationCode);
      email = api.email ?? emailAddress;
      await _rememberCurrentSession();
      notifyListeners();
      return null;
    } on ApiException catch (e) {
      if (e.isUnauthorized) _clearSession();
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请稍后重试';
    }
  }

  void _clearSession() {
    api.sessionId = null;
    api.userId = null;
    api.username = null;
    api.email = null;
    api.sessionExpiresAt = null;
    unawaited(_forgetRememberedSession());
    conversations.clear();
    _messages.clear();
    _pinned.clear();
    groups.clear();
    activeGroupId = null;
    groupsLoaded = false;
    loadingGroups = false;
    scheduleCourses.clear();
    scheduleTables.clear();
    activeScheduleTableId = '';
    scheduleSettings = const ScheduleSettings();
    scheduleLoaded = false;
    activeId = null;
    busy = false;
    preferences = const UserPreferences();
    userProfile = const UserProfile();
    learningCourses = const [];
    masteryReport = null;
    loadingLearningOverview = false;
    learningOverviewError = null;
    email = '';
    notifyListeners();
  }

  // ============ 服务端课表（SharedPreferences 仅作离线缓存/旧数据迁移） ============
  String get _scheduleStorageKey =>
      '$_scheduleStoragePrefix${api.userId ?? api.username ?? 'guest'}';

  String get _scheduleSettingsStorageKey =>
      '$_scheduleSettingsStoragePrefix${api.userId ?? api.username ?? 'guest'}';

  Future<void> loadSchedule({bool force = false}) async {
    if (scheduleLoaded && !force) return;
    scheduleLoaded = false;
    try {
      final snapshot = await api.getSchedule();
      var serverCourses = snapshot.courses;
      var serverSettings = snapshot.settings;
      final localPreferences = await _getLocalPreferences();
      // 旧版本地缓存只在"用户仅有一张空课表"时迁移上传；
      // 多张课程表说明服务端数据已是权威，切到空的新表时绝不能回灌缓存
      if (serverCourses.isEmpty &&
          snapshot.tables.length <= 1 &&
          localPreferences != null) {
        final rawCourses = localPreferences.getString(_scheduleStorageKey);
        if (rawCourses != null && rawCourses.isNotEmpty) {
          try {
            final decoded = jsonDecode(rawCourses);
            if (decoded is List) {
              final legacyCourses = decoded
                  .whereType<Map>()
                  .map(
                    (item) => ScheduleCourse.fromJson(
                      Map<String, dynamic>.from(item),
                    ),
                  )
                  .toList();
              final migrated = <ScheduleCourse>[];
              for (final course in legacyCourses) {
                migrated.add(await api.saveScheduleCourse(course));
              }
              serverCourses = migrated;
            }
          } on FormatException {
            // 损坏的旧缓存不迁移。
          }
        }
        final rawSettings = localPreferences.getString(
          _scheduleSettingsStorageKey,
        );
        if (rawSettings != null && rawSettings.isNotEmpty) {
          try {
            final decoded = jsonDecode(rawSettings);
            if (decoded is Map) {
              serverSettings = await api.saveScheduleSettings(
                ScheduleSettings.fromJson(Map<String, dynamic>.from(decoded)),
              );
            }
          } on FormatException {
            // 损坏的旧缓存不迁移。
          }
        }
      }
      scheduleCourses
        ..clear()
        ..addAll(serverCourses);
      scheduleTables
        ..clear()
        ..addAll(snapshot.tables);
      activeScheduleTableId = snapshot.activeTableId;
      scheduleSettings = serverSettings;
      scheduleLoaded = true;
      _sortSchedule();
      await _persistSchedule();
      notifyListeners();
      return;
    } on ApiException catch (error) {
      if (_handled401(error)) return;
      // 网络暂时不可用时读旧缓存，恢复联网后的写操作仍以服务端为准。
    } on ClientException {
      // 同上，保留离线只读回退。
    }
    final localPreferences = await _getLocalPreferences();
    if (localPreferences == null) {
      scheduleLoaded = true;
      notifyListeners();
      return;
    }
    final raw = localPreferences.getString(_scheduleStorageKey);
    final rawSettings = localPreferences.getString(_scheduleSettingsStorageKey);
    scheduleCourses.clear();
    if (raw != null && raw.isNotEmpty) {
      try {
        final decoded = jsonDecode(raw);
        if (decoded is List) {
          scheduleCourses.addAll(
            decoded.whereType<Map>().map(
              (item) =>
                  ScheduleCourse.fromJson(Map<String, dynamic>.from(item)),
            ),
          );
        }
      } on FormatException {
        // 本地缓存损坏时显示空课表，不影响主功能。
      }
    }
    scheduleSettings = const ScheduleSettings();
    if (rawSettings != null && rawSettings.isNotEmpty) {
      try {
        final decoded = jsonDecode(rawSettings);
        if (decoded is Map) {
          scheduleSettings = ScheduleSettings.fromJson(
            Map<String, dynamic>.from(decoded),
          );
        }
      } on FormatException {
        // 设置缓存损坏时使用默认作息。
      }
    }
    _sortSchedule();
    scheduleLoaded = true;
    notifyListeners();
  }

  Future<void> saveScheduleCourse(ScheduleCourse course) async {
    final saved = await api.saveScheduleCourse(course);
    final index = scheduleCourses.indexWhere((item) => item.id == saved.id);
    if (index < 0) {
      scheduleCourses.add(saved);
    } else {
      scheduleCourses[index] = saved;
    }
    _sortSchedule();
    scheduleLoaded = true;
    notifyListeners();
    await _persistSchedule();
  }

  Future<void> deleteScheduleCourse(String courseId) async {
    await api.deleteScheduleCourse(courseId);
    scheduleCourses.removeWhere((course) => course.id == courseId);
    scheduleLoaded = true;
    notifyListeners();
    await _persistSchedule();
  }

  Future<void> saveScheduleSettings(ScheduleSettings settings) async {
    scheduleSettings = await api.saveScheduleSettings(settings);
    scheduleLoaded = true;
    notifyListeners();
    final localPreferences = await _getLocalPreferences();
    if (localPreferences == null) return;
    await localPreferences.setString(
      _scheduleSettingsStorageKey,
      jsonEncode(scheduleSettings.toJson()),
    );
  }

  void _applyScheduleSnapshot(ScheduleSnapshot snapshot) {
    scheduleCourses
      ..clear()
      ..addAll(snapshot.courses);
    scheduleTables
      ..clear()
      ..addAll(snapshot.tables);
    activeScheduleTableId = snapshot.activeTableId;
    scheduleSettings = snapshot.settings;
    scheduleLoaded = true;
    _sortSchedule();
    notifyListeners();
  }

  ScheduleTable? get activeScheduleTable {
    for (final table in scheduleTables) {
      if (table.id == activeScheduleTableId) return table;
    }
    return null;
  }

  Future<void> switchScheduleTable(String tableId) async {
    if (tableId == activeScheduleTableId) return;
    final snapshot = await api.activateScheduleTable(tableId);
    _applyScheduleSnapshot(snapshot);
    await _persistSchedule();
  }

  Future<void> createScheduleTable(String name) async {
    await api.createScheduleTable(name);
    await loadSchedule(force: true);
  }

  Future<void> renameScheduleTable(String tableId, String name) async {
    final renamed = await api.renameScheduleTable(tableId, name);
    final index = scheduleTables.indexWhere((table) => table.id == tableId);
    if (index >= 0) scheduleTables[index] = renamed;
    notifyListeners();
  }

  Future<void> deleteScheduleTable(String tableId) async {
    await api.deleteScheduleTable(tableId);
    await loadSchedule(force: true);
  }

  Future<ScheduleImportResult> importScheduleFile({
    required String filename,
    required Uint8List bytes,
    bool toNewTable = false,
    String? newTableName,
  }) async {
    final result = await api.importScheduleFile(
      filename: filename,
      bytes: bytes,
      toNewTable: toNewTable,
      newTableName: newTableName,
    );
    // 导入可能新建并切换课程表，直接以服务端快照为准
    await loadSchedule(force: true);
    return result;
  }

  void _sortSchedule() {
    scheduleCourses.sort((a, b) {
      final day = a.weekday.compareTo(b.weekday);
      return day != 0 ? day : a.startPeriod.compareTo(b.startPeriod);
    });
  }

  Future<void> _persistSchedule() async {
    final localPreferences = await _getLocalPreferences();
    if (localPreferences == null) return;
    await localPreferences.setString(
      _scheduleStorageKey,
      jsonEncode(scheduleCourses.map((course) => course.toJson()).toList()),
    );
  }

  /// 统一处理 401 会话失效 直接回登录页
  bool _handled401(Object e) {
    if (e is ApiException && e.isUnauthorized) {
      _clearSession();
      return true;
    }
    return false;
  }

  // ============ 对话 ============
  Future<void> loadConversations() async {
    loadingConversations = true;
    notifyListeners();
    try {
      final list = activeWorkspace == WorkspaceType.learning
          ? await api.listConversations()
          : await api.listWorkspaceConversations(activeWorkspace);
      for (final c in list) {
        c.pinned = _pinned.contains(c.id);
      }
      conversations
        ..clear()
        ..addAll(list);
    } catch (e) {
      if (!_handled401(e)) rethrow;
    } finally {
      loadingConversations = false;
      notifyListeners();
    }
  }

  // ============ 对话分组 ============
  Future<void> loadGroups({bool force = false}) async {
    if (loadingGroups || (groupsLoaded && !force)) return;
    loadingGroups = true;
    notifyListeners();
    try {
      groups
        ..clear()
        ..addAll(await api.listGroups());
      groupsLoaded = true;
    } catch (error) {
      if (!_handled401(error)) rethrow;
    } finally {
      loadingGroups = false;
      notifyListeners();
    }
  }

  Future<ChatGroup> createGroup({
    required String name,
    String description = '',
    String customInstruction = '',
    String? style,
    String? tone,
  }) async {
    final group = await api.createGroup(
      name: name.trim(),
      description: description,
      customInstruction: customInstruction,
      style: style,
      tone: tone,
    );
    groups.insert(0, group);
    activeGroupId = group.id;
    notifyListeners();
    return group;
  }

  void setActiveGroup(String? groupId) {
    if (activeGroupId == groupId) return;
    activeGroupId = groupId;
    notifyListeners();
  }

  void reorderGroups(int oldIndex, int newIndex) {
    if (oldIndex < 0 || oldIndex >= groups.length) return;
    if (newIndex > oldIndex) newIndex -= 1;
    if (newIndex < 0) newIndex = 0;
    if (newIndex > groups.length) newIndex = groups.length;
    final group = groups.removeAt(oldIndex);
    groups.insert(newIndex, group);
    notifyListeners();
  }

  Future<ChatGroup> updateGroup(
    String groupId, {
    String? name,
    String? description,
    String? customInstruction,
    Object? style = groupFieldUnset,
    Object? tone = groupFieldUnset,
  }) async {
    final updated = await api.updateGroup(
      groupId,
      name: name?.trim(),
      description: description,
      customInstruction: customInstruction,
      style: style,
      tone: tone,
    );
    final index = groups.indexWhere((group) => group.id == groupId);
    if (index >= 0) {
      groups.removeAt(index);
    }
    groups.insert(0, updated);
    notifyListeners();
    return updated;
  }

  Future<void> deleteGroup(String groupId) async {
    await api.deleteGroup(groupId);
    groups.removeWhere((group) => group.id == groupId);
    if (activeGroupId == groupId) activeGroupId = null;
    for (final conversation in conversations) {
      if (conversation.groupId == groupId) conversation.groupId = null;
    }
    notifyListeners();
    await loadConversations();
  }

  Future<void> moveConversationToGroup(
    String conversationId,
    String? groupId,
  ) async {
    final index = conversations.indexWhere(
      (conversation) => conversation.id == conversationId,
    );
    if (index < 0) throw ApiException(404, '对话不存在');
    final previousGroupId = conversations[index].groupId;
    if (previousGroupId == groupId) return;
    await api.moveConversation(conversationId, groupId);
    conversations[index].groupId = groupId;
    _adjustGroupCounts(previousGroupId, groupId);
    notifyListeners();
  }

  void _adjustGroupCounts(String? fromGroupId, String? toGroupId) {
    if (fromGroupId == toGroupId) return;

    void adjust(String? groupId, int delta) {
      if (groupId == null) return;
      final index = groups.indexWhere((group) => group.id == groupId);
      if (index < 0) return;
      final group = groups[index];
      groups[index] = ChatGroup(
        id: group.id,
        userId: group.userId,
        name: group.name,
        description: group.description,
        customInstruction: group.customInstruction,
        style: group.style,
        tone: group.tone,
        conversationCount: (group.conversationCount + delta)
            .clamp(0, 1 << 30)
            .toInt(),
        createdAt: group.createdAt,
        updatedAt: group.updatedAt,
      );
    }

    adjust(fromGroupId, -1);
    adjust(toGroupId, 1);
  }

  Future<void> switchWorkspace(WorkspaceType workspace) async {
    if (workspace == activeWorkspace ||
        !availableWorkspaces.any((item) => item.type == workspace)) {
      return;
    }
    activeWorkspace = workspace;
    activeId = null;
    conversations.clear();
    notifyListeners();
    await loadConversations();
    if (conversations.isNotEmpty) await setActive(conversations.first.id);
    if (workspace == WorkspaceType.research) await loadResearchProjects();
  }

  Future<void> loadResearchProjects({bool force = false}) async {
    if (loadingResearchProjects || (researchProjectsLoaded && !force)) return;
    loadingResearchProjects = true;
    notifyListeners();
    try {
      researchProjects
        ..clear()
        ..addAll(await api.listResearchProjects());
      researchProjectsLoaded = true;
    } catch (error) {
      if (!_handled401(error)) rethrow;
    } finally {
      loadingResearchProjects = false;
      notifyListeners();
    }
  }

  Future<ResearchProject> createResearchProject(
    String name,
    String description,
  ) async {
    final project = await api.createResearchProject(
      name.trim(),
      description.trim(),
    );
    researchProjects.insert(0, project);
    notifyListeners();
    return project;
  }

  Future<ResearchProject> updateResearchProject(
    String id, {
    required String name,
    required String description,
  }) async {
    final updated = await api.updateResearchProject(
      id,
      name: name.trim(),
      description: description.trim(),
    );
    final index = researchProjects.indexWhere((item) => item.id == id);
    if (index >= 0) researchProjects[index] = updated;
    notifyListeners();
    return updated;
  }

  Future<void> archiveResearchProject(String id) async {
    await api.archiveResearchProject(id);
    researchProjects.removeWhere((item) => item.id == id);
    notifyListeners();
  }

  Future<void> openResearchProject(ResearchProject project) async {
    final existing = conversations.where(
      (item) => item.researchProjectId == project.id,
    );
    if (existing.isNotEmpty) {
      await setActive(existing.first.id);
      return;
    }
    final conversation = await api.createWorkspaceConversation(
      WorkspaceType.research,
      researchProjectId: project.id,
    );
    conversations.insert(0, conversation);
    _messages[conversation.id] = [];
    activeId = conversation.id;
    notifyListeners();
  }

  Future<void> openTeachingContext(
    TeachingClass classroom, {
    TeachingAssignment? assignment,
  }) async {
    if (activeWorkspace != WorkspaceType.teaching) {
      await switchWorkspace(WorkspaceType.teaching);
    }
    final existing = conversations.where(
      (item) =>
          item.classId == classroom.id && item.assignmentId == assignment?.id,
    );
    if (existing.isNotEmpty) {
      await setActive(existing.first.id);
      return;
    }
    final conversation = await api.createWorkspaceConversation(
      WorkspaceType.teaching,
      classId: classroom.id,
      assignmentId: assignment?.id,
    );
    conversations.insert(0, conversation);
    _messages[conversation.id] = [];
    activeId = conversation.id;
    notifyListeners();
  }

  Future<void> setActive(String id) async {
    activeId = id;
    notifyListeners();
    if (!_messages.containsKey(id)) {
      await _loadMessages(id);
    }
  }

  Future<void> _loadMessages(String id) async {
    loadingMessages = true;
    notifyListeners();
    try {
      final msgs = await api.getMessages(id);
      _messages[id] = msgs;
    } catch (e) {
      if (_handled401(e)) return;
      _messages[id] = [];
    } finally {
      loadingMessages = false;
      notifyListeners();
    }
  }

  bool get _activeConversationIsEmpty {
    final id = activeId;
    return id == null ||
        (_messages.containsKey(id) && (_messages[id]?.isEmpty ?? true));
  }

  Future<void> newConversation() async {
    // Keep the initial blank state empty unless a group selection explicitly
    // asks for a conversation to be created inside it.
    if (activeId == null && activeGroupId == null) return;
    if (activeId != null && _activeConversationIsEmpty) return;
    // 先立即切换到空白页，避免网络延迟期间还看到旧对话。
    activeId = null;
    notifyListeners();
    await _createConversation();
  }

  Future<void> _createConversation() async {
    final pending = _conversationCreation;
    if (pending != null) {
      await pending;
      return;
    }
    final operation = _createConversationImpl();
    _conversationCreation = operation;
    try {
      await operation;
    } finally {
      if (identical(_conversationCreation, operation)) {
        _conversationCreation = null;
      }
    }
  }

  Future<void> _createConversationImpl() async {
    try {
      final conv = activeWorkspace == WorkspaceType.learning
          ? await api.createConversation(groupId: activeGroupId)
          : await api.createWorkspaceConversation(
              activeWorkspace,
              groupId: activeGroupId,
            );
      conversations.insert(0, conv);
      _messages[conv.id] = [];
      activeId = conv.id;
      notifyListeners();
    } catch (e) {
      if (!_handled401(e)) rethrow;
    }
  }

  Future<void> renameConversation(String id, String title) async {
    final t = title.trim();
    if (t.isEmpty) return;
    for (final c in conversations) {
      if (c.id == id) c.title = t;
    }
    notifyListeners();
    try {
      await api.renameConversation(id, t);
    } catch (e) {
      if (!_handled401(e)) rethrow;
    }
  }

  Future<void> deleteConversation(String id) async {
    final index = conversations.indexWhere((c) => c.id == id);
    final removedGroupId = index >= 0 ? conversations[index].groupId : null;
    try {
      await api.deleteConversation(id);
    } catch (e) {
      if (_handled401(e)) return;
      rethrow;
    }
    conversations.removeWhere((c) => c.id == id);
    _messages.remove(id);
    _pinned.remove(id);
    _adjustGroupCounts(removedGroupId, null);
    if (activeId == id) {
      activeId = conversations.isNotEmpty ? conversations.first.id : null;
      if (activeId != null && !_messages.containsKey(activeId)) {
        await _loadMessages(activeId!);
      }
    }
    notifyListeners();
  }

  void togglePin(String id) {
    if (_pinned.contains(id)) {
      _pinned.remove(id);
    } else {
      _pinned.add(id);
    }
    for (final c in conversations) {
      if (c.id == id) c.pinned = _pinned.contains(id);
    }
    notifyListeners();
  }

  // ============ 发送消息 ============
  Future<void> send(
    String text, {
    bool markdown = false,
    String? displayText,
    List<String> attachmentIds = const [],
    List<DocumentAttachment> attachments = const [],
  }) async {
    final input = text.trim();
    if (input.isEmpty || busy) return;

    // 没有活动对话时先建一个
    if (activeId == null) {
      await _createConversation();
      if (activeId == null) return; // 建失败
    }
    final id = activeId!;
    final list = _messages.putIfAbsent(id, () => []);

    final visibleInput = (displayText ?? input).trim();
    final selectedAttachmentIds = attachmentIds.isNotEmpty
        ? attachmentIds
        : attachments.map((item) => item.id).toList();
    final userMessage = ChatMessage.user(
      visibleInput,
      markdown: markdown,
      attachments: attachments,
    );
    list.add(userMessage);
    _touchConversation(id, visibleInput);

    final placeholder = ChatMessage.typingPlaceholder();
    list.add(placeholder);
    busy = true;
    notifyListeners();

    try {
      if (streamOn) {
        await _receiveStream(
          id,
          input,
          list,
          placeholder,
          attachmentIds: selectedAttachmentIds,
          userMessage: userMessage,
        );
      } else {
        final newMsgs = selectedAttachmentIds.isEmpty
            ? await api.sendMessage(id, input)
            : await api.sendMessageWithAttachments(
                id,
                input,
                selectedAttachmentIds,
              );
        list.remove(placeholder);
        list.addAll(newMsgs.where((message) => !message.isUser));
        notifyListeners();
      }
    } catch (e) {
      if (placeholder.text.isEmpty && placeholder.reasoning.isEmpty) {
        list.remove(placeholder);
      } else {
        placeholder.typing = false;
      }
      if (_handled401(e)) return;
      // 手机浏览器切后台/锁屏/断网会掐断 SSE，但后端通常已完成生成并
      // 落库；先尝试用服务端持久化结果覆盖本地，只有拉不到时才报错
      final recovered = await _recoverInterruptedReply(id, list);
      if (!recovered) {
        final detail = e is ApiException ? e.detail : '无法连接服务器 请检查后端是否启动';
        list.add(
          ChatMessage(
            id: DateTime.now().microsecondsSinceEpoch.toString(),
            role: MessageRole.assistant,
            text: '（出错了：$detail）',
          ),
        );
      }
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  /// SSE 中断后从服务端拉取持久化消息，就地覆盖当前列表。
  /// 拉到以助手回复结尾的完整历史返回 true。
  Future<bool> _recoverInterruptedReply(
    String id,
    List<ChatMessage> list,
  ) async {
    try {
      final msgs = await api.getMessages(id);
      if (msgs.isEmpty || msgs.last.isUser) return false;
      list
        ..clear()
        ..addAll(msgs);
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }

  Future<void> _receiveStream(
    String conversationId,
    String input,
    List<ChatMessage> list,
    ChatMessage assistant, {
    List<String> attachmentIds = const [],
    ChatMessage? userMessage,
    int? replaceMessageId,
  }) async {
    var completed = false;
    final reasoningQueue = Queue<String>();
    final contentQueue = Queue<String>();
    Timer? typewriterTimer;
    Completer<void>? queueDrained;
    var streamEnded = false;

    void completeDrainIfReady() {
      if (!streamEnded ||
          reasoningQueue.isNotEmpty ||
          contentQueue.isNotEmpty) {
        return;
      }
      typewriterTimer?.cancel();
      typewriterTimer = null;
      final completer = queueDrained;
      if (completer != null && !completer.isCompleted) completer.complete();
    }

    void ensureTypewriter() {
      queueDrained ??= Completer<void>();
      typewriterTimer ??= Timer.periodic(EsaMotion.streamTick, (_) {
        // 手机浏览器后台会把定时器节流到秒级，回前台时队列可能积压了
        // 几千字符；按积压量批量出队，积压过大时直接整段刷出，
        // 避免以每 tick 一个字符的速度补播几十秒
        String takeFrom(Queue<String> queue) {
          var take = queue.length > 600 ? queue.length : queue.length ~/ 20;
          if (take < 1) take = 1;
          final buffer = StringBuffer();
          while (take-- > 0 && queue.isNotEmpty) {
            buffer.write(queue.removeFirst());
          }
          return buffer.toString();
        }

        if (reasoningQueue.isNotEmpty) {
          assistant.reasoning += takeFrom(reasoningQueue);
          assistant.notifyListeners();
        } else if (contentQueue.isNotEmpty) {
          assistant.text += takeFrom(contentQueue);
          assistant.notifyListeners();
        }
        completeDrainIfReady();
      });
    }

    void enqueue(Queue<String> queue, String delta) {
      if (delta.isEmpty) return;
      queue.addAll(delta.characters);
      ensureTypewriter();
    }

    Future<void> finishTypewriter() async {
      streamEnded = true;
      if (reasoningQueue.isEmpty && contentQueue.isEmpty) {
        queueDrained ??= Completer<void>()..complete();
      } else {
        ensureTypewriter();
      }
      completeDrainIfReady();
      await queueDrained!.future;
    }

    try {
      // 手机浏览器锁屏/切网时 fetch 流可能既不报错也不再有数据；相邻
      // 事件间隔超过 120 秒视为挂死，结束流走中断恢复。只在 Web 上
      // 启用：原生平台连接中断会正常抛错，而且 Stream.timeout 的假
      // 定时器会挂死 FakeAsync 测试环境。
      var events = replaceMessageId != null
          ? api.streamRevisedMessage(
              conversationId,
              input,
              replaceMessageId,
              attachmentIds,
            )
          : attachmentIds.isEmpty
          ? api.streamMessage(conversationId, input)
          : api.streamMessageWithAttachments(
              conversationId,
              input,
              attachmentIds,
            );
      if (kIsWeb) {
        events = events.timeout(
          const Duration(seconds: 120),
          onTimeout: (sink) => sink.close(),
        );
      }
      await for (final event in events) {
        switch (event.event) {
          case 'start':
            final persistedId = event.data['user_message_id']?.toString();
            if (persistedId != null && persistedId.isNotEmpty) {
              userMessage?.id = persistedId;
              userMessage?.notifyListeners();
            }
            break;
          case 'reasoning':
            enqueue(reasoningQueue, event.data['delta'] as String? ?? '');
          case 'content':
            enqueue(contentQueue, event.data['delta'] as String? ?? '');
          case 'tool_start':
            list.remove(assistant);
            list.add(
              ChatMessage(
                id:
                    event.data['id']?.toString() ??
                    DateTime.now().microsecondsSinceEpoch.toString(),
                role: MessageRole.tool,
                name: event.data['name'] as String?,
                toolRunning: true,
              ),
            );
            list.add(assistant);
            notifyListeners();
          case 'tool_progress':
            // 后端长任务心跳；保留调用中卡片并刷新 Web 的 SSE 超时计时。
            break;
          case 'tool':
            final toolId = event.data['id']?.toString();
            final toolIndex = toolId == null
                ? -1
                : list.indexWhere(
                    (message) => message.isTool && message.id == toolId,
                  );
            if (toolIndex >= 0) {
              final tool = list[toolIndex];
              tool.text = event.data['content']?.toString() ?? '';
              tool.toolRunning = false;
              tool.notifyListeners();
            } else {
              // 兼容尚未发送 tool_start 的旧后端。
              list.remove(assistant);
              list.add(
                ChatMessage(
                  id:
                      toolId ??
                      DateTime.now().microsecondsSinceEpoch.toString(),
                  role: MessageRole.tool,
                  name: event.data['name'] as String?,
                  text: event.data['content']?.toString() ?? '',
                ),
              );
              list.add(assistant);
            }
            notifyListeners();
          case 'done':
            await finishTypewriter();
            completed = true;
            assistant.typing = false;
            if (assistant.text.isEmpty && assistant.reasoning.isEmpty) {
              list.remove(assistant);
              notifyListeners();
            } else {
              assistant.notifyListeners();
            }
          case 'error':
            throw ApiException(
              500,
              event.data['detail'] as String? ?? '生成回复失败',
            );
        }
      }
    } finally {
      typewriterTimer?.cancel();
      if (!completed) {
        assistant.reasoning += reasoningQueue.join();
        assistant.text += contentQueue.join();
        reasoningQueue.clear();
        contentQueue.clear();
        assistant.notifyListeners();
        for (final message in list.where(
          (message) => message.isTool && message.toolRunning,
        )) {
          message.toolRunning = false;
          if (message.text.isEmpty) {
            message.text = '工具调用未完成：连接已中断';
          }
          message.notifyListeners();
        }
        notifyListeners();
      }
    }

    if (!completed) {
      throw ApiException(500, '流式连接意外中断');
    }
  }

  Future<DocumentAttachment> uploadConversationAttachment({
    required String filename,
    required Stream<List<int>> stream,
    required int length,
  }) async {
    if (activeId == null) {
      await _createConversation();
    }
    final conversationId = activeId;
    if (conversationId == null) {
      throw ApiException(0, '无法创建对话，请稍后重试');
    }
    return api.uploadConversationAttachment(
      conversationId: conversationId,
      filename: filename,
      stream: stream,
      length: length,
    );
  }

  Future<void> removeConversationAttachment(
    DocumentAttachment attachment,
    String conversationId,
  ) async {
    await api.deleteConversationAttachment(conversationId, attachment.id);
  }

  Future<void> reviseUserMessage(ChatMessage message, String text) async {
    final conversationId = activeId;
    final messageId = int.tryParse(message.id);
    final input = text.trim();
    if (conversationId == null || messageId == null || input.isEmpty || busy) {
      return;
    }
    final list = _messages[conversationId];
    final index = list?.indexWhere((item) => identical(item, message)) ?? -1;
    if (list == null || index < 0) return;
    message.text = input;
    message.notifyListeners();
    if (index + 1 < list.length) list.removeRange(index + 1, list.length);
    final placeholder = ChatMessage.typingPlaceholder();
    list.add(placeholder);
    busy = true;
    notifyListeners();
    try {
      await _receiveStream(
        conversationId,
        input,
        list,
        placeholder,
        attachmentIds: message.attachments.map((item) => item.id).toList(),
        userMessage: message,
        replaceMessageId: messageId,
      );
    } catch (error) {
      final recovered = await _recoverInterruptedReply(conversationId, list);
      if (!recovered) {
        list.remove(placeholder);
        list.add(
          ChatMessage(
            id: DateTime.now().microsecondsSinceEpoch.toString(),
            role: MessageRole.assistant,
            text: '（修改消息失败：${error is ApiException ? error.detail : '网络异常'}）',
          ),
        );
      }
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  void regenerate(String assistantMessageId) {
    final id = activeId;
    if (id == null || busy) return;
    final list = _messages[id];
    if (list == null) return;
    final index = list.indexWhere((m) => m.id == assistantMessageId);
    if (index < 0) return;
    String? prompt;
    for (var i = index - 1; i >= 0; i--) {
      if (list[i].isUser) {
        prompt = list[i].text;
        break;
      }
    }
    if (prompt != null) {
      final source = list.lastWhere(
        (message) => message.isUser && message.text == prompt,
      );
      send(prompt, markdown: source.markdown);
    }
  }

  void _touchConversation(String id, String firstInput) {
    final conv = activeConversation;
    if (conv == null || conv.id != id) return;
    conv.updatedAt = DateTime.now();
    if (conv.title == '新对话') {
      final title = firstInput.length > 18
          ? '${firstInput.substring(0, 18)}…'
          : firstInput;
      conv.title = title;
      // 持久化标题 忽略结果
      api.renameConversation(id, title).catchError((_) {});
    }
  }

  // ============ 设置 ============
  Future<void> loadPreferencesAndProfile() async {
    loadingProfile = true;
    notifyListeners();
    try {
      final values = await Future.wait([
        api.getPreferences(),
        api.getProfile(),
      ]);
      preferences = values[0] as UserPreferences;
      userProfile = values[1] as UserProfile;
    } catch (e) {
      if (!_handled401(e)) rethrow;
    } finally {
      loadingProfile = false;
      notifyListeners();
    }
  }

  Future<void> loadLearningOverview() async {
    if (!api.isLoggedIn || loadingLearningOverview) return;
    loadingLearningOverview = true;
    learningOverviewError = null;
    notifyListeners();
    try {
      final values = await Future.wait([
        api.getLearningCourses(),
        api.getMasteryReport(),
      ]);
      learningCourses = values[0] as List<LearningCourseSummary>;
      masteryReport = values[1] as MasteryReport;
    } on ApiException catch (error) {
      if (!_handled401(error)) learningOverviewError = error.detail;
    } catch (_) {
      learningOverviewError = '学习概览暂时无法加载';
    } finally {
      loadingLearningOverview = false;
      notifyListeners();
    }
  }

  Future<String?> savePreferencesAndProfile({
    required String preferredStyle,
    required String preferredTone,
    required String customInstruction,
    required String major,
    required String grade,
    required int currentWeek,
    required int totalWeeks,
    required bool profileEnabled,
  }) async {
    if (currentWeek > totalWeeks) return '当前教学周不能大于学期总周数';
    try {
      final values = await Future.wait([
        api.updatePreferences(
          preferredStyle: preferredStyle,
          preferredTone: preferredTone,
          customInstruction: customInstruction,
        ),
        api.updateProfile(
          major: major,
          grade: grade,
          currentWeek: currentWeek,
          totalWeeks: totalWeeks,
          profileEnabled: profileEnabled,
        ),
      ]);
      preferences = values[0] as UserPreferences;
      userProfile = values[1] as UserProfile;
      notifyListeners();
      return null;
    } on ApiException catch (e) {
      if (e.isUnauthorized) _clearSession();
      return e.detail;
    } catch (_) {
      return '无法连接服务器 请稍后重试';
    }
  }

  void setThemeMode(ThemeMode mode) {
    themeMode = mode;
    notifyListeners();
  }

  void setStreamOn(bool v) {
    streamOn = v;
    notifyListeners();
  }

  void setToolsOn(bool v) {
    toolsOn = v;
    notifyListeners();
  }

  void setCodeEditorIndentSize(int value) {
    if (value != 2 && value != 4 && value != 8) return;
    codeEditorIndentSize = value;
    notifyListeners();
    unawaited(_persistCodeEditorSetting(_codeEditorIndentSizeKey, value));
  }

  void setCodeEditorTheme(String value) {
    if (!isCodeEditorTheme(value)) return;
    codeEditorTheme = value;
    notifyListeners();
    unawaited(_persistCodeEditorSetting(_codeEditorThemeKey, value));
  }

  Future<void> _persistCodeEditorSetting(String key, Object value) async {
    final localPreferences = await _getLocalPreferences();
    if (localPreferences == null) return;
    if (value is int) await localPreferences.setInt(key, value);
    if (value is String) await localPreferences.setString(key, value);
  }

  void updateProfile({String? name, String? mail}) {
    if (name != null && name.trim().isNotEmpty) api.username = name.trim();
    if (mail != null) email = mail.trim();
    notifyListeners();
  }
}

/// 通过 InheritedNotifier 把 AppState 传给整棵子树
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child})
    : super(notifier: state);

  static AppState of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope != null, 'AppScope not found in widget tree');
    return scope!.notifier!;
  }
}
