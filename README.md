# astrbot_plugin_xhhnews

小黑盒（玩家社区）内容抓取与推送 AstrBot 插件。支持**社区热帖**抓取推送与
**游戏发售日历**查询，以 Markdown + 拼接封面图的形式发送到群聊。

## 功能

### 社区热帖

- **主页热帖抓取** — 从小黑盒主页抓取热度 TOP 5 帖子
- **社区订阅推送** — 订阅指定社区，从多个社区合并抓取热帖 TOP 8
- **名称搜索订阅** — 输入社区名称自动搜索并订阅，无需手动查找 ID
- **封面图拼接** — 将帖子封面按 2×4 网格拼接为一张图发送
- **QQ 键盘按钮** — 支持 QQ 官方平台的快捷操作按钮
- **扫码登录** — 通过二维码完成小黑盒账号登录

### 游戏发售日历

- **本周日历** `/hbweek` — 一周内每天的新游列表（游戏名 + 类型标签），
  并把当期封面按顺序拼成一张总览图一并发送
- **本月日历** `/hbmonth` — 每天一行「游戏名 + 首个标签」，
  另附整月概览（每天几款），不发送图片
- **指定月份** — `/hbmonth 2026-10` 查看任意月份
- **无需登录** — 日历走独立接口，未登录也能用

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
| `/hbweek` | 本周游戏发售日历（含封面图） |
| `/hbmonth [YYYY-MM]` | 本月游戏发售日历 |
| `/hblogin` | 扫码登录小黑盒 |
| `/hbhelp` | 显示帮助 |

## 使用流程

### 热帖推送

```
/hblogin          # 首次使用需扫码登录
/hb               # 抓取主页热帖
/hbsub 数码硬件   # 按名称搜索并订阅社区
/hbsub 18745      # 或直接用 ID 订阅
/hbpush           # 从所有订阅社区抓取热帖
```

### 发售日历

```
/hbweek           # 本周发售日历（含封面总览图）
/hbmonth          # 本月发售日历
/hbmonth 2026-10  # 指定月份
```

`/hbmonth` 的月份参数也接受 `2026/10`、`2026.10`、`10` 等写法。

## 输出示例

`/hbweek` — 先发封面总览图，再发文字列表：

```
# 🎮 本周游戏发售日历（09-21 ~ 09-27）
> 共 26 款新游 · 数据来自小黑盒
## 9月21日 周一
- 奇迹工厂　`自动化`
- 今天都是腿　`增量`
- 病娇病毒　`恐怖`
## 9月22日 周二
- Ved: 疗愈所　`动作`
- Delverium　`开放世界生存制作`
...
```

`/hbmonth` — 概览 + 每日简表：

```
# 🗓️ 2026年9月游戏发售日历
> 本月共 128 款新游 · 数据来自小黑盒
## 📊 本月概览
1日:7　2日:4　3日:5　4日:9　5日:1　6日-　7日:3
## 🎮 每日发售
### 9月1日 周二（6款）
WheelMates (双轮成行) `PC`、死亡游戏调查报告 `PC`、交叠之夏 `PC`
```

## 说明

- 热帖功能需要先 `/hblogin` 扫码登录；发售日历无需登录
- 日历数据与小黑盒 APP「游戏发售日历」同源
- 已过去日期的游戏标签接口不返回，此时类型显示为平台（PC / 主机 / 手机）
- 数据均来自小黑盒公开接口，请合理控制调用频率

## 依赖

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — 插件框架
- [cloakbrowser](https://pypi.org/project/cloakbrowser/) — 反检测无头浏览器
- [Pillow](https://pypi.org/project/Pillow/) — 图片处理
- [httpx](https://pypi.org/project/httpx/) — 异步 HTTP 客户端

## 开发

模块划分、接口口径与调试方式见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## License

AGPL-3.0
