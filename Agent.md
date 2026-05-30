# 小黑盒热帖推送插件 — 开发文档

AstrBot 插件，通过 Cloakbrowser 爬取小黑盒社区热帖，以 Markdown + 拼接封面图的形式推送到群聊。

## 项目结构

```
main.py                 # 插件入口，命令注册与消息发送
metadata.yaml           # 插件元数据
core/
    config.py           # 路径常量、订阅数据读写
    login_core.py       # 扫码登录流程
    scraper_core.py     # 浏览器抓取、图片拼接、Markdown 格式化、键盘按钮、订阅管理
    xhh_api.py          # 小黑盒 API 签名工具（hkey/nonce 生成）
```

## 核心模块

### scraper_core.py — 抓取与格式化

- `fetch_posts()` — 从小黑盒主页抓取帖子列表
- `fetch_topic_posts()` — 从指定社区页面抓取帖子
- `fetch_subscribed_posts()` — 遍历所有订阅社区，合并抓取结果
- `pick_top_posts()` — 按点赞+评论综合热度排序，取前 N 条
- `merge_covers()` — 下载封面图，按 2×4 网格拼接为一张
- `format_top_posts_markdown()` — 生成 QQ Markdown 格式文本
- `build_keyboard()` — 构建 QQ 官方键盘按钮数据
- `search_topic()` — 通过浏览器搜索框搜索社区，返回 (topic_id, topic_name)
- `fetch_topic_name()` — 从社区页面抓取社区名称
- 订阅管理：`add_subscription()` / `remove_subscription()` / `get_subscriptions()`

### login_core.py — 扫码登录

- `CloakAuthenticator` 启动浏览器实例，打开登录页，截取二维码
- `LoginTaskState` 作为 async 信号桥，协调二维码就绪与扫码完成事件

### config.py — 配置与数据

- 路径常量：`AUTH_STATE_FILE`、`QR_FILE`、`SUBSCRIBE_FILE`
- URL 模板：`COMMUNITY_URL`（主页）、`TOPIC_URL_TEMPLATE`（社区）
- `load_subscriptions()` / `save_subscriptions()` — JSON 订阅数据持久化（兼容旧 list 格式）

### xhh_api.py — API 签名

基于小黑盒 Web 前端逆向的 hkey/nonce 生成算法。关键发现：
- hkey 使用 `t+1` 时间偏移（`Wm[3]="g"`, `lv.g = ov(e, t+1, n)`）
- 交错拼接不排序，按原始顺序逐位取字符
- `Km` 函数需保留全部 6 元素求和（JS 修改原数组前 4 位后 reduce 对全部元素求和）

## 命令列表

| 命令 | 功能 |
|------|------|
| `/hb` | 抓取主页热帖 TOP 5 |
| `/hbpush` | 从订阅社区抓取热帖 TOP 8 |
| `/hbsub <ID 或 名称>` | 订阅社区（支持 ID 和名称搜索） |
| `/hbunsub <ID>` | 取消订阅 |
| `/hbsublist` | 查看订阅列表 |
| `/hblogin` | 扫码登录 |
| `/hbhelp` | 帮助 |

## 消息格式

- 封面图先下载并拼接为 2×4 网格（单张图片），通过 `event.image_result()` 发送
- 帖子摘要以 QQ Markdown（`msg_type=2`）发送，支持标题、引用、链接等语法
- QQ 官方平台额外支持键盘按钮（`keyboard` 参数），非 QQ 平台回退纯文本

## 依赖

- `cloakbrowser` — 反检测无头浏览器
- `Pillow` — 图片下载与拼接
- `httpx` — 异步图片下载
- `astrbot` — 插件框架与消息组件

## 订阅数据格式

存储在 `subscriptions.json`：

```json
{
  "group_id_1": {"18745": "数码硬件", "425422": "Steam"},
  "group_id_2": {"18745": "数码硬件"}
}
```

社区ID为链接 `https://www.xiaoheihe.cn/app/topic/link/{topic_id}` 中的数字部分。
