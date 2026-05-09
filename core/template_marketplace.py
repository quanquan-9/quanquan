"""
模板市场 — 20+ 预置视频模板，支持分类浏览/搜索/一键创建项目
=================================================================
集成 cold_start 系统，自动注册为可用模板。每个模板包含完整预设：
  - 风格预设 (style_preset)
  - 特效预设 (vfx_preset)
  - 平台定向 (platform_target)
  - 默认时长 (default_duration)
  - 预览图 (preview_image)

用法:
  marketplace = TemplateMarketplace(projects_store, director, ws_broadcaster)
  templates = marketplace.list_all()
  project = await marketplace.create_from_template("tech_explainer_01", text, user_id)
"""
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("quanquan.template_marketplace")


@dataclass
class VideoTemplate:
    """视频模板数据结构"""
    template_id: str            # 唯一标识: tech_explainer_01
    name: str                   # 模板名称: "硬核科技解说"
    description: str            # 模板描述
    category: str               # 分类: 科技解说/生活Vlog/电影大片...
    tags: List[str]             # 标签列表
    preview_image: str          # 预览图路径 (相对于 static/)
    default_duration: int       # 默认时长(秒)
    style_preset: str           # 风格预设ID (对应 stylization STYLE_MAP)
    vfx_preset: str             # 特效预设 (对应 VFXEngine preset)
    platform_target: str        # 目标平台: douyin/bilibili/youtube/universal
    voice_id: str               # 配音ID
    bgm_genre: str              # 配乐风格
    pace: str                   # 节奏: slow/medium/fast
    subtitle_style: dict        # 字幕样式
    transition: str             # 转场效果
    filter_preset: str          # 滤镜预设
    aspect_ratio: str           # 画幅比例: 9:16 / 16:9 / 1:1
    is_featured: bool = False   # 是否精选模板
    usage_count: int = 0        # 使用次数


# ══════════════════════════════════════════════════════════════════════════════
# 20+ 预置模板库
# ══════════════════════════════════════════════════════════════════════════════

TEMPLATES: Dict[str, VideoTemplate] = {
    # ── 科技解说 (3个模板) ──
    "tech_explainer_01": VideoTemplate(
        template_id="tech_explainer_01",
        name="硬核科技解说",
        description="专业科技产品评测与技术科普，适合AI/数码/芯片等硬核内容。清晰理性男声配音，现代简洁风格。",
        category="科技解说",
        tags=["科技", "AI", "数码", "评测", "技术", "产品", "芯片", "编程"],
        preview_image="templates/tech_explainer_01.png",
        default_duration=180,
        style_preset="modern_clean",
        vfx_preset="tech_blue",
        platform_target="bilibili",
        voice_id="clear_male_01",
        bgm_genre="corporate",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":32,"color":"#00D4FF","outline_width":2},
        transition="smooth_cut",
        filter_preset="modern_clean",
        aspect_ratio="16:9",
        is_featured=True,
    ),
    "tech_explainer_02": VideoTemplate(
        template_id="tech_explainer_02",
        name="AI前沿速递",
        description="快节奏AI资讯与行业动态解读，适合短视频平台。充满未来感的赛博风格。",
        category="科技解说",
        tags=["AI", "人工智能", "资讯", "前沿", "科技", "GPT", "深度学习"],
        preview_image="templates/tech_explainer_02.png",
        default_duration=60,
        style_preset="cyberpunk",
        vfx_preset="cyberpunk_purple",
        platform_target="douyin",
        voice_id="energetic_male_02",
        bgm_genre="electronic",
        pace="fast",
        subtitle_style={"font":"PingFang SC","size":40,"color":"#FF00FF","outline_width":3},
        transition="glitch",
        filter_preset="cyberpunk_purple",
        aspect_ratio="9:16",
        is_featured=False,
    ),
    "tech_explainer_03": VideoTemplate(
        template_id="tech_explainer_03",
        name="开发者日常",
        description="程序员工作日常Vlog、技术教程、开源项目分享。轻松自然的记录风格。",
        category="科技解说",
        tags=["编程", "开发者", "VSCode", "GitHub", "开源", "教程", "后端"],
        preview_image="templates/tech_explainer_03.png",
        default_duration=120,
        style_preset="documentary",
        vfx_preset="documentary_neutral",
        platform_target="bilibili",
        voice_id="clear_male_01",
        bgm_genre="lofi",
        pace="medium",
        subtitle_style={"font":"JetBrains Mono","size":28,"color":"#00FF88","outline_width":2},
        transition="dissolve",
        filter_preset="documentary_neutral",
        aspect_ratio="16:9",
        is_featured=False,
    ),

    # ── 生活Vlog (2个模板) ──
    "vlog_lifestyle_01": VideoTemplate(
        template_id="vlog_lifestyle_01",
        name="治愈系日常Vlog",
        description="温暖治愈的日常生活记录，适合美食/旅行/家居内容。柔和色调，舒缓节奏。",
        category="生活Vlog",
        tags=["vlog", "日常", "治愈", "生活", "温暖", "慢生活", "居家"],
        preview_image="templates/vlog_lifestyle_01.png",
        default_duration=150,
        style_preset="warm_sunshine",
        vfx_preset="warm_sunshine",
        platform_target="douyin",
        voice_id="warm_female_01",
        bgm_genre="acoustic",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":30,"color":"#FFD700","outline_width":2},
        transition="fade",
        filter_preset="warm_sunshine",
        aspect_ratio="9:16",
        is_featured=True,
    ),
    "vlog_lifestyle_02": VideoTemplate(
        template_id="vlog_lifestyle_02",
        name="城市探索者",
        description="城市漫步、探店打卡、街头摄影Vlog。复古胶片质感，快节奏剪辑。",
        category="生活Vlog",
        tags=["城市", "探店", "咖啡", "摄影", "街拍", "旅行", "文艺"],
        preview_image="templates/vlog_lifestyle_02.png",
        default_duration=120,
        style_preset="vintage_light",
        vfx_preset="film_grain",
        platform_target="douyin",
        voice_id="gentle_female_03",
        bgm_genre="indie",
        pace="fast",
        subtitle_style={"font":"PingFang SC","size":32,"color":"#FFB6C1","outline_width":1},
        transition="slide_left",
        filter_preset="vintage_light",
        aspect_ratio="9:16",
        is_featured=True,
    ),

    # ── 电影大片 (2个模板) ──
    "cinematic_epic_01": VideoTemplate(
        template_id="cinematic_epic_01",
        name="电影感宣传片",
        description="高端品牌宣传片、企业形象片。电影级调色，史诗感配乐，大气沉稳。",
        category="电影大片",
        tags=["电影", "宣传", "品牌", "高端", "商业", "企业", "发布会"],
        preview_image="templates/cinematic_epic_01.png",
        default_duration=120,
        style_preset="cinematic",
        vfx_preset="cinematic_teal",
        platform_target="youtube",
        voice_id="deep_male_03",
        bgm_genre="cinematic",
        pace="slow",
        subtitle_style={"font":"PingFang SC","size":36,"color":"#FFD700","outline_width":3},
        transition="dissolve",
        filter_preset="cinematic_teal",
        aspect_ratio="16:9",
        is_featured=True,
    ),
    "cinematic_epic_02": VideoTemplate(
        template_id="cinematic_epic_02",
        name="赛博朋克大片",
        description="霓虹灯效、未来都市、赛博朋克风格短片。炫酷转场，电子配乐。",
        category="电影大片",
        tags=["赛博朋克", "霓虹", "未来", "科幻", "炫酷", "夜间", "城市"],
        preview_image="templates/cinematic_epic_02.png",
        default_duration=60,
        style_preset="cyberpunk",
        vfx_preset="cyberpunk_neon",
        platform_target="bilibili",
        voice_id="deep_male_03",
        bgm_genre="synthwave",
        pace="fast",
        subtitle_style={"font":"PingFang SC","size":42,"color":"#FF00FF","outline_width":3},
        transition="glitch_dissolve",
        filter_preset="cyberpunk_neon",
        aspect_ratio="16:9",
        is_featured=True,
    ),

    # ── 短视频 (2个模板) ──
    "short_video_01": VideoTemplate(
        template_id="short_video_01",
        name="爆款短视频模板",
        description="抖音快手爆款短视频模板，快节奏卡点，高对比度视觉冲击，适合泛娱乐内容。",
        category="短视频",
        tags=["抖音", "快手", "爆款", "卡点", "快节奏", "娱乐", "热门"],
        preview_image="templates/short_video_01.png",
        default_duration=30,
        style_preset="vibrant_pop",
        vfx_preset="high_contrast",
        platform_target="douyin",
        voice_id="energetic_male_02",
        bgm_genre="pop",
        pace="fast",
        subtitle_style={"font":"PingFang SC","size":44,"color":"#FFFF00","outline_width":4},
        transition="flash",
        filter_preset="high_contrast",
        aspect_ratio="9:16",
        is_featured=True,
    ),
    "short_video_02": VideoTemplate(
        template_id="short_video_02",
        name="小红书图文视频",
        description="小红书风格图文展示视频，优雅排版，清新色调，适合好物分享/种草。",
        category="短视频",
        tags=["小红书", "好物", "种草", "分享", "图文", "清新", "女生"],
        preview_image="templates/short_video_02.png",
        default_duration=30,
        style_preset="pastel_dream",
        vfx_preset="soft_blush",
        platform_target="douyin",
        voice_id="warm_female_01",
        bgm_genre="chill",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":30,"color":"#FF69B4","outline_width":2},
        transition="slide_up",
        filter_preset="pastel_dream",
        aspect_ratio="9:16",
        is_featured=False,
    ),

    # ── 教育 (2个模板) ──
    "education_course_01": VideoTemplate(
        template_id="education_course_01",
        name="在线课程录制",
        description="知识付费/在线课程录制模板。清晰板书风格，舒缓背景音，适合长时间观看。",
        category="教育",
        tags=["教育", "课程", "知识", "学习", "培训", "教程", "讲座"],
        preview_image="templates/education_course_01.png",
        default_duration=300,
        style_preset="clean_white",
        vfx_preset="clean_white",
        platform_target="bilibili",
        voice_id="clear_female_02",
        bgm_genre="ambient",
        pace="slow",
        subtitle_style={"font":"PingFang SC","size":28,"color":"#333333","outline_width":1},
        transition="smooth_cut",
        filter_preset="clean_white",
        aspect_ratio="16:9",
        is_featured=True,
    ),
    "education_course_02": VideoTemplate(
        template_id="education_course_02",
        name="秒懂百科/知识科普",
        description="3分钟快速科普，动画+文字结合，适合百科类短视频。活泼节奏，便于理解。",
        category="教育",
        tags=["科普", "百科", "知识", "3分钟", "动画", "图解", "历史"],
        preview_image="templates/education_course_02.png",
        default_duration=180,
        style_preset="soft_focus",
        vfx_preset="soft_focus",
        platform_target="bilibili",
        voice_id="clear_male_01",
        bgm_genre="piano",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":32,"color":"#FF6600","outline_width":2},
        transition="dissolve",
        filter_preset="soft_focus",
        aspect_ratio="16:9",
        is_featured=False,
    ),

    # ── 游戏 (2个模板) ──
    "gaming_montage_01": VideoTemplate(
        template_id="gaming_montage_01",
        name="电竞高光集锦",
        description="游戏击杀集锦/高光时刻混剪。电子配乐，快速转场，字幕特效炸裂。",
        category="游戏",
        tags=["游戏", "电竞", "高光", "击杀", "集锦", "LOL", "吃鸡", "原神"],
        preview_image="templates/gaming_montage_01.png",
        default_duration=90,
        style_preset="cyberpunk_neon",
        vfx_preset="cyberpunk_neon",
        platform_target="bilibili",
        voice_id="energetic_male_02",
        bgm_genre="dubstep",
        pace="fast",
        subtitle_style={"font":"Impact","size":44,"color":"#FF4444","outline_width":3},
        transition="glitch",
        filter_preset="cyberpunk_neon",
        aspect_ratio="16:9",
        is_featured=True,
    ),
    "gaming_montage_02": VideoTemplate(
        template_id="gaming_montage_02",
        name="游戏剧情解说",
        description="游戏剧情/角色分析解说视频。沉浸式氛围，深度内容，适合长视频。",
        category="游戏",
        tags=["游戏", "剧情", "解说", "角色", "分析", "单机", "主机"],
        preview_image="templates/gaming_montage_02.png",
        default_duration=300,
        style_preset="night_city",
        vfx_preset="night_city",
        platform_target="bilibili",
        voice_id="deep_male_03",
        bgm_genre="orchestral",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":30,"color":"#CCCCCC","outline_width":2},
        transition="dissolve",
        filter_preset="night_city",
        aspect_ratio="16:9",
        is_featured=False,
    ),

    # ── 美妆 (1个模板) ──
    "beauty_makeup_01": VideoTemplate(
        template_id="beauty_makeup_01",
        name="美妆教程标准",
        description="美妆教程/护肤分享标准模板。柔和肤色滤镜，特写友好，精致字幕。",
        category="美妆",
        tags=["美妆", "化妆", "护肤", "教程", "彩妆", "种草", "口红"],
        preview_image="templates/beauty_makeup_01.png",
        default_duration=150,
        style_preset="portrait_soft",
        vfx_preset="soft_blush",
        platform_target="douyin",
        voice_id="warm_female_01",
        bgm_genre="rnb",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":30,"color":"#FF69B4","outline_width":2},
        transition="zoom_in",
        filter_preset="soft_blush",
        aspect_ratio="9:16",
        is_featured=True,
    ),

    # ── 美食 (1个模板) ──
    "food_cuisine_01": VideoTemplate(
        template_id="food_cuisine_01",
        name="美食探店/烹饪",
        description="美食探店、烹饪教程、食材展示。暖色调，食欲感max，诱人转场。",
        category="美食",
        tags=["美食", "探店", "烹饪", "食谱", "厨房", "火锅", "甜品", "烧烤"],
        preview_image="templates/food_cuisine_01.png",
        default_duration=90,
        style_preset="golden_hour",
        vfx_preset="golden_hour",
        platform_target="douyin",
        voice_id="warm_female_01",
        bgm_genre="acoustic",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":34,"color":"#FF8C00","outline_width":3},
        transition="slide_left",
        filter_preset="golden_hour",
        aspect_ratio="9:16",
        is_featured=True,
    ),

    # ── 旅行 (1个模板) ──
    "travel_wanderlust_01": VideoTemplate(
        template_id="travel_wanderlust_01",
        name="旅行风光大片",
        description="旅行Vlog/风光大片模板。自然鲜艳色彩，广阔构图，史诗感配乐。",
        category="旅行",
        tags=["旅行", "风光", "自然", "航拍", "户外", "风景", "无人机"],
        preview_image="templates/travel_wanderlust_01.png",
        default_duration=180,
        style_preset="nature_vivid",
        vfx_preset="travel_bright",
        platform_target="youtube",
        voice_id="clear_female_02",
        bgm_genre="world",
        pace="slow",
        subtitle_style={"font":"PingFang SC","size":28,"color":"#FFFFFF","outline_width":2},
        transition="zoomin",
        filter_preset="nature_vivid",
        aspect_ratio="16:9",
        is_featured=True,
    ),

    # ── 音乐 (1个模板) ──
    "music_performance_01": VideoTemplate(
        template_id="music_performance_01",
        name="音乐MV/翻唱",
        description="音乐演出、翻唱MV、乐器演奏视频模板。节奏同步，氛围灯光，动态字幕。",
        category="音乐",
        tags=["音乐", "MV", "翻唱", "演出", "乐器", "吉他", "钢琴", "DJ"],
        preview_image="templates/music_performance_01.png",
        default_duration=240,
        style_preset="synthwave",
        vfx_preset="synthwave",
        platform_target="bilibili",
        voice_id="clear_male_01",
        bgm_genre="electronic",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":36,"color":"#FF0080","outline_width":3},
        transition="flash",
        filter_preset="synthwave",
        aspect_ratio="16:9",
        is_featured=False,
    ),

    # ── 运动 (1个模板) ──
    "sports_action_01": VideoTemplate(
        template_id="sports_action_01",
        name="运动燃脂集锦",
        description="健身教程/运动集锦/极限运动。高能量节奏，动感字体，燃向配乐。",
        category="运动",
        tags=["运动", "健身", "跑步", "篮球", "足球", "极限", "马拉松"],
        preview_image="templates/sports_action_01.png",
        default_duration=60,
        style_preset="high_contrast",
        vfx_preset="travel_bright",
        platform_target="douyin",
        voice_id="deep_male_03",
        bgm_genre="hiphop",
        pace="fast",
        subtitle_style={"font":"PingFang SC","size":38,"color":"#FF6600","outline_width":3},
        transition="slide_up",
        filter_preset="travel_bright",
        aspect_ratio="9:16",
        is_featured=False,
    ),

    # ── 宠物 (1个模板) ──
    "pet_animal_01": VideoTemplate(
        template_id="pet_animal_01",
        name="萌宠合集",
        description="猫咪/狗狗/宠物日常合集。可爱滤镜，轻松配乐，温馨字幕。萌化人心！",
        category="宠物",
        tags=["宠物", "猫", "狗", "萌宠", "猫咪", "狗狗", "可爱", "小动物"],
        preview_image="templates/pet_animal_01.png",
        default_duration=60,
        style_preset="pastel_dream",
        vfx_preset="pastel_dream",
        platform_target="douyin",
        voice_id="warm_female_01",
        bgm_genre="ukulele",
        pace="medium",
        subtitle_style={"font":"PingFang SC","size":36,"color":"#FFD700","outline_width":2},
        transition="zoomin",
        filter_preset="pastel_dream",
        aspect_ratio="9:16",
        is_featured=True,
    ),

    # ── 商务 (1个模板) ──
    "business_presentation_01": VideoTemplate(
        template_id="business_presentation_01",
        name="商务演示/企业宣传",
        description="企业宣传片/商务演示/年会视频模板。专业沉稳，数据可视化友好。",
        category="商务",
        tags=["商务", "企业", "演示", "宣传", "年会", "汇报", "PPT", "金融"],
        preview_image="templates/business_presentation_01.png",
        default_duration=180,
        style_preset="documentary_neutral",
        vfx_preset="modern_clean",
        platform_target="youtube",
        voice_id="clear_male_01",
        bgm_genre="corporate",
        pace="slow",
        subtitle_style={"font":"PingFang SC","size":28,"color":"#FFFFFF","outline_width":2},
        transition="smooth_cut",
        filter_preset="documentary_neutral",
        aspect_ratio="16:9",
        is_featured=False,
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# 分类定义（含图标emoji和描述）
# ══════════════════════════════════════════════════════════════════════════════

CATEGORIES: Dict[str, dict] = {
    "科技解说": {"icon": "🤖", "description": "科技产品评测、技术科普、AI话题", "count": 0},
    "生活Vlog": {"icon": "🏠", "description": "日常生活记录、城市探索、治愈Vlog", "count": 0},
    "电影大片": {"icon": "🎬", "description": "电影感宣传片、赛博朋克、高端品牌", "count": 0},
    "短视频": {"icon": "📱", "description": "抖音快手短视频、爆款模板、小红书图文", "count": 0},
    "教育": {"icon": "📚", "description": "在线课程、知识科普、教育培训", "count": 0},
    "游戏": {"icon": "🎮", "description": "电竞高光、游戏解说、主机游戏", "count": 0},
    "美妆": {"icon": "💄", "description": "美妆教程、护肤分享、彩妆种草", "count": 0},
    "美食": {"icon": "🍔", "description": "美食探店、烹饪教程、食欲大片", "count": 0},
    "旅行": {"icon": "✈️", "description": "旅行Vlog、风光大片、航拍视频", "count": 0},
    "音乐": {"icon": "🎵", "description": "音乐MV、翻唱视频、乐器演奏", "count": 0},
    "运动": {"icon": "⚽", "description": "健身教程、运动集锦、极限运动", "count": 0},
    "宠物": {"icon": "🐱", "description": "萌宠日常、猫咪狗狗、可爱合集", "count": 0},
    "商务": {"icon": "💼", "description": "企业宣传、商务演示、年会视频", "count": 0},
}

# 预计算分类下的模板数量
for t in TEMPLATES.values():
    if t.category in CATEGORIES:
        CATEGORIES[t.category]["count"] += 1


class TemplateMarketplace:
    """
    视频模板市场
    
    功能:
      - 20+ 预置模板，按13个分类组织
      - 按分类/标签/全文搜索
      - 一键从模板创建视频项目
      - 自动注册到 cold_start 系统
      - 统计模板使用次数
    """

    def __init__(self, projects_store: dict = None, director=None, ws_broadcaster=None):
        """
        初始化模板市场
        
        Args:
            projects_store: 项目存储字典
            director: DirectorAgent 实例 (用于创建项目)
            ws_broadcaster: WSBroadcaster 实例 (用于推送事件)
        """
        self._projects_store = projects_store or {}
        self._director = director
        self._ws_broadcaster = ws_broadcaster
        self._custom_templates: Dict[str, VideoTemplate] = {}
        self._init_cold_start()

    def _init_cold_start(self):
        """将模板自动注册到 cold_start 系统"""
        try:
            from core.cold_start import COLD_START_TEMPLATES, ColdStartTemplate, ColdStartMatcher
            registered = set(t.name for t in COLD_START_TEMPLATES.values())
            for tid, tmpl in TEMPLATES.items():
                if tmpl.name not in registered and tmpl.is_featured:
                    cst = ColdStartTemplate(
                        name=tmpl.name,
                        style_tags=tmpl.tags,
                        voice_id=tmpl.voice_id,
                        transitions=[tmpl.transition],
                        filters=[tmpl.filter_preset],
                        bgm_genres=[tmpl.bgm_genre],
                        subtitle_style=tmpl.subtitle_style,
                        pace=tmpl.pace,
                        description=tmpl.description,
                    )
                    COLD_START_TEMPLATES[tid] = cst
            logger.info(f"[TemplateMarketplace] ✅ 已注册 {len(TEMPLATES)} 个模板到 cold_start 系统")
        except Exception as e:
            logger.warning(f"[TemplateMarketplace] cold_start 注册失败（非致命）: {e}")

    # ── 列表 & 查看 ──

    def list_all(self, include_custom: bool = True) -> List[dict]:
        """列出所有模板（含用户自定义模板）"""
        result = [self._template_to_dict(t) for t in TEMPLATES.values()]
        if include_custom:
            result += [self._template_to_dict(t) for t in self._custom_templates.values()]
        # 精选模板排在前面
        result.sort(key=lambda x: (not x["is_featured"], -x["usage_count"]))
        return result

    def get_by_id(self, template_id: str) -> Optional[dict]:
        """根据ID获取模板详情"""
        tmpl = TEMPLATES.get(template_id) or self._custom_templates.get(template_id)
        if tmpl:
            return self._template_to_dict(tmpl)
        return None

    def get_by_category(self, category: str) -> List[dict]:
        """按分类获取模板列表"""
        result = [
            self._template_to_dict(t)
            for t in list(TEMPLATES.values()) + list(self._custom_templates.values())
            if t.category == category
        ]
        result.sort(key=lambda x: -x["usage_count"])
        return result

    def search(self, query: str) -> List[dict]:
        """
        搜索模板（名称、描述、标签、分类模糊匹配）
        
        Args:
            query: 搜索关键词
        
        Returns:
            匹配的模板列表，按相关度排序
        """
        q = query.lower()
        scored = []
        for t in list(TEMPLATES.values()) + list(self._custom_templates.values()):
            score = 0
            # 名称完全匹配
            if q in t.name.lower():
                score += 10
            # 名称部分匹配
            for word in q.split():
                if word in t.name.lower():
                    score += 5
            # 标签匹配
            for tag in t.tags:
                if q in tag.lower() or tag.lower() in q:
                    score += 3
                    break
            # 描述匹配
            if q in t.description.lower():
                score += 2
            # 分类匹配
            if q in t.category.lower():
                score += 2
            # 平台匹配
            if q in t.platform_target.lower():
                score += 1

            if score > 0:
                scored.append((score, self._template_to_dict(t)))

        scored.sort(key=lambda x: (-x[0], -x[1]["usage_count"]))
        return [t for _, t in scored]

    def list_categories(self) -> List[dict]:
        """列出所有分类及模板数量"""
        return [
            {"name": name, "icon": info["icon"], "description": info["description"],
             "count": info["count"]}
            for name, info in CATEGORIES.items()
        ]

    def list_featured(self) -> List[dict]:
        """列出精选模板"""
        return [
            self._template_to_dict(t)
            for t in TEMPLATES.values()
            if t.is_featured
        ]

    def list_platform_targets(self) -> List[str]:
        """列出所有支持的平台"""
        return sorted(set(t.platform_target for t in TEMPLATES.values()))

    def get_usage_stats(self) -> List[dict]:
        """获取模板使用排行"""
        ranked = sorted(
            [self._template_to_dict(t) for t in TEMPLATES.values()],
            key=lambda x: x["usage_count"],
            reverse=True,
        )
        return ranked[:10]

    # ── 从模板创建项目 ──

    async def create_from_template(self, template_id: str, text: str, user_id: str = "anonymous",
                                    duration: int = None, extra_tags: List[str] = None) -> Optional[dict]:
        """
        从模板一键创建视频项目
        
        Args:
            template_id: 模板ID
            text: 用户输入的视频主题
            user_id: 用户ID
            duration: 覆盖默认时长（None则使用模板默认值）
            extra_tags: 额外标签
        
        Returns:
            项目信息字典，失败返回 None
        """
        tmpl = TEMPLATES.get(template_id) or self._custom_templates.get(template_id)
        if not tmpl:
            logger.warning(f"[TemplateMarketplace] 模板不存在: {template_id}")
            return None

        # 构建项目参数
        project_id = f"quan_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{user_id[:8]}"
        target_duration = duration or tmpl.default_duration
        combined_tags = list(set(tmpl.tags + (extra_tags or [])))

        project = {
            "project_id": project_id,
            "name": text[:50] if text else tmpl.name,
            "text": text,
            "duration": target_duration,
            "style": tmpl.style_preset,
            "status": "queued",
            "progress": 0.0,
            "state": "created_from_template",
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "tags": combined_tags,
            # 模板元数据
            "template_id": template_id,
            "template_name": tmpl.name,
            "template_category": tmpl.category,
            "platform_target": tmpl.platform_target,
            "vfx_preset": tmpl.vfx_preset,
            "voice_id": tmpl.voice_id,
            "bgm_genre": tmpl.bgm_genre,
            "pace": tmpl.pace,
            "subtitle_style": tmpl.subtitle_style,
            "transition": tmpl.transition,
            "filter_preset": tmpl.filter_preset,
            "aspect_ratio": tmpl.aspect_ratio,
        }

        # 存入项目存储
        if self._projects_store is not None:
            self._projects_store[project_id] = project

        # 推入导演 Agent 队列
        if self._director is not None:
            try:
                self._director.submit_project_nonblock({
                    "project_id": project_id,
                    "user_id": user_id,
                    "text_prompt": text,
                    "duration_target_sec": target_duration,
                    "style_tags": combined_tags,
                })
                project["status"] = "active"
                project["state"] = "queued"
            except Exception as e:
                logger.error(f"[TemplateMarketplace] 提交项目失败: {e}")
                project["status"] = "queued"
                project["state"] = "pending"

        # 更新模板使用次数
        tmpl.usage_count += 1

        # 通过 WebSocket 广播
        if self._ws_broadcaster is not None:
            await self._ws_broadcaster.on_template_applied(
                project_id, tmpl.name, template_id
            )
            await self._ws_broadcaster.broadcast(
                "project_created",
                {"project_id": project_id, "name": text[:50], "status": project["status"],
                 "template": tmpl.name},
            )

        logger.info(f"[TemplateMarketplace] ✅ 从模板 '{tmpl.name}' 创建项目 {project_id}")
        return project

    # ── 自定义模板 ──

    def add_custom_template(self, template: VideoTemplate) -> bool:
        """添加用户自定义模板"""
        tid = template.template_id
        if tid in TEMPLATES or tid in self._custom_templates:
            logger.warning(f"[TemplateMarketplace] 模板ID '{tid}' 已存在")
            return False
        self._custom_templates[tid] = template
        logger.info(f"[TemplateMarketplace] ✅ 已添加自定义模板: {template.name}")
        return True

    def remove_custom_template(self, template_id: str) -> bool:
        """删除用户自定义模板"""
        if template_id in self._custom_templates:
            del self._custom_templates[template_id]
            logger.info(f"[TemplateMarketplace] 已删除自定义模板: {template_id}")
            return True
        return False

    def register_usage(self, template_id: str):
        """手动增加模板使用计数"""
        if template_id in TEMPLATES:
            TEMPLATES[template_id].usage_count += 1

    # ── 工具方法 ──

    @staticmethod
    def _template_to_dict(tmpl: VideoTemplate) -> dict:
        """将 VideoTemplate 转换为字典"""
        return {
            "template_id": tmpl.template_id,
            "name": tmpl.name,
            "description": tmpl.description,
            "category": tmpl.category,
            "tags": tmpl.tags,
            "preview_image": tmpl.preview_image,
            "default_duration": tmpl.default_duration,
            "style_preset": tmpl.style_preset,
            "vfx_preset": tmpl.vfx_preset,
            "platform_target": tmpl.platform_target,
            "voice_id": tmpl.voice_id,
            "bgm_genre": tmpl.bgm_genre,
            "pace": tmpl.pace,
            "subtitle_style": tmpl.subtitle_style,
            "transition": tmpl.transition,
            "filter_preset": tmpl.filter_preset,
            "aspect_ratio": tmpl.aspect_ratio,
            "is_featured": tmpl.is_featured,
            "usage_count": tmpl.usage_count,
        }

    def count(self) -> int:
        """返回模板总数"""
        return len(TEMPLATES) + len(self._custom_templates)


# ── 全局单例 ──
template_marketplace: Optional[TemplateMarketplace] = None
