# Think or Not（astrbot_plugin_think_gate）

[简体中文](README.md) | English

Help your bot **choose more intelligently whether to use deep thinking on this turn**: before the main model replies, a judge model scores the need for deep thinking, then this plugin temporarily enables or disables thinking on the **same** chat provider.

- Does **not** register a second chat provider; it only edits the current provider’s `custom_extra_body`
- **Disabled by default**; when off, no judging and no thinking changes
- Default JSON matches DeepSeek-style `thinking.enabled / disabled` (customize for your API)
- WebUI strings ship in Chinese and English (`.astrbot-plugin/i18n/`)

Repo: https://github.com/Yucheng-Z/astrbot_plugin_think_gate

## What it does

Deep thinking is not equally useful for every message. Some turns need careful reasoning; others are greetings, banter, or short confirmations. This plugin adds a small router so the choice fits the conversation:

1. The judge model scores the latest user message from **0–100** (how much deep thinking is warranted)
2. Compare with **think density**: enable thinking when `score ≥ (100 − density)`; otherwise keep a non-thinking mode
3. When the Agent run finishes, restore the baseline so the switch does not stick from the previous turn

Density lets you bias toward “think more often” or “stay restrained”, but the core idea is **content-aware routing**, not a fixed always-on / always-off policy.

```text
User message
   │
   ▼
Judge model → score 0–100
   │
   ▼
score ≥ (100 − think_density) ?
   │yes             │no
   ▼                ▼
Enable thinking   Keep non-thinking
   │                │
   └──────┬─────────┘
          ▼
   Main model replies
          │
          ▼
   Agent done → restore baseline
```

## Requirements

- AstrBot (any version that loads normal Python plugins)
- Main chat provider must honor writable **`custom_extra_body`**
- Optional: a separate provider ID for the judge model

## Install

- **Plugin market**: search for “Think or Not” / 「思考 or 不思考」 / `astrbot_plugin_think_gate`
- **Manual**: place this repo under AstrBot `data/plugins/astrbot_plugin_think_gate/`, then reload plugins

## Quick start

1. Set **`enable`** to on
2. **`judge_provider_id`**: pick a model for scoring, or leave empty to use the session’s chat model
3. Start with **`think_density` = `50`**, then tune how eagerly thinking should turn on
4. If your main model is not DeepSeek-style thinking, edit `thinking_enabled_body` / `thinking_disabled_body`

## Configuration

| Key | Default | Meaning |
|-----|---------|---------|
| `enable` | `false` | Master switch. Off = no judge, no thinking edits |
| `think_density` | `50` | 0–100; **higher = easier to enable thinking**. Threshold = `100 − density` |
| `judge_provider_id` | (panel select) | Judge provider; missing/empty falls back to current chat model |
| `judge_timeout` | `5` | Judge timeout seconds; on timeout/failure → do **not** enable thinking |
| `judge_prompt` | (see panel) | System prompt; should ask for a **single 0–100 integer** |
| `thinking_enabled_body` | `{"thinking":{"type":"enabled"}}` | Written into `custom_extra_body` when thinking should be on |
| `thinking_disabled_body` | `{"thinking":{"type":"disabled"}}` | Used when restoring / turning off (also baseline reference) |

### Density examples

| Density | Threshold (`score ≥`) | Feel |
|---------|------------------------|------|
| `30` | `70` | More restrained; only higher scores enable thinking |
| `50` | `50` | Neutral (default) |
| `70` | `30` | More eager; moderate scores already enable thinking |

## Behavior details

- **One judge call per Agent turn**; later LLM calls in the same turn (e.g. after tools) reuse the decision
- Messages with **fewer than 8 effective characters** after stripping punctuation skip judging → thinking stays off
- Score parsing prefers integers; bare `yes`/`no` (and a few Chinese equivalents) map to 100 / 0
- Concurrent sessions use a refcount so one turn does not stomp another’s thinking switch
- Restore only on `on_agent_done`; thinking is not cleared mid-reply

## FAQ

**Enabled but nothing changes?**  
Confirm `enable` is on; confirm the provider actually applies `custom_extra_body`; check logs for `[think_gate] score=...` / `thinking=on|off`.

**Which judge model should I use?**  
Any configured chat provider works. Scoring is a light task—pick something responsive you already trust. Empty = same as the session main model.

**How does this interact with a provider’s fixed thinking setting?**  
This plugin **temporarily overrides** per turn, then restores the pre-turn baseline when the Agent finishes. Long-term defaults still come from the provider config.

**What if the judge times out or returns garbage?**  
This turn conservatively **does not** enable deep thinking, so the reply is not blocked.

## Notes

- Requires writable **`custom_extra_body`** on the main provider
- Each gated reply may add one short judge request
- For other vendors, change the two thinking JSON bodies to match their API—not only the judge prompt

## License

MIT © Yucheng-Z
