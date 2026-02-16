"""Session Manager 模块

多用户会话管理：
- VoiceSession: 语音会话数据类
- SessionManager: 会话管理器
"""

from speech_core.session.manager import SessionManager, SessionEvent, VoiceSession

__all__ = [
    "SessionManager",
    "SessionEvent",
    "VoiceSession",
]
