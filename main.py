"""思考 or 不思考：判断模型打 0–100 分 + think_density 阈值 → 临时改主模型 thinking。

默认关闭（enable=false）；开启后同一 Agent 轮只判断一次，仅在 on_agent_done 恢复。
解析兜底：裸 yes/YES→100、no/NO→0（兼容旧提示词或模型跑偏）。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

_SCORE = re.compile(r"(-?\d{1,3})")
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_DECISION_KEY = "think_gate_decision"
_ARMED_YES_KEY = "think_gate_armed_yes"


class ThinkGatePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._lock = asyncio.Lock()
        self._inflight_on = 0
        self._baseline_extra: dict[str, Any] | None = None

    def _enabled(self) -> bool:
        return bool(self.config.get("enable", False))

    def _think_density(self) -> int:
        """0–100：越高越容易开思考。阈值 = 100 - density。"""
        try:
            return max(0, min(100, int(self.config.get("think_density", 50))))
        except (TypeError, ValueError):
            return 50

    def _parse_body(self, key: str, default: dict) -> dict:
        raw = self.config.get(key)
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str) and raw.strip():
            try:
                val = json.loads(raw)
                if isinstance(val, dict):
                    return val
            except json.JSONDecodeError:
                logger.warning("[think_gate] %s JSON 无效，用默认", key)
        return dict(default)

    async def _get_chat_provider_async(self, event: AstrMessageEvent):
        if hasattr(self.context, "get_using_provider_async"):
            try:
                return await self.context.get_using_provider_async(
                    event.unified_msg_origin
                )
            except Exception:
                pass
        if hasattr(self.context, "get_using_provider"):
            try:
                return self.context.get_using_provider(event.unified_msg_origin)
            except Exception:
                pass
        return None

    async def _get_judge_provider(self, event: AstrMessageEvent):
        pid = str(self.config.get("judge_provider_id") or "").strip()
        if pid:
            prov = self.context.get_provider_by_id(pid)
            if prov is not None:
                return prov
            logger.warning("[think_gate] 找不到判断模型 %s，回退主模型", pid)
        return await self._get_chat_provider_async(event)

    @staticmethod
    def _is_short_skip(text: str) -> bool:
        compact = _NON_WORD.sub("", text or "")
        return len(compact) < 8

    @staticmethod
    def _parse_score(text: str) -> int | None:
        raw = (text or "").strip()
        if not raw:
            return None
        # 分数优先；裸 yes/no 兜底（旧 judge_prompt 或模型只回二元）
        m = _SCORE.search(raw)
        if m:
            try:
                return max(0, min(100, int(m.group(1))))
            except ValueError:
                pass
        token = _NON_WORD.sub("", raw).lower()
        if token in ("yes", "y", "true", "是", "需要"):
            return 100
        if token in ("no", "n", "false", "否", "不需要"):
            return 0
        return None

    async def _should_think(self, event: AstrMessageEvent, req) -> bool:
        prompt_user = (getattr(req, "prompt", None) or event.message_str or "").strip()
        density = self._think_density()
        threshold = 100 - density
        if not prompt_user or self._is_short_skip(prompt_user):
            logger.info(
                "[think_gate] 短句跳过 score=- threshold=%s density=%s → off",
                threshold,
                density,
            )
            return False
        judge = await self._get_judge_provider(event)
        if judge is None:
            return False
        system = str(
            self.config.get("judge_prompt")
            or "只输出 0–100 整数。复杂推理高分，闲聊低分。"
        )
        timeout = float(self.config.get("judge_timeout") or 5)

        async def _call():
            return await judge.text_chat(
                prompt=(
                    f"用户消息：\n{prompt_user[:2000]}\n\n"
                    "请只输出一个 0–100 的整数分（需要深度思考的程度）。"
                ),
                system_prompt=system,
                contexts=[],
            )

        try:
            resp = await asyncio.wait_for(_call(), timeout=timeout)
            text = str(getattr(resp, "completion_text", "") or "").strip()
            score = self._parse_score(text)
            if score is None:
                logger.info(
                    "[think_gate] 分数解析失败 raw=%r threshold=%s density=%s → off",
                    text[:80],
                    threshold,
                    density,
                )
                return False
            want = score >= threshold
            logger.info(
                "[think_gate] score=%s threshold=%s density=%s → %s",
                score,
                threshold,
                density,
                "on" if want else "off",
            )
            return want
        except asyncio.TimeoutError:
            logger.info(
                "[think_gate] 判断超时 threshold=%s density=%s → off",
                threshold,
                density,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("[think_gate] 判断失败，默认不思考: %s", exc)
            return False

    def _apply_extra(self, provider, body: dict) -> None:
        cfg = getattr(provider, "provider_config", None)
        if not isinstance(cfg, dict):
            return
        extra = cfg.get("custom_extra_body")
        if not isinstance(extra, dict):
            extra = {}
            cfg["custom_extra_body"] = extra
        for k, v in body.items():
            extra[k] = v

    def _ensure_baseline(self, provider) -> None:
        cfg = getattr(provider, "provider_config", None)
        if not isinstance(cfg, dict) or self._baseline_extra is not None:
            return
        cur = cfg.get("custom_extra_body")
        off = self._parse_body(
            "thinking_disabled_body", {"thinking": {"type": "disabled"}}
        )
        self._baseline_extra = dict(cur) if isinstance(cur, dict) else dict(off)

    async def _sync_provider_thinking(self, event: AstrMessageEvent) -> None:
        provider = await self._get_chat_provider_async(event)
        if provider is None:
            return
        on_body = self._parse_body(
            "thinking_enabled_body", {"thinking": {"type": "enabled"}}
        )
        async with self._lock:
            self._ensure_baseline(provider)
            if self._inflight_on > 0:
                self._apply_extra(provider, on_body)
            elif self._baseline_extra is not None:
                self._apply_extra(provider, self._baseline_extra)

    async def _arm(self, event: AstrMessageEvent, want: bool, *, reuse: bool) -> None:
        if reuse:
            logger.info(
                "[think_gate] reuse_decision thinking=%s",
                "on" if want else "off",
            )
            await self._sync_provider_thinking(event)
            return

        if hasattr(event, "set_extra"):
            event.set_extra(_DECISION_KEY, want)
            event.set_extra(_ARMED_YES_KEY, bool(want))

        provider = await self._get_chat_provider_async(event)
        if provider is None:
            return
        on_body = self._parse_body(
            "thinking_enabled_body", {"thinking": {"type": "enabled"}}
        )
        async with self._lock:
            self._ensure_baseline(provider)
            if want:
                self._inflight_on += 1
                self._apply_extra(provider, on_body)
            else:
                # 不踩踏其它会话的 on
                if self._inflight_on <= 0 and self._baseline_extra is not None:
                    self._apply_extra(provider, self._baseline_extra)
            logger.info("[think_gate] 本次 thinking=%s", "on" if want else "off")

    async def _disarm(self, event: AstrMessageEvent) -> None:
        if not (hasattr(event, "get_extra") and event.get_extra(_ARMED_YES_KEY)):
            if hasattr(event, "set_extra"):
                event.set_extra(_DECISION_KEY, None)
                event.set_extra(_ARMED_YES_KEY, False)
            return
        provider = await self._get_chat_provider_async(event)
        on_body = self._parse_body(
            "thinking_enabled_body", {"thinking": {"type": "enabled"}}
        )
        async with self._lock:
            self._inflight_on = max(0, self._inflight_on - 1)
            if provider is not None:
                self._ensure_baseline(provider)
                if self._inflight_on > 0:
                    self._apply_extra(provider, on_body)
                elif self._baseline_extra is not None:
                    self._apply_extra(provider, self._baseline_extra)
            logger.info(
                "[think_gate] agent_done 恢复，inflight_on=%s", self._inflight_on
            )
        if hasattr(event, "set_extra"):
            event.set_extra(_ARMED_YES_KEY, False)
            event.set_extra(_DECISION_KEY, None)

    @filter.on_llm_request(priority=5)
    async def gate(self, event: AstrMessageEvent, req):
        if not self._enabled():
            return
        if hasattr(event, "get_extra") and event.get_extra(_DECISION_KEY) is not None:
            await self._arm(event, bool(event.get_extra(_DECISION_KEY)), reuse=True)
            return
        want = await self._should_think(event, req)
        await self._arm(event, want, reuse=False)

    @filter.on_agent_done(priority=5)
    async def after_agent(self, event: AstrMessageEvent, run_context, llm_response):
        if not self._enabled():
            return
        await self._disarm(event)
