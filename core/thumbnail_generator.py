"""
AI 视频封面生成器 (Thumbnail Generator)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
- 基于 ffmpeg 生成风格化文字叠加封面图
- 四种布局模板：centered_title / split_left_right / bottom_bar / cinematic_letterbox
- 根据标题长度自动调整字号
- 颜色方案根据风格/情绪自动推导
- 支持渐变和纯色背景

使用示例：
    tg = ThumbnailGenerator()
    path = tg.generate(
        script={"title": "赛博朋克之夜"},
        style="cyberpunk",
        width=1280, height=720
    )
"""

import os
import json
import math
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger("quanquan.thumbnail_generator")


# ═══════════ 颜色方案库 ═══════════

@dataclass
class ColorScheme:
    """封面配色方案"""
    bg_start: str        # 背景渐变起始色 (hex)
    bg_end: str          # 背景渐变终止色 (hex)
    text_color: str      # 主文字颜色 (hex)
    accent_color: str    # 强调色（装饰条/边框）
    overlay_color: str   # 半透明覆盖层颜色


# 根据风格/情绪映射颜色方案
STYLE_COLOR_MAP: Dict[str, ColorScheme] = {
    # 赛博朋克 / 科技
    "cyberpunk": ColorScheme("#0a0020", "#1a0040", "#00ffcc", "#ff00ff", "black@0.4"),
    "tech": ColorScheme("#001a2e", "#003355", "#00d4ff", "#0088ff", "black@0.35"),
    "scifi": ColorScheme("#0d0221", "#1a0540", "#00e5ff", "#b300ff", "black@0.45"),
    # 自然 / 温暖
    "nature": ColorScheme("#1b3a1b", "#2d5a2d", "#ffffff", "#a8e6a3", "black@0.3"),
    "warm": ColorScheme("#3d1c00", "#5c2e0a", "#ffecd2", "#ff9900", "black@0.25"),
    "sunset": ColorScheme("#2d0a3d", "#5c1a6e", "#ffd700", "#ff6b35", "black@0.3"),
    # 暗黑 / 恐怖
    "dark": ColorScheme("#0a0a0a", "#1a1a1a", "#cccccc", "#ff3333", "black@0.5"),
    "horror": ColorScheme("#0d0000", "#1a0000", "#cc2222", "#660000", "black@0.55"),
    # 清新 / 可爱
    "fresh": ColorScheme("#e8f5e9", "#c8e6c9", "#1b5e20", "#4caf50", "white@0.2"),
    "cute": ColorScheme("#fce4ec", "#f8bbd0", "#880e4f", "#e91e63", "white@0.15"),
    # 商务 / 专业
    "business": ColorScheme("#0d1b2a", "#1b2d45", "#ffffff", "#1e88e5", "black@0.4"),
    "news": ColorScheme("#1a1a2e", "#16213e", "#ffffff", "#e94560", "black@0.45"),
    # 默认
    "auto": ColorScheme("#1a1a2e", "#2d2d44", "#ffffff", "#6c63ff", "black@0.4"),
    "default": ColorScheme("#1a1a2e", "#2d2d44", "#ffffff", "#6c63ff", "black@0.4"),
}

# 情绪到风格的映射（用于自动推导）
EMOTION_STYLE_MAP = {
    "激昂": "cyberpunk",
    "兴奋": "tech",
    "紧张": "horror",
    "温馨": "warm",
    "悲伤": "dark",
    "中立": "default",
    "欢快": "fresh",
    "严肃": "business",
}


class ThumbnailGenerator:
    """AI 封面生成器 — 使用 ffmpeg 创建带文字叠加的渐变背景封面

    覆盖了常见的视频封面需求，无需外部 AI 模型即可生成效果不错的封面图。
    支持多种布局模板和自动配色。
    """

    def __init__(self, font_path: Optional[str] = None, output_dir: str = "/data/quanquan/data/thumbnails"):
        """
        Args:
            font_path: 字体文件路径（用于中文渲染），默认查找系统字体
            output_dir: 输出目录
        """
        self._font_path = font_path or self._find_default_font()
        self._output_dir = output_dir
        os.makedirs(self._output_dir, exist_ok=True)
        logger.info(
            f"[ThumbnailGenerator] 初始化完成，输出目录={self._output_dir}，"
            f"字体={self._font_path}"
        )

    # ── 公共 API ──────────────────────────────────────────────

    def generate(
        self,
        script: dict,
        style: str = "auto",
        width: int = 1280,
        height: int = 720,
        layout: str = "centered_title",
    ) -> str:
        """生成封面缩略图

        Args:
            script: 脚本数据，至少包含 'title' 字段
            style: 视频风格（cyberpunk / nature / warm / dark / fresh / ... 或 auto）
            width: 封面宽度（默认 1280）
            height: 封面高度（默认 720）
            layout: 布局模板:
                - centered_title: 标题居中
                - split_left_right: 左文字右图标
                - bottom_bar: 底部标题栏
                - cinematic_letterbox: 电影上下黑边+居中标题

        Returns:
            生成的 PNG 文件绝对路径

        Example:
            path = tg.generate(
                script={"title": "10个必看的赛博朋克电影"},
                style="cyberpunk",
                layout="cinematic_letterbox"
            )
        """
        title = self._extract_title(script)
        color_scheme = self._resolve_color_scheme(style, script)

        # 推导输出路径
        safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in title)[:40]
        safe_title = safe_title.strip().replace(" ", "_")
        import time as _time
        filename = f"thumb_{safe_title}_{int(_time.time())}.png"
        output_path = os.path.join(self._output_dir, filename)

        # 生成
        layout_func = {
            "centered_title": self._draw_centered_title,
            "split_left_right": self._draw_split_left_right,
            "bottom_bar": self._draw_bottom_bar,
            "cinematic_letterbox": self._draw_cinematic_letterbox,
        }.get(layout, self._draw_centered_title)

        layout_func(output_path, title, color_scheme, width, height)

        logger.info(
            f"[ThumbnailGenerator] 封面生成完成: {output_path} "
            f"({width}x{height}, layout={layout}, style={style})"
        )
        return output_path

    # ── 布局模板 ──────────────────────────────────────────────

    def _draw_centered_title(
        self, output_path: str, title: str, cs: ColorScheme,
        width: int, height: int
    ):
        """centered_title: 标题垂直水平居中，带微妙阴影"""
        font_size = self._calculate_font_size(title, width, height, padding_ratio=0.6)
        shadow_offset = max(2, font_size // 20)

        # 构建 ffmpeg drawtext filter（允许 >= ffmpeg 4.x 语法）
        filter_chain = (
            # 1) 创建渐变背景
            f"color=c={cs.bg_start}:s={width}x{height}:d=0.1,"
            f"geq=r='lerp({_hex_to_r(cs.bg_start, 0)}, {_hex_to_r(cs.bg_end, 0)}, X/W)':"
            f"g='lerp({_hex_to_r(cs.bg_start, 1)}, {_hex_to_r(cs.bg_end, 1)}, X/W)':"
            f"b='lerp({_hex_to_r(cs.bg_start, 2)}, {_hex_to_r(cs.bg_end, 2)}, X/W)',"
            # 2) 覆盖层（半透明暗色）
            f"drawtext=text='':fontsize=1,"
            # 3) 阴影
            f"drawtext=text='{self._escape_ffmpeg_text(title)}':"
            f"fontfile='{self._font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor={cs.accent_color}@0.3:"
            f"x=(w-text_w)/2+{shadow_offset}:y=(h-text_h)/2+{shadow_offset},"
            # 4) 主文字
            f"drawtext=text='{self._escape_ffmpeg_text(title)}':"
            f"fontfile='{self._font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor={cs.text_color}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2,"
            f"format=rgba"
        )

        self._run_ffmpeg(filter_chain, output_path, width, height)

    def _draw_split_left_right(
        self, output_path: str, title: str, cs: ColorScheme,
        width: int, height: int
    ):
        """split_left_right: 左半部分文字，右侧装饰色块"""
        font_size = self._calculate_font_size(title, width // 2, height, padding_ratio=0.5)
        left_w = width * 2 // 3

        filter_chain = (
            f"color=c={cs.bg_start}:s={width}x{height}:d=0.1,"
            # 背景渐变
            f"geq=r='lerp({_hex_to_r(cs.bg_start, 0)}, {_hex_to_r(cs.bg_end, 0)}, X/W)':"
            f"g='lerp({_hex_to_r(cs.bg_start, 1)}, {_hex_to_r(cs.bg_end, 1)}, X/W)':"
            f"b='lerp({_hex_to_r(cs.bg_start, 2)}, {_hex_to_r(cs.bg_end, 2)}, X/W)',"
            # 右侧装饰条
            f"drawbox=x={left_w}:y=0:w={width-left_w}:h={height}:"
            f"color={cs.accent_color}@0.15:t=fill,"
            # 文字阴影
            f"drawtext=text='{self._escape_ffmpeg_text(title)}':"
            f"fontfile='{self._font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor={cs.accent_color}@0.25:"
            f"x=40+2:y=(h-text_h)/2+2,"
            # 主文字
            f"drawtext=text='{self._escape_ffmpeg_text(title)}':"
            f"fontfile='{self._font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor={cs.text_color}:"
            f"x=40:y=(h-text_h)/2,"
            f"format=rgba"
        )

        self._run_ffmpeg(filter_chain, output_path, width, height)

    def _draw_bottom_bar(
        self, output_path: str, title: str, cs: ColorScheme,
        width: int, height: int
    ):
        """bottom_bar: 底部半透明标题栏 + 背景全屏"""
        bar_height = height // 5
        font_size = self._calculate_font_size(
            title, width - 40, bar_height, padding_ratio=0.7
        )

        filter_chain = (
            f"color=c={cs.bg_start}:s={width}x{height}:d=0.1,"
            f"geq=r='lerp({_hex_to_r(cs.bg_start, 0)}, {_hex_to_r(cs.bg_end, 0)}, X/W)':"
            f"g='lerp({_hex_to_r(cs.bg_start, 1)}, {_hex_to_r(cs.bg_end, 1)}, X/W)':"
            f"b='lerp({_hex_to_r(cs.bg_start, 2)}, {_hex_to_r(cs.bg_end, 2)}, X/W)',"
            # 底部半透明栏
            f"drawbox=x=0:y={height-bar_height}:w={width}:h={bar_height}:"
            f"color={cs.bg_end}@0.75:t=fill,"
            # 装饰线
            f"drawbox=x=0:y={height-bar_height}:w={width}:h=4:"
            f"color={cs.accent_color}:t=fill,"
            # 文字
            f"drawtext=text='{self._escape_ffmpeg_text(title)}':"
            f"fontfile='{self._font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor={cs.text_color}:"
            f"x=20:y={height-bar_height}+(h-text_h)/2-text_h/4,"
            f"format=rgba"
        )

        self._run_ffmpeg(filter_chain, output_path, width, height)

    def _draw_cinematic_letterbox(
        self, output_path: str, title: str, cs: ColorScheme,
        width: int, height: int
    ):
        """cinematic_letterbox: 上下黑边 + 居中标题，电影感"""
        bar_height = height // 6
        content_h = height - 2 * bar_height
        font_size = self._calculate_font_size(
            title, width, content_h, padding_ratio=0.5
        )

        filter_chain = (
            f"color=c={cs.bg_start}:s={width}x{height}:d=0.1,"
            f"geq=r='lerp({_hex_to_r(cs.bg_start, 0)}, {_hex_to_r(cs.bg_end, 0)}, X/W)':"
            f"g='lerp({_hex_to_r(cs.bg_start, 1)}, {_hex_to_r(cs.bg_end, 1)}, X/W)':"
            f"b='lerp({_hex_to_r(cs.bg_start, 2)}, {_hex_to_r(cs.bg_end, 2)}, X/W)',"
            # 上部黑边
            f"drawbox=x=0:y=0:w={width}:h={bar_height}:color=black@0.85:t=fill,"
            # 下部黑边
            f"drawbox=x=0:y={height-bar_height}:w={width}:h={bar_height}:color=black@0.85:t=fill,"
            # 装饰细线
            f"drawbox=x=0:y={bar_height}:w={width}:h=2:color={cs.accent_color}@0.6:t=fill,"
            f"drawbox=x=0:y={height-bar_height-2}:w={width}:h=2:color={cs.accent_color}@0.6:t=fill,"
            # 文字阴影
            f"drawtext=text='{self._escape_ffmpeg_text(title)}':"
            f"fontfile='{self._font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor=black@0.3:"
            f"x=(w-text_w)/2+3:y=(h-text_h)/2+3,"
            # 主文字
            f"drawtext=text='{self._escape_ffmpeg_text(title)}':"
            f"fontfile='{self._font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor={cs.text_color}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2,"
            f"format=rgba"
        )

        self._run_ffmpeg(filter_chain, output_path, width, height)

    # ── 工具方法 ──────────────────────────────────────────────

    def _extract_title(self, script: dict) -> str:
        """从 script 中提取标题文本"""
        if not script:
            return "Untitled"
        title = (
            script.get("title")
            or script.get("text")
            or script.get("prompt")
            or script.get("topic")
            or "Untitled"
        )
        return str(title).strip()[:200]

    def _resolve_color_scheme(self, style: str, script: dict) -> ColorScheme:
        """根据风格和脚本内容推导颜色方案"""
        # 直接匹配
        if style.lower() in STYLE_COLOR_MAP:
            return STYLE_COLOR_MAP[style.lower()]

        # 通过情绪推导
        mood = (script or {}).get("mood", "").strip()
        if mood in EMOTION_STYLE_MAP:
            mapped = EMOTION_STYLE_MAP[mood]
            return STYLE_COLOR_MAP.get(mapped, STYLE_COLOR_MAP["default"])

        # 模糊匹配
        style_lower = style.lower()
        for key, scheme in STYLE_COLOR_MAP.items():
            if key in style_lower or style_lower in key:
                return scheme

        return STYLE_COLOR_MAP["default"]

    def _calculate_font_size(
        self, title: str, max_width: int, max_height: int,
        padding_ratio: float = 0.6
    ) -> int:
        """根据标题长度和可用空间自动计算合适的字号

        启发式算法：
        - 标题越长，字号越小
        - 可用宽度越小，字号越小
        - 确保标题大致适应 (max_width * padding_ratio)
        """
        char_count = len(title)
        available_w = max_width * padding_ratio

        # 粗略估计：每个中文字符约占 1.1 × font_size 的宽度
        if char_count == 0:
            return 48

        base_size = available_w / (char_count * 1.15)
        # 限制字号范围
        font_size = max(24, min(120, int(base_size)))
        # 高度约束
        max_by_height = int(max_height * 0.8)
        font_size = min(font_size, max_by_height)

        return font_size

    def _escape_ffmpeg_text(self, text: str) -> str:
        """转义 ffmpeg drawtext 中的特殊字符"""
        # 转义冒号、单引号、反斜杠、百分号
        text = text.replace("\\", "\\\\\\\\")
        text = text.replace(":", "\\\\:")
        text = text.replace("'", "\\\\'")
        text = text.replace("%", "\\\\%")
        return text

    def _find_default_font(self) -> str:
        """查找系统可用的中文字体"""
        candidates = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/PingFang.ttc",  # macOS
            "C:/Windows/Fonts/msyh.ttc",           # Windows
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        # 回退：让 ffmpeg 自己找
        logger.warning("[ThumbnailGenerator] 未找到中文字体，将使用 ffmpeg 默认字体")
        return "Sans"

    def _run_ffmpeg(
        self, filter_chain: str, output_path: str,
        width: int, height: int
    ):
        """执行 ffmpeg 渲染命令"""
        cmd = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", filter_chain,
            "-frames:v", "1",
            "-pix_fmt", "rgba",
            "-y",
            output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                stderr = result.stderr[-500:] if len(result.stderr) > 500 else result.stderr
                raise RuntimeError(
                    f"ffmpeg 渲染失败 (exit={result.returncode}): {stderr}"
                )
        except FileNotFoundError:
            # ffmpeg 未安装时创建占位图片
            logger.warning("[ThumbnailGenerator] ffmpeg 未安装，生成占位封面图")
            self._create_placeholder(output_path, width, height)

    def _create_placeholder(self, output_path: str, width: int, height: int):
        """当 ffmpeg 不可用时创建极简占位 PNG（纯色块）"""
        # 使用 Python 内置能力生成最简单的 PNG
        import struct
        import zlib

        def _make_png(w, h):
            # 生成简单的蓝色 PNG
            raw_data = b""
            for y in range(h):
                raw_data += b"\x00"  # filter byte
                for x in range(w):
                    # 蓝紫色渐变
                    r = int(30 + (x / w) * 40)
                    g = int(20 + (y / h) * 30)
                    b_val = int(60 + (x / w) * 100)
                    raw_data += struct.pack("BBB", r, g, b_val)

            compressed = zlib.compress(raw_data)

            png = b"\x89PNG\r\n\x1a\n"
            # IHDR
            ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
            png += struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
            # IDAT
            idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
            png += struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
            # IEND
            iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
            png += struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
            return png

        with open(output_path, "wb") as f:
            f.write(_make_png(width, height))

        logger.info(f"[ThumbnailGenerator] 占位封面已生成: {output_path}")


# ═══════════ 工具函数 ═══════════

def _hex_to_r(hex_color: str, channel: int) -> int:
    """从 hex 颜色中提取指定通道的 R/G/B 值 (0/1/2)"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) < 6:
        return 0
    return int(hex_color[channel * 2 : channel * 2 + 2], 16)


# ── 便捷工厂 ──────────────────────────────────────────────────

thumbnail_generator = ThumbnailGenerator()
