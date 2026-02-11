"""Pipeline 测试"""

from __future__ import annotations

import pytest

from speech_core.interfaces import ConversationState
from speech_core.pipeline.barge_in import BargeInConfig, BargeInController, BargeInPolicy


class TestConversationState:
    """对话状态机测试"""

    def test_states(self):
        assert ConversationState.IDLE.value == "idle"
        assert ConversationState.LISTENING.value == "listening"
        assert ConversationState.PROCESSING.value == "processing"
        assert ConversationState.SPEAKING.value == "speaking"


class TestBargeInController:
    """打断控制器测试"""

    def test_disabled_policy(self):
        config = BargeInConfig(policy=BargeInPolicy.DISABLED)
        controller = BargeInController(config)
        controller.on_bot_start_speaking()
        assert not controller.is_active

    def test_immediate_policy_activation(self):
        config = BargeInConfig(policy=BargeInPolicy.IMMEDIATE)
        controller = BargeInController(config)

        assert not controller.is_active
        controller.on_bot_start_speaking()
        assert controller.is_active
        controller.on_bot_stop_speaking()
        assert not controller.is_active

    @pytest.mark.asyncio
    async def test_immediate_trigger(self):
        config = BargeInConfig(policy=BargeInPolicy.IMMEDIATE, cooldown_ms=0)
        controller = BargeInController(config)

        triggered_events = []

        async def on_barge_in(event):
            triggered_events.append(event)

        controller.set_callback(on_barge_in)
        controller.on_bot_start_speaking()

        result = await controller.on_user_speech_detected("user1", "channel1")
        assert result is True
        assert len(triggered_events) == 1
        assert triggered_events[0].event == "barge_in"

    def test_reset(self):
        controller = BargeInController()
        controller.on_bot_start_speaking()
        assert controller.is_active
        controller.reset()
        assert not controller.is_active


class TestBargeInConfig:
    """打断配置测试"""

    def test_defaults(self):
        config = BargeInConfig()
        assert config.policy == BargeInPolicy.CONFIRMED
        assert config.confirm_duration_ms == 200.0
        assert config.cooldown_ms == 500.0
