# 开发文档

小黑盒「新游速报」插件。所有数据都走小黑盒的 HTTP 接口（复刻 APP 请求），
签名复用 Web 端的 hkey 算法，**不需要登录**。

> 当前插件只暴露 `/hbnews`（AI 新游速报）与 `/hbhelp` 两个指令。
> 月度日历的抓取与排版能力保留在 `calendar_core.py` / `calendar_format.py` 里
> （没有指令入口），需要恢复时在 `main.py` 加回一个 `@filter.command` handler 即可。

## 项目结构

```
main.py                  # 插件入口：命令注册与消息发送
metadata.yaml            # 插件元数据
core/
    config.py            # 路径常量、接口域名、共用异常、AI 精选配置
    calendar_core.py     # 发售日历抓取（数据模型、接口调用、标签补全）
    calendar_format.py   # 发售日历的 Markdown 排版 + 喂给 AI 的清单排版
    ai_review.py         # AI 精选：提示词模板 + 跨插件调用 + 降级
    peer_plugin.py       # 通用跨插件调用封装（注册表取实例 / 超时 / 兜异常）
    tag_cache.py         # 游戏标签的本地缓存
    xhh_api.py           # 小黑盒 API 签名工具（hkey/nonce 生成）
tests/                   # 单元测试（桩对象，不发网络、不起浏览器）
research/                # 开发期联调脚本（真实链路验证，不属于运行时）
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

- 本周：每天「游戏名 + 类型标签」列表（AI 不可用时的降级输出）
- 本月：每天「游戏名 + 第一个标签」+ 月概览（**函数保留、当前无指令入口**）
- 历史日期无明细时，退化为「本月早些时候（仅统计）」的数量行
- `format_week_digest()`：**喂给 AI** 的紧凑清单（「AI 可见」的超集，见下）
- `format_week_review_markdown()` / `format_week_review_fallback()`：AI 精选正文

> 定稿提示词已经把输出格式写死（只输出入选列表、禁止标题/开场白/总结语/避雷板块），
> 所以 `format_week_review_markdown()` **原样返回模型正文**，插件不再加自己的排版。

### ai_review.py + peer_plugin.py — AI 精选（跨插件调用）

把「本周新游清单」交给 `astrbot_plugin_aisearch`（Playwright 驱动 DeepSeek 网页版），
由模型联网检索口碑后挑出值得玩的游戏。链路与取舍：

```
fetch_week() → format_week_digest() → build_ai_prompt()（模板填清单）
            → aisearch._send_query(prompt, [])  ← 跨插件调用（peer_plugin）
            → clean_answer() → format_week_review_markdown() / 降级
```

关键设计（与 `ASTRBOT_CROSS_PLUGIN_CALL.md` 一致）：

- **提示词与代码解耦**：`AI_REVIEW_PROMPT` 是纯文本常量，占位符
  `{{在此处填入本周新游清单}}` 由 `build_ai_prompt()` 替换 —— 想改筛选口味/输出格式，
  只改这一段文本，不用动代码，也不用重载之外的任何操作；
- **「AI 可见 ≠ 玩家可见」**：清单里额外给了 **Steam AppID / 平台 / 小黑盒关注数**，
  这些字段不出现在玩家的周历里，但能让模型联网时准确定位游戏（中文译名搜不到时靠 AppID）、
  判断平台、并优先核验热门作品；
- **每次现取实例、不缓存**：对方插件热重载会换实例（`star_cls`），缓存旧引用必炸；
- **尽力而为 + 降级**：未安装 / 未激活 / 未登录 / 超时 / 抛异常 / 空回复，一律只记日志并
  返回空串，`main.py` 自动降级为「本周完整日历 + 一句说明」，日历主功能永不受影响；
- **善后**：调用方绕过了对方自己的 `_respond()`，所以成功后来一次
  `arm_peer_idle_timer()`，替对方重置会话空闲计时器，避免无头浏览器常驻。

可在 `config.py` 调整的项：`AI_REVIEW_ENABLED`（总开关）、`AI_REVIEW_PLUGIN` /
`AI_REVIEW_METHOD`（对方插件名与方法，改版时改这里）、`AI_REVIEW_TIMEOUT`（默认 180s）、
`AI_REVIEW_MAX_CHARS` / `AI_REVIEW_MAX_INPUT_CHARS`（输出/输入长度上限）、
`AI_REVIEW_PROGRESS_HINT`（等待期间是否先发「正在核验」提示）。

> aisearch 单次耗时通常 **20~90s**（浏览器自动化 + 联网搜索），且内部 `asyncio.Lock`
> 串行化：多人同时用会排队，超时就降级。QQ 被动回复窗口是 5 分钟，所以超时上限不宜超过 240s。

### tag_cache.py — 标签缓存

`{"<steam_appid>": {"tags": [...], "ts": <int>}}`，TTL 7 天。
写入用「临时文件 + `os.replace`」，失败只记日志不影响主流程。
路径可用环境变量 `XHH_TAG_CACHE` 覆盖（便于测试）。

## 命令列表

| 命令 | 功能 |
|------|------|
| `/hbnews` | AI 联网核验本周新游，精选 4~8 款值得玩的（AI 不可用时降级为本周完整日历） |
| `/hbhelp` | 帮助 |

## 消息格式

- 文本以 QQ Markdown（`msg_type=2`）发送，支持标题、引用、列表等语法
- QQ 官方平台额外支持键盘按钮（`keyboard` 参数），非 QQ 平台回退纯文本
- **不发送图片**
- `/hbnews` 会先 `event.send()` 一条「正在联网核验…」提示（`AI_REVIEW_PROGRESS_HINT`），
  再发最终结果 —— 因为 `yield` 的结果要等 handler 结束才由 RespondStage 统一发出，
  起不到「先告诉用户」的作用

## 数据存储

只有 `tag_cache.json`（已在 `.gitignore` 中，不要提交）。

## 本地调试

```bash
# 语法检查
python -m py_compile main.py core/*.py

# 单元测试（桩对象，不发网络、不起浏览器；覆盖跨插件调用的 10 个分支）
python -m unittest discover -s tests -t . -v
```

`research/` 下是真实链路验证脚本（需要 AstrBot 的 venv，脚本里硬编码了本机实例路径）：

```bash
# 1) 只验证抓数 + 拼 AI 清单/提示词（快，不调用 AI）
<instance>/venv/Scripts/python.exe research/verify_ai_review.py --fetch-only

# 2) 完整链路：真实小黑盒数据 → 真实 aisearch(DeepSeek) → 最终 QQ Markdown
#    产物写到 research/verify_output/（prompt.txt / ai_review_raw.txt / final_reply.md）
<instance>/venv/Scripts/python.exe research/verify_ai_review.py

# 3) 在**运行中的 AstrBot** 里真实发一条指令并收集回复（走 WebChat 平台通道）
<instance>/venv/Scripts/python.exe research/verify_in_astrbot.py /hbnews
```

调试接口时注意：**连续快速请求会被限流**（连接被掐断），脚本里都加了间隔。

## 依赖

- `astrbot` — 插件框架与消息组件
- `httpx` — 异步 HTTP 客户端
- `astrbot_plugin_aisearch` — **可选**。不装也能用 `/hbhelp`，
  只是 `/hbnews` 会降级为「本周完整日历 + 说明」

## 已知限制

- 已过去日期的标签必须逐个查详情接口（本周首次查询会慢几秒），命中缓存后很快
- 日历接口无官方文档，参数口径可能随 APP 版本变化，升级后需重新验证
- 批量接口每天最多返回 30 款，月末某天超过 30 款时会有截断
- `/hbnews` 的 AI 环节依赖 aisearch 的登录态（`auth_state.json`）；单次 20~90 秒，
  多人同时用会排队，超时（默认 180s）就降级为本周完整日历
- AI 与 aisearch 共用同一个 DeepSeek 会话，提示词开头已要求「忽略此前上下文」，
  但仍可能被上一轮对话轻微影响；想要完全干净可让用户先 `/ais new` 开新会话
