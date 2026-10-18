# astrbot_plugin_xhhnews

小黑盒「新游速报」AstrBot 插件 —— `/hbnews` 抓取小黑盒本周发售日历，交给
[`astrbot_plugin_aisearch`](https://github.com/Roi7687/astrbot_plugin_aisearch)（DeepSeek 联网搜索）
逐款核验口碑与评分，**从几十款新游里挑出 4~8 款真正值得玩的 3A 与高口碑独立游戏**。
数据与小黑盒 APP 的「游戏发售日历」同源，无需登录。

> 当前版本 **v1.4.0**：只保留 `/hbnews` 与 `/hbhelp` 两个指令。
> 旧版 `/hbweek`、`/hbmonth`、`/hbreview` 已下线（详见[更新日志](#-更新日志)）。

## ✨ 功能

- **`/hbnews` 本周新游速报**：抓本周发售清单 → AI 联网核验
  Steam 好评率 / Metacritic / OpenCritic → 输出 4~8 款精选，
  每款给出「类型与玩法 + 评价与反馈」两段式点评（约 30~90 秒）。
- **`/hbhelp` 帮助**：两个指令的用法说明。
- **无需登录**：直接调用小黑盒公开接口，不需要账号或扫码。
- **优雅降级**：aisearch 未安装 / 未启用 / 未登录 / 超时都不会报错，
  自动降级为「本周完整日历 + 一句说明」。

## 📦 安装

1. AstrBot 需已安装 `httpx` 依赖（AstrBot 自带）；
2. 克隆到 AstrBot 插件目录：

```bash
cd /path/to/astrbot/data/plugins
git clone https://github.com/Roi7687/astrbot_plugin_xhhnews.git
```

3. 在 AstrBot 管理面板启用插件（插件名 `xhhnews` / 显示名「小黑盒新游速报」）；
4. （可选，但强烈建议）安装并登录 `astrbot_plugin_aisearch`，`/hbnews` 的 AI 速报才可用。

> 更新插件：`git pull` 后在管理面板重载插件即可。

## 🎮 命令

| 命令 | 功能 | 耗时 |
|------|------|------|
| `/hbnews` | AI 联网核验本周新游，精选 4~8 款值得玩的 | 约 30~90 秒（先回一条「正在联网核验…」提示） |
| `/hbhelp` | 显示帮助 | 立即 |

`/hbnews` 的工作流：

```
小黑盒本周发售日历 → 拼「AI 可见清单」→ DeepSeek 联网检索候选游戏口碑
                 → 按关注数/好评率/媒体分筛选 → 4~8 款精选（原样输出模型正文）
```

## 🧠 AI 速报的筛选口径

提示词在 [`core/ai_review.py`](core/ai_review.py) 的 `AI_REVIEW_PROMPT`（用户定稿版，
改口味只改这段文本，不用动代码），核心规则：

1. **任务边界最高优先级**：忽略此前对话上下文、不提问、不输出思考过程、直接按格式输出；
2. **候选要联网核验**：先按小黑盒关注数初筛 10~15 款候选（关注数 ≥ 10,000 必查，
   4,000~10,000 里挑标签独特/知名工作室的潜力独立游戏），再逐款检索
   `Steam 好评率 / 评测`、`Metacritic / OpenCritic`；中文名搜不到时用 **Steam AppID 或英文原名**；
3. **入选标准（按优先级）**：质量与好评（Steam ≥ 80% 或 MC/OC ≥ 80）→
   重磅 3A / 知名大厂 / 经典 IP 新作（关注数通常 > 3 万）→ 口碑爆棚的独立佳作；
4. **一票否决**：粗制滥造、换皮模拟器、AI 劣质游戏，以及关注度高但首发翻车
   （Steam 好评率 < 70% 且差评集中在恶性 Bug / 优化灾难 / 内容缩水）的作品；
5. **特殊身份必须标注**：EA 转 1.0 正式版、重制 / 移植 / DLC、周末刚解锁的新作
   （样本 < 50 也不漏掉，标注「刚解锁样本少」）；
6. **数据防幻觉**：严禁编造评分与模糊区间（如 `53%~66%`），只标 Steam / MC / OC / IGN
   等原始评分平台，不写二手资讯网；全球与简中评价差 > 15% 时必须点明简中好评率及原因；
7. **输出格式**：只输出 4~8 款入选游戏，按「综合推荐度（质量+关注度）」排序，
   每款包含 `游戏名 + 发售日期 + 类型玩法 + 评价反馈` 四要素；
   禁止一级标题、开场白、总结语、避雷板块、表格与代码块。

> 插件对 AI 正文**不做二次排版**，原样发出 —— 保证最终样式完全由提示词决定。

## ⚙️ 配置

所有可调项都在 [`core/config.py`](core/config.py)（改完重载插件生效）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `AI_REVIEW_ENABLED` | `True` | AI 速报总开关；关掉后 `/hbnews` 只回提示 |
| `AI_REVIEW_PLUGIN` | `astrbot_plugin_aisearch` | 跨插件调用的目标插件名 |
| `AI_REVIEW_METHOD` | `_send_query` | 目标方法：`async (prompt, images) -> (created, answer)` |
| `AI_REVIEW_TIMEOUT` | `180.0` | 等 AI 回复的上限（秒）；超时降级为本周日历 |
| `AI_REVIEW_MAX_CHARS` | `2800` | AI 正文上限（4~8 款实测约 2000~2500 字符） |
| `AI_REVIEW_MAX_INPUT_CHARS` | `4000` | 喂给 AI 的新游清单上限（超长截断并标注） |
| `AI_REVIEW_PROGRESS_HINT` | `True` | 等待期间是否先发「正在联网核验…」提示 |

## 🖼️ 输出示例

`/hbnews` 真实实测输出（节选，格式由提示词定稿）：

```
**1. 〈雾锁王国 Enshrouded〉｜ 发售日期：10-15（PC/PS5，1.0正式版）**

* **类型与玩法**：KeenGames打磨近三年的体素生存动作RPG，1.0补全了残缺的地图并迎来故事阶段性结局……
* **评价与反馈**：Steam好评率85%［约9.5万篇评测］｜MC 89［9家媒体］。简中好评率约65%，与全球好评差距明显……
  适合《英灵神殿》式生存建造爱好者。

**2. 〈越过山丘 over the hill〉｜ 发售日期：10-14（PC，首发）**

* **类型与玩法**：《绝对漂移》《拉力赛艺术》团队Funselektor Labs的新作，荒野驾车探索游戏……
* **评价与反馈**：Steam好评率92.5%［约1,098篇评测］。玩家盛赞驾驶手感、美术和沉浸感……
```

更多实测记录见 [`research/verify_output/`](research/verify_output/)。

## ❓ 常见问题

**Q：`/hbnews` 只回了「本周完整日历 + AI 精选暂不可用」？**
A：说明 aisearch 不可用或超时。依次检查：插件是否启用 → `auth_state.json` 登录态是否有效 →
是否有人正在占用 aisearch（内部串行，多人同时用会排队）→ 适当调大 `AI_REVIEW_TIMEOUT`。

**Q：为什么 AI 和我在 `/ais` 里聊的内容串了？**
A：插件复用 aisearch 的「当前会话」。提示词第一段已要求忽略此前上下文，影响很小；
想完全干净可先发 `/ais new` 开新会话再 `/hbnews`。

**Q：想换推荐口味 / 改输出格式？**
A：只改 [`core/ai_review.py`](core/ai_review.py) 的 `AI_REVIEW_PROMPT`，重载插件即可；
单测 `tests/test_ai_review.py` 里的 Prompt 结构断言可能需要同步更新。

**Q：原来的 `/hbweek` / `/hbmonth` 怎么没了？**
A：v1.4.0 起指令精简为两个。月度日历的抓取与排版能力仍保留在 `core/` 里（无指令入口），
恢复方法见 [DEVELOPMENT.md](DEVELOPMENT.md) 的「恢复月度指令」章节。

**Q：为什么每次结果不一样？**
A：评分与口碑来自 AI 实时联网检索，样本与来源会随时间变化，属正常现象。

## 🗂️ 项目结构

```
main.py                  # 插件入口：/hbnews、/hbhelp、启动自检、消息发送
metadata.yaml            # 插件元数据（v1.4.0）
core/
    config.py            # 接口常量 + AI 速报配置
    calendar_core.py     # 小黑盒发售日历抓取（数据模型 / 签名 / 标签补全）
    calendar_format.py   # 玩家日历排版 + 喂给 AI 的精简清单排版
    ai_review.py         # 定稿提示词 + 跨插件调用 + 失败降级
    peer_plugin.py       # 通用跨插件调用封装（注册表取实例 / 超时 / 兜异常）
    tag_cache.py         # 游戏标签本地缓存（7 天）
    xhh_api.py           # 小黑盒 hkey/nonce 签名
tests/                   # 65 项单元测试（桩对象，不发网络、不起浏览器）
research/                # 真实链路验证脚本与产物（不属于运行时）
ASTRBOT_CROSS_PLUGIN_CALL.md  # 跨插件调用开发指南（本插件实践参考）
```

## 🧪 开发与测试

```bash
# 语法检查
python -m py_compile main.py core/*.py

# 单元测试（65 项：Prompt 规则、跨插件 10 个降级分支、指令面守卫、排版）
python -m unittest discover -s tests -t . -v

# 真实链路验证（需要 AstrBot 的 venv，详见 DEVELOPMENT.md）
<instance>/venv/Scripts/python.exe research/verify_ai_review.py --fetch-only
<instance>/venv/Scripts/python.exe research/verify_in_astrbot.py /hbnews
```

更详细的模块说明、接口口径、排障与恢复指引见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 🔁 更新日志

**v1.4.0（2026-10-18）**
- 新增 `/hbnews`：AI 联网核验本周新游 + 4~8 款精选（提示词为用户定稿版，只输出游戏列表）；
- 指令精简为 `/hbnews`、`/hbhelp`；**移除** `/hbweek`、`/hbmonth`、`/hbreview`（含别名 `/hbtop`、`/新游精选`）；
- 新增 `core/peer_plugin.py`、`core/ai_review.py` 与 65 项单测、真实链路验证脚本；
- 显示名改为「小黑盒新游速报」。

**v1.3.0（2026-10-17）**
- 新增 AI 精选（`/hbreview`）：跨插件调用 aisearch，把本周新游交给 LLM 联网核验；
- 新增启动自检、进度提示、降级与「AI 可见清单」（AppID / 平台 / 关注数）。

**v1.2.0**
- 移除热帖抓取；发售日历补全玩法标签；不再发送图片。

**v1.1.0 及更早**
- 游戏发售日历（`/hbweek`、`/hbmonth`）、社区订阅、名称搜索等早期功能。

## 📚 相关

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — 插件框架
- [astrbot_plugin_aisearch](https://github.com/Roi7687/astrbot_plugin_aisearch) — AI 联网核验能力来源
- [ASTRBOT_CROSS_PLUGIN_CALL.md](ASTRBOT_CROSS_PLUGIN_CALL.md) — AstrBot 跨插件调用指南

## License

AGPL-3.0
