"""
quanquan 项目类型安全层 — 核心业务 TypedDict 定义

所有业务数据结构在此统一定义，agents/ 和 core/ 下的模块从此处导入。
Python 3.8 兼容：使用 typing.TypedDict（非 class 语法），Optional 替代 NotRequired。
"""

from typing import List, Optional, Literal, TypedDict

# Python 3.8 兼容：NotRequired 从 typing_extensions 导入（3.11+ 内置在 typing 中）
try:
    from typing import NotRequired  # Python 3.11+
except ImportError:
    try:
        from typing_extensions import NotRequired  # pip install typing_extensions
    except ImportError:
        # 最终回退：Python 3.8 无 typing_extensions 时，用 Optional[X] 模拟 NotRequired
        # （Optional[X] 允许 None，NotRequired 允许键缺失；在 dict 使用场景中可接受）
        NotRequired = Optional  # type: ignore


# ============================================================
# 镜头构图类型（用于 Shot.type 枚举）
# ============================================================
ShotType = Literal[
    "extreme-wide",      # 极远景
    "wide",              # 远景
    "full",              # 全景
    "medium-wide",       # 中远景
    "medium",            # 中景
    "medium-close",      # 近景
    "close-up",          # 特写
    "extreme-close-up",  # 大特写
    "aerial",            # 航拍
    "dutch-angle",       # 斜角
    "over-shoulder",     # 过肩
    "pov",               # 主观视角
    "tracking",          # 跟拍
    "static",            # 静态固定
]


# ============================================================
# 情感类型（用于 Scene.emotion 枚举）
# ============================================================
EmotionType = Literal[
    "激昂", "温暖", "紧张", "轻松", "科技",
    "悲伤", "震撼", "幽默", "感性", "悬疑",
]


# ============================================================
# 转场类型（用于 Scene.transition 枚举）
# ============================================================
TransitionType = Literal[
    "硬切", "溶解", "淡入", "淡出", "淡入黑场",
    "淡入白场", "左划", "右划", "上划", "下划",
    "缩放转场", "匹配剪辑", "闪白", "故障",
]


# ============================================================
# 场景（脚本中的一个叙事段落）
# ============================================================
class Scene(TypedDict):
    """单个视频场景的结构化描述"""
    id: int                              # 场景序号（从 1 开始）
    title: str                           # 场景标题
    duration_sec: float                  # 场景时长（秒）
    narration: str                       # 旁白/解说词
    visual_description: str              # 画面建议/镜头描述
    emotion: EmotionType                 # 情感标签
    transition: NotRequired[str]         # 转场方式（可选）


# ============================================================
# 脚本（完整视频脚本）
# ============================================================
class Script(TypedDict):
    """完整视频脚本，由多个 Scene 组成"""
    title: str                           # 视频标题
    total_duration_sec: float            # 总时长（秒）
    scenes: List[Scene]                  # 场景列表
    keywords: List[str]                  # 关键词标签
    style_tags: List[str]                # 风格标签


# ============================================================
# 镜头（分镜中的一个拍摄单元）
# ============================================================
class Shot(TypedDict):
    """单个镜头的结构化描述"""
    id: str                              # 镜头 ID（如 "S1_1"）
    scene_id: int                        # 所属场景 ID
    type: ShotType                       # 镜头构图类型
    duration_sec: float                  # 镜头时长（秒）
    description: str                     # 镜头画面描述
    camera_movement: NotRequired[str]    # 摄像机运动描述（可选）


# ============================================================
# 分镜方案（完整的分镜计划）
# ============================================================
class Storyboard(TypedDict):
    """完整分镜方案，包含所有镜头和转场信息"""
    project_id: str                      # 项目 ID
    total_shots: int                     # 镜头总数
    shots: List[Shot]                    # 镜头列表
    transitions: List[dict]              # 转场列表（from/to/type）


# ============================================================
# 配音段落（单个配音片段）
# ============================================================
class VoiceSegment(TypedDict):
    """单个配音段落的结构化描述"""
    scene_id: int                        # 所属场景 ID
    text: str                            # 配音文本
    duration_sec: float                  # 配音时长（秒）
    pitch: NotRequired[int]              # 音高偏移（Hz，可选）
    speed: NotRequired[float]            # 语速倍率（可选）


# ============================================================
# 配音方案（完整配音计划）
# ============================================================
class Voiceover(TypedDict):
    """完整配音方案，包含音色选择和所有配音段落"""
    project_id: str                      # 项目 ID
    voice_profile: str                   # 音色名称（如 "male_clear"）
    segments: List[VoiceSegment]         # 配音段落列表
    audio_duration_sec: float            # 音频总时长（秒）
    audio_path: NotRequired[str]         # 音频文件路径（可选）


# ============================================================
# BGM 音轨信息
# ============================================================
class BGMTrack(TypedDict):
    """BGM 音轨的结构化描述"""
    track_name: str                      # 音轨名称
    bpm: int                             # 节拍数（BPM）
    genre: str                           # 音乐风格
    duration_sec: float                  # 时长（秒）
    mood: str                            # 情绪标签


# ============================================================
# 风格化结果（调色/滤镜应用结果）
# ============================================================
class StylizationResult(TypedDict):
    """调色与风格化处理的结果"""
    filter_applied: str                  # 应用的滤镜名称
    consistency_score: float             # 风格一致性评分（0.0 ~ 1.0）
    color_palette: List[str]             # 配色方案（hex 色值列表）
    lut_name: NotRequired[str]           # LUT 名称（可选）


# ============================================================
# 质检报告
# ============================================================
class QCReport(TypedDict):
    """质量检查报告"""
    fatal: int                           # 致命缺陷数
    major: int                           # 严重缺陷数
    minor: int                           # 轻微缺陷数
    pass_count: int                      # 通过检查数
    verdict: str                         # 判定结果（PASS / WARN / FAIL）
    issues: List[dict]                   # 缺陷详情列表


# ============================================================
# 交付包
# ============================================================
class DeliveryPackage(TypedDict):
    """最终交付物结构"""
    draft_format: str                    # 草稿格式（如 "jianying_pro"）
    video_duration_sec: float            # 视频时长（秒）
    director_notes: dict                 # 导演笔记（结构由 DeliveryAgent 定义）
    export_ready: bool                   # 是否可导出
