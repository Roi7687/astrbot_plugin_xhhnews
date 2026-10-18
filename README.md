# astrbot_plugin_xhhnews

小黑盒「新游速报」AstrBot 插件：`/hbnews` 抓取小黑盒本周发售日历，交给
`astrbot_plugin_aisearch`（DeepSeek 联网搜索）核验口碑与评分，
**从几十款新游里挑出 4~8 款真正值得玩的 3A 与高口碑独立游戏**。
数据与小黑盒 APP 的游戏发售日历同源，无需登录。

## 功能

- **`/hbnews` 本周新游速报** — 抓本周发售清单 → AI 联网核验 Steam 好评率 /
  Metacritic / OpenCritic → 输出 4~8 款精选，每款给出「类型玩法 + 评价反馈」两段式点评
  （约 30~90 秒；AI 不可用时自动降级为本周完整日历）
- **`/hbhelp` 帮助** — 命令说明
- **无需登录** — 直接调用小黑盒公开接口，不需要账号或扫码

> 插件只保留这两个指令。月度日历的抓取/排版能力仍保留在 `core/` 里（当前没有指令入口），
> 以后想恢复只需在 `main.py` 里加回 handler。

## 安装

1. 确保 AstrBot 已安装 `httpx` 依赖
2. 将本仓库克隆到 AstrBot 插件目录：

```bash
cd /path/to/astrbot/data/plugins
git clone https://github.com/Roi7687/astrbot_plugin_xhhnews.git
```

3. 在 AstrBot 管理界面启用插件
4. （可选）安装并登录 `astrbot_plugin_aisearch`，`/hbnews` 的 AI 精选才可用

## 命令

| 命令 | 功能 |
|------|------|
| `/hbnews` | AI 联网核验本周新游，精选 4~8 款值得玩的（约 30~90 秒） |
| `/hbhelp` | 显示帮助 |

## AI 精选的筛选口径

`/hbnews` 的提示词（`core/ai_review.py` 里的 `AI_REVIEW_PROMPT`，用户定稿版）要求模型：

1. **必须联网核验**：先按小黑盒关注数初筛出 10~15 款候选，再逐款检索
   `Steam 好评率 / 评测`、`Metacritic / OpenCritic`；中文名搜不到时用 **Steam AppID 或英文原名**；
2. **入选标准（按优先级）**：质量与好评优先（Steam ≥ 80% 或 MC/OC ≥ 80）→
   重磅 3A / 知名大厂 / 经典 IP 新作（关注数通常 > 3 万）→ 口碑爆棚的独立佳作；
3. **一票否决**：粗制滥造、换皮模拟器、AI 劣质游戏，以及**关注度高但首发翻车**
   （Steam 好评率 < 70% 且差评集中在恶性 Bug / 优化灾难 / 内容缩水）的作品直接淘汰；
4. **特殊身份必须标注**：EA 转 1.0 正式版、重制 / 移植 / DLC、周末刚解锁的新作
   （样本 < 50 也不漏掉，标注「刚解锁样本少」）；
5. **数据防幻觉**：严禁编造评分与模糊区间（如 `53%~66%`），只标 Steam / MC / OC / IGN
   等原始平台，不写二手资讯网；全球与简中评价差 > 15% 时必须点明简中好评率与原因；
6. **输出**：只输出 4~8 款入选游戏，按「综合推荐度（质量+关注度）」排序，每款包含
   `游戏名 + 发售日期 + 类型玩法 + 评价反馈` 四要素；禁止一级标题、开场白、总结语、避雷板块。

相关配置在 `core/config.py`：`AI_REVIEW_ENABLED`（总开关）、`AI_REVIEW_PLUGIN` /
`AI_REVIEW_METHOD`（跨插件调用的目标插件与方法）、`AI_REVIEW_TIMEOUT`（默认 180s）、
`AI_REVIEW_MAX_CHARS`（默认 2800，够放 4~8 款）等。

> 未安装 / 未启用 `astrbot_plugin_aisearch` 时，`/hbnews` 不会报错，
> 而是降级为「本周完整日历 + 一句说明」。

## 输出示例

`/hbnews`（真实实测输出，节选；格式由提示词定稿，插件不再加标题/脚注）：

```
**1. 〈战锤40K：爆矢枪2 Warhammer 40,000: Boltgun 2〉｜ 发售日期：10-14（PC / PS5 / Xbox Series，续作）**

* **类型与玩法**：复古 boomer shooter 的全面进化版……双角色 + 分支关卡 + 滑步处决链锯剑。
* **评价与反馈**：Steam 好评率约 **94%**［约 248 篇评测］｜ **Metacritic 81**｜ **OpenCritic 83**。
  玩家称其为「教科书级续作」，槽点是多周目才能看全分支战役。

**2. 〈越过山丘 Over the Hill〉｜ 发售日期：10-14（PC，正式发售）**
* **类型与玩法**：轻量化越野驾驶探索，没有计时没有名次，开着 60-80 年代四驱车找路看风景。
* **评价与反馈**：Steam 好评率 **92.5%**［约 1,098 篇评测］，特别好评；门槛是节奏偏慢、挑人。

**3. 〈女巫的面包店 The Witch's Bakery〉｜ 发售日期：10-15（PC / PS5 / Xbox / NS，正式发售）**
* **类型与玩法**：温馨 2D 叙事冒险 RPG，白天在巴黎经营魔法烘焙坊，夜晚推进剧情。
* **评价与反馈**：Steam 好评率 **96%**［首发样本少］，愿望单超 15 万；部分媒体认为烘焙玩法深度有限。

（更多游戏按「综合推荐度（质量+关注度）」从高到低排列，共 4~8 款）
```

## 说明

- 数据来自小黑盒公开接口，与 APP「游戏发售日历」同源
- 玩法标签取游戏类型（如 `模拟`、`动作`、`冒险`）；已过去日期的标签需要逐个查询详情接口，
  首次查询会慢一些并写入本地缓存（`tag_cache.json`，7 天有效）
- `/hbnews` 的评分与口碑来自 AI 联网检索，**以实时搜索结果为准**；刚发售的游戏常没有
  足够评测样本，此时会明确标注「样本少/暂无评分」
- `/hbnews` 等待时间较长（30~90 秒），会先回一条「正在联网核验…」提示；超时会自动
  降级为本周普通日历
- 请合理控制调用频率，短时间内大量请求可能被服务端限流

## 依赖

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) — 插件框架
- [httpx](https://pypi.org/project/httpx/) — 异步 HTTP 客户端
- [astrbot_plugin_aisearch](https://github.com/Roi7687/astrbot_plugin_aisearch)（可选）—
  AI 联网核验能力来源；不装则 `/hbnews` 自动降级

## 开发

模块划分、接口口径与调试方式见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## License

AGPL-3.0
