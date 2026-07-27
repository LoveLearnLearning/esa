// ESA 全局编译期开关
//
// kOfflineMode:
//   true  => 离线模式 不连后端 用本地假数据 任意用户名 + 合法密码即可登录进入对话页
//            适合无后端 / 演示 / 纯前端调试
//   false => 正常模式 通过 ApiClient 调用真实后端 (见 API.md)
//
// 上线前记得改回 false
const bool kOfflineMode = true;
