"""
quanquan 完整 LUT 色彩风格库 — 50 个预设风格

分类：电影级 · 温暖系 · 清冷系 · 复古系 · 黑白系 · 创意系 ·
      柔美系 · 自然系 · 美食系 · 人像系 · 都市系 · 旅行系 ·
      恐怖系 · 科幻系 · 纪录系 · 日系 · 韩系 · 欧美系 · 国风系
"""

from typing import Dict, List, Any

# ═══════════════════════════════════════════════════════════
# 50 LUT 风格预设
# ═══════════════════════════════════════════════════════════

FULL_LUT_LIBRARY: Dict[str, Dict[str, Any]] = {
    # ==================== 电影级 (CINEMATIC) ====================
    "cinematic_teal": {
        "name": "电影青橙", "category": "cinematic",
        "description": "经典好莱坞青橙对比色调",
        "params": {"contrast": 1.2, "saturation": 1.1, "temperature": -5, "tint": 3},
        "mood": "大片感", "best_for": ["宣传片", "短片", "Vlog"],
    },
    "cinematic_gold": {
        "name": "电影金调", "category": "cinematic",
        "description": "温暖金色电影调色",
        "params": {"contrast": 1.15, "saturation": 1.05, "temperature": 8, "tint": 5},
        "mood": "史诗感", "best_for": ["旅行", "纪录片"],
    },
    "cinematic_noir": {
        "name": "黑色电影", "category": "cinematic",
        "description": "高对比度暗调，经典黑色电影风格",
        "params": {"contrast": 1.5, "saturation": 0.3, "temperature": -15, "tint": -5},
        "mood": "悬疑", "best_for": ["剧情片", "悬疑"],
    },
    "blockbuster": {
        "name": "好莱坞大片", "category": "cinematic",
        "description": "高饱和高对比，商业大片风格",
        "params": {"contrast": 1.25, "saturation": 1.3, "temperature": -2},
        "mood": "震撼", "best_for": ["宣传片", "广告"],
    },
    "indie_film": {
        "name": "独立电影", "category": "cinematic",
        "description": "低饱和暖调，文艺电影质感",
        "params": {"contrast": 1.0, "saturation": 0.7, "temperature": 5, "grain": 0.03},
        "mood": "文艺", "best_for": ["文艺片", "Vlog"],
    },

    # ==================== 温暖系 (WARM) ====================
    "warm_sunset": {
        "name": "温暖日落", "category": "warm",
        "params": {"contrast": 1.1, "saturation": 1.15, "temperature": 12, "tint": 8},
        "mood": "温暖", "best_for": ["旅行", "生活", "户外"],
    },
    "golden_hour": {
        "name": "黄金时刻", "category": "warm",
        "params": {"contrast": 1.05, "saturation": 1.1, "temperature": 15, "tint": 10},
        "mood": "浪漫", "best_for": ["人像", "婚礼", "旅行"],
    },
    "autumn_glow": {
        "name": "秋日暖阳", "category": "warm",
        "params": {"contrast": 1.08, "saturation": 1.2, "temperature": 10, "tint": 5},
        "mood": "温馨", "best_for": ["生活", "美食", "户外"],
    },
    "candle_light": {
        "name": "烛光暖调", "category": "warm",
        "params": {"contrast": 0.9, "saturation": 0.85, "temperature": 20, "tint": 12},
        "mood": "亲密", "best_for": ["室内", "美食", "氛围"],
    },

    # ==================== 清冷系 (COOL) ====================
    "cool_moonlight": {
        "name": "清冷月光", "category": "cool",
        "params": {"contrast": 1.1, "saturation": 0.9, "temperature": -12, "tint": -3},
        "mood": "清冷", "best_for": ["夜景", "氛围"],
    },
    "arctic_blue": {
        "name": "极地冰蓝", "category": "cool",
        "params": {"contrast": 1.15, "saturation": 0.8, "temperature": -20, "tint": -5},
        "mood": "冷静", "best_for": ["科技", "产品", "冰雪"],
    },
    "winter_mist": {
        "name": "冬日薄雾", "category": "cool",
        "params": {"contrast": 0.85, "saturation": 0.5, "temperature": -8, "tint": 0},
        "mood": "静谧", "best_for": ["风景", "氛围"],
    },

    # ==================== 复古系 (VINTAGE) ====================
    "vintage_sepia": {
        "name": "复古棕褐", "category": "vintage",
        "params": {"contrast": 0.85, "saturation": 0.4, "temperature": 15, "tint": 15, "grain": 0.05},
        "mood": "怀旧", "best_for": ["回忆", "老照片"],
    },
    "70s_film": {
        "name": "70年代胶片", "category": "vintage",
        "params": {"contrast": 0.8, "saturation": 0.6, "temperature": 10, "tint": 5, "grain": 0.04},
        "mood": "复古", "best_for": ["Vlog", "时尚"],
    },
    "polaroid": {
        "name": "宝丽来", "category": "vintage",
        "params": {"contrast": 0.9, "saturation": 0.75, "temperature": 5, "tint": 10},
        "mood": "复古清新", "best_for": ["生活", "旅行"],
    },
    "8mm_home_video": {
        "name": "8毫米家庭录像", "category": "vintage",
        "params": {"contrast": 0.7, "saturation": 0.5, "temperature": 8, "grain": 0.08, "vignette": 0.3},
        "mood": "怀旧", "best_for": ["回忆", "生活"],
    },
    "super8": {
        "name": "Super 8胶片", "category": "vintage",
        "params": {"contrast": 0.75, "saturation": 0.55, "temperature": 12, "grain": 0.06},
        "mood": "复古电影", "best_for": ["婚礼", "旅行"],
    },

    # ==================== 黑白系 (B&W) ====================
    "high_contrast_bw": {
        "name": "高对比黑白", "category": "bw",
        "params": {"contrast": 1.5, "saturation": 0, "temperature": 0},
        "mood": "经典", "best_for": ["人像", "街拍", "艺术"],
    },
    "soft_bw": {
        "name": "柔光黑白", "category": "bw",
        "params": {"contrast": 0.85, "saturation": 0, "temperature": 0, "brightness": 0.05},
        "mood": "柔和", "best_for": ["人像", "情绪"],
    },
    "selenium_tone": {
        "name": "硒色调", "category": "bw",
        "params": {"contrast": 1.1, "saturation": 0, "temperature": 5, "tint": 2},
        "mood": "古典", "best_for": ["艺术", "建筑"],
    },

    # ==================== 创意系 (CREATIVE) ====================
    "cyberpunk_neon": {
        "name": "赛博霓虹", "category": "creative",
        "params": {"contrast": 1.3, "saturation": 1.5, "temperature": -10, "tint": 8},
        "mood": "未来感", "best_for": ["科技", "游戏", "城市"],
    },
    "vaporwave": {
        "name": "蒸汽波", "category": "creative",
        "params": {"contrast": 1.1, "saturation": 1.4, "temperature": -5, "tint": 15},
        "mood": "复古未来", "best_for": ["音乐", "时尚", "创意"],
    },
    "glitch_core": {
        "name": "故障艺术", "category": "creative",
        "params": {"contrast": 1.4, "saturation": 1.3, "temperature": -8},
        "mood": "前卫", "best_for": ["音乐", "艺术", "实验"],
    },
    "retro_pop": {
        "name": "复古波普", "category": "creative",
        "params": {"contrast": 1.2, "saturation": 1.6, "temperature": 5},
        "mood": "活泼", "best_for": ["时尚", "社媒", "广告"],
    },
    "synthwave": {
        "name": "合成波", "category": "creative",
        "params": {"contrast": 1.25, "saturation": 1.35, "temperature": -3, "tint": 10},
        "mood": "80年代", "best_for": ["音乐", "游戏", "氛围"],
    },

    # ==================== 柔美系 (SOFT) ====================
    "pastel_dream": {
        "name": "粉彩梦境", "category": "soft",
        "params": {"contrast": 0.8, "saturation": 0.6, "temperature": 3, "brightness": 0.08},
        "mood": "梦幻", "best_for": ["女性", "美妆", "婚礼"],
    },
    "soft_blush": {
        "name": "柔粉腮红", "category": "soft",
        "params": {"contrast": 0.85, "saturation": 0.55, "temperature": 5, "tint": 5},
        "mood": "温柔", "best_for": ["美妆", "人像", "生活"],
    },
    "morning_dew": {
        "name": "晨露清新", "category": "soft",
        "params": {"contrast": 0.9, "saturation": 0.7, "temperature": 0, "brightness": 0.05},
        "mood": "清新", "best_for": ["自然", "生活", "Vlog"],
    },
    "ethereal": {
        "name": "空灵仙境", "category": "soft",
        "params": {"contrast": 0.7, "saturation": 0.4, "temperature": -2, "brightness": 0.1},
        "mood": "空灵", "best_for": ["风景", "艺术", "氛围"],
    },

    # ==================== 自然系 (NATURE) ====================
    "nature_vivid": {
        "name": "自然鲜艳", "category": "nature",
        "params": {"contrast": 1.15, "saturation": 1.3, "temperature": 2},
        "mood": "生机", "best_for": ["风景", "户外", "旅行"],
    },
    "forest_green": {
        "name": "森林绿意", "category": "nature",
        "params": {"contrast": 1.05, "saturation": 1.2, "temperature": 0, "tint": 8},
        "mood": "自然", "best_for": ["森林", "户外", "环保"],
    },
    "ocean_depth": {
        "name": "深海幽蓝", "category": "nature",
        "params": {"contrast": 1.15, "saturation": 1.1, "temperature": -8, "tint": -5},
        "mood": "深邃", "best_for": ["海洋", "水下", "旅行"],
    },
    "desert_dusk": {
        "name": "沙漠黄昏", "category": "nature",
        "params": {"contrast": 1.1, "saturation": 1.15, "temperature": 10, "tint": 8},
        "mood": "壮阔", "best_for": ["沙漠", "旅行", "冒险"],
    },

    # ==================== 美食系 (FOOD) ====================
    "food_warm": {
        "name": "美食暖调", "category": "food",
        "params": {"contrast": 1.1, "saturation": 1.25, "temperature": 8, "brightness": 0.03},
        "mood": "食欲", "best_for": ["美食", "探店", "烹饪"],
    },
    "bakery_fresh": {
        "name": "烘焙鲜香", "category": "food",
        "params": {"contrast": 1.0, "saturation": 1.1, "temperature": 12, "tint": 5},
        "mood": "甜蜜", "best_for": ["烘焙", "甜点", "咖啡"],
    },
    "japanese_cuisine": {
        "name": "日料雅致", "category": "food",
        "params": {"contrast": 0.95, "saturation": 0.9, "temperature": 3, "tint": -2},
        "mood": "精致", "best_for": ["日料", "美食", "探店"],
    },

    # ==================== 人像系 (PORTRAIT) ====================
    "portrait_soft": {
        "name": "人像柔肤", "category": "portrait",
        "params": {"contrast": 0.9, "saturation": 0.85, "temperature": 3, "brightness": 0.04},
        "mood": "柔美", "best_for": ["人像", "写真", "美妆"],
    },
    "fashion_editorial": {
        "name": "时尚大片", "category": "portrait",
        "params": {"contrast": 1.2, "saturation": 0.8, "temperature": -2},
        "mood": "高级", "best_for": ["时尚", "模特", "杂志"],
    },
    "street_portrait": {
        "name": "街头人像", "category": "portrait",
        "params": {"contrast": 1.15, "saturation": 1.0, "temperature": 0},
        "mood": "街头", "best_for": ["街拍", "潮流", "时尚"],
    },

    # ==================== 都市系 (URBAN) ====================
    "urban_grit": {
        "name": "都市硬朗", "category": "urban",
        "params": {"contrast": 1.3, "saturation": 0.9, "temperature": -5},
        "mood": "硬朗", "best_for": ["城市", "建筑", "街拍"],
    },
    "night_city": {
        "name": "夜色都市", "category": "urban",
        "params": {"contrast": 1.25, "saturation": 1.2, "temperature": -10, "tint": 3},
        "mood": "都市夜", "best_for": ["夜景", "城市", "氛围"],
    },
    "tokyo_drift": {
        "name": "东京漂移", "category": "urban",
        "params": {"contrast": 1.2, "saturation": 1.3, "temperature": -3, "tint": 8},
        "mood": "霓虹", "best_for": ["城市", "旅行", "氛围"],
    },

    # ==================== 旅行系 (TRAVEL) ====================
    "travel_bright": {
        "name": "旅行明快", "category": "travel",
        "params": {"contrast": 1.1, "saturation": 1.25, "temperature": 5},
        "mood": "快乐", "best_for": ["旅行", "Vlog", "户外"],
    },
    "tropical_vibe": {
        "name": "热带风情", "category": "travel",
        "params": {"contrast": 1.15, "saturation": 1.4, "temperature": 8, "tint": 5},
        "mood": "热情", "best_for": ["海岛", "度假", "旅行"],
    },
    "european_summer": {
        "name": "欧洲夏日", "category": "travel",
        "params": {"contrast": 1.05, "saturation": 1.15, "temperature": 5},
        "mood": "惬意", "best_for": ["欧洲", "旅行", "城市"],
    },

    # ==================== 恐怖系 (HORROR) ====================
    "horror_dark": {
        "name": "恐怖暗调", "category": "horror",
        "params": {"contrast": 1.2, "saturation": 0.3, "temperature": -15, "brightness": -0.1},
        "mood": "恐怖", "best_for": ["恐怖", "悬疑", "氛围"],
    },
    "found_footage": {
        "name": "伪纪录片", "category": "horror",
        "params": {"contrast": 1.1, "saturation": 0.4, "temperature": -5, "grain": 0.07},
        "mood": "不安", "best_for": ["恐怖", "实验"],
    },

    # ==================== 科幻系 (SCIFI) ====================
    "sci_fi_cool": {
        "name": "科幻冷调", "category": "scifi",
        "params": {"contrast": 1.2, "saturation": 0.85, "temperature": -15, "tint": -5},
        "mood": "未来", "best_for": ["科技", "科幻", "产品"],
    },
    "hologram": {
        "name": "全息投影", "category": "scifi",
        "params": {"contrast": 1.1, "saturation": 1.0, "temperature": -20, "tint": 10},
        "mood": "科幻", "best_for": ["科技", "产品", "游戏"],
    },

    # ==================== 纪录系 (DOCUMENTARY) ====================
    "documentary_neutral": {
        "name": "纪录中性", "category": "documentary",
        "params": {"contrast": 1.05, "saturation": 1.0, "temperature": 0},
        "mood": "客观", "best_for": ["纪录片", "新闻", "采访"],
    },
}

# ═══════════════════════════════════════════════════════════
# 便捷查询
# ═══════════════════════════════════════════════════════════

LUT_CATEGORIES = {
    "cinematic": "电影级", "warm": "温暖系", "cool": "清冷系",
    "vintage": "复古系", "bw": "黑白系", "creative": "创意系",
    "soft": "柔美系", "nature": "自然系", "food": "美食系",
    "portrait": "人像系", "urban": "都市系", "travel": "旅行系",
    "horror": "恐怖系", "scifi": "科幻系", "documentary": "纪录系",
}

LUT_MOODS = [
    "大片感", "史诗感", "悬疑", "震撼", "文艺",
    "温暖", "浪漫", "温馨", "亲密",
    "清冷", "冷静", "静谧",
    "怀旧", "复古清新", "复古电影",
    "经典", "柔和", "古典",
    "未来感", "复古未来", "前卫", "活泼", "80年代",
    "梦幻", "温柔", "清新", "空灵",
    "生机", "自然", "深邃", "壮阔",
    "食欲", "甜蜜", "精致",
    "柔美", "高级", "街头",
    "硬朗", "都市夜", "霓虹",
    "快乐", "热情", "惬意",
    "恐怖", "不安",
    "未来", "科幻",
    "客观",
]


def get_luts_by_category(category: str) -> list:
    """按类别获取 LUT"""
    return [
        {"id": k, **v}
        for k, v in FULL_LUT_LIBRARY.items()
        if v["category"] == category
    ]


def get_luts_by_mood(mood: str) -> list:
    """按情绪获取 LUT"""
    return [
        {"id": k, **v}
        for k, v in FULL_LUT_LIBRARY.items()
        if v.get("mood") == mood or mood.lower() in v.get("mood", "").lower()
    ]


def get_luts_by_best_for(use_case: str) -> list:
    """按适用场景获取 LUT"""
    return [
        {"id": k, **v}
        for k, v in FULL_LUT_LIBRARY.items()
        if any(use_case.lower() in u.lower() for u in v.get("best_for", []))
    ]


def list_all_luts() -> list:
    """列出所有 LUT"""
    return [{"id": k, **v} for k, v in FULL_LUT_LIBRARY.items()]


def list_categories() -> dict:
    """列出所有类别"""
    return LUT_CATEGORIES


def get_lut_params(lut_id: str) -> dict:
    """获取 LUT 的 ffmpeg 参数"""
    lut = FULL_LUT_LIBRARY.get(lut_id, {})
    return lut.get("params", {})
