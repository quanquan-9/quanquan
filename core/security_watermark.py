"""
安全水印与DRM (Security & DRM)

功能：
- 可见/不可见水印
- 数字指纹
- 视频加密
- 播放授权
- 防盗链
"""

import asyncio
import hashlib
import json
import os
import secrets
import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class WatermarkMode(Enum):
    VISIBLE = "visible"           # 可见水印
    INVISIBLE = "invisible"       # 不可见水印（频域嵌入）
    QR = "qr"                     # 二维码水印
    MOVING = "moving"             # 移动水印


@dataclass
class WatermarkInfo:
    """水印信息"""
    user_id: str
    project_id: str
    timestamp: str
    serial: str = ""  # 唯一序列号
    custom_data: Dict[str, str] = field(default_factory=dict)


class SecurityWatermark:
    """安全水印引擎"""

    WATERMARK_POSITIONS = [
        "top_left", "top_right", "bottom_left", "bottom_right",
        "center", "moving_diagonal",
    ]

    async def embed_visible(
        self,
        input_path: str,
        output_path: str,
        info: WatermarkInfo,
        position: str = "bottom_right",
        opacity: float = 0.15,
    ) -> str:
        """嵌入可见水印"""
        text = f"ID:{info.user_id[:8]} | {info.timestamp[:10]}"
        pos_map = {
            "top_left": "x=20:y=20",
            "top_right": "x=w-tw-20:y=20",
            "bottom_left": "x=20:y=h-th-20",
            "bottom_right": "x=w-tw-20:y=h-th-20",
            "center": "x=(w-tw)/2:y=(h-th)/2",
        }
        pos = pos_map.get(position, pos_map["bottom_right"])
        escaped = text.replace(":", "\\:").replace("'", "\\'")

        vf = (
            f"drawtext=text='{escaped}':"
            f"fontsize=20:fontcolor=white@{opacity}:"
            f"{pos}:shadowcolor=black@0.2:shadowx=1:shadowy=1"
        )

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    async def embed_moving(
        self,
        input_path: str,
        output_path: str,
        info: WatermarkInfo,
        opacity: float = 0.1,
    ) -> str:
        """嵌入移动水印（更难去除）"""
        text = f"{info.user_id[:8]}"
        escaped = text.replace(":", "\\:")
        # 水印从左上角移动到右下角
        vf = (
            f"drawtext=text='{escaped}':"
            f"fontsize=18:fontcolor=white@{opacity}:"
            f"x='mod(t*30,w+tw)-tw':y='mod(t*20,h+th)-th':"
            f"shadowcolor=black@0.2:shadowx=1:shadowy=1"
        )

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    async def embed_qr(
        self,
        input_path: str,
        output_path: str,
        info: WatermarkInfo,
    ) -> str:
        """嵌入二维码水印"""
        # 生成包含用户信息的 JSON → QR 码图片 → ffmpeg overlay
        qr_data = json.dumps({
            "uid": info.user_id,
            "pid": info.project_id,
            "ts": info.timestamp,
            "serial": info.serial or secrets.token_hex(8),
        })

        # 生成 QR → 叠加
        qr_path = os.path.join(os.path.dirname(output_path), "qr_watermark.png")
        try:
            import qrcode
            img = qrcode.make(qr_data)
            img.save(qr_path)
        except ImportError:
            logger.warning("qrcode not installed, using text fallback")
            return await self.embed_visible(input_path, output_path, info)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path, "-i", qr_path,
            "-filter_complex",
            "[1:v]scale=80:80[qr];[0:v][qr]overlay=W-w-20:H-h-20",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()

        if os.path.exists(qr_path):
            os.remove(qr_path)
        return output_path


class VideoEncryptor:
    """视频加密器"""

    async def encrypt_hls(
        self,
        input_path: str,
        output_dir: str,
        encryption_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """HLS 加密输出"""
        if encryption_key is None:
            encryption_key = secrets.token_hex(16)

        os.makedirs(output_dir, exist_ok=True)

        # 创建 keyinfo 文件
        key_path = os.path.join(output_dir, "enc.key")
        keyinfo_path = os.path.join(output_dir, "enc.keyinfo")

        with open(key_path, "w") as f:
            f.write(encryption_key)

        key_uri = f"enc.key"
        iv = secrets.token_hex(16)
        with open(keyinfo_path, "w") as f:
            f.write(f"{key_uri}\n{key_path}\n{iv}\n")

        # HLS 加密输出
        playlist_path = os.path.join(output_dir, "playlist.m3u8")
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-hls_time", "6",
            "-hls_playlist_type", "vod",
            "-hls_key_info_file", keyinfo_path,
            "-hls_segment_filename", os.path.join(output_dir, "seg_%03d.ts"),
            playlist_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()

        return {
            "playlist": playlist_path,
            "encryption_key": encryption_key,
            "iv": iv,
            "format": "HLS+AES-128",
        }

    async def generate_signed_url(
        self,
        base_url: str,
        user_id: str,
        expires_in_sec: int = 3600,
        secret: str = "",
    ) -> str:
        """生成签名播放 URL"""
        if not secret:
            secret = secrets.token_hex(16)

        expires = int(time.time()) + expires_in_sec
        signature = hashlib.sha256(
            f"{base_url}:{user_id}:{expires}:{secret}".encode()
        ).hexdigest()[:16]

        return f"{base_url}?uid={user_id}&exp={expires}&sig={signature}"


class DigitalFingerprinter:
    """数字指纹 — 为每个用户嵌入唯一标识"""

    async def embed_fingerprint(
        self,
        input_path: str,
        output_path: str,
        user_id: str,
    ) -> str:
        """嵌入数字指纹（频域水印）"""
        # 使用 ffmpeg 的简单方法：在特定时间点插入微小亮度变化
        uid_hash = hashlib.md5(user_id.encode()).hexdigest()
        bits = bin(int(uid_hash[:8], 16))[2:].zfill(32)

        # 构建 enable 表达式：在特定帧 +/- 微小亮度
        enable_exprs = []
        for i, bit in enumerate(bits[:8]):  # 只用前8位简化
            if bit == "1":
                t_start = 1.0 + i * 0.5
                t_end = t_start + 0.1
                enable_exprs.append(f"between(t,{t_start},{t_end})")

        if enable_exprs:
            enable_str = "+".join(enable_exprs)
            vf = f"eq=brightness='if({enable_str},0.02,0)':contrast=1.0"
        else:
            vf = "null"

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    async def extract_fingerprint(self, video_path: str) -> Optional[str]:
        """提取数字指纹"""
        # 简化版：采样帧亮度
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", "signalstats",
            "-vframes", "10",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        return None  # 完整实现需更复杂的频域分析
