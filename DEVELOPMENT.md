# 开发文档（v1.4.0）

小黑盒「新游速报」插件：`/hbnews` 抓取小黑盒本周发售日历 → 交给
`astrbot_plugin_aisearch`（Playwright 驱动 DeepSeek 网页版）联网核验口碑与评分 →
精选 4~8 款值得玩的游戏输出。所有小黑盒数据都走其 HTTP 接口（复刻 APP 请求），
签名复用 Web 端 hkey 算法，**不需要登录**。

> **当前指令面只有两个**：`/hbnews`（AI 速报）与 `/hbhelp`（帮助）。
> 月度日历的抓取与排版能力保留在 `calendar_core.py` / `calendar_format.py` 里
> （没有指令入口），恢复方法见文末「[恢复月度指令](#恢复月度指令)」。
>
> 跨插件调用的通用原理与实践见仓库根目录的
> [`ASTRBOT_CROSS_PLUGIN_CALL.md`](ASTRBOT_CROSS_PLUGIN_CALL.md)，本文只讲本插件的实现。

## 1. 架构与数据流

```
                    ┌────────────────────────────── main.py ──────────────────────────────┐
/hbnews ──────────► │ news_command                                                          │
                    │   ├─ XhhCalendarCore.fetch_week()        ← core/calendar_core.py     │
                    │   ├─ format_week_digest(days)            ← core/calendar_format.py   │
                    │   ├─ event.send("正在联网核验…")          ← 进度提示（紧跟 msg_id）    │
                    │   ├─ ask_ai_review(context, digest)      ← core/ai_review.py         │
                    │   │     ├─ build_ai_prompt()（模板填清单）                            │
                    │   │     └─ peer_plugin.ask_peer_text()   ← core/peer_plugin.py        │
                    │   │           └─ aisearch._send_query(prompt, [])                     │
                    │   │                 └─ DeepSeek 网页版（联网检索）                    │
                    │   ├─ format_week_review_markdown(review)  ← 原样返回模型正文          │
                    │   └─ _reply() → QQ 键盘 Markdown / 普通 Markdown                     │
                    └──────────────────────────────────────────────────────────────────────┘

失败路径：任一步失败 → ask_ai_review 返回 "" → format_week_review_fallback(days)
         → 「本周完整日历 + 一句说明」；日历主功能永不受影响。
```

- 数据抓取约 0.5~1s（本周 46 款、全部带标签与 AppID）；
- AI 环节现场实测 **33~53s**（浏览器自动化 + 联网搜索），提示词约 5100 字；
- 输出经 `clean_answer()` 归一化并按 `AI_REVIEW_MAX_CHARS` 截断，实测 7 款约 2062 字符。

## 2. 项目结构

```
main.py                  # 插件入口：/hbnews、/hbhelp、启动自检、消息发送
metadata.yaml            # 插件元数据（name/display_name/desc/version v1.4.0）
core/
    config.py            # 接口常量 + AI 速报配置
    calendar_core.py     # 发售日历抓取（数据模型、接口调用、标签补全）
    calendar_format.py   # 玩家日历排版 + 喂给 AI 的精简清单排版
    ai_review.py         # 定稿提示词 + 跨插件调用 + 失败降级
    peer_plugin.py       # 通用跨插件调用封装（注册表取实例 / 超时 / 兜异常）
    tag_cache.py         # 游戏标签的本地缓存
    xhh_api.py           # 小黑盒 API 签名工具（hkey/nonce 生成）
tests/                   # 65 项单元测试（桩对象，不发网络、不起浏览器）
research/                # 开发期联调脚本与真实链路产物（不属于运行时）
ASTRBOT_CROSS_PLUGIN_CALL.md  # 跨插件调用指南（本插件实践参考）
```

## 3. 模块速查

| 模块 | 关键内容 |
|------|----------|
| `main.py` | `XhhCalendarPlugin.news_command`（唯一业务指令）、`help_command`、`_ai_selfcheck` + `@filter.on_astrbot_loaded`、`_send_progress`、`_reply` / `_try_send_with_keyboard` / `_build_keyboard` |
| `core/config.py` | `CALENDAR_API_HOST`、`TAG_CACHE_FILE`、`AI_REVIEW_*` 配置项、`AuthError` |
| `core/calendar_core.py` | `GameItem` / `DayRelease`、`fetch_week()`（唯一在用）、`fetch_month()` 等月度能力（保留）、`enrich_tags()`、`_clean_tags()` |
| `core/calendar_format.py` | `format_week_digest()`（AI 输入）、`format_week_review_markdown()`（恒等返回）、`format_week_review_fallback()`、`format_week_markdown()` / `format_month_markdown()`（月度排版保留） |
| `core/ai_review.py` | `AI_REVIEW_PROMPT`（定稿提示词）、`build_ai_prompt()`、`clean_answer()`、`ask_ai_review()` |
| `core/peer_plugin.py` | `resolve_peer()`、`call_peer()`、`ask_peer_text()`、`arm_peer_idle_timer()` |
| `core/tag_cache.py` | `steam_appid -> tags` 持久化缓存（TTL 7 天） |
| `core/xhh_api.py` | `generate_sign_params(path)`（hkey/nonce/time） |

## 4. 小黑盒接口口径

接口来自小黑盒 APP 1.3.395 反编译（`com.max.xiaoheihe.network.HeyBoxService`），
域名 `https://api.xiaoheihe.cn`，**路径在根级别，没有 `/bbs/app/api` 前缀**：

| 用途 | 路径 | 说明 |
|------|------|------|
| 单日完整列表 | `/game/release_calendar/game_list/single_day` | 参数 `day_timestamp`；补本周已过去的日子 |
| 批量窗口 | `/game/release_calendar/game_list` | 返回「当天起约 8 天」的分组，`hot_tags` 最全 |
| 每日数量 | `/game/release_calendar/game_count` | 覆盖 24 个月（月度概览用，当前无指令入口） |
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

### 标签是怎么来的

1. `hot_tags[].desc` —— 日历接口直接给（仅限未来日期）；
2. 缺标签时用 `steam_appid` 查 `/game/get_game_detail/`，取
   `common_tags` 中 `type == "simple_tag"` 的 `desc`；
3. 结果写入 `tag_cache.json`（7 天有效，环境变量 `XHH_TAG_CACHE` 可覆盖路径）；
4. 仍然没有标签时，展示层退化显示平台（`PC` / `主机` / `手机`）。

标签清洗规则（`_clean_tags`）：

- 丢弃营销/状态类噪音：`心愿单热门`、`近期热销`、`折扣` 等（见 `_NOISE_TAGS`）；
- 丢弃 `支持中文`、`支持手柄` 这类平台功能标签（正则 `_NOISE_TAG_RE`）；
- **保留** `独立`、`抢先体验`、`单人`、`在线合作` —— 这些是 Steam 的真实分类。

> 注意：`GameItem.tags` 只存真实玩法标签，平台兜底放在 `GameItem.display_tag` 属性里；
> 否则 `enrich_tags()` 会把兜底值当「已有标签」而跳过补全（踩过的坑）。

### 请求策略（当前只走本周）

- 本周：批量窗口一次覆盖「今天起约 8 天」，本周里已过去的日子再用 `single_day` 补；
- 标签补全单次上限 40（本周），未补完的留到下次查询继续；
- 月度策略（`fetch_month`，当前无指令入口）：批量窗口 + 逐日补，约 24 次请求，标签上限 80。

## 5. AI 速报链路细节

### 5.1 提示词结构（`core/ai_review.py` → `AI_REVIEW_PROMPT`）

| 段落 | 作用 |
|------|------|
| `# 任务边界（最高优先级）` | 忽略此前对话上下文、不提问、不输出思考过程、无开场白/结束语 |
| `# 角色与目标` | 资深评测编辑；从本周清单挑 4~8 款，宁缺毋滥 |
| `**核心入选标准**` | 质量好评优先 → 3A/大厂/经典 IP → 高口碑独立黑马 → 一票否决首发翻车 |
| `# 一、 联网检索与核验规则` | 10~15 款候选初筛（关注数门槛）、搜索锚点（AppID/英文名）、特殊身份识别、数据防幻觉铁律 |
| `# 二、 输出格式（严格执行）` | 禁一级标题/开场白/总结语/避雷板块；按综合推荐度排序；四要素排版模板 |
| `# 三、 待分析数据` | 占位符 `{{在此处填入本周新游清单}}`，由 `build_ai_prompt()` 替换 |

- **改口味只改这段文本**：`build_ai_prompt()` 只做占位符替换与超长截断，不拼业务规则；
- 单测 `tests/test_ai_review.py::TestPrompt` 会校验关键规则是否存在，改提示词后同步调整断言；
- 输出格式由提示词定死，所以 `format_week_review_markdown()` 是**恒等函数**（原样返回）。

### 5.2 「AI 可见清单」（`format_week_digest`）

比玩家日历多给三类检索锚点，格式一行一款：

```
【本周范围】2026-10-12（周一）→ 2026-10-18（周日），今天是 2026-10-18（周日）
【统计】本周共 46 款新游，按发售日排列
【清单】（格式：序号. 名称 ｜ 发售日 ｜ 玩法标签 ｜ 平台 ｜ 小黑盒关注数 ｜ Steam AppID）
28. 雾锁王国 ｜ 10-15 周四 ｜ 动作 / 冒险 / 独立 ｜ PC ｜ 关注 292536 ｜ AppID 1203620
```

- **Steam AppID**：中文译名搜不到/重名时最可靠的锚点；
- **平台**：`steam/pc → PC`、`console → 主机` 等规范化，避免清单里一列全是 `STEAM`；
- **小黑盒关注数**：提示词用它做「必查 ≥ 10,000」的初筛依据；
- 超长按 `AI_REVIEW_MAX_INPUT_CHARS`（默认 4000）截断并标注「清单过长，已截断」。

### 5.3 跨插件调用与降级矩阵

使用 `core/peer_plugin.py`（原理见 `ASTRBOT_CROSS_PLUGIN_CALL.md`）：

```
resolve_peer(context, "astrbot_plugin_aisearch")
  → 判 activated / star_cls
  → getattr(inst, "_send_query") 并确认 callable
  → asyncio.wait_for(inst._send_query(prompt, []), timeout=180)
  → 解析 (created, answer)（created 只表示是否新建会话，不代表成功）
  → 成功后 arm_peer_idle_timer(inst)
```

任何异常只记日志、不外抛，降级行为如下：

| 情况 | 行为 |
|------|------|
| aisearch 未安装 / 被禁用 / `star_cls` 为空 | 降级：本周完整日历 + 一句说明 |
| 对方没有 `_send_query`（版本不兼容） | 同上（日志 WARNING） |
| `AuthError`（未登录）/ 其它异常 | 同上 |
| 超时（默认 180s） | 同上 |
| 返回空内容 | 同上 |
| 成功 | 原样输出 AI 正文 |

> 铁律：**每次现取实例、不缓存**（对方热重载会换 `star_cls`）；
> **不 import 对方异常类**（避免硬依赖）；QQ 被动回复窗口 5 分钟，所以超时上限不宜超过 240s。

## 6. 指令与消息格式

### `/hbnews` 执行顺序

1. `fetch_week()` 取本周数据；`total == 0` 直接回「本周暂无发售数据」；
2. `format_week_digest()` 生成 AI 清单；
3. `_send_progress()` → `event.send(MessageChain().message("🔎 正在联网核验…"))`
   **立即发出**（`yield` 要等 handler 结束才由 RespondStage 统一发送，起不到提示作用）；
4. `ask_ai_review()` 等待 AI（失败则空串）；
5. 排版：成功 → 原样 AI 正文；失败 → `format_week_review_fallback()`；
6. `_reply()`：QQ 官方平台优先发「Markdown + 键盘按钮」（`msg_type=2`），
   按钮为「🔄 重新核验 `/hbnews`」「❓ 帮助 `/hbhelp`」；其它平台回退普通 Markdown。

消息格式约定：

- QQ Markdown（`msg_type=2`），支持标题、引用、列表、加粗等；
- **不发送图片**；
- 键盘直发时 `msg_seq` 用随机值，避免与同 `msg_id` 下的进度提示重复
  （QQ 文档：相同 `msg_id + msg_seq` 重复发送会失败，被动消息最多回复 5 次）；
- 启动自检：`__init__` 里 `strict=False` 只记 DEBUG；`@filter.on_astrbot_loaded()` 里
  `strict=True`，此时代码里所有插件都已注册，解析不到会记 WARNING。

## 7. 配置项（`core/config.py`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `AI_REVIEW_ENABLED` | `True` | AI 速报总开关（False 时 `/hbnews` 直接回提示） |
| `AI_REVIEW_PLUGIN` | `astrbot_plugin_aisearch` | 目标插件名（对应其 `metadata.yaml` 的 `name:`） |
| `AI_REVIEW_METHOD` | `_send_query` | 目标方法；对方改版时优先改这里 |
| `AI_REVIEW_TIMEOUT` | `180.0` | 等 AI 回复上限（秒） |
| `AI_REVIEW_MAX_CHARS` | `2800` | AI 正文上限（超出截断并补 `…`） |
| `AI_REVIEW_MAX_INPUT_CHARS` | `4000` | AI 清单上限 |
| `AI_REVIEW_PROGRESS_HINT` | `True` | 是否先发「正在联网核验…」提示 |
| `TAG_CACHE_FILE` | `<plugin>/tag_cache.json` | 标签缓存路径（环境变量 `XHH_TAG_CACHE` 可覆盖） |

## 8. 测试与验证

### 8.1 单元测试（65 项，不联网、不起浏览器）

```bash
python -m unittest discover -s tests -t . -v
```

| 文件 | 项数 | 覆盖 |
|------|------|------|
| `tests/test_commands.py` | 7 | 指令面守卫：恰好 `/hbnews` `/hbhelp`、无别名、旧指令零残留、按钮只指向有效指令、帮助文本、metadata 与 `@register` 版本一致 |
| `tests/test_ai_review.py` | 29 | Prompt 六段规则断言、清单填/截断、回答修剪、跨插件成功/各类降级 |
| `tests/test_peer_plugin.py` | 21 | `resolve_peer` / `call_peer` / `ask_peer_text` / `arm_peer_idle_timer` 的 10 个分支 |
| `tests/test_calendar_format.py` | 8 | AI 清单字段（AppID/平台/关注数）、恒等排版、降级输出 |

### 8.2 真实链路验证脚本（`research/`）

脚本里硬编码了本机实例路径（`D:\Program Files\.astrbot_launcher\instances\...`），
换机器需先改开头的 `INSTANCE` 常量。

```bash
# 1) 只验证抓数 + 拼 AI 清单/提示词（快，不调用 AI）
<instance>/venv/Scripts/python.exe research/verify_ai_review.py --fetch-only

# 2) 完整链路：真实小黑盒数据 → 真实 aisearch(DeepSeek) → 最终消息形态
#    产物写到 research/verify_output/（prompt.txt / ai_review_raw.txt / final_reply.md）
<instance>/venv/Scripts/python.exe research/verify_ai_review.py

# 3) 在**运行中的 AstrBot** 里真实发指令并收集回复（走 WebChat 平台通道，自签 Dashboard JWT）
<instance>/venv/Scripts/python.exe research/verify_in_astrbot.py /hbnews
```

> 验证时注意：aisearch 是浏览器自动化，单次 30~90s，且内部 `asyncio.Lock` 串行化；
> 另一个进程直接起 `DeepSeekSessionCore` 会占用一份浏览器资源，别和线上同时压测。

### 8.3 实测基线（2026-10-18，本周 46 款）

| 指标 | 数值 |
|------|------|
| 日历抓取 | 0.7~0.9s（46 款全部带标签与 AppID） |
| AI 调用（离线脚本 / AstrBot 在线） | 53.4s / 42.0s |
| 输出 | 5~7 款、1956~2062 字符，无截断 |

## 9. 排障清单

| 现象 | 排查顺序 |
|------|----------|
| 日志 `AI 精选不可用：未安装/未加载插件` | aisearch 是否安装、启用、插件名是否改成别的 |
| 日志 `插件 ... 处于未激活（被禁用）状态` | 管理面板启用 aisearch |
| 日志 `没有方法 _send_query` | aisearch 版本变了：改 `AI_REVIEW_METHOD` 或适配对方入口 |
| 日志 `AuthError: ...` / `未检测到登录凭证` | 重新登录 aisearch（`/cloak登录`），确认 `auth_state.json` 有效 |
| 日志 `超时（>180s）` | 对方浏览器启动慢/多人排队/深度思考长文，适当加大 `AI_REVIEW_TIMEOUT` |
| 用户只收到「本周完整日历」 | 即降级路径生效；看 WARNING 日志定位原因 |
| QQ 收不到键盘消息 | 平台非 QQ 官方，自动回退普通 Markdown（属预期） |
| 抓数失败/`SSL EOF` | 小黑盒限流，稍后重试；代码已有 2/6/14s 退避 |

## 10. 已知限制

- 已过去日期的标签必须逐个查详情接口（本周首次查询慢几秒），命中缓存后很快；
- 日历接口无官方文档，参数口径可能随 APP 版本变化，升级后需重新验证；
- 批量接口每天最多返回 30 款，月末某天超过 30 款时会有截断；
- `/hbnews` 依赖 aisearch 的登录态与空闲浏览器；单次 20~90 秒，多人同时用会排队，
  超时（默认 180s）降级为本周完整日历；
- AI 与 aisearch 共用同一个 DeepSeek 会话：提示词第一段已要求忽略此前上下文，
  但仍可能被上一轮对话轻微影响，想要完全干净可先 `/ais new`；
- 评分与口碑来自 AI 实时联网检索，不同时间/多次调用结果可能不同（属预期）。

## 恢复月度指令

月度抓取与排版函数没有删除，加回一个 handler 即可（可选地把 `fetch_month` 的
月份参数解析也加回来）：

```python
from .core.calendar_format import format_month_markdown

@filter.command("hbmonth")
async def month_command(self, event: AstrMessageEvent):
    releases, counts, total = await self.calendar.fetch_month()
    target = releases[0].date
    md_text = format_month_markdown(
        releases, counts, total, target.year, target.month, self.calendar.today(),
    )
    result = await self._reply(event, md_text, [("❓ 帮助", "/hbhelp")])
    if result is not None:
        yield result
```

> 注意：`tests/test_commands.py` 会断言指令面只有两个，加回旧指令后需要同步更新该测试。

## 变更记录

| 版本 | 变更 |
|------|------|
| **v1.4.0**（2026-10-18） | 新增 `/hbnews`（定稿 Prompt 的 AI 新游速报，只输出 4~8 款游戏列表）；指令精简为 `/hbnews` + `/hbhelp`，移除 `/hbweek`、`/hbmonth`、`/hbreview`（BREAKING）；新增 `peer_plugin.py`、`ai_review.py`、65 项单测与真实链路验证脚本 |
| v1.3.0（2026-10-17） | 新增 AI 精选（`/hbreview`）：跨插件调用 aisearch 联网核验；启动自检、进度提示、降级、AI 可见清单（AppID/平台/关注数） |
| v1.2.0 | 移除热帖抓取；发售日历补全玩法标签；不再发送图片 |
| v1.1.0 及更早 | 游戏发售日历（`/hbweek`、`/hbmonth`）、社区订阅、名称搜索等早期功能 |
