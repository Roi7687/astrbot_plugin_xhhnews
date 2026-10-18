# verify_output —— 真实链路验证产物

> 这些文件由 `research/` 下的验证脚本生成，用于留存「真实数据 → 真实 AI → 真实排版」
> 的证据，不参与插件运行。重新生成见 `DEVELOPMENT.md` 的「本地调试」。

| 文件 | 来源 | 说明 |
|------|------|------|
| `week_calendar.md` | `verify_ai_review.py` | 「本周完整日历」markdown（`/hbnews` 降级输出用的形态，本周 46 款新游，真实小黑盒接口） |
| `week_digest.txt` | 同上 | **喂给 AI** 的紧凑清单（含 Steam AppID / 平台 / 小黑盒关注数） |
| `prompt.txt` | 同上 | 完整提示词 = `AI_REVIEW_PROMPT`（用户定稿版）+ 上述清单（5122 字） |
| `ai_review_raw.txt` | 同上 | 端到端脚本（真实 DeepSeek 调用）拿到的 AI 正文 |
| `final_reply.md` | 同上 | 最终发送形态（定稿提示词已规定版式，插件不再加标题/脚注，与 raw 相同） |
| `meta.json` | 同上 | 该次运行统计（抓数 0.8s、AI 53.4s、正文 1956 字符） |
| `astrbot_reply.md` | `verify_in_astrbot.py /hbnews` | **在运行中的 AstrBot 里**真实执行的 `/hbnews`：0.7s 进度提示 + 42.0s AI 速报（7 款精选，2062 字符） |

实测摘要（新提示词，2026-10-18，本周 46 款新游）：

- 数据抓取：0.8s（46 款全部带标签与 AppID，历史日期标签命中本地缓存）
- AI 联网核验：53.4s（DeepSeek 网页版 + 联网搜索，跨插件调用 aisearch）
- 输出形态：**5 款**入选（要求 4~8 款），严格按定稿格式 —— 每款「游戏名｜发售日期（平台/身份）」
  + 「类型与玩法」+「评价与反馈」两段，无一级标题、无开场白/总结语/避雷板块，
  只写原始评分平台（Steam / MC / OC），并标注样本量少、简中好评率等陷阱。
