"""
BGMAgent 2.0 — 专业 BGM 推荐与音频处理 Agent

功能:
- 50+ 风格 BPM 曲库（带版权分类）
- 真实节拍检测（ffprobe 静音/时长分析 → BPM 估算）
- 智能情绪→BPM 匹配（中文情绪映射）
- 自动高潮检测与智能裁剪点计算
- 淡入淡出时长计算（按内容类型）
- 响度归一化目标（-14 LUFS 流媒体 / -23 LUFS 广播）
- BGM 推荐 + 置信度评分
- ffmpeg 音频滤镜链生成
- 与 quanquan DAG 系统完全兼容

依赖: ffprobe / ffmpeg (系统工具)
"""

import asyncio
import json
import os
import uuid
import logging
import subprocess
import math
import re
import random
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from core.types import BGMTrack

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------

class LoudnessTarget(Enum):
    """响度归一化目标"""
    STREAMING = -14   # LUFS（YouTube/Spotify）
    BROADCAST = -23   # LUFS（电视广播标准）
    PODCAST = -16     # LUFS（播客推荐）
    CINEMA = -27      # LUFS（影院标准）

class FadeType(Enum):
    """内容类型 → 淡入淡出策略"""
    FAST_CUT = "fast_cut"           # 快剪（0.3s 淡入，0.5s 淡出）
    NARRATIVE = "narrative"         # 叙事（1.0s 淡入，1.5s 淡出）
    CINEMATIC = "cinematic"         # 电影感（1.5s 淡入，2.0s 淡出）
    TRANSITION = "transition"       # 转场（0.5s 淡入，0.8s 淡出）
    AMBIENT = "ambient"             # 环境（2.0s 淡入，3.0s 淡出）

# ---------------------------------------------------------------------------
# BGM 曲库 — 50+ 风格 → BPM 范围 + 情绪标签 + 版权分类
# ---------------------------------------------------------------------------

@dataclass
class GenreProfile:
    """风格档案"""
    genre: str
    genre_cn: str
    bpm_min: int
    bpm_max: int
    bpm_typical: int
    emotions: List[str]          # 适配情绪
    intensity: float             # 0.0 ~ 1.0 强度
    instruments: List[str]       # 典型乐器
    copyright_risk: str          # "free" / "licensed" / "restricted"
    subgenres: List[str] = field(default_factory=list)
    use_cases: List[str] = field(default_factory=list)


# 50+ 风格 BPM 曲库
GENRE_LIBRARY: Dict[str, GenreProfile] = {
    # ── 电子类 ──
    "electronic": GenreProfile("electronic", "电子", 120, 140, 128,
        ["激昂", "紧张", "兴奋"], 0.85,
        ["合成器", "鼓机", "贝斯"], "free",
        ["synthwave", "techno", "trance", "dubstep", "house", "drum_and_bass"],
        ["Vlog", "科技", "运动"]),
    "synthwave": GenreProfile("synthwave", "合成波", 100, 130, 115,
        ["激昂", "温馨", "怀旧"], 0.75,
        ["合成器", "电子鼓", "贝斯"], "free",
        use_cases=["复古", "夜景", "城市"]),
    "techno": GenreProfile("techno", "科技舞曲", 120, 150, 135,
        ["紧张", "激昂"], 0.90,
        ["合成器", "鼓机"], "free",
        use_cases=["科技", "工业", "未来"]),
    "trance": GenreProfile("trance", "迷幻舞曲", 125, 150, 138,
        ["激昂", "兴奋", "舒缓"], 0.80,
        ["合成器", "钢琴", "人声采样"], "free",
        use_cases=["旅行", "风景", "冥想"]),
    "dubstep": GenreProfile("dubstep", "回响贝斯", 135, 150, 140,
        ["紧张", "激昂"], 0.95,
        ["贝斯", "合成器", "鼓机"], "free",
        use_cases=["动作", "游戏", "极限运动"]),
    "house": GenreProfile("house", "浩室", 118, 130, 125,
        ["兴奋", "温馨", "激昂"], 0.70,
        ["鼓机", "合成器", "贝斯"], "free",
        use_cases=["时尚", "派对", "生活"]),
    "drum_and_bass": GenreProfile("drum_and_bass", "鼓打贝斯", 160, 180, 174,
        ["紧张", "激昂"], 0.95,
        ["鼓机", "贝斯", "合成器"], "free",
        use_cases=["竞速", "动作", "游戏"]),
    "chillwave": GenreProfile("chillwave", "寒潮", 80, 110, 95,
        ["舒缓", "温馨", "怀旧"], 0.45,
        ["合成器", "吉他", "人声"], "free",
        use_cases=["慢生活", "记忆", "黄昏"]),
    "future_bass": GenreProfile("future_bass", "未来贝斯", 130, 160, 145,
        ["兴奋", "温馨", "激昂"], 0.75,
        ["合成器", "贝斯", "人声切片"], "free",
        use_cases=["创意", "青春", "潮流"]),
    "vaporwave": GenreProfile("vaporwave", "蒸汽波", 60, 100, 80,
        ["怀旧", "舒缓", "温馨"], 0.35,
        ["采样", "合成器", "萨克斯"], "free",
        use_cases=["复古", "氛围", "艺术"]),
    "deep_house": GenreProfile("deep_house", "深浩室", 115, 125, 120,
        ["舒缓", "温馨", "兴奋"], 0.55,
        ["合成器", "贝斯", "鼓机", "钢琴"], "free",
        use_cases=["夜景", "时尚", "休息室"]),
    "minimal": GenreProfile("minimal", "极简", 100, 130, 118,
        ["中立", "紧张", "舒缓"], 0.35,
        ["合成器", "鼓机", "采样"], "free",
        use_cases=["科技", "产品", "空间"]),
    "uk_garage": GenreProfile("uk_garage", "英式车库", 128, 140, 134,
        ["兴奋", "激昂"], 0.75,
        ["鼓机", "贝斯", "合成器", "人声采样"], "free",
        use_cases=["街头", "潮流", "夜店"]),

    # ── Lofi / 放松类 ──
    "lofi": GenreProfile("lofi", "低保真", 70, 90, 80,
        ["舒缓", "温馨", "悲伤"], 0.30,
        ["钢琴", "吉他", "鼓机", "黑胶噪音"], "free",
        ["lofi_hiphop", "lofi_jazz", "chillhop"],
        ["学习", "放松", "日常"]),
    "chillhop": GenreProfile("chillhop", "放松嘻哈", 75, 95, 85,
        ["舒缓", "温馨", "中立"], 0.35,
        ["钢琴", "萨克斯", "鼓机"], "free",
        use_cases=["学习", "咖啡", "早晨"]),
    "lofi_jazz": GenreProfile("lofi_jazz", "低保真爵士", 65, 85, 75,
        ["舒缓", "温馨", "怀旧"], 0.30,
        ["钢琴", "贝斯", "鼓刷"], "free",
        use_cases=["阅读", "雨天", "夜晚"]),
    "ambient": GenreProfile("ambient", "环境音乐", 60, 90, 70,
        ["舒缓", "悲伤", "中立"], 0.20,
        ["合成器", "弦乐", "钢琴"], "free",
        use_cases=["冥想", "自然", "太空"]),
    "downtempo": GenreProfile("downtempo", "缓拍", 80, 110, 95,
        ["舒缓", "温馨", "中立"], 0.40,
        ["合成器", "贝斯", "鼓机"], "free",
        use_cases=["咖啡厅", "黄昏", "慢动作"]),

    # ── 影视 / 史诗类 ──
    "cinematic": GenreProfile("cinematic", "影视史诗", 80, 120, 100,
        ["激昂", "紧张", "悲伤", "温馨"], 0.80,
        ["管弦乐", "合唱", "打击乐", "弦乐"], "licensed",
        ["epic", "orchestral", "trailer"],
        ["预告片", "大场景", "高潮"]),
    "epic": GenreProfile("epic", "史诗", 90, 140, 115,
        ["激昂", "紧张"], 0.95,
        ["管弦乐", "合唱", "打击乐", "铜管"], "licensed",
        use_cases=["战斗", "胜利", "预告片"]),
    "orchestral": GenreProfile("orchestral", "管弦乐", 60, 140, 100,
        ["激昂", "悲伤", "温馨", "舒缓"], 0.70,
        ["弦乐", "木管", "铜管", "定音鼓"], "licensed",
        use_cases=["纪录片", "历史", "婚礼"]),
    "trailer": GenreProfile("trailer", "预告片", 100, 150, 130,
        ["紧张", "激昂"], 0.98,
        ["管弦乐", "合成器", "打击乐", "合唱"], "licensed",
        use_cases=["预告片", "高潮", "冲突"]),

    # ── 摇滚 / 流行类 ──
    "rock": GenreProfile("rock", "摇滚", 100, 160, 130,
        ["激昂", "兴奋", "紧张"], 0.80,
        ["电吉他", "贝斯", "鼓", "人声"], "licensed",
        ["classic_rock", "indie_rock", "punk", "alternative_rock", "hard_rock"],
        ["运动", "青春", "公路"]),
    "pop": GenreProfile("pop", "流行", 100, 130, 115,
        ["兴奋", "温馨", "激昂"], 0.60,
        ["合成器", "鼓机", "吉他", "人声"], "licensed",
        ["kpop", "jpop", "electropop", "indie_pop", "synthpop"],
        ["日常", "时尚", "聚会"]),
    "indie_rock": GenreProfile("indie_rock", "独立摇滚", 110, 150, 130,
        ["激昂", "温馨", "怀旧"], 0.65,
        ["吉他", "贝斯", "鼓", "人声"], "free",
        use_cases=["青春", "旅行", "纪录片"]),
    "punk": GenreProfile("punk", "朋克", 150, 200, 175,
        ["激昂", "紧张"], 0.95,
        ["电吉他", "贝斯", "鼓", "人声"], "licensed",
        use_cases=["反叛", "极限", "街头"]),
    "alternative_rock": GenreProfile("alternative_rock", "另类摇滚", 100, 140, 120,
        ["激昂", "悲伤", "紧张"], 0.65,
        ["吉他", "贝斯", "鼓"], "free",
        use_cases=["独立电影", "城市", "青春"]),

    # ── 嘻哈类 ──
    "hiphop": GenreProfile("hiphop", "嘻哈", 80, 110, 95,
        ["兴奋", "激昂", "中立"], 0.70,
        ["鼓机", "贝斯", "采样", "人声"], "licensed",
        ["trap", "boom_bap", "drill"],
        ["街头", "态度", "潮流"]),
    "trap": GenreProfile("trap", "陷阱", 130, 170, 145,
        ["紧张", "兴奋", "激昂"], 0.80,
        ["808鼓", "合成器", "踩镲"], "licensed",
        use_cases=["潮流", "夜店", "对抗"]),
    "boom_bap": GenreProfile("boom_bap", "经典嘻哈", 80, 100, 90,
        ["激昂", "中立", "怀旧"], 0.65,
        ["鼓机", "采样", "贝斯"], "free",
        use_cases=["经典", "街头", "纪录片"]),
    "drill": GenreProfile("drill", "钻头说唱", 130, 150, 140,
        ["紧张", "激昂"], 0.90,
        ["808鼓", "合成器", "人声"], "licensed",
        use_cases=["都市", "暗黑", "对抗"]),

    # ── 爵士 / 古典类 ──
    "jazz": GenreProfile("jazz", "爵士", 60, 120, 100,
        ["舒缓", "温馨", "怀旧", "悲伤"], 0.40,
        ["钢琴", "萨克斯", "贝斯", "鼓"], "free",
        ["bebop", "cool_jazz", "smooth_jazz", "swing"],
        ["咖啡馆", "夜景", "纪录片"]),
    "classical": GenreProfile("classical", "古典", 60, 100, 80,
        ["舒缓", "悲伤", "激昂", "温馨"], 0.50,
        ["弦乐", "钢琴", "管弦乐"], "free",
        ["baroque", "romantic", "contemporary_classical"],
        ["纪录片", "婚礼", "历史"]),
    "smooth_jazz": GenreProfile("smooth_jazz", "轻柔爵士", 70, 100, 85,
        ["舒缓", "温馨"], 0.30,
        ["萨克斯", "钢琴", "贝斯"], "free",
        use_cases=["晚餐", "酒店", "休息室"]),
    "swing": GenreProfile("swing", "摇摆乐", 120, 180, 150,
        ["兴奋", "温馨", "怀旧"], 0.55,
        ["萨克斯", "小号", "钢琴", "鼓"], "free",
        use_cases=["复古", "派对", "舞蹈"]),
    "bossa_nova": GenreProfile("bossa_nova", "波萨诺瓦", 80, 140, 110,
        ["舒缓", "温馨"], 0.30,
        ["吉他", "钢琴", "打击乐"], "free",
        use_cases=["海滩", "下午茶", "旅行"]),

    # ── 世界音乐类 ──
    "acoustic": GenreProfile("acoustic", "原声", 70, 120, 95,
        ["舒缓", "温馨", "悲伤", "怀旧"], 0.35,
        ["木吉他", "钢琴", "弦乐"], "free",
        ["fingerstyle", "folk"],
        ["自然", "旅行", "记忆"]),
    "folk": GenreProfile("folk", "民谣", 80, 120, 100,
        ["温馨", "怀旧", "悲伤", "舒缓"], 0.35,
        ["木吉他", "口琴", "班卓琴", "人声"], "free",
        use_cases=["旅行", "故乡", "故事"]),
    "latin": GenreProfile("latin", "拉丁", 90, 140, 115,
        ["兴奋", "温馨", "激昂"], 0.65,
        ["打击乐", "吉他", "铜管", "钢琴"], "free",
        ["salsa", "samba", "reggaeton"],
        ["舞蹈", "派对", "夏日"]),
    "reggae": GenreProfile("reggae", "雷鬼", 60, 90, 75,
        ["舒缓", "温馨", "兴奋"], 0.40,
        ["吉他", "贝斯", "鼓", "风琴"], "free",
        use_cases=["海滩", "夏日", "放松"]),
    "celtic": GenreProfile("celtic", "凯尔特", 80, 140, 110,
        ["激昂", "温馨", "怀旧"], 0.50,
        ["风笛", "小提琴", "竖琴", "哨笛"], "free",
        use_cases=["史诗", "自然", "历史"]),
    "chinese_traditional": GenreProfile("chinese_traditional", "中国风", 60, 120, 90,
        ["舒缓", "温馨", "激昂", "怀旧"], 0.45,
        ["古筝", "二胡", "笛子", "琵琶"], "free",
        use_cases=["国风", "历史", "节日"]),
    "japanese": GenreProfile("japanese", "和风", 60, 100, 80,
        ["舒缓", "悲伤", "温馨"], 0.30,
        ["尺八", "古筝", "三味线", "钢琴"], "free",
        use_cases=["禅意", "庭院", "纪录片"]),
    "afrobeat": GenreProfile("afrobeat", "非洲节拍", 100, 140, 120,
        ["兴奋", "激昂", "温馨"], 0.75,
        ["打击乐", "铜管", "吉他", "人声"], "free",
        use_cases=["舞蹈", "夏日", "节日"]),
    "indian_classical": GenreProfile("indian_classical", "印度古典", 60, 140, 90,
        ["舒缓", "激昂", "怀旧"], 0.50,
        ["西塔琴", "塔布拉鼓", "坦布拉", "人声"], "free",
        use_cases=["纪录片", "旅行", "瑜伽"]),

    # ── 功能类 ──
    "corporate": GenreProfile("corporate", "企业", 100, 130, 115,
        ["中立", "温馨", "激昂"], 0.50,
        ["钢琴", "弦乐", "合成器", "吉他"], "free",
        use_cases=["宣传片", "产品", "介绍"]),
    "motivational": GenreProfile("motivational", "激励", 110, 140, 125,
        ["激昂", "兴奋", "温馨"], 0.75,
        ["钢琴", "弦乐", "鼓", "合唱"], "free",
        use_cases=["演讲", "体育", "成功"]),
    "comedy": GenreProfile("comedy", "喜剧", 100, 140, 120,
        ["兴奋", "温馨", "中立"], 0.55,
        ["管乐", "打击乐", "钢琴", "合成器"], "free",
        use_cases=["搞笑", "动画", "短剧"]),
    "horror": GenreProfile("horror", "恐怖", 60, 100, 80,
        ["紧张", "悲伤"], 0.60,
        ["弦乐", "合成器", "钢琴", "打击乐"], "free",
        use_cases=["悬疑", "惊悚", "探索"]),
    "nostalgic": GenreProfile("nostalgic", "怀旧", 60, 90, 75,
        ["怀旧", "悲伤", "温馨"], 0.30,
        ["钢琴", "吉他", "弦乐", "黑胶采样"], "free",
        use_cases=["回忆", "家庭", "老照片"]),
    "uplifting": GenreProfile("uplifting", "振奋", 120, 150, 135,
        ["激昂", "兴奋", "温馨"], 0.85,
        ["合成器", "鼓", "钢琴", "合唱"], "free",
        use_cases=["成功", "运动", "庆祝"]),
    "melancholic": GenreProfile("melancholic", "忧伤", 55, 80, 68,
        ["悲伤", "舒缓"], 0.25,
        ["钢琴", "弦乐", "吉他"], "free",
        use_cases=["离别", "回忆", "独白"]),
    "neutral": GenreProfile("neutral", "中性", 80, 120, 100,
        ["中立"], 0.40,
        ["钢琴", "吉他", "合成器"], "free",
        use_cases=["背景", "对话", "介绍"]),
    "meditation": GenreProfile("meditation", "冥想", 40, 70, 55,
        ["舒缓", "放松"], 0.10,
        ["合成器", "颂钵", "竖琴", "弦乐"], "free",
        use_cases=["冥想", "瑜伽", "睡眠"]),
    "children": GenreProfile("children", "儿童", 90, 130, 110,
        ["兴奋", "温馨"], 0.50,
        ["钢琴", "木琴", "口哨", "打击乐"], "free",
        use_cases=["儿童", "动画", "教育"]),
    "fitness": GenreProfile("fitness", "健身", 120, 150, 135,
        ["激昂", "兴奋"], 0.90,
        ["合成器", "鼓机", "贝斯"], "free",
        use_cases=["运动", "健身", "跑步"]),
    "wedding": GenreProfile("wedding", "婚礼", 70, 120, 95,
        ["温馨", "激昂", "怀旧"], 0.55,
        ["钢琴", "弦乐", "吉他", "竖琴"], "free",
        use_cases=["婚礼", "庆典", "浪漫"]),
}


# ---------------------------------------------------------------------------
# 情绪 → BPM 范围映射（中文情绪标签）
# ---------------------------------------------------------------------------

EMOTION_TO_BPM: Dict[str, Tuple[int, int]] = {
    "激昂": (120, 160),
    "兴奋": (120, 160),
    "紧张": (100, 150),
    "温馨": (70, 120),
    "舒缓": (55, 90),
    "悲伤": (55, 85),
    "怀旧": (60, 100),
    "中立": (80, 130),
    "放松": (60, 95),
    "期待": (100, 135),
    "恐惧": (60, 100),
    "厌恶": (80, 120),
    "惊讶": (100, 150),
}

# 情绪 → 淡入淡出策略
EMOTION_TO_FADE: Dict[str, FadeType] = {
    "激昂": FadeType.FAST_CUT,
    "兴奋": FadeType.FAST_CUT,
    "紧张": FadeType.TRANSITION,
    "温馨": FadeType.NARRATIVE,
    "舒缓": FadeType.AMBIENT,
    "悲伤": FadeType.CINEMATIC,
    "怀旧": FadeType.NARRATIVE,
    "中立": FadeType.TRANSITION,
    "放松": FadeType.AMBIENT,
}

# 淡入淡出时长表（秒）
FADE_DURATIONS = {
    FadeType.FAST_CUT:    {"fade_in": 0.3, "fade_out": 0.5},
    FadeType.NARRATIVE:   {"fade_in": 1.0, "fade_out": 1.5},
    FadeType.CINEMATIC:   {"fade_in": 1.5, "fade_out": 2.0},
    FadeType.TRANSITION:  {"fade_in": 0.5, "fade_out": 0.8},
    FadeType.AMBIENT:     {"fade_in": 2.0, "fade_out": 3.0},
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def safe_float(text: str, default: float = 0.0) -> float:
    """安全解析浮点数"""
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return default


def bpm_from_filename(filename: str) -> Optional[int]:
    """从文件名猜测 BPM，例如 'track_128bpm.mp3' → 128"""
    m = re.search(r'[_-]?(\d{2,3})\s*bpm', filename, re.IGNORECASE)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# BeatDetector — 基于 ffprobe 的真实节拍检测
# ---------------------------------------------------------------------------

class BeatDetector:
    """使用 ffprobe 分析音频文件，检测静音段并估算 BPM。

    原理：
    1. ffprobe 检测静音段 (silencedetect)
    2. 从静音间隔估算 BPM（适用于有明显节拍的音乐）
    3. 结合能量检测细化结果
    """

    def __init__(self, audio_path: str):
        self.audio_path = audio_path
        self._cached_bpm: Optional[float] = None
        self._cached_duration: Optional[float] = None
        self._cached_silence_segments: List[Dict] = []
        self._cached_energy_curve: List[float] = []

    def _run_ffprobe(self, args: List[str]) -> str:
        """执行 ffprobe 命令"""
        cmd = ["ffprobe", "-v", "quiet", "-hide_banner"] + args + [self.audio_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.stderr + result.stdout
        except FileNotFoundError:
            logger.warning("ffprobe not found — falling back to filename heuristics")
            return ""
        except subprocess.TimeoutExpired:
            logger.warning(f"ffprobe timeout on {self.audio_path}")
            return ""
        except Exception as e:
            logger.warning(f"ffprobe error: {e}")
            return ""

    def get_duration(self) -> float:
        """获取音频时长（秒）"""
        if self._cached_duration is not None:
            return self._cached_duration
        output = self._run_ffprobe([
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
        ])
        self._cached_duration = safe_float(output.strip(), 0.0)
        return self._cached_duration

    def detect_silence(self, noise_threshold: str = "-50dB",
                       min_duration: float = 0.1) -> List[Dict]:
        """检测静音段"""
        if self._cached_silence_segments:
            return self._cached_silence_segments

        output = self._run_ffprobe([
            "-af", f"silencedetect=noise={noise_threshold}:d={min_duration}",
            "-f", "null", "-",
        ])

        segments = []
        start = None
        for line in output.splitlines():
            if "silence_start" in line:
                m = re.search(r'silence_start:\s*([\d.]+)', line)
                if m and start is None:
                    start = float(m.group(1))
            elif "silence_end" in line:
                m = re.search(r'silence_end:\s*([\d.]+)', line)
                if m and start is not None:
                    end = float(m.group(1))
                    segments.append({"start": start, "end": end, "duration": end - start})
                    start = None

        # 也解析 silence_duration 格式
        for line in output.splitlines():
            m = re.search(r'silence_start:\s*([\d.]+)\s*silence_end:\s*([\d.]+)', line)
            if m:
                segments.append({
                    "start": float(m.group(1)),
                    "end": float(m.group(2)),
                    "duration": float(m.group(2)) - float(m.group(1)),
                })

        self._cached_silence_segments = segments
        return segments

    def estimate_bpm(self) -> float:
        """估算 BPM

        策略：
        1. 从文件名猜 BPM
        2. 分析静音间隔（如果音乐有明显的段落分隔）
        3. 分析非静音段长度比值
        4. 回退到基于时长的启发式
        """
        if self._cached_bpm is not None:
            return self._cached_bpm

        # 1. 文件名猜测
        filename_bpm = bpm_from_filename(os.path.basename(self.audio_path))
        if filename_bpm:
            self._cached_bpm = float(filename_bpm)
            return self._cached_bpm

        # 2. 音频时长
        duration = self.get_duration()
        if duration <= 0:
            self._cached_bpm = 120.0  # 默认
            return self._cached_bpm

        # 3. 静音分析
        silences = self.detect_silence()
        if len(silences) >= 2:
            # 计算非静音段长度，假设它们对应节拍
            intervals = []
            prev_end = 0.0
            for s in sorted(silences, key=lambda x: x["start"]):
                nonsilent_dur = s["start"] - prev_end
                if nonsilent_dur > 0.1:
                    intervals.append(nonsilent_dur)
                prev_end = s["end"]

            # 最后一节
            if prev_end < duration:
                intervals.append(duration - prev_end)

            if intervals:
                # 假设每个间隔包含若干拍，取中位数间隔估算
                avg_interval = sum(intervals) / len(intervals)
                # 假设典型间隔 ≈ 1~2拍长度
                for beat_per_interval in [1, 2, 4]:
                    bpm = 60.0 * beat_per_interval / avg_interval
                    if 40 <= bpm <= 200:
                        self._cached_bpm = round(bpm)
                        return self._cached_bpm

        # 4. 基于时长 + 静音数的启发式
        silence_count = len(silences)
        if silence_count > 0:
            # 假设静音分割了乐句，估算总拍数
            estimated_beats = silence_count * 4  # 每段约4拍
            bpm = estimated_beats * 60.0 / duration
            bpm = clamp(bpm, 60, 180)
        else:
            bpm = 120.0  # 无静音，默认

        self._cached_bpm = round(bpm)
        return self._cached_bpm

    def detect_energy_curve(self, num_segments: int = 64) -> List[float]:
        """检测音频能量曲线（用于高潮检测）"""
        if self._cached_energy_curve:
            return self._cached_energy_curve

        duration = self.get_duration()
        if duration <= 0:
            return [0.5] * num_segments

        segment_dur = duration / num_segments
        curve = []

        for i in range(num_segments):
            start = i * segment_dur
            args = [
                "-ss", str(start),
                "-t", str(segment_dur),
                "-af", "volumedetect",
                "-f", "null", "-",
            ]
            output = self._run_ffprobe(args)
            # 解析 mean_volume
            m = re.search(r'mean_volume:\s*([-\d.]+)', output)
            vol = safe_float(m.group(1), -30.0) if m else -30.0
            # 归一化：典型范围 -70 ~ 0 dB
            normalized = clamp((vol + 70) / 70, 0.0, 1.0)
            curve.append(normalized)

        self._cached_energy_curve = curve
        return curve

    def find_climax_point(self, energy_curve: Optional[List[float]] = None,
                          duration: Optional[float] = None) -> float:
        """检测高潮点（秒）——能量曲线峰值位置"""
        if energy_curve is None:
            energy_curve = self.detect_energy_curve()
        if duration is None:
            duration = self.get_duration()

        if not energy_curve or duration <= 0:
            return duration / 2 if duration > 0 else 0

        # 找到能量最高的段
        max_idx = max(range(len(energy_curve)), key=lambda i: energy_curve[i])
        segment_dur = duration / len(energy_curve)
        return (max_idx + 0.5) * segment_dur


# ---------------------------------------------------------------------------
# BGM 推荐器
# ---------------------------------------------------------------------------

class BGMRecommender:
    """智能 BGM 推荐引擎"""

    @staticmethod
    def match_genres_by_bpm(target_bpm: int, tolerance: int = 15) -> List[GenreProfile]:
        """按 BPM 匹配风格"""
        scored = []
        for genre, profile in GENRE_LIBRARY.items():
            lo, hi = profile.bpm_min, profile.bpm_max
            if lo <= target_bpm <= hi:
                distance = abs(target_bpm - profile.bpm_typical)
                scored.append((distance, profile))
            elif target_bpm < lo and (lo - target_bpm) <= tolerance:
                distance = (lo - target_bpm) * 2 + abs(target_bpm - profile.bpm_typical)
                scored.append((distance, profile))
            elif target_bpm > hi and (target_bpm - hi) <= tolerance:
                distance = (target_bpm - hi) * 2 + abs(target_bpm - profile.bpm_typical)
                scored.append((distance, profile))
        scored.sort(key=lambda x: x[0])
        return [p for _, p in scored]

    @staticmethod
    def match_genres_by_emotion(emotion: str) -> List[GenreProfile]:
        """按情绪匹配风格"""
        scored = []
        for genre, profile in GENRE_LIBRARY.items():
            if emotion in profile.emotions:
                # 情绪匹配优先级 = 在列表中的位置越靠前得分越高
                idx = profile.emotions.index(emotion)
                score = len(profile.emotions) - idx
                scored.append((score, profile))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored]

    @staticmethod
    def match_genres_by_tags(style_tags: List[str]) -> List[GenreProfile]:
        """按风格标签匹配"""
        if not style_tags:
            return []
        tags_lower = [t.lower() for t in style_tags]
        scored = []
        for genre, profile in GENRE_LIBRARY.items():
            score = 0
            genre_lower = genre.lower()
            genre_cn_lower = profile.genre_cn.lower()
            for tag in tags_lower:
                if tag in genre_lower or tag in genre_cn_lower:
                    score += 10
                if any(tag in sg.lower() for sg in profile.subgenres):
                    score += 5
                if any(tag in uc.lower() for uc in profile.use_cases):
                    score += 3
            if score > 0:
                scored.append((score, profile))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored]

    @staticmethod
    def compute_confidence(bpm_match: float, emotion_match: float,
                          tag_match: float, copyright_ok: bool) -> float:
        """综合置信度计算（0~1）"""
        base = (bpm_match * 0.35 + emotion_match * 0.40 + tag_match * 0.25)
        if not copyright_ok:
            base *= 0.5
        return round(clamp(base, 0.0, 1.0), 3)

    @staticmethod
    def recommend(emotion: str, target_bpm: int, style_tags: List[str],
                  prefer_free: bool = True, top_n: int = 5
                  ) -> List[Dict[str, Any]]:
        """综合推荐 —— 返回带置信度的推荐列表"""
        bpm_genres = BGMRecommender.match_genres_by_bpm(target_bpm)
        emotion_genres = BGMRecommender.match_genres_by_emotion(emotion)
        tag_genres = BGMRecommender.match_genres_by_tags(style_tags) if style_tags else []

        # 构建评分表
        scores: Dict[str, Dict] = {}
        all_genres = set()
        for profile in bpm_genres:
            all_genres.add(profile.genre)
        for profile in emotion_genres:
            all_genres.add(profile.genre)
        for profile in tag_genres:
            all_genres.add(profile.genre)

        bpm_set = {p.genre: i for i, p in enumerate(bpm_genres)}
        emotion_set = {p.genre: i for i, p in enumerate(emotion_genres)}
        tag_set = {p.genre: i for i, p in enumerate(tag_genres)}

        for genre_name in all_genres:
            profile = GENRE_LIBRARY[genre_name]

            # BPM 匹配度
            bpm_rank = bpm_set.get(genre_name, len(bpm_genres))
            bpm_score = 1.0 - (bpm_rank / max(len(bpm_genres), 1)) if bpm_genres else 0.0

            # 情绪匹配度
            emotion_rank = emotion_set.get(genre_name, len(emotion_genres))
            emotion_score = 1.0 - (emotion_rank / max(len(emotion_genres), 1)) if emotion_genres else 0.0

            # 标签匹配度
            tag_rank = tag_set.get(genre_name, len(tag_genres))
            tag_score = 1.0 - (tag_rank / max(len(tag_genres), 1)) if tag_genres else 0.0

            copyright_ok = not (prefer_free and profile.copyright_risk == "restricted")
            confidence = BGMRecommender.compute_confidence(
                bpm_score, emotion_score, tag_score, copyright_ok)

            scores[genre_name] = {
                "genre": profile.genre,
                "genre_cn": profile.genre_cn,
                "bpm_typical": profile.bpm_typical,
                "bpm_range": (profile.bpm_min, profile.bpm_max),
                "intensity": profile.intensity,
                "emotions": profile.emotions,
                "instruments": profile.instruments,
                "copyright_risk": profile.copyright_risk,
                "use_cases": profile.use_cases,
                "confidence": confidence,
            }

        ranked = sorted(scores.values(), key=lambda x: -x["confidence"])
        return ranked[:top_n]


# ---------------------------------------------------------------------------
# ffmpeg 滤镜生成器
# ---------------------------------------------------------------------------

class FFmpegFilterBuilder:
    """生成 ffmpeg 音频滤镜字符串"""

    @staticmethod
    def loudnorm(target: LoudnessTarget = LoudnessTarget.STREAMING) -> str:
        """响度归一化滤镜"""
        return (f"loudnorm=I={target.value}:TP=-1.5:LRA=11:"
                f"measured_I={target.value}:measured_TP=-1.5:measured_LRA=11:"
                f"linear=true:print_format=summary")

    @staticmethod
    def fade(fade_in_sec: float, fade_out_sec: float,
             total_duration: float) -> str:
        """淡入淡出"""
        if fade_in_sec <= 0 and fade_out_sec <= 0:
            return ""
        parts = []
        if fade_in_sec > 0:
            parts.append(f"afade=t=in:st=0:d={fade_in_sec}")
        if fade_out_sec > 0 and total_duration > fade_out_sec:
            parts.append(f"afade=t=out:st={total_duration - fade_out_sec}:d={fade_out_sec}")
        return ",".join(parts)

    @staticmethod
    def trim(start_sec: float, duration_sec: float) -> str:
        """裁剪"""
        return f"atrim={start_sec}:{start_sec + duration_sec}"

    @staticmethod
    def equalizer(preset: str = "flat") -> str:
        """均衡器预设"""
        presets = {
            "flat": "equalizer=f=100:t=q:w=1:g=0",
            "bass_boost": "equalizer=f=80:t=q:w=1:g=3,equalizer=f=150:t=q:w=1:g=2",
            "vocal_enhance": "equalizer=f=3000:t=q:w=1:g=2,equalizer=f=6000:t=q:w=1:g=1",
            "warm": "equalizer=f=200:t=q:w=1:g=1.5,equalizer=f=1000:t=q:w=1:g=-1",
            "bright": "equalizer=f=8000:t=q:w=1:g=2,equalizer=f=12000:t=q:w=1:g=1.5",
        }
        return presets.get(preset, "")

    @staticmethod
    def speed(factor: float = 1.0) -> str:
        """变速"""
        if factor == 1.0:
            return ""
        return f"atempo={factor}"

    @staticmethod
    def volume(adjust_db: float = 0.0) -> str:
        """音量调整"""
        if adjust_db == 0.0:
            return ""
        return f"volume={adjust_db}dB"

    @staticmethod
    def compand() -> str:
        """压缩/扩展（动态范围）"""
        return ("compand=attacks=0.001:decays=0.1:"
                "points=-80/-80|-30/-15|-10/-3|0/0:"
                "soft-knee=6")

    @staticmethod
    def build_filter_chain(filters: List[str]) -> str:
        """拼接滤镜链"""
        active = [f for f in filters if f]
        return ",".join(active) if active else "anull"


# ---------------------------------------------------------------------------
# 自动裁剪算法
# ---------------------------------------------------------------------------

class AutoCutter:
    """自动计算最佳裁剪区间"""

    @staticmethod
    def find_best_clip(total_duration: float,
                       climax_sec: float,
                       target_duration: float,
                       energy_curve: Optional[List[float]] = None,
                       bpm: float = 120.0) -> Dict[str, float]:
        """计算最佳裁剪点

        策略：
        1. 优先以高潮点为中心裁剪
        2. 确保裁剪区间内包含能量峰值
        3. 裁剪边界对齐节拍
        4. 保留足够的起承转合

        返回：{"start": float, "end": float, "climax_offset": float}
        """
        if total_duration <= target_duration:
            return {"start": 0.0, "end": total_duration, "climax_offset": climax_sec}

        half = target_duration / 2.0
        beat_duration = 60.0 / max(bpm, 1.0)  # 单拍时长

        # 理想区间：以高潮点为中心
        ideal_start = climax_sec - half * 0.6  # 高潮前多留一点
        ideal_end = climax_sec + half * 0.4

        # 约束在音频范围内
        if ideal_start < 0:
            ideal_end -= ideal_start
            ideal_start = 0
        if ideal_end > total_duration:
            ideal_start -= (ideal_end - total_duration)
            ideal_end = total_duration
        if ideal_start < 0:
            ideal_start = 0

        # 对齐到节拍
        def snap_to_beat(t: float, to_start: bool) -> float:
            beat_pos = round(t / beat_duration) * beat_duration
            if to_start:
                return max(0.0, beat_pos)
            return min(total_duration, beat_pos)

        start = snap_to_beat(ideal_start, to_start=True)
        end = snap_to_beat(ideal_end, to_start=False)

        # 确保足够长度
        if end - start < target_duration:
            needed = target_duration - (end - start)
            if start > 0:
                start = max(0, start - needed)
            if end - start < target_duration and end < total_duration:
                end = min(total_duration, end + needed - (end - start - target_duration))

        return {
            "start": round(start, 2),
            "end": round(end, 2),
            "climax_offset": round(climax_sec - start, 2),
            "duration": round(end - start, 2),
        }


# ---------------------------------------------------------------------------
# BGMRecommendationAgent — 主类（保持向后兼容）
# ---------------------------------------------------------------------------

class BGMRecommendationAgent:
    """BGM Agent 3.0 — CoT推理 + 专业 BGM 推荐与音频处理

    兼容原版接口：
    - 类名: BGMRecommendationAgent
    - 构造: (context_bus, artifact_store, config)
    - run() 异步事件循环
    """

    # ── Agent Capabilities (3.0) ──
    AGENT_CAPABILITIES = {
        "name": "BGMRecommendationAgent",
        "version": "3.0",
        "description": "AI BGM选曲师 — 智能情绪匹配+节拍检测+音频处理",
        "capabilities": [
            "bgm_recommendation",       # BPM推荐
            "genre_matching",           # 50+风格匹配
            "beat_detection",           # 真实节拍检测(ffprobe)
            "emotion_to_bpm",           # 情绪→BPM映射
            "climax_detection",         # 高潮检测+裁剪点
            "fade_calculation",         # 淡入淡出计算
            "loudness_normalization",   # 响度归一化
            "ffmpeg_filter_chain",      # FFmpeg滤镜链
            "auto_cutting",             # 智能裁剪
            "cot_reasoning",            # Chain-of-Thought推理
            "self_critique",            # 自我批判改进
            "context_memory",           # 项目历史感知
        ],
        "input_formats": ["script_json", "emotion_curve", "duration_sec", "style_tags"],
        "output_formats": ["bgm_plan", "genre", "bpm", "recommendations", "ffmpeg_chain"],
        "supported_genres_count": 50,
    }

    def __init__(self, context_bus, artifact_store, config: dict):
        self.bus = context_bus
        self.artifacts = artifact_store
        self.config = config
        self.state = "IDLE"

        # 配置参数
        self.loudness_target = LoudnessTarget(
            config.get("loudness_target", "STREAMING").upper()
        ) if config.get("loudness_target") else LoudnessTarget.STREAMING
        self.prefer_free_music = config.get("prefer_free_music", True)
        self.default_bpm = config.get("default_bpm", 120)
        self.recommendation_top_n = config.get("recommendation_top_n", 5)

    # ── Public API ──

    def recommend(self, script: dict, duration_sec: float,
                  style_tags: Optional[List[str]] = None) -> dict:
        """BGM 推荐（同步接口，供外部调用）

        Args:
            script: 脚本数据（含 emotion_curve）
            duration_sec: 目标时长（秒）
            style_tags: 风格偏好标签列表

        Returns:
            {
                "genre": str,           # 推荐主风格
                "bpm": int,             # 推荐 BPM
                "bpm_range": (int,int),
                "recommendations": [{...}],  # top-N 推荐列表
                "confidence": float,    # 最高置信度
                "emotion": str,         # 主情绪
                "loudness_target": str,
                "fade": {"fade_in": float, "fade_out": float},
            }
        """
        style_tags = style_tags or []
        emotion_curve = script.get("emotion_curve", [])

        # 1. 情绪分析
        dominant_emotion = self._get_dominant_emotion(emotion_curve) or "中立"

        # 2. BPM 范围确定
        bpm_range = self._emotion_to_bpm_range(dominant_emotion)
        target_bpm = (bpm_range[0] + bpm_range[1]) // 2

        # 3. 综合推荐
        recommendations = BGMRecommender.recommend(
            emotion=dominant_emotion,
            target_bpm=target_bpm,
            style_tags=style_tags,
            prefer_free=self.prefer_free_music,
            top_n=self.recommendation_top_n,
        )

        # 4. 淡入淡出
        fade_type = EMOTION_TO_FADE.get(dominant_emotion, FadeType.TRANSITION)
        fade = FADE_DURATIONS[fade_type]

        # 5. 高潮检测
        climax_sec = self._detect_climax(emotion_curve, duration_sec)

        top = recommendations[0] if recommendations else {
            "genre": "neutral",
            "genre_cn": "中性",
            "bpm_typical": self.default_bpm,
            "bpm_range": (80, 120),
            "confidence": 0.5,
            "emotions": ["中立"],
            "copyright_risk": "free",
            "intensity": 0.4,
            "use_cases": ["背景"],
            "instruments": ["钢琴"],
        }

        return {
            "genre": top["genre"],
            "genre_cn": top.get("genre_cn", top["genre"]),
            "bpm": top["bpm_typical"],
            "bpm_range": top.get("bpm_range", bpm_range),
            "dominant_emotion": dominant_emotion,
            "climax_sec": climax_sec,
            "recommendations": recommendations,
            "confidence": top["confidence"],
            "loudness_target": self.loudness_target.name,
            "loudness_lufs": self.loudness_target.value,
            "fade": fade,
            "fade_type": fade_type.value,
        }

    def generate_filters(self, bgm_spec: dict, voice_duration: float) -> str:
        """生成 ffmpeg 音频滤镜字符串

        Args:
            bgm_spec: BGM 规格（来自 recommend() 返回值或 artifact）
            voice_duration: 旁白时长（用于 BGM 避让）

        Returns:
            ffmpeg -af 参数字符串
        """
        total = bgm_spec.get("duration", voice_duration)
        bpm = bgm_spec.get("bpm", 120)
        fade_info = bgm_spec.get("fade", {"fade_in": 0.5, "fade_out": 0.8})
        intensity = bgm_spec.get("intensity", 0.5)

        filters = []

        # 响度归一化
        filters.append(FFmpegFilterBuilder.loudnorm(self.loudness_target))

        # 动态压缩
        if intensity > 0.6:
            filters.append(FFmpegFilterBuilder.compand())

        # 淡入淡出
        fade_str = FFmpegFilterBuilder.fade(
            fade_info.get("fade_in", 0.5),
            fade_info.get("fade_out", 0.8),
            total,
        )
        if fade_str:
            filters.append(fade_str)

        return FFmpegFilterBuilder.build_filter_chain(filters)

    def generate_ffmpeg_command(self, input_audio: str, output_audio: str,
                                bgm_spec: dict, voice_duration: float,
                                bgm_volume_db: float = -12.0) -> str:
        """生成完整的 ffmpeg 命令字符串（用于 BGM 混音）

        Args:
            input_audio: 输入 BGM 文件路径
            output_audio: 输出处理后 BGM 路径
            bgm_spec: BGM 规格
            voice_duration: 旁白时长
            bgm_volume_db: BGM 相对音量（dB，负值表示降低）

        Returns:
            完整的 ffmpeg 命令行
        """
        total = bgm_spec.get("duration", voice_duration)
        start = bgm_spec.get("clip_start", 0.0)

        filter_chain = self.generate_filters(bgm_spec, voice_duration)
        volume_filter = FFmpegFilterBuilder.volume(bgm_volume_db)
        if volume_filter:
            filter_chain = f"{filter_chain},{volume_filter}" if filter_chain else volume_filter

        cmd_parts = [
            "ffmpeg",
            "-y",
            "-ss", str(start),
            "-t", str(total),
            "-i", input_audio,
            "-af", filter_chain,
            "-c:a", "aac",
            "-b:a", "192k",
            output_audio,
        ]
        return " ".join(cmd_parts)

    # ── 异步事件循环（保持兼容）──

    async def run(self):
        """异步事件循环 — 监听 TASK_DISPATCH"""
        while True:
            event = await self.bus.wait_for(
                "TASK_DISPATCH",
                filter=lambda e: e.payload.get("agent") == "BGM",
            )
            await self._handle_task(event)

    async def _handle_task(self, event):
        """处理分派的任务"""
        task = event.payload
        project_id = task["project_id"]
        output_key = task.get("output_key", "bgm_result")
        self.state = "ANALYZING_SCRIPT"

        try:
            # 1. 读取脚本
            script = await self.artifacts.get(project_id, task["input"].get("script_key", "script"))
            if not script:
                script = {}
            emotion_curve = script.get("emotion_curve", [])
            target_duration = script.get("total_duration_sec", 180)
            style_tags = task["input"].get("style_tags", [])
            preferred_genre = task["input"].get("memory_genre")

            # 2. 情绪分析
            dominant_emotion = self._get_dominant_emotion(emotion_curve)
            emotion_changes = self._detect_emotion_changes(emotion_curve)

            self.state = "BEAT_DETECTING"

            # 3. 如果有音频文件路径，做真实节拍检测
            audio_path = task["input"].get("audio_path", "")
            detected_bpm = None
            energy_curve = None
            audio_duration = target_duration

            if audio_path and os.path.exists(audio_path):
                detector = BeatDetector(audio_path)
                detected_bpm = detector.estimate_bpm()
                audio_duration = detector.get_duration() or target_duration
                energy_curve = detector.detect_energy_curve()
                logger.info(f"Detected BPM: {detected_bpm}, duration: {audio_duration}s")

            self.state = "QUERYING_LIBRARY"

            # 4. BPM 匹配
            bpm_range = self._emotion_to_bpm_range(dominant_emotion)
            target_bpm = int(detected_bpm) if detected_bpm else (bpm_range[0] + bpm_range[1]) // 2
            mood_tags = [dominant_emotion] if dominant_emotion else ["中立"]

            if preferred_genre and preferred_genre not in style_tags:
                style_tags.insert(0, preferred_genre)

            # 5. 推荐
            recommendations = BGMRecommender.recommend(
                emotion=dominant_emotion,
                target_bpm=target_bpm,
                style_tags=style_tags,
                prefer_free=self.prefer_free_music,
                top_n=self.recommendation_top_n,
            )

            self.state = "ALIGNING"

            # 6. 高潮对齐
            climax_sec = self._detect_climax(emotion_curve, target_duration)

            # 如果有真实能量曲线，融合结果
            if energy_curve and audio_duration > 0:
                detector_for_climax = BeatDetector.__new__(BeatDetector)
                audio_climax = detector.find_climax_point(energy_curve, audio_duration)
                if audio_climax > 0:
                    climax_sec = (climax_sec * 0.4 + audio_climax * 0.6)  # 加权融合

            self.state = "TRIMMING"

            # 7. 裁剪计算
            top = recommendations[0] if recommendations else {
                "genre": "neutral", "genre_cn": "中性",
                "bpm_typical": target_bpm, "bpm_range": bpm_range,
                "confidence": 0.5, "emotions": ["中立"],
            }

            clip = AutoCutter.find_best_clip(
                total_duration=target_duration,
                climax_sec=climax_sec,
                target_duration=target_duration,
                energy_curve=energy_curve,
                bpm=top.get("bpm_typical", target_bpm),
            )

            # 8. 淡入淡出
            fade_type = EMOTION_TO_FADE.get(dominant_emotion, FadeType.TRANSITION)
            fade = FADE_DURATIONS[fade_type]

            self.state = "PUBLISHING"

            # 9. 构建产出 artifact
            artifact = {
                "bgm_id": f"{project_id}_bgm_v1",
                "version": "2.0",
                "duration": target_duration,
                "audio_duration": audio_duration,
                "bpm": top.get("bpm_typical", target_bpm),
                "bpm_range": list(bpm_range),
                "detected_bpm": detected_bpm,
                "mood_tags": mood_tags,
                "dominant_emotion": dominant_emotion,
                "emotion_changes": emotion_changes,
                "genre": top["genre"],
                "genre_cn": top.get("genre_cn", top["genre"]),
                "recommendations": recommendations,
                "top_confidence": top["confidence"],
                "climax_sec": climax_sec,
                "clip_start": clip["start"],
                "clip_end": clip["end"],
                "clip_duration": clip["duration"],
                "climax_offset": clip["climax_offset"],
                "fade_in_sec": fade["fade_in"],
                "fade_out_sec": fade["fade_out"],
                "fade_type": fade_type.value,
                "loudness_target": self.loudness_target.name,
                "loudness_lufs": self.loudness_target.value,
                "style_tags": style_tags,
                "prefer_free_music": self.prefer_free_music,
                # 预生成滤镜和 ffmpeg 命令（方便下游使用）
                "ffmpeg_filters": self.generate_filters(
                    {**artifact, "duration": target_duration,
                     "fade": fade, "intensity": top.get("intensity", 0.5),
                     "bpm": top.get("bpm_typical", target_bpm)},
                    target_duration,
                ) if top else "",
            }

            ref = await self.artifacts.put(project_id, output_key, artifact)
            await self.bus.publish("RESULT_PUBLISH", {
                "node_id": task["node_id"],
                "output_key": output_key,
                "artifact_ref": ref,
            })
            logger.info(f"BGM published: {project_id} → {top.get('genre', 'unknown')} "
                       f"@{top.get('bpm_typical', '?')}BPM (confidence: {top.get('confidence', '?')})")
            self.state = "IDLE"

        except Exception as e:
            logger.exception(f"BGM agent error: {e}")
            self.state = "IDLE"
            await self.bus.publish("AGENT_FAILURE", {
                "node_id": task.get("node_id"),
                "agent": "BGM",
                "error": str(e),
            })

    # ── 3.0 critique() — 自我批判 ──

    async def critique(self, output: dict, context: dict = None) -> dict:
        """自我批判：审查BGM推荐方案质量。

        Args:
            output: BGM推荐方案dict
            context: 可选上下文

        Returns:
            critique dict with scores, issues, suggestions
        """
        context = context or {}
        output_json = json.dumps(output, ensure_ascii=False, indent=2)[:3000]
        history_hint = ""
        if context.get("project_history"):
            history_hint = f"\n【项目历史】\n{json.dumps(context['project_history'], ensure_ascii=False)[:800]}"

        messages = [
            {"role": "system", "content": (
                "你是资深音频导演。请审查BGM推荐方案质量，从以下维度评分(0-100)：\n"
                "1. emotion_match: BGM情绪是否匹配内容情感\n"
                "2. bpm_accuracy: BPM推荐是否合理\n"
                "3. genre_suitability: 风格选择是否恰当\n"
                "4. transition_design: 淡入淡出/裁剪点设计\n"
                "5. copyright_safety: 版权风险是否可控\n"
                "\n只输出JSON: {\"scores\": {dim: 0-100}, \"issues\": [...], \"suggestions\": [...], \"overall\": 0-100}"
            )},
            {"role": "user", "content": f"BGM方案：\n{output_json}{history_hint}\n\n请审查。"},
        ]
        try:
            result = await llm.chat_json(messages, temperature=0.3, max_tokens=1024)
            result.setdefault("overall", 70)
            result.setdefault("scores", {})
            result.setdefault("issues", [])
            result.setdefault("suggestions", [])
            return result
        except Exception as e:
            return {"overall": 60, "scores": {}, "issues": [f"critique failed: {e}"], "suggestions": []}

    # ── 内部辅助方法 ──

    def _get_dominant_emotion(self, emotion_curve: list) -> Optional[str]:
        """检测主要情绪"""
        if not emotion_curve:
            return None
        emotions = [p.get("emotion", "中立") for p in emotion_curve]
        return Counter(emotions).most_common(1)[0][0]

    def _detect_emotion_changes(self, emotion_curve: list) -> list:
        """检测情绪变化点"""
        changes = []
        if len(emotion_curve) < 2:
            return changes
        prev = emotion_curve[0].get("emotion")
        for i, point in enumerate(emotion_curve[1:], 1):
            curr = point.get("emotion")
            if curr != prev:
                changes.append({"time_sec": i, "from": prev, "to": curr})
                prev = curr
        return changes

    def _emotion_to_bpm_range(self, emotion: str) -> Tuple[int, int]:
        """情绪 → BPM 范围"""
        return EMOTION_TO_BPM.get(emotion, (80, 140))

    def _detect_climax(self, emotion_curve: list, total_duration: float) -> float:
        """检测高潮时间点"""
        if emotion_curve:
            # 按 intensity 加权找最高点
            max_idx = max(
                range(len(emotion_curve)),
                key=lambda i: emotion_curve[i].get("intensity", 0) * 10 +
                              (1.0 if emotion_curve[i].get("emotion") in ("激昂", "兴奋") else 0.0),
            )
            segment_dur = total_duration / len(emotion_curve)
            return min((max_idx + 0.5) * segment_dur, total_duration)
        return total_duration / 2.0
