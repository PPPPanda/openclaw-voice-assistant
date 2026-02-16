"""Multi-user Session Manager

按 voiceChannelId + userId 隔离会话，管理多用户对话历史和状态机。
支持 Active Speaker 策略和会话超时清理。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from speech_core.interfaces import ConversationState

logger = logging.getLogger(__name__)


class SessionEvent(Enum):
    """会话事件"""
    CREATED = "created"
    ACTIVATED = "activated"
    DEACTIVATED = "deactivated"
    TIMEOUT = "timeout"
    REMOVED = "removed"


@dataclass
class VoiceSession:
    """语音会话

    代表一个用户在语音频道中的会话状态。
    """

    user_id: str
    channel_id: str
    state: ConversationState = ConversationState.IDLE
    history: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    is_active_speaker: bool = False

    def add_to_history(self, role: str, content: str) -> None:
        """添加到对话历史

        Args:
            role: 角色 (user/assistant)
            content: 内容
        """
        self.history.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        self.last_active_at = time.time()

    def update_activity(self) -> None:
        """更新最后活跃时间"""
        self.last_active_at = time.time()

    @property
    def idle_duration_s(self) -> float:
        """空闲时长（秒）"""
        return time.time() - self.last_active_at


class SessionManager:
    """多用户会话管理器

    管理语音频道中的多个用户会话。
    支持：
    - 按 channel_id + user_id 隔离会话
    - Active Speaker 策略（同时只处理一个活跃用户）
    - 会话超时自动清理
    - 状态同步

    Usage:
        manager = SessionManager(timeout_s=300)

        # 创建/获取会话
        session = manager.create_session("user123", "channel456")

        # 设置活跃说话者
        manager.set_active_speaker("channel456", "user123")

        # 获取活跃说话者
        active = manager.get_active_speaker("channel456")

        # 定期清理超时会话
        await manager.cleanup()
    """

    def __init__(
        self,
        timeout_s: float = 300.0,
        cleanup_interval_s: float = 60.0,
    ) -> None:
        """初始化会话管理器

        Args:
            timeout_s: 会话超时时间（秒），默认 5 分钟
            cleanup_interval_s: 清理任务间隔（秒）
        """
        self._timeout_s = timeout_s
        self._sessions: dict[str, VoiceSession] = {}  # key: "channel_id:user_id"
        self._active_speakers: dict[str, str] = {}  # key: channel_id -> user_id
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval_s = cleanup_interval_s

    def _make_session_key(self, channel_id: str, user_id: str) -> str:
        """生成会话唯一键

        Args:
            channel_id: 频道 ID
            user_id: 用户 ID

        Returns:
            会话键
        """
        return f"{channel_id}:{user_id}"

    async def create_session(
        self,
        user_id: str,
        channel_id: str,
    ) -> VoiceSession:
        """创建或获取会话

        Args:
            user_id: 用户 ID
            channel_id: 频道 ID

        Returns:
            语音会话
        """
        async with self._lock:
            key = self._make_session_key(channel_id, user_id)

            if key in self._sessions:
                session = self._sessions[key]
                session.update_activity()
                logger.debug(f"Session retrieved: channel={channel_id}, user={user_id}")
                return session

            # 创建新会话
            session = VoiceSession(
                user_id=user_id,
                channel_id=channel_id,
            )
            self._sessions[key] = session

            logger.info(f"Session created: channel={channel_id}, user={user_id}")
            return session

    async def get_session(
        self,
        user_id: str,
        channel_id: str,
    ) -> Optional[VoiceSession]:
        """获取会话（如果存在）

        Args:
            user_id: 用户 ID
            channel_id: 频道 ID

        Returns:
            语音会话，如果不存在则返回 None
        """
        key = self._make_session_key(channel_id, user_id)
        return self._sessions.get(key)

    async def remove_session(
        self,
        user_id: str,
        channel_id: str,
    ) -> bool:
        """移除会话

        Args:
            user_id: 用户 ID
            channel_id: 频道 ID

        Returns:
            是否成功移除
        """
        async with self._lock:
            key = self._make_session_key(channel_id, user_id)

            if key in self._sessions:
                del self._sessions[key]

                # 如果是活跃说话者，清除
                if self._active_speakers.get(channel_id) == user_id:
                    del self._active_speakers[channel_id]

                logger.info(f"Session removed: channel={channel_id}, user={user_id}")
                return True

            return False

    async def get_active_speaker(self, channel_id: str) -> Optional[str]:
        """获取频道的活跃说话者

        Args:
            channel_id: 频道 ID

        Returns:
            用户 ID，如果没有活跃说话者则返回 None
        """
        return self._active_speakers.get(channel_id)

    async def set_active_speaker(
        self,
        channel_id: str,
        user_id: str,
    ) -> None:
        """设置频道的活跃说话者

        Args:
            channel_id: 频道 ID
            user_id: 用户 ID
        """
        async with self._lock:
            old_speaker = self._active_speakers.get(channel_id)

            # 取消之前的活跃说话者
            if old_speaker and old_speaker != user_id:
                old_key = self._make_session_key(channel_id, old_speaker)
                if old_key in self._sessions:
                    self._sessions[old_key].is_active_speaker = False

            # 设置新的活跃说话者
            self._active_speakers[channel_id] = user_id
            new_key = self._make_session_key(channel_id, user_id)

            if new_key in self._sessions:
                self._sessions[new_key].is_active_speaker = True

            logger.info(
                f"Active speaker changed: channel={channel_id}, "
                f"old={old_speaker}, new={user_id}"
            )

    async def clear_active_speaker(self, channel_id: str) -> None:
        """清除频道的活跃说话者

        Args:
            channel_id: 频道 ID
        """
        async with self._lock:
            user_id = self._active_speakers.get(channel_id)

            if user_id:
                key = self._make_session_key(channel_id, user_id)
                if key in self._sessions:
                    self._sessions[key].is_active_speaker = False

                del self._active_speakers[channel_id]

                logger.info(f"Active speaker cleared: channel={channel_id}")

    async def cleanup(self) -> int:
        """清理超时会话

        Returns:
            清理的会话数量
        """
        async with self._lock:
            now = time.time()
            to_remove = []

            for key, session in self._sessions.items():
                if now - session.last_active_at > self._timeout_s:
                    to_remove.append(key)

            # 移除超时会话
            for key in to_remove:
                session = self._sessions.pop(key)
                channel_id = session.channel_id

                # 如果是活跃说话者，清除
                if self._active_speakers.get(channel_id) == session.user_id:
                    del self._active_speakers[channel_id]

                logger.info(
                    f"Session timed out: channel={channel_id}, "
                    f"user={session.user_id}, idle={session.idle_duration_s:.0f}s"
                )

            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} timed out sessions")

            return len(to_remove)

    async def start_cleanup_task(self) -> None:
        """启动定期清理任务"""
        if self._cleanup_task is not None:
            return

        async def cleanup_loop():
            while True:
                await asyncio.sleep(self._cleanup_interval_s)
                await self.cleanup()

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("Session cleanup task started")

    async def stop_cleanup_task(self) -> None:
        """停止定期清理任务"""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Session cleanup task stopped")

    async def get_channel_sessions(
        self,
        channel_id: str,
    ) -> list[VoiceSession]:
        """获取频道的所有会话

        Args:
            channel_id: 频道 ID

        Returns:
            会话列表
        """
        return [
            s for s in self._sessions.values()
            if s.channel_id == channel_id
        ]

    async def get_all_sessions(self) -> list[VoiceSession]:
        """获取所有会话"""
        return list(self._sessions.values())

    @property
    def session_count(self) -> int:
        """会话总数"""
        return len(self._sessions)
