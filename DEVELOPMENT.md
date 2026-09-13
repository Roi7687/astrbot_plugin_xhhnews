# 开发文档

小黑盒游戏发售日历插件。所有数据都走小黑盒的 HTTP 接口（复刻 APP 请求），
签名复用 Web 端的 hkey 算法，**不需要登录**。

## 项目结构

```
main.py                  # 插件入口：命令注册与消息发送
metadata.yaml            # 插件元数据
core/
    config.py            # 路径常量、接口域名、共用异常
    calendar_core.py     # 发售日历抓取（数据模型、接口调用、标签补全）
    calendar_format.py   # 发售日历的 Markdown 排版
    tag_cache.py         # 游戏标签的本地缓存
    xhh_api.py           # 小黑盒 API 签名工具（hkey/nonce 生成）
```

## 核心模块

### config.py — 配置与数据

- `PLUGIN_DIR`、`TAG_CACHE_FILE` — 插件目录与标签缓存路径
- `CALENDAR_API_HOST` — 接口域名 `https://api.xiaoheihe.cn`
- `CALENDAR_PAGE_URL` — APP 内日历页路由（仅作参考，不可直接 HTTP 访问）

### xhh_api.py — API 签名

基于小黑盒 Web 前端逆向的 hkey/nonce 生成算法。关键发现：

- hkey 使用 `t+1` 时间偏移（`Wm[3]="g"`, `lv.g = ov(e, t+1, n)`）
- 交错拼接不排序，按原始顺序逐位取字符
- `Km` 函数需保留全部 6 元素求和（JS 修改原数组前 4 位后 reduce 对全部元素求和）

`generate_sign_params(path)` 产出全套公共参数（`os_type` / `client_type` /
`version` / `hkey` / `_time` / `nonce` 等）。服务端会强校验：
缺 `hkey` 返回 `hkey 不能为空`，缺 `_time` 返回 `_time 不能为空`。

### calendar_core.py — 发售日历

接口来自小黑盒 APP 1.3.395 反编译（`com.max.xiaoheihe.network.HeyBoxService`），
域名 `https://api.xiaoheihe.cn`，**路径在根级别，没有 `/bbs/app/api` 前缀**：

| 用途 | 路径 | 说明 |
|------|------|------|
| 单日完整列表 | `/game/release_calendar/game_list/single_day` | 参数 `day_timestamp` |
| 批量窗口 | `/game/release_calendar/game_list` | 返回「当天起约 8 天」的分组，`hot_tags` 最全 |
| 每日数量 | `/game/release_calendar/game_count` | 覆盖 24 个月，整月概览用它 |
| 筛选项 | `/game/release_calendar/filters` | `filter_hot`(all/hot)、`filter_platform`(pc/xbox/switch/ps4) |
| 游戏详情 | `/game/get_game_detail/` | 参数 `steam_appid`，历史日期的标签只能靠它 |

关键口径（均为实测结论，改代码前务必读）：

- 签名复用 Web 端 hkey 算法，`heybox_id=-1` 即可，**无需登录**；
- `day_timestamp` 只认「当天及以后」，传过去的日期会返回今天起的窗口；
- `offset` / `limit` / `page` **被服务端忽略**，批量接口按组截断（每天最多 30 款）；
- `game_count` 是唯一整月完整的数据源，`count_by_day[].count` 与 `single_day` 实际条数一致；
- **已过去日期的 `hot_tags` 返回 `null`**，只有未来日期才有玩法标签；
- 详情接口一次只能查一款游戏（`appids` 参数是另一个接口，且 `genres` 为空）；
- 请求过密会被直接掐断连接（`SSL EOF`），需低并发 + 退避重试
  （日历接口并发 3，重试间隔 2/6/14 秒，最多 4 次；详情接口并发 4）。

#### 标签是怎么来的

1. `hot_tags[].desc` —— 日历接口直接给（仅限未来的日期）；
2. 缺标签时用 `steam_appid` 查 `/game/get_game_detail/`，取
   `common_tags` 中 `type == "simple_tag"` 的 `desc`；
3. 结果写入 `tag_cache.json`（7 天有效），避免重复请求；
4. 仍然没有标签时，展示层退化显示平台（`PC` / `主机` / `手机`）。

标签清洗规则（`_clean_tags`）：

- 丢弃营销/状态类噪音：`心愿单热门`、`近期热销`、`折扣` 等（见 `_NOISE_TAGS`）；
- 丢弃 `支持中文`、`支持手柄` 这类平台功能标签（正则 `_NOISE_TAG_RE`）；
- **保留** `独立`、`抢先体验`、`单人`、`在线合作` —— 这些是 Steam 的真实分类。

> 注意：`GameItem.tags` 只存真实玩法标签，平台兜底放在
> `GameItem.display_tag` 属性里。否则 `enrich_tags()` 会把兜底值当
> 「已有标签」而跳过补全（这是踩过的坑）。

#### 请求策略

- 本周：批量窗口一次覆盖「今天起约 8 天」，本周里已过去的日子再用 `single_day` 补；
- 本月：先用批量窗口覆盖月初之后的日子，剩余日子逐个 `single_day`，共约 24 次请求；
- 标签补全有单次上限（本周 40、本月 80），未补完的留到下次查询继续。

### calendar_format.py — 排版

- 本周：每天「游戏名 + 标签」列表
- 本月：每天「游戏名 + 第一个标签」，配一个月概览（每天几款）
- 历史日期无明细时，退化为「本月早些时候（仅统计）」的数量行

### tag_cache.py — 标签缓存

`{"<steam_appid>": {"tags": [...], "ts": <int>}}`，TTL 7 天。
写入用「临时文件 + `os.replace`」，失败只记日志不影响主流程。
路径可用环境变量 `XHH_TAG_CACHE` 覆盖（便于测试）。

## 命令列表

| 命令 | 功能 |
|------|------|
| `/hbweek` | 本周游戏发售日历 |
| `/hbmonth [YYYY-MM]` | 本月（或指定月份）游戏发售日历 |
| `/hbhelp` | 帮助 |

## 消息格式

- 文本以 QQ Markdown（`msg_type=2`）发送，支持标题、引用、列表等语法
- QQ 官方平台额外支持键盘按钮（`keyboard` 参数），非 QQ 平台回退纯文本
- **不发送图片**

## 数据存储

只有 `tag_cache.json`（已在 `.gitignore` 中，不要提交）。

## 本地调试

```bash
# 语法检查
python -m py_compile main.py core/*.py

# 集成测试：用 AstrBot 运行环境加载插件并跑命令，
# 结果写入 tools/plugin_test_out.txt
<astrbot venv>/python.exe tools/test_calendar.py week month month-bad help
```

`tools/` 下的脚本是开发期联调工具，不属于插件运行时。
调试接口时注意：**连续快速请求会被限流**（连接被掐断），脚本里都加了间隔。

## 依赖

- `astrbot` — 插件框架与消息组件
- `httpx` — 异步 HTTP 客户端

## 已知限制

- 已过去日期的标签必须逐个查详情接口，首次查询本月会慢（约 30 秒）
- 日历接口无官方文档，参数口径可能随 APP 版本变化，升级后需重新验证
- 批量接口每天最多返回 30 款，月末某天超过 30 款时会有截断
