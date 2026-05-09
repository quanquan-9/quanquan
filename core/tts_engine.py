"""
TTS Engine — edge-tts 免费中文配音
支持多音色 · 语速/音调调整 · 音频文件输出
"""
import asyncio, os, logging, tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger("quanquan.tts")

# 可用中文音色
VOICES = {
    "default": "zh-CN-XiaoxiaoNeural",     # 晓晓 — 温柔女声
    "male": "zh-CN-YunxiNeural",           # 云希 — 男声
    "girl": "zh-CN-XiaoyiNeural",          # 晓伊 — 活泼女声
    "story": "zh-CN-YunjianNeural",        # 云健 — 叙事男声
    "news": "zh-CN-YunyangNeural",         # 云扬 — 新闻男声
    "cantonese": "zh-HK-HiuMaanNeural",    # 粤语女声
    "taiwan": "zh-TW-HsiaoChenNeural",     # 台湾女声
}


class TTSEngine:
    """Microsoft Edge TTS 引擎"""

    def __init__(self, output_dir: str = "/data/quanquan/output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def synthesize(self, text: str, output_path: str = None,
                         voice: str = "default", rate: str = "+0%",
                         pitch: str = "+0Hz") -> Optional[str]:
        """将文本合成为 MP3 音频"""
        voice_name = VOICES.get(voice, VOICES["default"])

        if not output_path:
            output_path = str(self.output_dir / f"tts_{hash(text) & 0xFFFFFFF:08x}.mp3")

        try:
            import edge_tts
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_name,
                rate=rate,
                pitch=pitch,
            )
            await communicate.save(output_path)
            logger.info(f"TTS synthesized: {len(text)} chars → {output_path}")
            return output_path
        except Exception as e:
            logger.warning(f"TTS failed: {e}")
            return None

    async def synthesize_scenes(self, script: dict, project_id: str,
                                voice: str = "default") -> Optional[str]:
        """将脚本所有场景合成为一个音频文件"""
        scenes = script.get("scenes", []) or script.get("segments", [])
        if not scenes:
            return None

        # 拼接所有旁白文本
        full_text = "。".join(
            s.get("narration", "") or s.get("text", "")
            for s in scenes if s.get("narration") or s.get("text")
        )
        if not full_text:
            return None

        output = str(self.output_dir / f"{project_id}_voice.mp3")
        return await self.synthesize(full_text, output, voice=voice)


tts = TTSEngine()
