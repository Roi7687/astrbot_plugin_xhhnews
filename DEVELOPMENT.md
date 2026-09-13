# 开发文档

本插件有两条完全独立的数据链路，改代码前先确认你在动哪一条：

| 链路 | 通道 | 认证 | 模块 |
|------|------|------|------|
| 社区热帖 | Cloakbrowser 无头浏览器渲染页面后取 DOM | 需要扫码登录 | `scraper_core.py` / `login_core.py` |
| 游戏发售日历 | 直连 HTTP 接口（复刻 APP 请求） | **无需登录** | `calendar_core.py` |

## 项目结构

```
main.py                  # 插件入口，命令注册与消息发送
metadata.yaml            # 插件元数据
core/
    config.py            # 路径常量、URL、订阅数据读写
    login_core.py        # 扫码登录流程
    scraper_core.py      # 浏览器抓取、封面拼接、Markdown 格式化、键盘按钮、订阅管理
    xhh_api.py           # 小黑盒 API 签名工具（hkey/nonce 生成）
    calendar_core.py     # 发售日历抓取（直连接口 + 封面拼接）
    calendar_format.py   # 发售日历的 Markdown 排版
```

## 核心模块

### config.py — 配置与数据

- 路径常量：`AUTH_STATE_FILE`、`QR_FILE`、`SUBSCRIBE_FILE`
- URL 常量：`COMMUNITY_URL`（主页）、`TOPIC_URL_TEMPLATE`（社区）、
  `CALENDAR_API_HOST`（日历接口域名）、`CALENDAR_PAGE_URL`（APP 内日历页路由）
- `load_subscriptions()` / `save_subscriptions()` — JSON 订阅数据持久化（兼容旧 list 格式）

### scraper_core.py — 帖子抓取与格式化

- `fetch_posts()` — 从小黑盒主页抓取帖子列表
- `fetch_topic_posts()` — 从指定社区页面抓取帖子
- `fetch_subscribed_posts()` — 遍历所有订阅社区，合并抓取结果
- `pick_top_posts()` — 按点赞 + 评论综合热度排序，取前 N 条
- `merge_covers()` — 下载封面图，按 2×4 网格拼接为一张
- `format_top_posts_markdown()` — 生成 QQ Markdown 格式文本
- `build_keyboard()` — 构建 QQ 官方键盘按钮数据
- `search_topic()` — 通过浏览器搜索框搜索社区，返回 `(topic_id, topic_name)`
- `fetch_topic_name()` — 从社区页面抓取社区名称
- 订阅管理：`add_subscription()` / `remove_subscription()` / `get_subscriptions()`

> 帖子数据靠 `EXTRACT_POSTS_JS` 在页面里跑一段 JS 取 DOM，
> 所以**小黑盒改版 Web 结构会让抓取失效**，改动集中在那个常量里。

### login_core.py — 扫码登录

- `CloakAuthenticator` 启动浏览器实例，打开登录页，截取二维码
- `LoginTaskState` 作为 async 信号桥，协调「二维码就绪」与「扫码完成」事件
- 登录态落在 `auth_state.json`（已在 `.gitignore` 中）

### xhh_api.py — API 签名

基于小黑盒 Web 前端逆向的 hkey/nonce 生成算法。关键发现：

- hkey 使用 `t+1` 时间偏移（`Wm[3]="g"`, `lv.g = ov(e, t+1, n)`）
- 交错拼接不排序，按原始顺序逐位取字符
- `Km` 函数需保留全部 6 元素求和（JS 修改原数组前 4 位后 reduce 对全部元素求和）

`generate_sign_params(path)` 产出全套公共参数（`os_type` / `client_type` /
`version` / `hkey` / `_time` / `nonce` 等）。**日历接口与帖子接口共用这一套签名**，
服务端对二者都做校验：缺 `hkey` 返回 `hkey 不能为空`，缺 `_time` 返回 `_time 不能为空`。

### calendar_core.py — 游戏发售日历

接口来自小黑盒 APP 1.3.395 反编译（`com.max.xiaoheihe.network.HeyBoxService`），
域名 `https://api.xiaoheihe.cn`，**路径在根级别，没有 `/bbs/app/api` 前缀**：

| 用途 | 路径 | 说明 |
|------|------|------|
| 单日完整列表 | `/game/release_calendar/game_list/single_day` | 参数 `day_timestamp`，本月日历用它 |
| 批量窗口 | `/game/release_calendar/game_list` | 返回「当天起约一周」的分组，标签最全，本周用它 |
| 每日数量 | `/game/release_calendar/game_count` | 覆盖 24 个月，整月概览用它 |
| 筛选项 | `/game/release_calendar/filters` | `filter_hot`(all/hot)、`filter_platform`(pc/xbox/switch/ps4) |

关键口径（均为实测结论，改代码前务必读）：

- 签名复用 Web 端 hkey 算法，`heybox_id=-1` 即可，**无需登录**；
- `day_timestamp` 只认「当天及以后」，传过去的日期会返回今天起的窗口；
- `offset` / `limit` / `page` **被服务端忽略**，批量接口按组截断（每天最多 30 款）；
- `game_count` 是唯一整月完整的数据源，`count_by_day[].count` 与 `single_day` 的实际条数一致；
- **已过去日期的 `hot_tags` 返回 `null`**，只有未来日期才有玩法标签，
  因此历史日期只能退化为 `game_type`（PC/主机/手机）；
- 请求过密会被直接掐断连接（`SSL EOF`），需低并发 + 退避重试
  （`_CONCURRENCY=3`，重试间隔 2/6/14 秒，最多 4 次）。

标签取值顺序：`hot_tags[].desc` → `genres[]` → `game_type`（映射为 PC/主机/手机）。

数据模型：`GameItem`（单款游戏）、`DayRelease`（某一天的列表）。
`CoverCollage` 负责封面拼接：等比缩放 + 居中裁剪，默认 3 列、每格 400×187、最多 24 张，
**不在图上渲染文字**（中文渲染依赖系统字体，跨平台不稳），文字全部交给 Markdown。

### calendar_format.py — 日历排版

- 本周：每天「游戏名 + 标签」列表，封面图另拼成一张 3 列总览图发送
- 本月：每天「游戏名 + 第一个标签」，不发图；配一个月概览（每天几款）
- 历史日期无明细时，本月视图退化为「本月早些时候（仅统计）」的数量行

## 命令列表

| 命令 | 功能 |
|------|------|
| `/hb` | 抓取主页热帖 TOP 5 |
| `/hbpush` | 从订阅社区抓取热帖 TOP 8 |
| `/hbsub <ID 或 名称>` | 订阅社区（支持 ID 和名称搜索） |
| `/hbunsub <ID>` | 取消订阅 |
| `/hbsublist` | 查看订阅列表 |
| `/hbweek` | 本周游戏发售日历（含封面总览图） |
| `/hbmonth [YYYY-MM]` | 本月游戏发售日历（可指定月份） |
| `/hblogin` | 扫码登录 |
| `/hbhelp` | 帮助 |

## 消息格式

- 帖子封面先下载并拼接为 2×4 网格（单张图片），通过 `event.image_result()` 发送
- 日历封面（`/hbweek`）拼接为 3 列总览图，顺序与文字列表一致
- 文本以 QQ Markdown（`msg_type=2`）发送，支持标题、引用、列表等语法
- QQ 官方平台额外支持键盘按钮（`keyboard` 参数），非 QQ 平台回退纯文本
- 临时图片写入系统临时目录，发送后立即删除

## 数据存储

订阅数据存 `subscriptions.json`：

```json
{
  "group_id_1": {"18745": "数码硬件", "425422": "Steam"},
  "group_id_2": {"18745": "数码硬件"}
}
```

社区 ID 为链接 `https://www.xiaoheihe.cn/app/topic/link/{topic_id}` 中的数字部分。

登录态存 `auth_state.json`（Playwright storage_state 格式）。
两个文件都在 `.gitignore` 中，不要提交。

## 本地调试

```bash
# 语法检查
python -m py_compile main.py core/*.py

# 日历核心直连联调（不依赖 AstrBot）
python tools/dry_run_calendar.py
```

`tools/` 下的脚本是开发期用的联调工具，不属于插件运行时，可按需保留或删除。
调试日历接口时注意：**连续快速请求会被限流**，脚本里都加了请求间隔。

## 依赖

- `astrbot` — 插件框架与消息组件
- `cloakbrowser` — 反检测无头浏览器（帖子抓取）
- `Pillow` — 图片下载与拼接
- `httpx` — 异步 HTTP 客户端（日历接口、图片下载）

## 已知限制

- 已过去日期的游戏标签接口不返回，只能显示平台（PC/主机/手机）
- 帖子抓取依赖小黑的 Web 页面结构，对方改版需同步更新 `EXTRACT_POSTS_JS`
- 日历接口无官方文档，参数口径可能随 APP 版本变化，升级后需重新验证
