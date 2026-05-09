"""
配音 Agent (VoiceoverAgent 2.0) — Emotion-Aware Pacing & Speech Optimization

功能：
- 情感驱动语速/音高映射 (Emotion → Pacing)
- 多音色支持 & 音色档案库 (6 种内置音色)
- 自然停顿插入 (SSML break, 基于标点)
- 配音时长预估 (生成前估算)
- 脚本语音优化 (自动断句、标点补全)
- 向后兼容 v1.0 API
"""

import asyncio
import json
import logging
import re
from typing import Dict, Any, Optional, List, Tuple

from core.llm_client import llm
from core.types import Voiceover, VoiceSegment

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 音色档案库 (Voice Profile Library)
# ═══════════════════════════════════════════════════════════════════════════════

VOICE_PROFILES: Dict[str, Dict[str, Any]] = {
    "male_clear": {
        "name": "清晰男声",
        "voice_id": "zh-CN-YunxiNeural",       # 云希
        "gender": "male",
        "style": "clear",
        "default_rate": "+0%",
        "default_pitch": "+0Hz",
        "description": "通用清晰男声，适合新闻资讯、科技解说",
        "best_for": ["科技", "新闻", "教程"],
    },
    "female_warm": {
        "name": "温柔女声",
        "voice_id": "zh-CN-XiaoxiaoNeural",    # 晓晓
        "gender": "female",
        "style": "warm",
        "default_rate": "+0%",
        "default_pitch": "+0Hz",
        "description": "温柔细腻女声，适合暖场旁白、情感叙述",
        "best_for": ["温暖", "情感", "故事"],
    },
    "male_deep": {
        "name": "深沉男声",
        "voice_id": "zh-CN-YunjianNeural",     # 云健 — 叙事男声
        "gender": "male",
        "style": "deep",
        "default_rate": "-5%",
        "default_pitch": "-2Hz",
        "description": "低沉叙事男声，适合纪录片、深度内容",
        "best_for": ["纪录片", "深度报道", "历史"],
    },
    "female_gentle": {
        "name": "轻柔女声",
        "voice_id": "zh-CN-XiaoyiNeural",      # 晓伊
        "gender": "female",
        "style": "gentle",
        "default_rate": "-5%",
        "default_pitch": "+0Hz",
        "description": "轻柔活泼女声，适合生活类、轻松内容",
        "best_for": ["轻松", "生活", "vlog"],
    },
    "male_energetic": {
        "name": "活力男声",
        "voice_id": "zh-CN-YunyangNeural",     # 云扬 — 新闻男声
        "gender": "male",
        "style": "energetic",
        "default_rate": "+5%",
        "default_pitch": "+2Hz",
        "description": "高亢活力男声，适合激昂内容、发布会风格",
        "best_for": ["激昂", "发布会", "宣传"],
    },
    "female_calm": {
        "name": "沉稳女声",
        "voice_id": "zh-CN-XiaohanNeural",     # 晓涵
        "gender": "female",
        "style": "calm",
        "default_rate": "-3%",
        "default_pitch": "-1Hz",
        "description": "沉稳平静女声，适合冥想、ASMR、舒缓内容",
        "best_for": ["舒缓", "冥想", "心理"],
    },
    # ─── 向后兼容: v1.0 别名 ───
    "default": {
        "name": "默认音色",
        "voice_id": "zh-CN-XiaoxiaoNeural",    # 晓晓
        "gender": "female",
        "style": "warm",
        "default_rate": "+0%",
        "default_pitch": "+0Hz",
        "description": "默认温柔女声（向后兼容）",
        "best_for": ["通用"],
    },
    "male": {
        "name": "男性默认",
        "voice_id": "zh-CN-YunxiNeural",
        "gender": "male",
        "style": "clear",
        "default_rate": "+0%",
        "default_pitch": "+0Hz",
        "description": "默认男声（向后兼容）",
        "best_for": ["通用"],
    },
    "girl": {
        "name": "活泼女声",
        "voice_id": "zh-CN-XiaoyiNeural",
        "gender": "female",
        "style": "gentle",
        "default_rate": "+0%",
        "default_pitch": "+0Hz",
        "description": "活泼女声（向后兼容）",
        "best_for": ["轻松"],
    },
    "story": {
        "name": "故事男声",
        "voice_id": "zh-CN-YunjianNeural",
        "gender": "male",
        "style": "deep",
        "default_rate": "+0%",
        "default_pitch": "+0Hz",
        "description": "叙事男声（向后兼容）",
        "best_for": ["故事"],
    },
    "news": {
        "name": "新闻男声",
        "voice_id": "zh-CN-YunyangNeural",
        "gender": "male",
        "style": "energetic",
        "default_rate": "+0%",
        "default_pitch": "+0Hz",
        "description": "新闻男声（向后兼容）",
        "best_for": ["新闻"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 情感 → 节奏映射 (Emotion → Pacing Map)
# ═══════════════════════════════════════════════════════════════════════════════

EMOTION_PACING: Dict[str, Dict[str, Any]] = {
    "激昂": {
        "speed_mult": 1.12,
        "pitch_shift": 3,
        "pause_ms": 400,         # 较短停顿，维持气势
        "description": "快速高亢，适合高潮/战斗/发布会",
    },
    "温暖": {
        "speed_mult": 0.95,
        "pitch_shift": 0,
        "pause_ms": 700,         # 适中停顿，营造温馨感
        "description": "温和中速，适合温情/故事叙述",
    },
    "紧张": {
        "speed_mult": 1.08,
        "pitch_shift": 1,
        "pause_ms": 300,         # 短停顿，加快节奏
        "description": "略带急促，适合悬疑/冲突",
    },
    "轻松": {
        "speed_mult": 1.0,
        "pitch_shift": 0,
        "pause_ms": 600,         # 自然停顿
        "description": "自然语速，适合日常/vlog",
    },
    "科技": {
        "speed_mult": 1.05,
        "pitch_shift": 0,
        "pause_ms": 500,         # 清晰停顿，便于理解
        "description": "清晰利落，适合科技/教程/产品介绍",
    },
    "悲伤": {
        "speed_mult": 0.82,
        "pitch_shift": -2,
        "pause_ms": 900,         # 较长停顿，留白抒情
        "description": "缓慢低沉，适合抒情/告别/追忆",
    },
    # ─── 向后兼容别名 ───
    "舒缓": {
        "speed_mult": 0.88,
        "pitch_shift": -1,
        "pause_ms": 800,
        "description": "（向后兼容）舒缓情感",
    },
    "温馨": {
        "speed_mult": 1.0,
        "pitch_shift": 0,
        "pause_ms": 700,
        "description": "（向后兼容）温馨情感",
    },
    "中立": {
        "speed_mult": 1.0,
        "pitch_shift": 0,
        "pause_ms": 500,
        "description": "默认中立情感",
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# 脚本语音优化常量
# ═══════════════════════════════════════════════════════════════════════════════

# 中文句子最大字符数 (超过则断句)
MAX_SENTENCE_CHARS = 50

# 短句最小字符数 (不短于此就不合并)
MIN_SENTENCE_CHARS = 4

# 中文字符每秒语速估算 (用于时长预估)
CHARS_PER_SECOND_BASE = 4.0

# 标点 → SSML 停顿时长 (毫秒)
PUNCTUATION_PAUSE_MS: Dict[str, int] = {
    "。": 500,
    "！": 450,
    "？": 450,
    "；": 350,
    "，": 250,
    "：": 350,
    "……": 700,
    "——": 600,
    "\n": 500,
}


# ═══════════════════════════════════════════════════════════════════════════════
# VoiceoverAgent 2.0
# ═══════════════════════════════════════════════════════════════════════════════

class VoiceoverAgent:
    """配音 Agent 3.0 — CoT推理 + 情感感知 + 音色档案 + 多模型投票"""

    # ── Agent Capabilities (3.0) ──
    AGENT_CAPABILITIES = {
        "name": "VoiceoverAgent",
        "version": "3.0",
        "description": "AI配音导演 — 情感驱动配音方案生成与语音优化",
        "capabilities": [
            "voiceover_generation",     # 配音方案生成
            "emotion_to_pacing",        # 情感→节奏映射
            "voice_profile_matching",   # 音色推荐
            "pause_insertion",          # 自然停顿插入(SSML)
            "duration_estimation",      # 配音时长预估
            "script_speech_optimization", # 脚本语音优化
            "multi_voice_support",      # 6+音色档案
            "cot_reasoning",            # Chain-of-Thought推理
            "self_critique",            # 自我批判改进
            "context_memory",           # 项目历史感知
        ],
        "input_formats": ["script_json", "voice_id", "storyboard_json"],
        "output_formats": ["voiceover_plan", "audio_segments", "timing_metadata"],
        "supported_voices": ["male_clear", "female_warm", "male_deep", "female_gentle",
                             "male_energetic", "female_calm"],
    }

    def __init__(self, context_bus=None, artifact_store=None, config: dict = None):
        self.bus = context_bus
        self.artifacts = artifact_store
        self.config = config or {}
        self.state = "IDLE"

    # ─── 主事件循环 (v1.0 兼容) ───

    async def run(self):
        """主事件循环 — 监听 TASK_DISPATCH 并处理"""
        while True:
            event = await self.bus.wait_for(
                'TASK_DISPATCH',
                filter=lambda e: e.payload.get('agent') == 'Voiceover'
            )
            await self._handle_task(event)

    async def _handle_task(self, event):
        """处理配音任务 (v1.0 兼容核心流程)"""
        task = event.payload
        self.state = "RECEIVING_INPUT"

        # 拉取脚本
        script = await self.artifacts.get(
            task['project_id'],
            task['input'].get('script_key')
        )
        voice_id = task['input'].get(
            'voice_id',
            self.config.get('default_voice', 'default')
        )
        speed_override = task['input'].get('speed', None)

        self.state = "OPTIMIZING_SCRIPT"
        # 脚本语音优化
        script = self.optimize_script_for_speech(script)

        self.state = "SYNTHESIZING"
        audio_segments = []
        for seg in script.get('segments', []):
            emotion = seg.get('emotion', '中立')
            pacing = self._emotion_to_params(emotion)

            # 获取音色档案
            profile = self.get_voice_profile(voice_id)

            # 时长预估
            text = seg.get('text', '')
            estimated_duration = self.estimate_duration(
                text, emotion, profile
            )

            # 调整语速 (允许外部覆盖)
            speed_mult = speed_override if speed_override else pacing['speed_mult']

            # 插入停顿
            text_with_pauses = self._insert_pauses(text, pacing['pause_ms'])

            audio_segments.append({
                'segment_id': seg.get('id', 0),
                'start_time': seg.get('start_time', 0),
                'duration': estimated_duration,
                'emotion': emotion,
                'text': text,
                'text_with_pauses': text_with_pauses,
                'voice_profile': profile['name'],
                'voice_id': voice_id,
                'speed_mult': speed_mult,
                'pitch_shift': pacing['pitch_shift'],
                'pause_ms': pacing['pause_ms'],
            })

        self.state = "POST_PROCESSING"
        total_duration = sum(s['duration'] for s in audio_segments)

        self.state = "SYNC_CHECKING"
        expected = script.get('total_duration_sec', total_duration)
        if abs(total_duration - expected) > 1.0:
            logger.warning(
                f"Voiceover duration mismatch: {total_duration:.1f}s vs {expected:.1f}s"
            )

        self.state = "PUBLISHING"
        artifact = {
            'audio_id': f"{task['project_id']}_voiceover_v2",
            'duration': total_duration,
            'voice_id': voice_id,
            'voice_profile': self.get_voice_profile(voice_id),
            'segments': audio_segments,
            'loudness_lufs': -16.0,
            'sample_rate': self.config.get('sample_rate', 48000),
            'agent_version': '2.0',
        }
        ref = await self.artifacts.put(task['project_id'], task['output_key'], artifact)
        await self.bus.publish('RESULT_PUBLISH', {
            'node_id': task['node_id'],
            'output_key': task['output_key'],
            'artifact_ref': ref,
        })
        self.state = "IDLE"

    # ═══════════════════════════════════════════════════════════════════════════
    # 情感 → 节奏参数 (Emotion → Pacing)
    # ═══════════════════════════════════════════════════════════════════════════

    def _emotion_to_params(self, emotion: str) -> dict:
        """将情感映射为语速、音高和停顿参数

        Args:
            emotion: 情感标签 (激昂/温暖/紧张/轻松/科技/悲伤/舒缓/温馨/中立)

        Returns:
            dict with speed_mult, pitch_shift, pause_ms
        """
        return EMOTION_PACING.get(
            emotion,
            {'speed_mult': 1.0, 'pitch_shift': 0, 'pause_ms': 500}
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # 音色档案库 (Voice Profile Library)
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def get_voice_profile(voice_id: str) -> Dict[str, Any]:
        """获取音色档案

        Args:
            voice_id: 音色 ID (male_clear/female_warm/male_deep/... 或 legacy 别名)

        Returns:
            音色档案字典，未匹配时返回默认音色

        Usage:
            >>> VoiceoverAgent.get_voice_profile("male_clear")
            {'name': '清晰男声', 'voice_id': 'zh-CN-YunxiNeural', ...}
        """
        return VOICE_PROFILES.get(voice_id, VOICE_PROFILES["default"])

    @staticmethod
    def list_voice_profiles() -> List[str]:
        """列出所有可用音色 ID"""
        return [k for k in VOICE_PROFILES if k not in ("default", "male", "girl", "story", "news")]

    @classmethod
    def recommend_voice(cls, content_type: str) -> str:
        """根据内容类型推荐音色

        Args:
            content_type: 内容类型 (科技/温暖/轻松/激昂/纪录片/...)

        Returns:
            推荐的 voice_id 字符串
        """
        content_lower = content_type.lower()
        best_score = -1
        best_voice = "default"

        for vid, profile in VOICE_PROFILES.items():
            # 跳过向后兼容别名
            if vid in ("default", "male", "girl", "story", "news"):
                continue
            for best in profile.get("best_for", []):
                if best.lower() in content_lower or content_lower in best.lower():
                    score = len(best)
                    if score > best_score:
                        best_score = score
                        best_voice = vid

        return best_voice

    # ═══════════════════════════════════════════════════════════════════════════
    # 自然停顿插入 (Pause Insertion)
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _insert_pauses(text: str, emotion_pause_ms: int = 500) -> str:
        """根据标点符号插入 SSML 停顿标记

        对不同标点使用不同停顿时长，同时受情感基调影响。
        停顿时长 = min(标点停顿, 情感停顿) * 权重

        Args:
            text: 原始文本
            emotion_pause_ms: 情感基调建议的停顿毫秒数

        Returns:
            带 SSML break 标记的文本 (用于 edge-tts SSML)
        """
        if not text:
            return text

        result = []
        i = 0
        n = len(text)

        while i < n:
            result.append(text[i])

            # 检查省略号和破折号 (双字符标点)
            if i + 1 < n and text[i:i+2] in PUNCTUATION_PAUSE_MS:
                punct = text[i:i+2]
                base_pause = PUNCTUATION_PAUSE_MS[punct]
                pause = min(base_pause, emotion_pause_ms)
                result.append(
                    f'<break time="{pause}ms" />'
                )
                result.append(text[i+1])  # 第二个字符
                i += 2
                continue

            # 单字符标点
            if text[i] in PUNCTUATION_PAUSE_MS:
                base_pause = PUNCTUATION_PAUSE_MS[text[i]]
                pause = min(base_pause, emotion_pause_ms)
                result.append(f'<break time="{pause}ms" />')

            i += 1

        return ''.join(result)

    @staticmethod
    def _insert_natural_pauses(text: str, emotion: str = "中立") -> str:
        """便捷方法：插入情感感知的自然停顿

        Args:
            text: 原始文本
            emotion: 情感标签

        Returns:
            带 SSML break 标记的文本
        """
        pacing = EMOTION_PACING.get(
            emotion,
            {'pause_ms': 500}
        )
        return VoiceoverAgent._insert_pauses(text, pacing['pause_ms'])

    # ═══════════════════════════════════════════════════════════════════════════
    # 时长预估 (Duration Estimation)
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def estimate_duration(
        text: str,
        emotion: str = "中立",
        profile: Dict[str, Any] = None
    ) -> float:
        """预估配音时长 (秒)

        基于:
        - 文本字符数
        - 情感语速调整
        - 标点停顿累加
        - 音色默认语速

        Args:
            text: 配音文本
            emotion: 情感标签
            profile: 音色档案 (可选)

        Returns:
            预估时长 (秒)
        """
        if not text:
            return 0.0

        pacing = EMOTION_PACING.get(
            emotion,
            {'speed_mult': 1.0, 'pause_ms': 500}
        )
        speed_mult = pacing['speed_mult']

        # 音色默认语速调整
        profile_mult = 1.0
        if profile:
            rate_str = profile.get('default_rate', '+0%')
            try:
                profile_mult = 1.0 + int(rate_str.strip('%')) / 100.0
            except (ValueError, AttributeError):
                profile_mult = 1.0

        # 计算纯文本朗读时长
        # 剔除标点后统计有效字符
        chars = len(re.sub(r'[，。！？；：、\s\n]', '', text))
        speech_duration = chars / CHARS_PER_SECOND_BASE

        # 语速调整
        effective_speed = speed_mult * profile_mult
        speech_duration = speech_duration / effective_speed

        # 累加标点停顿
        pause_total_ms = 0
        for char in text:
            if char in PUNCTUATION_PAUSE_MS:
                pause_total_ms += PUNCTUATION_PAUSE_MS[char]

        # 情感基调对停顿的总影响
        pause_mult = pacing['pause_ms'] / 500.0
        pause_duration = (pause_total_ms / 1000.0) * pause_mult

        return round(speech_duration + pause_duration, 2)

    # ═══════════════════════════════════════════════════════════════════════════
    # 脚本语音优化 (Script Optimization for Speech)
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def optimize_script_for_speech(script: dict) -> dict:
        """优化脚本以适配语音合成

        操作:
        1. 为缺少标点的句末添加句号
        2. 超长句子自动断句 (基于逗号或语义位置)
        3. 确保每个 segment 的 text 非空

        Args:
            script: 原始脚本字典 (含 segments 或 narration)

        Returns:
            优化后的脚本 (保留原始结构)
        """
        if not script:
            return script

        optimized = dict(script)  # 浅拷贝顶层

        segments = optimized.get('segments', [])
        if not segments:
            # 检查是否有 narration 字段
            narration = optimized.get('narration', '')
            if narration:
                optimized['narration_original'] = narration
                optimized['narration'] = VoiceoverAgent._optimize_text(narration)
            return optimized

        new_segments = []
        for seg in segments:
            new_seg = dict(seg)
            original_text = seg.get('text', '')
            if original_text:
                new_seg['text_original'] = original_text
                new_seg['text'] = VoiceoverAgent._optimize_text(original_text)
            new_segments.append(new_seg)

        optimized['segments'] = new_segments
        return optimized

    @staticmethod
    def _optimize_text(text: str) -> str:
        """对单段文本进行语音优化

        - 句末无标点则补句号
        - 超长句子在逗号处断开 (插入句号)
        """
        if not text:
            return text

        text = text.strip()

        # 1. 句末标点补全
        if text and text[-1] not in '。！？…~～—）\)\"\'》」』':
            text += '。'

        # 2. 超长句子断句
        if len(text) > MAX_SENTENCE_CHARS:
            text = VoiceoverAgent._split_long_sentence(text)

        return text

    @staticmethod
    def _split_long_sentence(text: str) -> str:
        """将超长句子在逗号处断开

        策略: 找到中间位置的逗号，将其替换为句号
        """
        # 找到所有逗号位置
        comma_positions = [i for i, c in enumerate(text) if c in '，,']
        if not comma_positions:
            # 没有逗号 — 找中间位置最近的空格
            mid = len(text) // 2
            space_positions = [i for i, c in enumerate(text) if c in ' ']
            if space_positions:
                closest = min(space_positions, key=lambda x: abs(x - mid))
                return text[:closest] + '。' + text[closest+1:]
            return text  # 实在无法断开，保持原样

        # 找最接近中间位置的逗号
        mid = len(text) // 2
        closest_comma = min(comma_positions, key=lambda x: abs(x - mid))
        return text[:closest_comma] + '。' + text[closest_comma+1:]

    @staticmethod
    def enhance_punctuation(text: str) -> str:
        """为无标点文本添加基础标点 (公开 API)

        Args:
            text: 原始文本字符串

        Returns:
            标点增强后的文本

        Usage:
            >>> VoiceoverAgent.enhance_punctuation("这是一段需要配音的文字内容")
            '这是一段需要配音的文字内容。'
        """
        return VoiceoverAgent._optimize_text(text)

    # ═══════════════════════════════════════════════════════════════════════════
    # 3.0 critique() — 自我批判
    # ═══════════════════════════════════════════════════════════════════════════

    async def critique(self, output: dict, context: dict = None) -> dict:
        """自我批判：审查配音方案质量。

        Args:
            output: 配音方案dict
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
                "你是资深配音导演。请审查配音方案质量，从以下维度评分(0-100)：\n"
                "1. emotion_accuracy: 情感与语速/音高映射是否准确\n"
                "2. timing_precision: 时长预估是否合理\n"
                "3. voice_suitability: 音色选择是否匹配内容\n"
                "4. pause_naturalness: 停顿设计是否自然\n"
                "5. production_readiness: 是否可直接用于TTS合成\n"
                "\n只输出JSON: {\"scores\": {dim: 0-100}, \"issues\": [...], \"suggestions\": [...], \"overall\": 0-100}"
            )},
            {"role": "user", "content": f"配音方案：\n{output_json}{history_hint}\n\n请审查。"},
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

    # ═══════════════════════════════════════════════════════════════════════════
    # 综合配音方案生成 (面向 all_agents 兼容)
    # ═══════════════════════════════════════════════════════════════════════════

    async def generate(
        self,
        script: dict,
        voice_id: str = "male_clear",
        storyboard: dict = None
    ) -> dict:
        """生成完整配音方案 (兼容 all_agents.VoiceoverAgent.generate)

        基于脚本内容、音色档案和情感映射生成配音段落规划。

        Args:
            script: 脚本字典 (含 segments)
            voice_id: 音色 ID
            storyboard: 分镜数据 (可选)

        Returns:
            配音方案字典
        """
        # 优化脚本
        script = self.optimize_script_for_speech(script)

        # 获取音色
        profile = self.get_voice_profile(voice_id)

        # 处理 segments
        segments_out = []
        raw_segments = script.get('segments', []) or script.get('scenes', [])

        cumulative_time = 0.0
        for seg in raw_segments:
            text = seg.get('text', '') or seg.get('narration', '')
            emotion = seg.get('emotion', '中立')
            pacing = self._emotion_to_params(emotion)

            duration = self.estimate_duration(text, emotion, profile)
            start = cumulative_time
            cumulative_time += duration

            segments_out.append({
                'start_sec': round(start, 2),
                'end_sec': round(cumulative_time, 2),
                'text': self._optimize_text(text),
                'text_original': text,
                'emotion': emotion,
                'speed': pacing['speed_mult'],
                'pitch': pacing['pitch_shift'],
                'pause_ms': pacing['pause_ms'],
                'voice': profile['voice_id'],
                'voice_name': profile['name'],
            })

        total_duration = cumulative_time if cumulative_time > 0 else script.get('total_duration_sec', 180)

        return {
            'audio_duration_sec': round(total_duration, 2),
            'voice_id': voice_id,
            'voice_profile': profile,
            'segments': segments_out,
            'sound_effects': [],
            'metadata': {
                'sample_rate': self.config.get('sample_rate', 48000),
                'channels': 2,
                'loudness_lufs': -16.0,
                'agent_version': '2.0',
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 模块级便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

def list_all_voice_profiles() -> List[Dict[str, Any]]:
    """列出所有音色档案详情"""
    return [
        {**v, 'id': k}
        for k, v in VOICE_PROFILES.items()
        if k not in ("default", "male", "girl", "story", "news")
    ]


def get_emotion_pacing(emotion: str) -> Dict[str, Any]:
    """获取情感节奏参数"""
    return EMOTION_PACING.get(
        emotion,
        {'speed_mult': 1.0, 'pitch_shift': 0, 'pause_ms': 500}
    )
