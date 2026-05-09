"""
音乐库引擎 (Music Library)

功能：
- 音乐素材索引与搜索
- BPM/节拍预分析缓存
- 情绪标签匹配
- 版权过滤
"""

import asyncio
import json
import os
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MusicTrack:
    """音乐曲目"""
    track_id: str
    path: str
    title: str = ""
    artist: str = ""
    duration_sec: float = 0
    bpm: float = 120
    key: str = ""
    genre: str = ""
    mood_tags: List[str] = field(default_factory=list)
    energy: float = 0.5           # 0~1, 能量等级
    valence: float = 0.5          # 0~1, 情绪正负
    license_type: str = "unknown"
    beat_points: List[float] = field(default_factory=list)  # 重拍时间点
    downbeats: List[float] = field(default_factory=list)     # 小节第一拍
    waveform_hash: str = ""
    usage_count: int = 0
    created_at: str = ""

    @property
    def bpm_category(self) -> str:
        if self.bpm < 60: return "very_slow"
        if self.bpm < 90: return "slow"
        if self.bpm < 120: return "medium"
        if self.bpm < 150: return "fast"
        return "very_fast"


class MusicLibrary:
    """音乐库管理"""

    EMOTION_GENRE_MAP = {
        '激昂': ['epic', 'cinematic', 'rock', 'electronic'],
        '紧张': ['suspense', 'thriller', 'industrial', 'dark_ambient'],
        '舒缓': ['ambient', 'chill', 'lofi', 'classical'],
        '悲伤': ['piano', 'sad', 'melancholic', 'post_rock'],
        '温馨': ['acoustic', 'folk', 'jazz', 'indie'],
        '中立': ['corporate', 'pop', 'electronic', 'ambient'],
    }

    EMOTION_BPM_MAP = {
        '激昂': (120, 160),
        '紧张': (100, 140),
        '舒缓': (60, 90),
        '悲伤': (60, 85),
        '温馨': (75, 110),
        '中立': (90, 130),
    }

    def __init__(self, base_dir: str = "music_library/"):
        self.base_dir = base_dir
        self.tracks: Dict[str, MusicTrack] = {}
        self._loaded = False

    async def load(self, index_file: str = "music_index.json"):
        """从索引加载"""
        path = os.path.join(self.base_dir, index_file)
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
            for t in data.get('tracks', []):
                track = MusicTrack(**{k: v for k, v in t.items()
                                       if k in MusicTrack.__dataclass_fields__})
                self.tracks[track.track_id] = track
            self._loaded = True
            logger.info(f"Music library loaded: {len(self.tracks)} tracks")

    async def save(self, index_file: str = "music_index.json"):
        path = os.path.join(self.base_dir, index_file)
        data = {
            'version': 1,
            'updated_at': datetime.utcnow().isoformat(),
            'total': len(self.tracks),
            'tracks': [t.__dict__ for t in self.tracks.values()],
        }
        os.makedirs(self.base_dir, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    async def index_directory(self, directory: str) -> int:
        """索引目录中所有音频文件"""
        audio_exts = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
        count = 0

        for root, dirs, files in os.walk(directory):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in audio_exts:
                    continue

                full_path = os.path.join(root, fname)
                track_id = hashlib.md5(full_path.encode()).hexdigest()[:12]

                # 从文件名猜测信息
                stem = os.path.splitext(fname)[0]
                parts = stem.split(' - ') if ' - ' in stem else [stem]

                # 尝试用 ffprobe 获取时长
                duration = 0
                try:
                    import subprocess
                    cmd = ['ffprobe', '-v', 'quiet', '-show_entries',
                           'format=duration', '-of', 'csv=p=0', full_path]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    duration = float(result.stdout.strip())
                except Exception:
                    pass

                track = MusicTrack(
                    track_id=track_id,
                    path=full_path,
                    title=parts[-1].strip() if len(parts) > 1 else stem,
                    artist=parts[0].strip() if len(parts) > 1 else "",
                    duration_sec=duration,
                    created_at=datetime.utcnow().isoformat(),
                )
                self.tracks[track_id] = track
                count += 1

        await self.save()
        logger.info(f"Music library indexed: {count} tracks from {directory}")
        return count

    async def analyze_track(self, track_id: str) -> Optional[MusicTrack]:
        """分析单个音轨（BPM/节拍/情绪）"""
        track = self.tracks.get(track_id)
        if not track or track.bpm != 120:  # 如果已分析过
            return track

        try:
            # 使用 aubio / librosa 分析（简化：用 ffmpeg 近似）
            import subprocess
            # 尝试用 ffmpeg 的 ebur128 获取响度信息作为能量的近似
            cmd = ['ffprobe', '-v', 'quiet', '-f', 'lavfi',
                   '-i', f'amovie={track.path},ebur128=video=0:meter=18',
                   '-show_entries', 'frame_tags=lavfi.r128.I',
                   '-of', 'csv=p=0']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            # 极简 BPM 估算: 用 ffmpeg 节奏检测
            # 实际上 BPM 分析需要专业的音频分析库，这里留接口
        except Exception as e:
            logger.warning(f"Track analysis failed for {track_id}: {e}")

        return track

    async def search(
        self,
        mood: Optional[str] = None,
        genre: Optional[str] = None,
        bpm_range: Optional[Tuple[float, float]] = None,
        duration_range: Optional[Tuple[float, float]] = None,
        energy_min: Optional[float] = None,
        license_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[MusicTrack]:
        """多条件音乐搜索"""
        results = list(self.tracks.values())

        if mood:
            # 按情绪匹配流派
            mood_genres = self.EMOTION_GENRE_MAP.get(mood, [])
            results = [t for t in results
                       if t.genre in mood_genres
                       or any(m in (t.mood_tags or []) for m in [mood])]

        if genre:
            results = [t for t in results if t.genre == genre]

        if bpm_range:
            lo, hi = bpm_range
            results = [t for t in results if lo <= t.bpm <= hi]

        if duration_range:
            lo, hi = duration_range
            results = [t for t in results if lo <= t.duration_sec <= hi]

        if energy_min is not None:
            results = [t for t in results if t.energy >= energy_min]

        if license_type:
            results = [t for t in results if t.license_type == license_type]

        # 按使用次数 + 匹配度排序
        results.sort(key=lambda t: t.usage_count, reverse=True)

        return results[:limit]

    async def get_mood_tracks(self, mood: str, target_duration: float,
                               bpm_range: Optional[Tuple[float, float]] = None,
                               limit: int = 10) -> List[MusicTrack]:
        """快捷：按情绪获取音乐"""
        if bpm_range is None:
            bpm_range = self.EMOTION_BPM_MAP.get(mood, (80, 140))

        return await self.search(
            mood=mood,
            bpm_range=bpm_range,
            duration_range=(target_duration * 0.5, target_duration * 2.0),
            limit=limit,
        )

    def get_by_id(self, track_id: str) -> Optional[MusicTrack]:
        return self.tracks.get(track_id)

    def record_usage(self, track_id: str):
        track = self.tracks.get(track_id)
        if track:
            track.usage_count += 1
