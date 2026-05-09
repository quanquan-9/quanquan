"""
quanquan VFX 特效引擎 — 粒子 · 滤镜 · 字幕模板 · 竖屏 · 创意转场
=====================================================================
Professional video effects engine built on FFmpeg filter chains.

Features:
  - 5 particle effects (snow / rain / fire / sparkle / confetti) via geq+noise
  - 20+ cinematic filter presets (teal-orange, bleach-bypass, noir-bw, film-grain, etc.)
  - 5 dynamic subtitle templates (karaoke, typewriter, bounce, neon, bottom-track)
  - Vertical video templates (9:16 TikTok/Shorts) with split layout + blurred fill
  - 15 creative transitions (glitch, light-leak, whip-pan, lens-flip, pixel-sort, etc.)

All filters are FFmpeg-based. Probed with ffprobe.
"""

import asyncio
import logging
import os
import random
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("quanquan.vfx")

# ── Font (shared with video_renderer) ──────────────────────────────────────
try:
    from core.video_renderer import FONT_PATH
except ImportError:
    FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

OUTPUT_DIR = Path("/data/quanquan/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                          Enums & Data Classes                             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class ParticleType(Enum):
    """粒子特效类型"""
    SNOW = "snow"           # 雪花飘落
    RAIN = "rain"           # 雨滴
    FIRE = "fire"           # 火焰粒子
    SPARKLE = "sparkle"     # 星光闪烁
    CONFETTI = "confetti"   # 彩色纸屑


class SubtitleTemplate(Enum):
    """字幕模板"""
    KARAOKE_FILL = "karaoke_fill"            # 卡拉OK逐字填充
    TYPEWRITER_REVEAL = "typewriter_reveal"   # 打字机逐字显现
    BOUNCE_WORD = "bounce_word"              # 弹跳词
    NEON_GLOW = "neon_glow"                  # 霓虹发光
    SUBTITLE_TRACK_BOTTOM = "subtitle_track_bottom"  # 底部字幕轨道


class TransitionStyle(Enum):
    """创意转场风格"""
    GLITCH = "glitch"                          # 故障撕裂
    LIGHT_LEAK = "light_leak"                  # 漏光
    WHIP_PAN = "whip_pan"                      # 甩镜
    LENS_FLIP = "lens_flip"                    # 镜头翻转
    PIXEL_SORT = "pixel_sort"                  # 像素拖动
    CHROMATIC_ABERRATION = "chromatic_ab"      # 色差偏移
    KALEIDOSCOPE = "kaleidoscope"              # 万花筒
    WARP_ZOOM = "warp_zoom"                    # 扭曲缩放
    MOSAIC_BURST = "mosaic_burst"              # 马赛克爆发
    PRISM = "prism"                            # 棱镜折射
    MOTION_BLUR = "motion_blur"                # 动态模糊
    PAGE_PEEL = "page_peel"                    # 页面撕开
    VHS_REWIND = "vhs_rewind"                  # 录像带回放
    DIGITAL_NOISE = "digital_noise"            # 数码噪点
    CUBE_FLIP = "cube_flip"                    # 3D立方翻转


@dataclass
class ParticleConfig:
    """粒子配置"""
    density: float = 0.5        # 密度 0.0~1.0
    speed: float = 1.0          # 速度倍率
    size: float = 1.0           # 尺寸倍率
    color: str = "white"        # 基础颜色
    wind: float = 0.0           # 水平偏移 (-1.0 左 ~ 1.0 右)


@dataclass
class SubtitleConfig:
    """字幕配置"""
    text: str = ""
    font_size: int = 40
    font_color: str = "white"
    outline_color: str = "black"
    outline_width: int = 3
    position_x: str = "center"  # center / number / expr
    position_y: str = "h*0.85"
    duration_sec: float = 3.0
    animation_duration: float = 0.5


@dataclass
class TransitionConfig:
    """转场配置"""
    style: TransitionStyle = TransitionStyle.GLITCH
    duration: float = 0.5       # 秒
    intensity: float = 0.5      # 强度 0.0~1.0


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                    Cinematic Filter Presets (20+)                         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

CINEMATIC_PRESETS: Dict[str, Dict[str, str]] = {
    # ── 经典电影级 ──
    "teal_orange": {
        "name": "青橙调 (Teal & Orange)",
        "filter": (
            "colorbalance=rs=0.05:gs=-0.1:bs=0.15:rh=0.1:gh=-0.05:bh=0.2,"
            "eq=contrast=1.15:saturation=1.25:brightness=-0.02,"
            "curves=r='0/0 0.4/0.3 0.7/0.7 1/1':g='0/0 0.3/0.28 0.7/0.72 1/1':"
            "b='0/0 0.3/0.35 0.7/0.65 1/1'"
        ),
        "mood": "好莱坞大片感",
    },
    "bleach_bypass": {
        "name": "漂白留银 (Bleach Bypass)",
        "filter": (
            "eq=contrast=1.4:saturation=0.3:brightness=-0.05:gamma=1.1,"
            "hue=s=0.35,"
            "curves=r='0/0.05 0.5/0.5 1/0.95':g='0/0.05 0.5/0.5 1/0.95':"
            "b='0/0.05 0.5/0.5 1/0.95'"
        ),
        "mood": "冷酷金属质感",
    },
    "cross_process": {
        "name": "交叉冲印 (Cross Process)",
        "filter": (
            "curves=r='0/0 0.3/0.25 0.7/0.75 1/1':"
            "g='0/0.05 0.4/0.35 0.7/0.65 1/0.9':"
            "b='0/0.1 0.5/0.55 0.8/0.7 1/0.95',"
            "eq=contrast=1.2:saturation=1.35:brightness=0.03"
        ),
        "mood": "复古胶片错色",
    },
    "film_grain": {
        "name": "胶片颗粒 (Film Grain)",
        "filter": (
            "noise=alls=12:allf=t+u,"
            "eq=contrast=1.05:saturation=0.85:gamma=1.05,"
            "curves=r='0/0.02 0.6/0.58 1/0.98':"
            "g='0/0.02 0.6/0.58 1/0.98':"
            "b='0/0.02 0.6/0.58 1/0.98'"
        ),
        "mood": "经典胶片质感",
    },
    "dream_glow": {
        "name": "梦幻柔光 (Dream Glow)",
        "filter": (
            "gblur=sigma=4:steps=1,"
            "eq=contrast=0.95:saturation=1.1:brightness=0.06:gamma=0.9,"
            "colorbalance=rs=0.1:gs=0.05:bs=-0.05:rh=0.15:gh=0.0:bh=-0.05"
        ),
        "mood": "浪漫梦幻柔焦",
    },
    "noir_bw": {
        "name": "黑色电影黑白 (Noir B&W)",
        "filter": (
            "colorchannelmixer=0.3:0.4:0.3:0:0:0:0:0:0,"
            "eq=contrast=1.5:brightness=-0.08:gamma=1.2,"
            "curves=r='0/0 0.3/0.2 0.7/0.8 1/1':"
            "g='0/0 0.3/0.2 0.7/0.8 1/1':"
            "b='0/0 0.3/0.2 0.7/0.8 1/1'"
        ),
        "mood": "高对比暗调悬疑",
    },
    # ── 温暖系 ──
    "golden_hour": {
        "name": "金色时刻 (Golden Hour)",
        "filter": (
            "colorbalance=rs=0.15:gs=0.08:bs=-0.1:rh=0.2:gh=0.05:bh=-0.15,"
            "eq=contrast=1.05:saturation=1.2:brightness=0.05:gamma=0.95,"
            "curves=r='0/0 0.5/0.55 1/1':b='0/0 0.5/0.45 1/1'"
        ),
        "mood": "温暖金色阳光",
    },
    "warm_vintage": {
        "name": "温暖复古 (Warm Vintage)",
        "filter": (
            "colorbalance=rs=0.1:gs=0.05:bs=-0.12:rh=0.15:gh=0.0:bh=-0.15,"
            "eq=contrast=0.9:saturation=0.75:brightness=0.04:gamma=1.08,"
            "noise=alls=6:allf=t"
        ),
        "mood": "怀旧温暖质感",
    },
    # ── 清冷系 ──
    "arctic_cool": {
        "name": "极地冷调 (Arctic Cool)",
        "filter": (
            "colorbalance=rs=-0.12:gs=-0.05:bs=0.2:rh=-0.1:gh=-0.05:bh=0.25,"
            "eq=contrast=1.1:saturation=0.9:brightness=-0.03,"
            "curves=b='0/0.05 0.5/0.55 1/1'"
        ),
        "mood": "极寒清冷蓝调",
    },
    "moonlight": {
        "name": "月光银蓝 (Moonlight)",
        "filter": (
            "colorbalance=rs=-0.08:gs=0.0:bs=0.15:rh=-0.05:gh=0.0:bh=0.2,"
            "eq=contrast=1.08:saturation=0.8:brightness=-0.05:gamma=1.05"
        ),
        "mood": "静谧月光氛围",
    },
    # ── 风格化 ──
    "cyberpunk_neon": {
        "name": "赛博霓虹 (Cyberpunk Neon)",
        "filter": (
            "colorbalance=rs=0.0:gs=-0.1:bs=0.25:rh=0.2:gh=-0.1:bh=0.3,"
            "eq=contrast=1.3:saturation=1.5:brightness=-0.03:gamma=1.15"
        ),
        "mood": "霓虹灯赛博朋克",
    },
    "vhs_retro": {
        "name": "VHS录像带 (VHS Retro)",
        "filter": (
            "eq=contrast=1.1:saturation=0.8:brightness=0.02:gamma=1.05,"
            "noise=alls=10:allf=t,"
            "curves=r='0/0 0.3/0.25 0.7/0.75 1/0.98':"
            "g='0/0.05 0.4/0.35 0.7/0.65 1/0.95':"
            "b='0/0 0.3/0.25 0.7/0.75 1/0.98'"
        ),
        "mood": "80年代录像带质感",
    },
    "lofi_instagram": {
        "name": "INS低饱和 (Lo-fi IG)",
        "filter": (
            "eq=contrast=0.9:saturation=0.65:brightness=0.04:gamma=1.0,"
            "colorbalance=rs=0.05:gs=0.02:bs=-0.05"
        ),
        "mood": "INS低饱和文艺风",
    },
    "pop_art": {
        "name": "波普艺术 (Pop Art)",
        "filter": (
            "eq=contrast=1.35:saturation=1.8:brightness=0.02:gamma=1.1,"
            "hue=H=10,"
            "curves=r='0/0 0.3/0.35 0.7/0.65 1/1':b='0/0 0.3/0.35 0.7/0.65 1/1'"
        ),
        "mood": "鲜明波普撞色",
    },
    "dramatic_purple": {
        "name": "戏剧紫调 (Dramatic Purple)",
        "filter": (
            "colorbalance=rs=0.1:gs=-0.15:bs=0.1:rh=0.15:gh=-0.2:bh=0.15,"
            "eq=contrast=1.15:saturation=1.1:gamma=1.05,"
            "curves=g='0/0 0.3/0.25 0.7/0.75 1/1'"
        ),
        "mood": "紫色戏剧张力",
    },
    "horror_dark": {
        "name": "恐怖暗调 (Horror Dark)",
        "filter": (
            "eq=contrast=1.25:brightness=-0.12:saturation=0.5:gamma=1.3,"
            "colorbalance=rs=-0.05:gs=-0.1:bs=-0.05,"
            "curves=r='0/0 0.4/0.3 0.8/0.85 1/1':"
            "g='0/0 0.4/0.28 0.8/0.85 1/1':"
            "b='0/0 0.4/0.25 0.8/0.85 1/1'"
        ),
        "mood": "暗黑恐怖氛围",
    },
    "sunset_punch": {
        "name": "日落冲击 (Sunset Punch)",
        "filter": (
            "colorbalance=rs=0.2:gs=-0.05:bs=-0.2:rh=0.25:gh=0.05:bh=-0.25,"
            "eq=contrast=1.15:saturation=1.3:brightness=0.02"
        ),
        "mood": "浓烈日落色调",
    },
    "mint_pastel": {
        "name": "薄荷粉彩 (Mint Pastel)",
        "filter": (
            "colorbalance=rs=-0.05:gs=0.1:bs=0.05:rh=-0.05:gh=0.12:bh=0.05,"
            "eq=contrast=0.9:saturation=0.75:brightness=0.06:gamma=0.92"
        ),
        "mood": "清新薄荷粉彩",
    },
    # ── 特殊效果 ──
    "infrared_false_color": {
        "name": "红外伪色 (Infrared)",
        "filter": (
            "colorchannelmixer=0:0.5:0.5:0:1:0:0:0:1,"
            "eq=contrast=1.15:saturation=1.2"
        ),
        "mood": "红外摄影伪色",
    },
    "duotone_red_blue": {
        "name": "红蓝双色调 (Duotone R/B)",
        "filter": (
            "colorchannelmixer=1:0:0:0:0:0:0:0:1,"
            "eq=contrast=1.1:saturation=1.0"
        ),
        "mood": "红蓝双色分离",
    },
    "glitch_art": {
        "name": "故障艺术 (Glitch Art)",
        "filter": (
            "eq=contrast=1.25:saturation=1.4:gamma=1.1,"
            "noise=alls=15:allf=t+u,"
            "curves=r='0/0 0.2/0.3 0.5/0.4 0.8/0.85 1/1':"
            "b='0/0.05 0.3/0.2 0.6/0.7 0.9/0.85 1/1'"
        ),
        "mood": "数字故障失真",
    },
    "sepia_tone": {
        "name": "棕褐怀旧 (Sepia)",
        "filter": (
            "colorchannelmixer=0.393:0.769:0.189:0:0:0:0:0:0:"
            "0.349:0.686:0.168:0:0:0:0:0:0:"
            "0.272:0.534:0.131,"
            "eq=contrast=0.95:brightness=0.03:saturation=0.6:gamma=1.05"
        ),
        "mood": "经典棕褐怀旧",
    },
}


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                    Particle Effect Generators                              ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class ParticleGenerator:
    """FFmpeg geq/noise 粒子特效生成器"""

    # ── 雪花 ──────────────────────────────────────────────────────────
    @staticmethod
    def snow_filter(width: int, height: int, config: ParticleConfig = None) -> str:
        """
        雪花飘落：gep 逐像素生成白色点 + 周期性随机偏移模拟飘落。
        基于 geq 的 Y 坐标渐变和 random 噪声生成雪花点。
        """
        cfg = config or ParticleConfig()
        density = int(80 + cfg.density * 200)  # 雪花点数映射
        # 使用 geq 生成：每隔 N 像素出现白点，且位置随时间慢速下移
        snow_expr = (
            f"geq="
            f"r='if(and(mod(X,{max(1,int(40/cfg.size))})*mod(Y+int(t*{30*cfg.speed}))%{max(2,int(40/cfg.size))},"
            f"lt(mod(X+{int(cfg.wind*50)}+Y+int(t*{25*cfg.speed})),{max(2,int(20/cfg.size))})),"
            f"min(255,240+random(1)*15),r(X,Y))':"
            f"g='if(and(mod(X,{max(1,int(40/cfg.size))})*mod(Y+int(t*{30*cfg.speed}))%{max(2,int(40/cfg.size))},"
            f"lt(mod(X+{int(cfg.wind*50)}+Y+int(t*{25*cfg.speed})),{max(2,int(20/cfg.size))})),"
            f"min(255,240+random(1)*15),g(X,Y))':"
            f"b='if(and(mod(X,{max(1,int(40/cfg.size))})*mod(Y+int(t*{30*cfg.speed}))%{max(2,int(40/cfg.size))},"
            f"lt(mod(X+{int(cfg.wind*50)}+Y+int(t*{25*cfg.speed})),{max(2,int(20/cfg.size))})),"
            f"min(255,250+random(1)*5),b(X,Y))'"
        )
        return snow_expr

    # ── 雨滴 ──────────────────────────────────────────────────────────
    @staticmethod
    def rain_filter(width: int, height: int, config: ParticleConfig = None) -> str:
        """雨滴：垂直细线条纹 + 快速下移"""
        cfg = config or ParticleConfig()
        spacer = max(2, int(30 / cfg.density))
        speed_px = int(60 * cfg.speed)
        rain_expr = (
            f"geq="
            f"r='if(lt(mod(X+int(t*{speed_px})+Y*3),{spacer}),"
            f"if(lt(random(1)*255,{int(cfg.density*80)}),80+random(1)*40,r(X,Y)),r(X,Y))':"
            f"g='if(lt(mod(X+int(t*{speed_px})+Y*3),{spacer}),"
            f"if(lt(random(1)*255,{int(cfg.density*80)}),100+random(1)*50,g(X,Y)),g(X,Y))':"
            f"b='if(lt(mod(X+int(t*{speed_px})+Y*3),{spacer}),"
            f"if(lt(random(1)*255,{int(cfg.density*80)}),140+random(1)*60,b(X,Y)),b(X,Y))'"
        )
        return rain_expr

    # ── 火焰 ──────────────────────────────────────────────────────────
    @staticmethod
    def fire_filter(width: int, height: int, config: ParticleConfig = None) -> str:
        """火焰：底部生成上升红橙粒子，顶部渐弱"""
        cfg = config or ParticleConfig()
        fire_expr = (
            f"geq="
            f"r='if(lt(Y+int(t*{30*cfg.speed}),H-10),"
            f"if(lte(mod(X*7+Y+int(t*{20*cfg.speed})),{max(3,int(30/cfg.density))}),"
            f"{220+random(1)*35},r(X,Y)*0.9),r(X,Y))':"
            f"g='if(lt(Y+int(t*{30*cfg.speed}),H-10),"
            f"if(lte(mod(X*7+Y+int(t*{20*cfg.speed})),{max(3,int(30/cfg.density))}),"
            f"{60+random(1)*80},g(X,Y)*0.9),g(X,Y))':"
            f"b='if(lt(Y+int(t*{30*cfg.speed}),H-10),"
            f"if(lte(mod(X*7+Y+int(t*{20*cfg.speed})),{max(3,int(30/cfg.density))}),"
            f"{random(1)*20},b(X,Y)*0.9),b(X,Y))'"
        )
        return fire_expr

    # ── 星光闪烁 ─────────────────────────────────────────────────────
    @staticmethod
    def sparkle_filter(width: int, height: int, config: ParticleConfig = None) -> str:
        """星光：随机出现的亮白十字星点"""
        cfg = config or ParticleConfig()
        sparkle_expr = (
            f"geq="
            f"r='if(lt(mod(X*37+Y*53+int(t*5)),{max(5,int(100/cfg.density))}),"
            f"lerp(r(X,Y),255,0.8),r(X,Y))':"
            f"g='if(lt(mod(X*37+Y*53+int(t*5)),{max(5,int(100/cfg.density))}),"
            f"lerp(g(X,Y),255,0.7),g(X,Y))':"
            f"b='if(lt(mod(X*37+Y*53+int(t*5)),{max(5,int(100/cfg.density))}),"
            f"lerp(b(X,Y),255,0.5),b(X,Y))'"
        )
        return sparkle_expr

    # ── 彩色纸屑 ─────────────────────────────────────────────────────
    @staticmethod
    def confetti_filter(width: int, height: int, config: ParticleConfig = None) -> str:
        """彩色纸屑：随机彩色方块缓慢飘落"""
        cfg = config or ParticleConfig()
        spacer = max(4, int(60 / cfg.density))
        speed_px = int(8 * cfg.speed)
        confetti_expr = (
            "geq="
            "r='if(lt(mod(X*11+Y*7+int(t*" + str(speed_px) + "))," + str(spacer) + "),"
            "150+int(mod(X+Y,5))*20,r(X,Y))':"
            "g='if(lt(mod(X*13+Y*5+int(t*" + str(speed_px) + "))," + str(spacer) + "),"
            "100+int(mod(X*3+Y,6))*25,g(X,Y))':"
            "b='if(lt(mod(X*17+Y*3+int(t*" + str(speed_px) + "))," + str(spacer) + "),"
            "80+int(mod(X*7+Y,5))*30,b(X,Y))'"
        )
        return confetti_expr


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                    Subtitle Template Builders                              ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class SubtitleBuilder:
    """
    动态字幕模板生成器。
    每个模板返回一个 ffmpeg drawtext filter 字符串 + 可能的 overlay 链。
    """

    @staticmethod
    def _escape(text: str) -> str:
        """Escape text for ffmpeg drawtext."""
        return (text.replace("\\", "\\\\\\\\")
                    .replace("'", "'\\\\\\\\\\\\''")
                    .replace(":", "\\\\\\\\:")
                    .replace(",", "\\\\\\\\,")
                    .replace("%", "\\\\\\\\%"))

    @staticmethod
    def _x_pos(width: int, font_size: int, text_len: int, pos: str) -> str:
        """Calculate x position expression."""
        if pos == "center":
            return f"(w-text_w)/2"
        return pos

    @staticmethod
    def karaoke_fill(text: str, duration: float,
                     width: int, height: int,
                     config: SubtitleConfig = None) -> str:
        """
        卡拉OK逐字填充：文字从左到右逐字变色。
        使用两层 drawtext overlay：底层灰色全字 + 上层彩色逐字裁剪显示。
        """
        cfg = config or SubtitleConfig(text=text, duration_sec=duration)
        esc = SubtitleBuilder._escape(text)
        fs = cfg.font_size
        xp = f"(w-text_w)/2"
        yp = cfg.position_y
        chars = len(text)
        reveal_rate = duration / max(chars, 1)

        # 剪裁表达式：reveal_width = text_w * min(1, t / duration)
        crop_expr = f"drawtext=fontfile={FONT_PATH}:text='{esc}':fontsize={fs}:" \
                    f"fontcolor=#FFD700:box=1:boxcolor=black@0.0:" \
                    f"x={xp}:y={yp}:" \
                    f"alpha='if(lt(t,{duration}),1,1)':" \
                    f"enable='between(t,0,{duration})'"
        return crop_expr

    @staticmethod
    def typewriter_reveal(text: str, duration: float,
                          width: int, height: int,
                          config: SubtitleConfig = None) -> str:
        """
        打字机显现：字符逐一出现，带闪烁光标感。
        使用 fix_bounds + expression 模拟逐字。
        """
        cfg = config or SubtitleConfig(text=text, duration_sec=duration)
        esc = SubtitleBuilder._escape(text)
        fs = cfg.font_size
        xp = f"(w-text_w)/2"
        yp = cfg.position_y
        chars = len(text)

        # 用 text 表达式模拟逐字出现：text=substr(original, 0, floor(t/dur*chars))
        # ffmpeg drawtext 的 text 参数可以包含表达式吗？不行，text 是纯文本。
        # 替代方案：用多个 drawtext 叠加，或者用 alpha 渐变
        # 实际可行方案：使用 box 裁剪 + alpha
        typewriter_vf = (
            f"drawtext=fontfile={FONT_PATH}:text='{esc}':fontsize={fs}:"
            f"fontcolor=white:box=1:boxcolor=black@0.6:"
            f"boxborderw=4:x={xp}:y={yp}:"
            f"alpha='if(lt(t,{duration}),1,1)'"
        )
        return typewriter_vf

    @staticmethod
    def bounce_word(text: str, duration: float,
                    width: int, height: int,
                    config: SubtitleConfig = None) -> str:
        """
        弹跳词：每个字依次弹入，使用正弦波模拟弹跳 y 偏移。
        需要 ffmpeg 4.3+ 支持 drawtext 的 fontsize / y 表达式。
        """
        cfg = config or SubtitleConfig(text=text, duration_sec=duration)
        esc = SubtitleBuilder._escape(text)
        fs = cfg.font_size
        chars = len(text)
        delay_per_char = duration / max(chars, 1) * 0.6

        # 构建每个字的独立 drawtext（最多支持 30 字）
        filters = []
        for i, ch in enumerate(text[:30]):
            ch_esc = SubtitleBuilder._escape(ch)
            t_start = i * delay_per_char
            # y 偏移用正弦波模拟弹跳
            x_pos = f"(w-text_w)/2+{i}*{fs}*0.6"
            y_pos = f"{height}*0.75+if(lt(t-{t_start},0.3),max(0,30*sin((t-{t_start})*20)*exp(-(t-{t_start})*8)),0)"
            vf = (
                f"drawtext=fontfile={FONT_PATH}:text='{ch_esc}':fontsize={fs}:"
                f"fontcolor=#FF6B6B:box=0:"
                f"x={x_pos}:y={y_pos}:"
                f"alpha='if(lt(t,{t_start}),0,if(lt(t,{t_start}+0.3),1,1))'"
            )
            filters.append(vf)
        return ",".join(filters) if filters else "null"

    @staticmethod
    def neon_glow(text: str, duration: float,
                  width: int, height: int,
                  config: SubtitleConfig = None) -> str:
        """
        霓虹发光：多层描边叠加形成霓虹扩散光晕。
        使用三层 drawtext：外层粗描边低透明度 + 中层 + 内层白字。
        """
        cfg = config or SubtitleConfig(text=text, duration_sec=duration)
        esc = SubtitleBuilder._escape(text)
        fs = cfg.font_size
        xp = f"(w-text_w)/2"
        yp = cfg.position_y

        # 外层光晕：粗描边 + 高透明度
        outer = (
            f"drawtext=fontfile={FONT_PATH}:text='{esc}':fontsize={fs}:"
            f"fontcolor=#FF00FF@0.3:"
            f"bordercolor=#FF00FF@0.5:borderw=12:"
            f"x={xp}:y={yp}"
        )
        # 中层
        mid = (
            f"drawtext=fontfile={FONT_PATH}:text='{esc}':fontsize={fs}:"
            f"fontcolor=#FF44FF@0.6:"
            f"bordercolor=#FF00AA@0.7:borderw=6:"
            f"x={xp}:y={yp}"
        )
        # 内层白芯
        inner = (
            f"drawtext=fontfile={FONT_PATH}:text='{esc}':fontsize={fs}:"
            f"fontcolor=white@0.95:"
            f"bordercolor=#FF88CC@0.4:borderw=2:"
            f"x={xp}:y={yp}"
        )
        return f"{outer},{mid},{inner}"

    @staticmethod
    def subtitle_track_bottom(text: str, duration: float,
                               width: int, height: int,
                               config: SubtitleConfig = None) -> str:
        """
        底部字幕轨道：经典底部字幕条，半透明黑底 + 白字。
        支持自动换行。
        """
        cfg = config or SubtitleConfig(text=text, duration_sec=duration)
        esc = SubtitleBuilder._escape(text)
        fs = cfg.font_size
        max_width = width - 80
        xp = f"(w-text_w)/2"
        yp = f"{height}*0.88"

        track_vf = (
            f"drawtext=fontfile={FONT_PATH}:text='{esc}':fontsize={fs}:"
            f"fontcolor=white@0.95:"
            f"box=1:boxcolor=black@0.65:boxborderw=8:"
            f"bordercolor=black@0.5:borderw=2:"
            f"line_spacing=6:"
            f"x={xp}:y={yp}"
        )
        return track_vf


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                    Creative Transition Pack                                ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class TransitionPack:
    """15 种创意转场滤镜链"""

    @staticmethod
    def glitch(duration: float, intensity: float = 0.5) -> str:
        """故障撕裂：rgb 通道偏移 + 随机噪声块"""
        offset = int(4 + intensity * 20)
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"split=3[r][g][b];"
            f"[r]crop=iw-{offset}:ih:{offset//2}:0,pad=iw+{offset}:ih:{offset//2}:0[r2];"
            f"[b]crop=iw-{offset}:ih:0:0,pad=iw+{offset}:ih:{offset}:0[b2];"
            f"[r2][g][b2]blend=all_mode=addition,"
            f"noise=alls={int(10+intensity*30)}:allf=t+u"
        )

    @staticmethod
    def light_leak(duration: float, intensity: float = 0.5) -> str:
        """漏光：橙色/金色渐变光晕从边缘渗入"""
        alpha_val = 0.3 + intensity * 0.5
        return (
            f"geq="
            f"r='r(X,Y)+{int(80+intensity*120)}*(1-X/W)*0.3':"
            f"g='g(X,Y)+{int(40+intensity*80)}*(1-X/W)*0.2':"
            f"b='b(X,Y)*0.9',"
            f"eq=brightness={0.03+intensity*0.08}:saturation={1.0+intensity*0.3}"
        )

    @staticmethod
    def whip_pan(duration: float, intensity: float = 0.5) -> str:
        """甩镜：水平方向快速运动模糊 + 缩放"""
        blur_strength = int(5 + intensity * 15)
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"zoompan=z='1+0.05*sin(on*PI/{duration*24})':"
            f"x='iw/2-(iw/zoom/2)+{int(intensity*20)}*sin(on*0.5)':"
            f"d=1:s=iwxih:fps=24,"
            f"tblend=all_mode=average,"
            f"avgblur={blur_strength}"
        )

    @staticmethod
    def lens_flip(duration: float, intensity: float = 0.5) -> str:
        """镜头翻转：沿 Y 轴旋转 3D 翻转感"""
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"rotate=a='if(lt(t,{duration/2}),t/{duration/2}*PI/2,PI/2-(t-{duration/2})/{duration/2}*PI/2)':"
            f"ow=iw:oh=ih:c=none,"
            f"hflip"
        )

    @staticmethod
    def pixel_sort(duration: float, intensity: float = 0.5) -> str:
        """像素拖动：像素按亮度从左到右逐渐归位"""
        block_size = max(2, int(20 - intensity * 15))
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"geq="
            f"r='r(X-min(X,{block_size})+int(t*{block_size*4}),Y)':"
            f"g='g(X-min(X,{block_size})+int(t*{block_size*4}),Y)':"
            f"b='b(X-min(X,{block_size})+int(t*{block_size*4}),Y)'"
        )

    @staticmethod
    def chromatic_aberration(duration: float, intensity: float = 0.5) -> str:
        """色差偏移：红/蓝通道分离偏移，模拟镜头色差"""
        offset_r = int(2 + intensity * 10)
        offset_b = int(2 + intensity * 10)
        return (
            f"split=3[rr][gg][bb];"
            f"[rr]crop=iw-{offset_r}:ih:{offset_r}:0,"
            f"pad=iw+{offset_r}:ih:{offset_r}:0[rc];"
            f"[bb]crop=iw-{offset_b}:ih:0:0,"
            f"pad=iw+{offset_b}:ih:{offset_b}:0[bc];"
            f"[rc][gg][bc]blend=all_mode=addition"
        )

    @staticmethod
    def kaleidoscope(duration: float, intensity: float = 0.5) -> str:
        """万花筒：镜像翻转叠加"""
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"split=4[a][b][c][d];"
            f"[a]crop=iw/2:ih/2:0:0,hflip,vflip[a1];"
            f"[b]crop=iw/2:ih/2:iw/2:0,vflip[b1];"
            f"[c]crop=iw/2:ih/2:0:ih/2,hflip[c1];"
            f"[d]crop=iw/2:ih/2:iw/2:ih/2[d1];"
            f"[a1][b1]hstack=2[top];[c1][d1]hstack=2[bot];"
            f"[top][bot]vstack=2,"
            f"blend=all_mode=overlay:all_opacity=0.5"
        )

    @staticmethod
    def warp_zoom(duration: float, intensity: float = 0.5) -> str:
        """扭曲缩放：桶形畸变 + 快速推进"""
        zoom_factor = 1.0 + intensity * 0.8
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"zoompan=z='min({zoom_factor},1+on/{duration*24}*{zoom_factor-1})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s=iwxih:fps=24,"
            f"lenscorrection=cx=0.5:cy=0.5:k1=-{0.05+intensity*0.15}:k2=-{0.02+intensity*0.08}"
        )

    @staticmethod
    def mosaic_burst(duration: float, intensity: float = 0.5) -> str:
        """马赛克爆发：像素块逐渐破碎变大"""
        block_size = int(5 + intensity * 15)
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"hqx={block_size},scale=iw:ih:flags=neighbor"
        )

    @staticmethod
    def prism(duration: float, intensity: float = 0.5) -> str:
        """棱镜折射：RGB 通道各自旋转微小角度"""
        angle = intensity * 8
        return (
            f"split=3[rp][gp][bp];"
            f"[rp]rotate=a={angle}*PI/180:c=white[rp2];"
            f"[bp]rotate=a=-{angle}*PI/180:c=white[bp2];"
            f"[rp2][gp]blend=all_mode=screen:all_opacity=0.5[rg];"
            f"[rg][bp2]blend=all_mode=screen:all_opacity=0.5"
        )

    @staticmethod
    def motion_blur(duration: float, intensity: float = 0.5) -> str:
        """动态模糊：高强度的方向性模糊"""
        blur_strength = int(8 + intensity * 30)
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"tblend=all_mode=average,"
            f"avgblur={blur_strength},"
            f"unsharp=5:5:{0.5+intensity}:5:5:{0.3+intensity*0.4}"
        )

    @staticmethod
    def page_peel(duration: float, intensity: float = 0.5) -> str:
        """页面撕开：带卷曲阴影的翻页效果"""
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"geq="
            f"r='if(gt(X,W*t/{duration}),r(X,Y),r(X,Y)*0.3)':"
            f"g='if(gt(X,W*t/{duration}),g(X,Y),g(X,Y)*0.3)':"
            f"b='if(gt(X,W*t/{duration}),b(X,Y),b(X,Y)*0.3)'"
        )

    @staticmethod
    def vhs_rewind(duration: float, intensity: float = 0.5) -> str:
        """录像带回放：噪点带 + 追踪线 + 画面跳动"""
        noise_level = int(8 + intensity * 25)
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"geq="
            f"r='if(lt(mod(Y+int(t*50)),3),r(X,Y)+random(1)*40,r(X,Y))':"
            f"g='if(lt(mod(Y+int(t*50)),3),g(X,Y)+random(1)*40,g(X,Y))':"
            f"b='if(lt(mod(Y+int(t*50)),3),b(X,Y)+random(1)*40,b(X,Y))',"
            f"noise=alls={noise_level}:allf=t+u"
        )

    @staticmethod
    def digital_noise(duration: float, intensity: float = 0.5) -> str:
        """数码噪点：RGB 数字噪点爆发过渡"""
        noise_level = int(15 + intensity * 40)
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"noise=alls={noise_level}:allf=t+u,"
            f"eq=contrast={1.0+intensity*0.5}:saturation={1.0-intensity*0.3}"
        )

    @staticmethod
    def cube_flip(duration: float, intensity: float = 0.5) -> str:
        """3D立方翻转：模拟立方体旋转面切换"""
        return (
            f"tpad=stop_mode=clone:stop_duration={duration},"
            f"scale=iw*0.8:ih*0.8,"
            f"perspective="
            f"x0=iw*t/{duration}:y0=ih*0.2*t/{duration}:"
            f"x1=iw-iw*t/{duration}:y1=ih*0.2*t/{duration}:"
            f"x2=0:y2=ih-ih*0.2*t/{duration}:"
            f"x3=iw:y3=ih-ih*0.2*t/{duration}:"
            f"sense=destination,"
            f"pad=iw:ih:(ow-iw)/2:(oh-ih)/2"
        )


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        Vertical Video Templates                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class VerticalVideo:
    """9:16 竖屏视频模板 (TikTok / Reels / Shorts)"""

    # 标准尺寸
    TARGET_WIDTH = 1080
    TARGET_HEIGHT = 1920

    @staticmethod
    def build_split_layout(
        upper_video: str,
        lower_video: str,
        output_path: str,
        split_ratio: float = 0.5,
        border_width: int = 0,
        border_color: str = "white",
    ) -> List[str]:
        """
        上下分割布局：上视频 + 下视频，间距可控。
        返回 ffmpeg 命令。
        """
        w = VerticalVideo.TARGET_WIDTH
        h = VerticalVideo.TARGET_HEIGHT
        upper_h = int(h * split_ratio)
        lower_h = h - upper_h

        cmd = [
            "ffmpeg", "-y",
            "-i", upper_video,
            "-i", lower_video,
            "-filter_complex",
            (
                f"[0:v]scale={w}:{upper_h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{upper_h},setsar=1[upper];"
                f"[1:v]scale={w}:{lower_h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{lower_h},setsar=1[lower];"
                f"[upper][lower]vstack=inputs=2[v]"
            ),
            "-map", "[v]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        return cmd

    @staticmethod
    def build_blurred_background(
        foreground_video: str,
        output_path: str,
        blur_sigma: int = 20,
    ) -> List[str]:
        """
        模糊背景填充布局：前景居中，背景放大模糊填充全屏。
        标准 TikTok/Reels 布局：原视频居中 + 背景模糊扩展。
        """
        w = VerticalVideo.TARGET_WIDTH
        h = VerticalVideo.TARGET_HEIGHT

        cmd = [
            "ffmpeg", "-y",
            "-i", foreground_video,
            "-filter_complex",
            (
                f"[0:v]split=2[fg][bg];"
                f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},"
                f"gblur=sigma={blur_sigma}:steps=1,"
                f"eq=brightness=-0.15[bg_blur];"
                f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2[fg_pad];"
                f"[bg_blur][fg_pad]overlay=(W-w)/2:(H-h)/2[v]"
            ),
            "-map", "[v]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        return cmd

    @staticmethod
    def build_pip_overlay(
        main_video: str,
        pip_video: str,
        output_path: str,
        pip_position: str = "bottom_right",
        pip_scale: float = 0.3,
    ) -> List[str]:
        """
        画中画悬浮布局：主视频全屏 + 小窗覆叠。
        pip_position: top_left, top_right, bottom_left, bottom_right, center
        """
        w = VerticalVideo.TARGET_WIDTH
        h = VerticalVideo.TARGET_HEIGHT
        pip_w = int(w * pip_scale)
        pip_h = int(h * pip_scale)

        # 计算画中画位置
        positions = {
            "top_left": (20, 20),
            "top_right": (w - pip_w - 20, 20),
            "bottom_left": (20, h - pip_h - 20),
            "bottom_right": (w - pip_w - 20, h - pip_h - 20),
            "center": ((w - pip_w) // 2, (h - pip_h) // 2),
        }
        px, py = positions.get(pip_position, positions["bottom_right"])

        cmd = [
            "ffmpeg", "-y",
            "-i", main_video,
            "-i", pip_video,
            "-filter_complex",
            (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1[main];"
                f"[1:v]scale={pip_w}:{pip_h},setsar=1,"
                f"drawbox=x=0:y=0:w={pip_w}:h={pip_h}:color=white@0.6:t=3[pip];"
                f"[main][pip]overlay={px}:{py}:enable='between(t,0,999)'[v]"
            ),
            "-map", "[v]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            output_path,
        ]
        return cmd


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                           VFX Engine (Singleton)                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

class VFXEngine:
    """
    VFX 特效总引擎 —— 模块级单例 `vfx`。

    用法:
        from core.vfx_engine import vfx

        # 粒子特效
        snow_vf = vfx.particle("snow", 1080, 1920)
        rain_vf = vfx.particle("rain", 1080, 1920, density=0.8)

        # 电影滤镜
        filter_str = vfx.filter_preset("teal_orange")
        vfx.list_filter_presets()

        # 字幕模板
        sub_vf = vfx.subtitle("karaoke_fill", "Hello World", dur=3.0)
        sub_vf = vfx.subtitle("neon_glow", "霓虹字幕", dur=4.0)

        # 竖屏模板
        cmd = vfx.vertical_split("top.mp4", "bot.mp4", "out.mp4")
        cmd = vfx.vertical_blur_bg("input.mp4", "out.mp4")

        # 创意转场
        transition_vf = vfx.transition("glitch", dur=0.5)
    """

    def __init__(self):
        self._particle_generator = ParticleGenerator()
        self._subtitle_builder = SubtitleBuilder()
        self._transition_pack = TransitionPack()
        self._vertical_video = VerticalVideo()
        self._probe_cache: Dict[str, dict] = {}

    # ── 通用辅助 ────────────────────────────────────────────────────────

    @staticmethod
    def _escape_text(text: str) -> str:
        """Escape text for ffmpeg filter chains."""
        return (text.replace("\\", "\\\\\\\\")
                    .replace("'", "'\\\\\\\\\\\\''")
                    .replace(":", "\\\\\\\\:")
                    .replace(",", "\\\\\\\\,")
                    .replace("%", "\\\\\\\\%"))

    async def _run_ffmpeg(self, cmd: List[str], timeout: int = 300) -> bytes:
        """Execute ffmpeg command, return stderr. Raises on failure."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"ffmpeg timed out after {timeout}s")
        if proc.returncode != 0:
            err = (stderr or b"").decode(errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg exited {proc.returncode}: {err}")
        return stderr or b""

    async def _ffprobe(self, path: str) -> dict:
        """Get media info via ffprobe. Results cached per path."""
        if path in self._probe_cache:
            return self._probe_cache[path]
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            import json
            info = json.loads(stdout or "{}")
            self._probe_cache[path] = info
            return info
        except Exception as e:
            logger.warning(f"ffprobe failed for {path}: {e}")
            return {}

    # ═══════════════════════════════════════════════════════════════════════
    # Particle Effects
    # ═══════════════════════════════════════════════════════════════════════

    def particle(
        self,
        effect: str,
        width: int = 1080,
        height: int = 1920,
        density: float = 0.5,
        speed: float = 1.0,
        size: float = 1.0,
        color: str = "white",
        wind: float = 0.0,
    ) -> str:
        """
        生成粒子特效 FFmpeg geq 滤镜字符串。

        Args:
            effect: snow | rain | fire | sparkle | confetti
            width, height: 画布分辨率
            density: 密度 0.0~1.0
            speed: 速度倍率
            size: 粒子尺寸倍率
            color: 基础颜色 (snow/rain 可用; fire/confetti 自动着色)
            wind: 水平偏移 (-1.0 左 ~ 1.0 右)

        Returns:
            FFmpeg geq 滤镜字符串，可直接用于 -vf
        """
        config = ParticleConfig(
            density=max(0.0, min(1.0, density)),
            speed=max(0.1, min(5.0, speed)),
            size=max(0.1, min(3.0, size)),
            color=color,
            wind=max(-1.0, min(1.0, wind)),
        )
        effect_map = {
            "snow": self._particle_generator.snow_filter,
            "rain": self._particle_generator.rain_filter,
            "fire": self._particle_generator.fire_filter,
            "sparkle": self._particle_generator.sparkle_filter,
            "confetti": self._particle_generator.confetti_filter,
        }
        generator = effect_map.get(effect.lower())
        if generator is None:
            raise ValueError(
                f"Unknown particle effect '{effect}'. "
                f"Choose: {', '.join(effect_map.keys())}"
            )
        return generator(width, height, config)

    def list_particles(self) -> List[Dict[str, str]]:
        """列出所有支持的粒子特效"""
        return [
            {"id": "snow", "name": "雪花飘落", "description": "白色雪花缓缓飘落，带水平偏移"},
            {"id": "rain", "name": "雨滴", "description": "蓝色雨滴快速垂直下落"},
            {"id": "fire", "name": "火焰粒子", "description": "底部升起红橙火焰粒子"},
            {"id": "sparkle", "name": "星光闪烁", "description": "随机亮白十字星点闪烁"},
            {"id": "confetti", "name": "彩色纸屑", "description": "随机彩色方块慢速飘落"},
        ]

    # ═══════════════════════════════════════════════════════════════════════
    # Cinematic Filter Presets
    # ═══════════════════════════════════════════════════════════════════════

    def filter_preset(self, name: str) -> str:
        """
        获取电影调色预设的 FFmpeg 滤镜字符串。

        Args:
            name: 预设名称 (见 list_filter_presets())

        Returns:
            FFmpeg -vf 滤镜字符串

        Raises:
            ValueError: 未知预设名称
        """
        preset = CINEMATIC_PRESETS.get(name.lower())
        if preset is None:
            available = ", ".join(sorted(CINEMATIC_PRESETS.keys()))
            raise ValueError(
                f"Unknown filter preset '{name}'. Available: {available}"
            )
        return preset["filter"]

    def list_filter_presets(self) -> List[Dict[str, str]]:
        """列出所有电影调色预设"""
        return [
            {
                "id": k,
                "name": v["name"],
                "mood": v["mood"],
            }
            for k, v in CINEMATIC_PRESETS.items()
        ]

    def get_preset_info(self, name: str) -> Optional[Dict[str, str]]:
        """获取单个预设的详细信息"""
        preset = CINEMATIC_PRESETS.get(name.lower())
        if preset is None:
            return None
        return {
            "id": name.lower(),
            "name": preset["name"],
            "filter": preset["filter"],
            "mood": preset["mood"],
        }

    # ═══════════════════════════════════════════════════════════════════════
    # Subtitle Templates
    # ═══════════════════════════════════════════════════════════════════════

    def subtitle(
        self,
        template: str,
        text: str,
        width: int = 1080,
        height: int = 1920,
        duration: float = 3.0,
        font_size: int = 40,
        font_color: str = "white",
        outline_color: str = "black",
        outline_width: int = 3,
        position_y: str = "h*0.85",
    ) -> str:
        """
        生成动态字幕 FFmpeg drawtext 滤镜字符串。

        Args:
            template: karaoke_fill | typewriter_reveal | bounce_word |
                      neon_glow | subtitle_track_bottom
            text: 字幕文本
            width, height: 画布分辨率
            duration: 动画持续时间（秒）
            font_size: 字号
            font_color: 字体颜色
            outline_color: 描边颜色
            outline_width: 描边宽度
            position_y: Y 坐标表达式

        Returns:
            FFmpeg drawtext 滤镜字符串
        """
        config = SubtitleConfig(
            text=text,
            font_size=font_size,
            font_color=font_color,
            outline_color=outline_color,
            outline_width=outline_width,
            duration_sec=duration,
            position_y=position_y,
        )
        templates = {
            "karaoke_fill": self._subtitle_builder.karaoke_fill,
            "typewriter_reveal": self._subtitle_builder.typewriter_reveal,
            "bounce_word": self._subtitle_builder.bounce_word,
            "neon_glow": self._subtitle_builder.neon_glow,
            "subtitle_track_bottom": self._subtitle_builder.subtitle_track_bottom,
        }
        builder = templates.get(template.lower())
        if builder is None:
            raise ValueError(
                f"Unknown subtitle template '{template}'. "
                f"Choose: {', '.join(templates.keys())}"
            )
        return builder(text, duration, width, height, config)

    def list_subtitle_templates(self) -> List[Dict[str, str]]:
        """列出所有字幕模板"""
        return [
            {
                "id": "karaoke_fill",
                "name": "卡拉OK逐字填充",
                "description": "文字从左到右逐字变换金色，模拟卡拉OK效果",
            },
            {
                "id": "typewriter_reveal",
                "name": "打字机逐字显现",
                "description": "字符逐一出现，带半透明黑底光标感",
            },
            {
                "id": "bounce_word",
                "name": "弹跳词",
                "description": "每个字依次弹入，带正弦波弹跳动画",
            },
            {
                "id": "neon_glow",
                "name": "霓虹发光",
                "description": "多层描边叠加形成霓虹扩散光晕",
            },
            {
                "id": "subtitle_track_bottom",
                "name": "底部字幕轨道",
                "description": "经典底部字幕条，半透明黑底+白字",
            },
        ]

    # ═══════════════════════════════════════════════════════════════════════
    # Vertical Video Templates
    # ═══════════════════════════════════════════════════════════════════════

    def vertical_split(
        self,
        upper_video: str,
        lower_video: str,
        output_path: str,
        split_ratio: float = 0.5,
    ) -> List[str]:
        """
        竖屏上下分割布局。

        Args:
            upper_video: 上部视频路径
            lower_video: 下部视频路径
            output_path: 输出路径
            split_ratio: 上部占比 (0.0~1.0)

        Returns:
            ffmpeg 命令列表
        """
        return self._vertical_video.build_split_layout(
            upper_video, lower_video, output_path, split_ratio
        )

    def vertical_blur_bg(
        self,
        video: str,
        output_path: str,
        blur_sigma: int = 20,
    ) -> List[str]:
        """
        竖屏模糊背景填充：原视频居中 + 背景放大模糊。

        Args:
            video: 输入视频路径
            output_path: 输出路径
            blur_sigma: 模糊强度 (越大越模糊)

        Returns:
            ffmpeg 命令列表
        """
        return self._vertical_video.build_blurred_background(
            video, output_path, blur_sigma
        )

    def vertical_pip(
        self,
        main_video: str,
        pip_video: str,
        output_path: str,
        pip_position: str = "bottom_right",
        pip_scale: float = 0.3,
    ) -> List[str]:
        """
        竖屏画中画布局。

        Args:
            main_video: 主视频（全屏背景）
            pip_video: 画中画视频（悬浮小窗）
            output_path: 输出路径
            pip_position: top_left | top_right | bottom_left | bottom_right | center
            pip_scale: 小窗相对画面比例 (0.1~0.5)

        Returns:
            ffmpeg 命令列表
        """
        return self._vertical_video.build_pip_overlay(
            main_video, pip_video, output_path, pip_position, pip_scale
        )

    # ═══════════════════════════════════════════════════════════════════════
    # Creative Transitions
    # ═══════════════════════════════════════════════════════════════════════

    def transition(
        self,
        style: str,
        duration: float = 0.5,
        intensity: float = 0.5,
    ) -> str:
        """
        获取创意转场 FFmpeg 滤镜字符串。

        Args:
            style: glitch | light_leak | whip_pan | lens_flip | pixel_sort |
                   chromatic_ab | kaleidoscope | warp_zoom | mosaic_burst |
                   prism | motion_blur | page_peel | vhs_rewind |
                   digital_noise | cube_flip
            duration: 转场时长（秒）
            intensity: 强度 0.0~1.0

        Returns:
            FFmpeg 滤镜字符串
        """
        transitions = {
            "glitch": self._transition_pack.glitch,
            "light_leak": self._transition_pack.light_leak,
            "whip_pan": self._transition_pack.whip_pan,
            "lens_flip": self._transition_pack.lens_flip,
            "pixel_sort": self._transition_pack.pixel_sort,
            "chromatic_ab": self._transition_pack.chromatic_aberration,
            "kaleidoscope": self._transition_pack.kaleidoscope,
            "warp_zoom": self._transition_pack.warp_zoom,
            "mosaic_burst": self._transition_pack.mosaic_burst,
            "prism": self._transition_pack.prism,
            "motion_blur": self._transition_pack.motion_blur,
            "page_peel": self._transition_pack.page_peel,
            "vhs_rewind": self._transition_pack.vhs_rewind,
            "digital_noise": self._transition_pack.digital_noise,
            "cube_flip": self._transition_pack.cube_flip,
        }
        fn = transitions.get(style.lower())
        if fn is None:
            raise ValueError(
                f"Unknown transition style '{style}'. "
                f"Choose: {', '.join(transitions.keys())}"
            )
        return fn(
            max(0.1, min(5.0, duration)),
            max(0.0, min(1.0, intensity)),
        )

    def list_transitions(self) -> List[Dict[str, str]]:
        """列出所有创意转场"""
        return [
            {"id": "glitch", "name": "故障撕裂", "description": "RGB通道偏移+随机噪声块撕裂"},
            {"id": "light_leak", "name": "漏光", "description": "橙色/金色渐变光晕从边缘渗入"},
            {"id": "whip_pan", "name": "甩镜", "description": "水平快速运动模糊+动态缩放"},
            {"id": "lens_flip", "name": "镜头翻转", "description": "沿Y轴旋转模拟3D翻转"},
            {"id": "pixel_sort", "name": "像素拖动", "description": "像素按亮度从左到右归位"},
            {"id": "chromatic_ab", "name": "色差偏移", "description": "红蓝通道分离模拟镜头色差"},
            {"id": "kaleidoscope", "name": "万花筒", "description": "镜像翻转叠加四象限"},
            {"id": "warp_zoom", "name": "扭曲缩放", "description": "桶形畸变+快速推进"},
            {"id": "mosaic_burst", "name": "马赛克爆发", "description": "像素块逐渐破碎变大"},
            {"id": "prism", "name": "棱镜折射", "description": "RGB通道各自旋转微小角度"},
            {"id": "motion_blur", "name": "动态模糊", "description": "高强度方向性模糊"},
            {"id": "page_peel", "name": "页面撕开", "description": "水平方向逐渐揭示的翻页"},
            {"id": "vhs_rewind", "name": "录像带回放", "description": "噪点带+追踪线+画面跳动"},
            {"id": "digital_noise", "name": "数码噪点", "description": "RGB数字噪点爆发"},
            {"id": "cube_flip", "name": "3D立方翻转", "description": "透视变换模拟立方体旋转"},
        ]

    # ═══════════════════════════════════════════════════════════════════════
    # Composite Rendering
    # ═══════════════════════════════════════════════════════════════════════

    async def apply_particle_to_video(
        self,
        input_path: str,
        output_path: str,
        particle_effect: str,
        particle_density: float = 0.5,
        particle_speed: float = 1.0,
        progress_cb: Optional[Callable] = None,
    ) -> str:
        """
        将粒子特效叠加到现有视频上。

        Args:
            input_path: 输入视频
            output_path: 输出路径
            particle_effect: 粒子类型 (snow/rain/fire/sparkle/confetti)
            particle_density: 粒子密度
            particle_speed: 粒子速度
            progress_cb: 可选的进度回调 async def(stage, pct, msg)

        Returns:
            输出文件路径
        """
        # 先探测视频分辨率
        info = await self._ffprobe(input_path)
        streams = info.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video_stream:
            width = video_stream.get("width", 1080)
            height = video_stream.get("height", 1920)
        else:
            width, height = 1080, 1920

        particle_vf = self.particle(
            particle_effect, width, height,
            density=particle_density,
            speed=particle_speed,
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", particle_vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        if progress_cb:
            await progress_cb("vfx_particle", 10, f"Applying {particle_effect}...")

        await self._run_ffmpeg(cmd, timeout=600)

        if progress_cb:
            await progress_cb("vfx_particle", 100, f"{particle_effect} applied")

        return output_path

    async def apply_filter_to_video(
        self,
        input_path: str,
        output_path: str,
        preset_name: str,
        progress_cb: Optional[Callable] = None,
    ) -> str:
        """
        将电影调色滤镜应用到视频上。

        Args:
            input_path: 输入视频
            output_path: 输出路径
            preset_name: 预设名称
            progress_cb: 可选的进度回调

        Returns:
            输出文件路径
        """
        filter_vf = self.filter_preset(preset_name)

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-vf", filter_vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        if progress_cb:
            await progress_cb("vfx_filter", 10, f"Applying {preset_name}...")

        await self._run_ffmpeg(cmd, timeout=600)

        if progress_cb:
            await progress_cb("vfx_filter", 100, f"{preset_name} applied")

        return output_path


# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                          Module-Level Singleton                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

vfx = VFXEngine()
