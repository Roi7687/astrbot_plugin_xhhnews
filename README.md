# astrbot_plugin_xhhnews

小黑盒社区热帖抓取与推送 AstrBot 插件。通过 Cloakbrowser 无头浏览器爬取小黑盒热帖，以 Markdown + 拼接封面图的形式推送到群聊，支持社区订阅和 QQ 键盘按钮。

## 功能

- **主页热帖抓取** — 从小黑盒主页抓取热度 TOP 5 帖子
- **社区订阅推送** — 订阅指定社区，从多个社区合并抓取热帖 TOP 8
- **名称搜索订阅** — 输入社区名称自动搜索并订阅，无需手动查找 ID
- **封面图拼接** — 将帖子封面按 2×4 网格拼接为一张图发送
- **Markdown 消息** — 使用 QQ Markdown 格式展示帖子摘要
- **QQ 键盘按钮** — 支持 QQ 官方平台的快捷操作按钮
- **扫码登录** — 通过二维码完成小黑盒账号登录

## 安装

1. 确保 AstrBot 已安装 `cloakbrowser`、`Pillow`、`httpx` 依赖
2. 将本仓库克隆到 AstrBot 插件目录：

```bash
cd /path/to/astrbot/data/plugins
git clone https://github.com/Roi7687/astrbot_plugin_xhhnews.git
```

3. 在 AstrBot 管理界面启用插件

## 命令

| 命令 | 功能 |
|------|------|
| `/hb` | 抓取主页热帖 TOP 5 |
| `/hbpush` | 从订阅社区抓取热帖 TOP 8 |
| `/hbsub <ID 或 名称>` | 订阅社区 |
| `/hbunsub <ID>` | 取消订阅 |
| `/hbsublist` | 查看订阅列表 |
| `/hblogin` | 扫码登录小黑盒 |
| `/hbhelp` | 显示帮助 |

## 使用流程

```
/hblogin          # 首次使用需扫码登录
/hb               # 抓取主页热帖
/hbsub 数码硬件   # 按名称搜索并订阅社区
/hbsub 18745      # 或直接用 ID 订阅
/hbpush           # 从所有订阅社区抓取热帖
```

## 依赖

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — 插件框架
- [cloakbrowser](https://pypi.org/project/cloakbrowser/) — 反检测无头浏览器
- [Pillow](https://pypi.org/project/Pillow/) — 图片处理
- [httpx](https://pypi.org/project/httpx/) — 异步 HTTP 客户端

## License

AGPL-3.0
