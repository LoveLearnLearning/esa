# 华中科技大学教务课表导入调研与实现

更新时间：2026-08-18

## 调研结论

华中科技大学本科课表仍由 HUB 系统承载，并通过学校 CAS 统一身份认证。2026 年学校
本科生院的选课通知给出的现行入口是 <https://hubs.hust.edu.cn/>。匿名在线核验显示：

1. `https://hubs.hust.edu.cn/cas/login` 会跳转到 `pass.hust.edu.cn` 的 CAS；
2. CAS 登录页通过 `/cas/rsa` 动态获取 RSA 公钥，将账号、密码分别以 PKCS#1 v1.5
   加密后提交为 `ul`、`pl`，早期项目使用的 DES 流程已经过时；
3. 图形验证码来自 `/cas/code`；
4. 历史课表查询路径 `aam/score/CourseInquiry_ido.action` 仍进入当前鉴权链，但匿名
   状态只能验证路由存在，认证后的完整响应仍需在校生账号做端到端验收。

HUB 可能拒绝校外或云服务器 IP。生产部署如收到 403，需要校园网、学校 VPN 或校内
代理；代码不会尝试绕过学校的访问控制。

## 一手资料

- [华中科技大学 2026-2027 学年第一学期选课通知](https://ugs.hust.edu.cn/info/1142/7482.htm)
- [华中科技大学本科生院](https://ugs.hust.edu.cn/)
- [HUB 学生系统](https://hubs.hust.edu.cn/)
- [华中科技大学统一身份认证](https://pass.hust.edu.cn/cas/login)

## 开源项目评估

| 项目 | 可借鉴内容 | 不直接复用的原因 |
| --- | --- | --- |
| [tctco/hust-timetable](https://github.com/tctco/hust-timetable) | 老 HUB 课表路径与 `start/end/title/txt` 事件形态 | 2020 年 DES 登录已失效，且仓库无明确许可证 |
| [naivekun/libhustpass](https://github.com/naivekun/libhustpass) | CAS 改用 RSA 的公开协议线索 | 许可证标注不一致，且验证码 OCR 与课表领域逻辑不适合本项目 |
| [fhzheng/hustRoom](https://github.com/fhzheng/hustRoom) | 教学楼公开课表参考 | 不是个人选课结果，且无明确许可证 |

本实现采用 clean-room 方式重新编写，只使用公开可观察的协议事实，不复制上述项目源码。

## 本项目实现

导入复用现有课表、用户鉴权、SQLite 和知识地图关联，不建立第二套课表数据模型：

- `POST /me/schedule/import/hust/challenge`：获取登录页、动态 RSA 公钥和验证码，创建
  短期、用户绑定的内存 challenge；此时不接收账号密码。
- `POST /me/schedule/import/hust/complete`：一次性消费 challenge，完成 RSA 登录、
  CAS ticket 跳转、课表查询和解析，再写入当前课表或新课表。
- 具体日期事件按课程、教师、地点、星期和节次合并；只合并连续周，单双周或跳周不会
  被错误扩展成连续区间。
- 解析 `txt` 元数据时仅使用 `json.loads` 或 `ast.literal_eval`，禁止 `eval`。
- 导入后同步 `term_start_date`、总周数和 `user_courses`，使现有课表页与知识地图继续
  使用同一份数据。

## 安全设计

- 密码进入 Pydantic 后立即使用 `SecretStr`；跨字段校验在 SecretStr 构造后执行，
  避免 422 响应回显原始密码。
- 账号、密码、CAS Cookie、ticket 不写 SQLite 或日志；challenge 过期或完成后关闭
  独立 Cookie 会话。
- challenge 按 ESA 用户绑定、一次性消费，同一用户只保留最新一个。
- 登录重定向仅允许配置中的 HUST 主机，拒绝携带 Cookie 跟随 HTTPS 到 HTTP。
- Flutter 客户端只允许向 HTTPS 或 localhost/模拟器本机地址提交教务凭据。

## 配置

默认值基于 2026 年学校入口和匿名在线核验，部署时可用环境变量覆盖：

```text
HUST_CAS_LOGIN_URL=https://hubs.hust.edu.cn/cas/login
HUST_CAPTCHA_URL=https://pass.hust.edu.cn/cas/code
HUST_RSA_URL=https://pass.hust.edu.cn/cas/rsa
HUST_SERVICE_URL=https://hubs.hust.edu.cn/cas/login
HUST_QUERY_URL=https://hubs.hust.edu.cn/aam/score/CourseInquiry_ido.action
HUST_CHALLENGE_TTL=300
HUST_HTTP_TIMEOUT=20
```

## 发布前真实账号验收

自动测试不包含真实华科学号或密码。合并前应由在校生在校园网/VPN 环境完成：

1. 导入包含单双周、实验课、不同校区和调课日期的一个学期；
2. 对照 HUB 核验课程名、教师、地点、星期、节次和周次；
3. 分别验证验证码错误、密码错误、二次认证、403、空课表和 challenge 过期；
4. 检查日志与 SQLite，确认没有账号、密码、CAS Cookie 或 ticket；
5. 验证导入当前课表与新建课表两种目标，并确认重复/冲突课程的跳过提示。
