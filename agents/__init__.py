"""
Agent 统一导出桥接 (Agent Bridge)

让 director 可以用统一的 `agents` 包导入所有 agent，
同时保持各个独立 agent 文件的完整性。
"""

# 从独立 agent 文件导出（优先使用增强版）
try:
    from agents.voiceover import VoiceoverAgent as _Voiceover
    voiceover = _Voiceover(None, None, {})
except Exception:
    from agents.all_agents import voiceover

try:
    from agents.bgm import BGMRecommendationAgent as _BGM
    bgm = _BGM(None, None, {})
except Exception:
    from agents.all_agents import bgm

try:
    from agents.qc import QualityControlAgent as _QC
    qc = _QC(None, None, {})
except Exception:
    from agents.all_agents import qc

try:
    from agents.stylization import StylizationAgent as _Styling
    styling = _Styling(None, None, {})
except Exception:
    from agents.all_agents import styling

try:
    from agents.delivery import DeliveryAgent as _Delivery
    delivery = _Delivery(None, None, {})
except Exception:
    from agents.all_agents import delivery

# 确保从 all_agents 的导出依然可用
from agents.all_agents import voiceover as _vo, bgm as _bgm, qc as _qc, styling as _st, delivery as _dl

# 编剧和分镜始终从独立文件
from agents.scriptwriter import scriptwriter
from agents.storyboard import storyboard

# 字幕 agent
try:
    from agents.subtitle import SubtitleAgent as _Subtitle
    subtitle = _Subtitle(None, None, {})
except Exception:
    subtitle = None

__all__ = [
    'scriptwriter', 'storyboard', 'voiceover', 'bgm',
    'qc', 'styling', 'delivery', 'subtitle',
]
