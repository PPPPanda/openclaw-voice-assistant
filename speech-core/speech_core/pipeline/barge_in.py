"""Barge-in（打断）控制器

实现用户打断 Bot 说话的能力。
当检测到用户在 Bot 说话期间开始说话时，立即停止 TTS 播放。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Awaitable

from speech_core.interfaces import ConversationState, SpeechEvent

logger = logging.getLogger(__name__)


class BargeInPolicy(Enum):
    """打断策略"""
    DISABLED = "disabled"       # 不允许打断
    IMMEDIATE = "immediate"     # 检测到语音立即打断
    CONFIRMED = "confirmed"     # 持续说话一段时间后打断（减少误触发）


@dataclass
class BargeInConfig:
    """打断配置"""
    policy: BargeInPolicy = BargeInPolicy.CONFIRMED
    confirm_duration_ms: float = 200.0  # CONFIRMED 策略下需要持续说话多久
    cooldown_ms: float = 500.0           # 打断后的冷却时间（避免连续打断）


class BargeInController:
    """打断控制器

    管理 Bot 说话期间的打断检测与执行。

    工作流程：
    1. Bot 开始说话 → 控制器进入 ACTIVE 状态
    2. 检测到用户语音 → 根据策略决定是否打断
    3. 确认打断 → 触发停止 TTS 播放，切换到 LISTENING 状态
    4. 冷却时间内不再触发打断

    状态机：
        INACTIVE → (bot_starts_speaking) → ACTIVE
        ACTIVE → (user_speech_detected) → PENDING_CONFIRM (if CONFIRMED policy)
        ACTIVE → (user_speech_detected) → TRIGGERED (if IMMEDIATE policy)
        PENDING_CONFIRM → (speech_duration >= confirm_ms) → TRIGGERED
        PENDING_CONFIRM → (speech_stopped) → ACTIVE
        TRIGGERED → (cooldown) → INACTIVE
    """

    def __init__(self, config: BargeInConfig | None = None) -> None:
        self._config = config or BargeInConfig()
        self._state: _BargeInState = _BargeInState.INACTIVE
        self._user_speech_start_ms: float | None = None
        self._last_trigger_ms: float = 0.0
        self._on_barge_in: Callable[[SpeechEvent], Awaitable[None]] | None = None

    def set_callback(
        self, callback: Callable[[SpeechEvent], Awaitable[None]]
    ) -> None:
        """设置打断回调

        当确认打断时调用此回调。

        Args:
            callback: 异步回调函数，接收 SpeechEvent
        """
        self._on_barge_in = callback

    def on_bot_start_speaking(self) -> None:
        """Bot 开始说话，激活打断检测"""
        if self._config.policy == BargeInPolicy.DISABLED:
            return

        self._state = _BargeInState.ACTIVE
        self._user_speech_start_ms = None
        logger.debug("Barge-in controller activated")

    def on_bot_stop_speaking(self) -> None:
        """Bot 停止说话，停用打断检测"""
        self._state = _BargeInState.INACTIVE
        self._user_speech_start_ms = None
        logger.debug("Barge-in controller deactivated")

    async def on_user_speech_detected(
        self,
        user_id: str,
        channel_id: str,
        confidence: float = 0.0,
    ) -> bool:
        """用户语音被检测到

        Args:
            user_id: 用户 ID
            channel_id: 频道 ID
            confidence: VAD 置信度

        Returns:
            True 如果触发了打断
        """
        if self._config.policy == BargeInPolicy.DISABLED:
            return False

        if self._state == _BargeInState.INACTIVE:
            return False

        now_ms = time.time() * 1000

        # 冷却检查
        if now_ms - self._last_trigger_ms < self._config.cooldown_ms:
            return False

        if self._config.policy == BargeInPolicy.IMMEDIATE:
            return await self._trigger_barge_in(user_id, channel_id, now_ms)

        # CONFIRMED 策略
        if self._user_speech_start_ms is None:
            self._user_speech_start_ms = now_ms
            self._state = _BargeInState.PENDING_CONFIRM
            return False

        speech_duration = now_ms - self._user_speech_start_ms
        if speech_duration >= self._config.confirm_duration_ms:
            return await self._trigger_barge_in(user_id, channel_id, now_ms)

        return False

    def on_user_speech_stopped(self) -> None:
        """用户停止说话（在 PENDING_CONFIRM 状态下取消打断）"""
        if self._state == _BargeInState.PENDING_CONFIRM:
            self._state = _BargeInState.ACTIVE
            self._user_speech_start_ms = None
            logger.debug("Barge-in cancelled (user stopped speaking)")

    async def _trigger_barge_in(
        self,
        user_id: str,
        channel_id: str,
        now_ms: float,
    ) -> bool:
        """触发打断"""
        self._state = _BargeInState.INACTIVE
        self._last_trigger_ms = now_ms
        self._user_speech_start_ms = None

        event = SpeechEvent(
            event="barge_in",
            user_id=user_id,
            channel_id=channel_id,
            timestamp=now_ms,
        )

        logger.info(f"Barge-in triggered by user={user_id} in channel={channel_id}")

        if self._on_barge_in:
            try:
                await self._on_barge_in(event)
            except Exception:
                logger.exception("Error in barge-in callback")

        return True

    @property
    def is_active(self) -> bool:
        """打断检测是否激活"""
        return self._state != _BargeInState.INACTIVE

    def reset(self) -> None:
        """重置控制器状态"""
        self._state = _BargeInState.INACTIVE
        self._user_speech_start_ms = None


class _BargeInState(Enum):
    """内部打断状态"""
    INACTIVE = "inactive"
    ACTIVE = "active"
    PENDING_CONFIRM = "pending_confirm"
