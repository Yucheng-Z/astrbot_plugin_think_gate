# 思考 or 不思考（astrbot_plugin_think_gate）

每次主模型回复前，用可配置的**判断模型**打 **0–100 分**，再按 `think_density`（思考浓度）阈值决定是否临时打开**同一主模型**的深度思考（写入 `custom_extra_body`，**不分叉**第二套聊天提供商）。

## 安装

- **插件市场**（推荐）：搜索「思考 or 不思考」或 `astrbot_plugin_think_gate` 安装。
- **手动**：将本仓库放入 AstrBot 的 `data/plugins/astrbot_plugin_think_gate/`，在面板重载插件。

仓库：https://github.com/Yucheng-Z/astrbot_plugin_think_gate

## 配置

| 键 | 说明 |
|----|------|
| `enable` | 总开关（**默认关**；关闭时无额外判断调用） |
| `think_density` | 0–100，越高越容易开思考；阈值 = `100 - density` |
| `judge_provider_id` | 判断模型（面板下拉；留空用当前聊天模型） |
| `judge_timeout` | 超时秒数，超时默认不思考 |
| `judge_prompt` | 系统提示：要求只输出一行 0–100 整数 |
| `thinking_enabled_body` / `thinking_disabled_body` | 写入 `custom_extra_body` 的 JSON（按你的主模型格式改） |

## 行为要点

- `on_llm_request`：判断 → 改主模型 thinking；同一 event 只判一次，工具二跳复用
- `on_agent_done`：恢复基线（默认 disabled）
- 解析：优先整数分；裸 `yes` / `no` 兜底为 100 / 0
- 过短消息会跳过判断（省调用）

## 许可

MIT
