"""
Voice Cloner — 声音克隆与风格迁移引擎
支持：声音注册、风格分析、多声音混合、TTS参数优化
"""
import os, json, logging, subprocess, tempfile
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("quanquan.voice_cloner")

@dataclass
class VoiceProfile:
    """声音档案"""
    name: str
    voice_id: str
    description: str = ""
    gender: str = "neutral"       # male/female/neutral
    age_range: str = "adult"       # child/young/adult/senior
    style: str = "neutral"         # 激昂/温暖/严肃/活泼/磁性
    sample_path: str = ""
    pitch_base: float = 0.0        # 基准音调偏移 (半音)
    speed_base: float = 1.0        # 基准语速倍率
    energy: float = 0.5            # 力度 0-1
    breathiness: float = 0.0       # 气声
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "voice_id": self.voice_id,
            "description": self.description, "gender": self.gender,
            "age_range": self.age_range, "style": self.style,
            "pitch_base": self.pitch_base, "speed_base": self.speed_base,
            "energy": self.energy, "breathiness": self.breathiness,
        }


BUILTIN_VOICES: Dict[str, VoiceProfile] = {
    "male_clear": VoiceProfile(name="清晰男声", voice_id="male_clear",
        description="标准男声播报，适合科技解说", gender="male", style="科技",
        pitch_base=0, speed_base=1.0, energy=0.6),
    "female_warm": VoiceProfile(name="温暖女声", voice_id="female_warm",
        description="温暖柔和女声，适合Vlog旁白", gender="female", style="温暖",
        pitch_base=5, speed_base=0.95, energy=0.4),
    "male_deep": VoiceProfile(name="深沉男声", voice_id="male_deep",
        description="低沉磁性男声，适合电影预告", gender="male", style="严肃",
        pitch_base=-3, speed_base=0.9, energy=0.7),
    "female_gentle": VoiceProfile(name="温柔女声", voice_id="female_gentle",
        description="温柔细腻女声，适合情感内容", gender="female", style="温暖",
        pitch_base=3, speed_base=0.88, energy=0.3),
    "male_energetic": VoiceProfile(name="活力男声", voice_id="male_energetic",
        description="年轻活力男声，适合短视频快剪", gender="male", style="活泼",
        pitch_base=2, speed_base=1.15, energy=0.8),
    "female_calm": VoiceProfile(name="知性女声", voice_id="female_calm",
        description="冷静知性女声，适合教育培训", gender="female", style="严肃",
        pitch_base=0, speed_base=0.92, energy=0.35),
    "child_happy": VoiceProfile(name="童声", voice_id="child_happy",
        description="活泼童声，适合儿童内容", gender="neutral", age_range="child",
        style="活泼", pitch_base=12, speed_base=1.1, energy=0.7),
    "elder_wisdom": VoiceProfile(name="长者之声", voice_id="elder_wisdom",
        description="沉稳长者声音，适合纪录片旁白", gender="male", age_range="senior",
        style="严肃", pitch_base=-5, speed_base=0.85, energy=0.45),
}


class VoiceCloner:
    """声音克隆引擎 — 管理声音档案、分析、混合"""

    def __init__(self, data_dir: str = "/data/quanquan/data/voices"):
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._custom_voices: Dict[str, VoiceProfile] = {}
        self._load_custom()

    def _load_custom(self):
        """加载自定义声音档案"""
        path = os.path.join(self._data_dir, "custom_voices.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                for v in data:
                    profile = VoiceProfile(**v)
                    self._custom_voices[profile.voice_id] = profile
                logger.info(f"加载 {len(self._custom_voices)} 个自定义声音")
            except Exception as e:
                logger.warning(f"加载自定义声音失败: {e}")

    def _save_custom(self):
        """保存自定义声音档案"""
        path = os.path.join(self._data_dir, "custom_voices.json")
        with open(path, "w") as f:
            json.dump([v.to_dict() for v in self._custom_voices.values()], f, ensure_ascii=False, indent=2)

    # ── 公共 API ──

    def list_voices(self) -> List[dict]:
        """列出所有可用声音（内置 + 自定义）"""
        all_voices = list(BUILTIN_VOICES.values()) + list(self._custom_voices.values())
        return [v.to_dict() for v in all_voices]

    def get_voice(self, voice_id: str) -> Optional[dict]:
        """获取指定声音档案"""
        if voice_id in BUILTIN_VOICES:
            return BUILTIN_VOICES[voice_id].to_dict()
        if voice_id in self._custom_voices:
            return self._custom_voices[voice_id].to_dict()
        return None

    def register_voice(self, name: str, voice_id: str, **kwargs) -> dict:
        """注册自定义声音

        Args:
            name: 声音名称
            voice_id: 唯一ID
            **kwargs: VoiceProfile 的其他字段
        """
        if voice_id in BUILTIN_VOICES:
            raise ValueError(f"声音ID '{voice_id}' 与内置声音冲突")
        profile = VoiceProfile(name=name, voice_id=voice_id, **kwargs)
        self._custom_voices[voice_id] = profile
        self._save_custom()
        logger.info(f"注册声音: {name} ({voice_id})")
        return profile.to_dict()

    def analyze_voice(self, audio_path: str) -> dict:
        """分析音频文件的声音特征

        使用 ffprobe 提取基本音频属性，估算声音参数。
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        result = {
            "path": audio_path,
            "duration_sec": 0.0,
            "sample_rate": 0,
            "channels": 0,
            "bitrate": "",
            "estimated_pitch": 0.0,
            "estimated_speed": 1.0,
            "estimated_energy": 0.5,
        }

        try:
            # 使用 ffprobe 获取音频元数据
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", audio_path
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0:
                info = json.loads(proc.stdout)
                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        result["duration_sec"] = float(stream.get("duration", 0))
                        result["sample_rate"] = int(stream.get("sample_rate", 0))
                        result["channels"] = int(stream.get("channels", 0))
                        break
                fmt = info.get("format", {})
                result["bitrate"] = fmt.get("bit_rate", "")

            # 估算能量（使用 volumedetect）
            cmd2 = ["ffmpeg", "-i", audio_path, "-af", "volumedetect", "-f", "null", "-"]
            proc2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
            for line in proc2.stderr.split("\n"):
                if "mean_volume" in line:
                    try:
                        db = float(line.split(":")[-1].strip().replace("dB", ""))
                        result["estimated_energy"] = min(1.0, max(0.1, (db + 35) / 25))
                    except: pass
                if "max_volume" in line:
                    try:
                        db = float(line.split(":")[-1].strip().replace("dB", ""))
                        result["estimated_energy"] = max(result["estimated_energy"], min(1.0, (db + 30) / 25))
                    except: pass

            logger.info(f"分析声音: {os.path.basename(audio_path)} — 时长{result['duration_sec']:.1f}s")
        except Exception as e:
            logger.warning(f"声音分析异常: {e}")

        return result

    def clone_voice(self, source_audio: str, target_voice_id: str, output_dir: str = None) -> dict:
        """克隆声音风格

        将源音频的风格特征迁移到目标声音上，生成参数配置。
        实际语音合成需配合 TTS 引擎使用。

        Returns:
            dict: 包含混合参数的配置，供 TTS 引擎使用
        """
        source_profile = self.analyze_voice(source_audio)
        target = self.get_voice(target_voice_id)
        if not target:
            raise ValueError(f"目标声音不存在: {target_voice_id}")

        # 计算混合参数
        clone_params = {
            "source": source_profile,
            "target": target,
            "mixed": {
                "pitch_shift": target.get("pitch_base", 0),
                "speed": target.get("speed_base", 1.0) * source_profile.get("estimated_speed", 1.0),
                "energy": (target.get("energy", 0.5) + source_profile.get("estimated_energy", 0.5)) / 2,
                "breathiness": target.get("breathiness", 0),
            },
            "instructions": (
                f"使用 {target['name']} 的声音，"
                f"语速 {target.get('speed_base', 1.0):.2f}x，"
                f"力度 {target.get('energy', 0.5):.0%}"
            ),
        }

        return clone_params

    def mix_voices(self, voice_id_a: str, voice_id_b: str, mix_ratio: float = 0.5) -> dict:
        """混合两个声音特征

        Args:
            voice_id_a: 声音A ID
            voice_id_b: 声音B ID
            mix_ratio: 混合比例 (0=纯A, 1=纯B, 0.5=均等)

        Returns:
            dict: 混合后的声音参数
        """
        a = self.get_voice(voice_id_a)
        b = self.get_voice(voice_id_b)
        if not a or not b:
            raise ValueError("声音不存在")

        r = mix_ratio
        inv_r = 1 - r

        mixed = {
            "name": f"{a['name']}×{b['name']}",
            "voice_id": f"mix_{voice_id_a}_{voice_id_b}_{int(r*100)}",
            "description": f"{a['name']} ({inv_r:.0%}) + {b['name']} ({r:.0%}) 混合",
            "pitch_base": a.get("pitch_base", 0) * inv_r + b.get("pitch_base", 0) * r,
            "speed_base": a.get("speed_base", 1.0) * inv_r + b.get("speed_base", 1.0) * r,
            "energy": a.get("energy", 0.5) * inv_r + b.get("energy", 0.5) * r,
            "breathiness": a.get("breathiness", 0) * inv_r + b.get("breathiness", 0) * r,
        }

        logger.info(f"混合声音: {mixed['name']}")
        return mixed

    def recommend_voice(self, style: str, gender: str = "any", age: str = "any") -> List[dict]:
        """根据风格/性别/年龄推荐声音"""
        all_voices = list(BUILTIN_VOICES.values()) + list(self._custom_voices.values())
        scored = []
        for v in all_voices:
            score = 0
            if v.style == style: score += 3
            elif style in v.style or v.style in style: score += 1
            if gender != "any" and v.gender == gender: score += 2
            if age != "any" and v.age_range == age: score += 2
            if score > 0:
                scored.append((score, v.to_dict()))
        scored.sort(key=lambda x: -x[0])
        return [v for _, v in scored[:5]]

    def delete_voice(self, voice_id: str) -> bool:
        """删除自定义声音"""
        if voice_id in self._custom_voices:
            del self._custom_voices[voice_id]
            self._save_custom()
            return True
        return False


# 模块级实例
voice_cloner = VoiceCloner()
