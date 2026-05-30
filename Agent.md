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
- 订阅管理：`add_subscription()` / `remove_subscription()` / `get_subscriptions()`

### login_core.py — 扫码登录

- `CloakAuthenticator` 启动浏览器实例，打开登录页，截取二维码
- `LoginTaskState` 作为 async 信号桥，协调二维码就绪与扫码完成事件

### config.py — 配置与数据

- 路径常量：`AUTH_STATE_FILE`、`QR_FILE`、`SUBSCRIBE_FILE`
- URL 模板：`COMMUNITY_URL`（主页）、`TOPIC_URL_TEMPLATE`（社区）
- `load_subscriptions()` / `save_subscriptions()` — JSON 订阅数据持久化

## 命令列表

| 命令 | 功能 |
|------|------|
| `/hb` | 抓取主页热帖 TOP 5 |
| `/hbpush` | 从订阅社区抓取热帖 TOP 8 |
| `/hbsub <ID>` | 订阅社区 |
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
  "group_id_1": ["18745", "425422"],
  "group_id_2": ["18745"]
}
```

社区ID为链接 `https://www.xiaoheihe.cn/app/topic/link/{topic_id}` 中的数字部分。
