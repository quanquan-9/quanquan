"""
调色与风格化 Agent — 50+ 风格完整映射

每个风格对应 LUT、配色、情绪、字幕偏好等全链路参数
"""
import asyncio, json, logging
from typing import Dict, Any, Optional, List

from core.types import StylizationResult

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 50+ 完整风格映射
# ═══════════════════════════════════════════════════════════
STYLE_MAP: Dict[str, dict] = {
    # ── 电影级 ──
    "cinematic_teal": {"name":"电影青橙","lut":"cinematic_teal","colors":["#FF8C42","#3AADA8"],"mood":"大片感","category":"cinematic","contrast":1.2,"saturation":1.1,"temp":-5,"transition":"dissolve","bgm":"cinematic","pace":"medium","voice":"deep_male_03","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":32},
    "cinematic_gold": {"name":"电影金调","lut":"cinematic_gold","colors":["#DAA520","#8B4513"],"mood":"史诗感","category":"cinematic","contrast":1.15,"saturation":1.05,"temp":8,"transition":"smooth_cut","bgm":"cinematic","pace":"medium","voice":"deep_male_03","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":32},
    "cinematic_noir": {"name":"黑色电影","lut":"cinematic_noir","colors":["#1a1a1a","#c0c0c0"],"mood":"悬疑","category":"cinematic","contrast":1.5,"saturation":0.3,"temp":-15,"transition":"fade","bgm":"suspense","pace":"slow","voice":"deep_male_03","subtitle_font":"Georgia","subtitle_color":"#FFFFFF","subtitle_size":28},
    "blockbuster": {"name":"好莱坞大片","lut":"blockbuster","colors":["#FF4500","#1E90FF"],"mood":"震撼","category":"cinematic","contrast":1.25,"saturation":1.3,"temp":-2,"transition":"flash","bgm":"epic","pace":"fast","voice":"deep_male_03","subtitle_font":"Impact","subtitle_color":"#FF4500","subtitle_size":40},
    "indie_film": {"name":"独立电影","lut":"indie_film","colors":["#D2B48C","#556B2F"],"mood":"文艺","category":"cinematic","contrast":1.0,"saturation":0.7,"temp":5,"transition":"dissolve","bgm":"indie","pace":"slow","voice":"gentle_female_03","subtitle_font":"KaiTi","subtitle_color":"#E8D5B7","subtitle_size":28},

    # ── 创意 ──
    "cyberpunk": {"name":"赛博朋克","lut":"cyberpunk_neon","colors":["#7B2FBE","#00FFFF","#FF006E"],"mood":"未来感","category":"creative","contrast":1.3,"saturation":1.5,"temp":-10,"transition":"glitch","bgm":"electronic","pace":"fast","voice":"energetic_male_02","subtitle_font":"Impact","subtitle_color":"#00FFFF","subtitle_size":40},
    "vaporwave": {"name":"蒸汽波","lut":"vaporwave","colors":["#FF71CE","#01CDFE","#B967FF"],"mood":"复古未来","category":"creative","contrast":1.1,"saturation":1.4,"temp":-5,"transition":"glitch","bgm":"electronic","pace":"fast","voice":"warm_female_01","subtitle_font":"Comic Sans MS","subtitle_color":"#FF71CE","subtitle_size":36},
    "glitch_core": {"name":"故障艺术","lut":"glitch_core","colors":["#FF0000","#00FF00","#0000FF"],"mood":"前卫","category":"creative","contrast":1.4,"saturation":1.3,"temp":-8,"transition":"glitch","bgm":"industrial","pace":"fast","voice":"energetic_male_02","subtitle_font":"Courier New","subtitle_color":"#00FF00","subtitle_size":38},
    "retro_pop": {"name":"复古波普","lut":"retro_pop","colors":["#FF1493","#FFD700","#00BFFF"],"mood":"活泼","category":"creative","contrast":1.2,"saturation":1.6,"temp":5,"transition":"zoom_in","bgm":"pop","pace":"fast","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#FF1493","subtitle_size":36},
    "synthwave": {"name":"合成波","lut":"synthwave","colors":["#FF007F","#7B2FBE","#00FFFF"],"mood":"80年代","category":"creative","contrast":1.25,"saturation":1.35,"temp":-3,"transition":"slide_up","bgm":"electronic","pace":"fast","voice":"energetic_male_02","subtitle_font":"Impact","subtitle_color":"#FF007F","subtitle_size":40},

    # ── 国风 ──
    "ink_wash": {"name":"水墨国风","lut":"ink_wash","colors":["#1a1a1a","#4a4a4a","#8a8a8a"],"mood":"古典雅致","category":"chinese","contrast":0.9,"saturation":0.3,"temp":5,"transition":"dissolve","bgm":"classical","pace":"slow","voice":"gentle_female_03","subtitle_font":"KaiTi","subtitle_color":"#1a1a1a","subtitle_size":28},
    "chinese_red": {"name":"中国红","lut":"chinese_red","colors":["#DE2910","#FFD700"],"mood":"喜庆","category":"chinese","contrast":1.1,"saturation":1.2,"temp":8,"transition":"slide_left","bgm":"world","pace":"medium","voice":"clear_female_02","subtitle_font":"KaiTi","subtitle_color":"#FFD700","subtitle_size":32},
    "porcelain": {"name":"青花瓷","lut":"porcelain","colors":["#0047AB","#FFFFFF"],"mood":"典雅","category":"chinese","contrast":1.05,"saturation":0.9,"temp":-3,"transition":"fade","bgm":"classical","pace":"slow","voice":"gentle_female_03","subtitle_font":"KaiTi","subtitle_color":"#0047AB","subtitle_size":28},
    "dunhuang": {"name":"敦煌壁画","lut":"dunhuang","colors":["#CD853F","#DAA520","#20B2AA"],"mood":"瑰丽","category":"chinese","contrast":1.1,"saturation":1.15,"temp":5,"transition":"dissolve","bgm":"world","pace":"slow","voice":"gentle_female_03","subtitle_font":"KaiTi","subtitle_color":"#DAA520","subtitle_size":30},

    # ── 复古 ──
    "vintage_film": {"name":"复古胶片","lut":"vintage_film","colors":["#C8A96E","#6B4C3B"],"mood":"怀旧","category":"vintage","contrast":0.85,"saturation":0.7,"temp":15,"transition":"fade","bgm":"jazz","pace":"slow","voice":"clear_male_01","subtitle_font":"Georgia","subtitle_color":"#C8A96E","subtitle_size":28},
    "vintage_sepia": {"name":"复古棕褐","lut":"vintage_sepia","colors":["#704214","#C49A6C"],"mood":"怀旧","category":"vintage","contrast":0.85,"saturation":0.4,"temp":15,"transition":"fade","bgm":"jazz","pace":"slow","voice":"clear_male_01","subtitle_font":"Georgia","subtitle_color":"#C49A6C","subtitle_size":28},
    "70s_film": {"name":"70年代胶片","lut":"70s_film","colors":["#DAA520","#8B0000"],"mood":"复古","category":"vintage","contrast":0.8,"saturation":0.6,"temp":10,"transition":"dissolve","bgm":"funk","pace":"slow","voice":"clear_male_01","subtitle_font":"Courier New","subtitle_color":"#DAA520","subtitle_size":26},
    "8mm_home_video": {"name":"8毫米家庭录像","lut":"8mm_home_video","colors":["#FFDAB9","#8B4513"],"mood":"怀旧","category":"vintage","contrast":0.7,"saturation":0.5,"temp":8,"transition":"fade","bgm":"acoustic","pace":"slow","voice":"warm_female_01","subtitle_font":"Georgia","subtitle_color":"#FFDAB9","subtitle_size":26},
    "super8": {"name":"Super 8胶片","lut":"super8","colors":["#DEB887","#A0522D"],"mood":"复古电影","category":"vintage","contrast":0.75,"saturation":0.55,"temp":12,"transition":"fade","bgm":"indie","pace":"slow","voice":"warm_female_01","subtitle_font":"Georgia","subtitle_color":"#DEB887","subtitle_size":26},

    # ── 二次元 ──
    "anime": {"name":"二次元","lut":"anime","colors":["#FF69B4","#4ECDC4","#FFE66D"],"mood":"活泼","category":"anime","contrast":1.15,"saturation":1.4,"temp":-5,"transition":"zoom_in","bgm":"anime","pace":"fast","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#FF69B4","subtitle_size":34},
    "ghibli": {"name":"吉卜力","lut":"ghibli","colors":["#87CEEB","#98FB98","#FFD700"],"mood":"治愈","category":"anime","contrast":1.0,"saturation":1.2,"temp":3,"transition":"dissolve","bgm":"piano","pace":"slow","voice":"gentle_female_03","subtitle_font":"PingFang SC","subtitle_color":"#2E8B57","subtitle_size":30},
    "manga": {"name":"漫画风","lut":"manga","colors":["#000000","#FFFFFF","#FF0000"],"mood":"热血","category":"anime","contrast":1.3,"saturation":1.1,"temp":0,"transition":"slide_up","bgm":"rock","pace":"fast","voice":"energetic_male_02","subtitle_font":"Impact","subtitle_color":"#FF0000","subtitle_size":38},
    "pixel_art": {"name":"像素风","lut":"pixel_art","colors":["#00FF00","#FF00FF","#00FFFF"],"mood":"复古游戏","category":"anime","contrast":1.2,"saturation":1.3,"temp":-5,"transition":"pixelate","bgm":"chiptune","pace":"fast","voice":"energetic_male_02","subtitle_font":"Courier New","subtitle_color":"#00FF00","subtitle_size":34},

    # ── 现代 ──
    "modern": {"name":"现代简约","lut":"modern","colors":["#FFFFFF","#333333","#2196F3"],"mood":"干净","category":"modern","contrast":1.05,"saturation":1.0,"temp":0,"transition":"smooth_cut","bgm":"corporate","pace":"medium","voice":"clear_male_01","subtitle_font":"PingFang SC","subtitle_color":"#FFFFFF","subtitle_size":30},
    "minimal_bw": {"name":"极简黑白","lut":"minimal_bw","colors":["#000000","#FFFFFF"],"mood":"极简","category":"modern","contrast":1.1,"saturation":0,"temp":0,"transition":"smooth_cut","bgm":"ambient","pace":"slow","voice":"clear_female_02","subtitle_font":"Helvetica","subtitle_color":"#FFFFFF","subtitle_size":28},
    "apple_style": {"name":"Apple风","lut":"apple_style","colors":["#F5F5F7","#1D1D1F","#0071E3"],"mood":"高级","category":"modern","contrast":1.05,"saturation":1.0,"temp":-2,"transition":"smooth_cut","bgm":"corporate","pace":"medium","voice":"clear_male_01","subtitle_font":"SF Pro","subtitle_color":"#1D1D1F","subtitle_size":30},

    # ── 温暖 ──
    "warm_sunset": {"name":"温暖日落","lut":"warm_sunset","colors":["#FF7F50","#FFD700"],"mood":"温暖","category":"warm","contrast":1.1,"saturation":1.15,"temp":12,"transition":"dissolve","bgm":"acoustic","pace":"medium","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":32},
    "golden_hour": {"name":"黄金时刻","lut":"golden_hour","colors":["#FFD700","#FFA500"],"mood":"浪漫","category":"warm","contrast":1.05,"saturation":1.1,"temp":15,"transition":"dissolve","bgm":"acoustic","pace":"slow","voice":"gentle_female_03","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":30},
    "autumn_glow": {"name":"秋日暖阳","lut":"autumn_glow","colors":["#FF8C00","#8B4513"],"mood":"温馨","category":"warm","contrast":1.08,"saturation":1.2,"temp":10,"transition":"dissolve","bgm":"indie","pace":"medium","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#FF8C00","subtitle_size":30},
    "soft_blush": {"name":"柔粉腮红","lut":"soft_blush","colors":["#FFB6C1","#FF69B4"],"mood":"温柔","category":"soft","contrast":0.85,"saturation":0.55,"temp":5,"transition":"dissolve","bgm":"chill","pace":"slow","voice":"gentle_female_03","subtitle_font":"PingFang SC","subtitle_color":"#FF69B4","subtitle_size":28},
    "pastel_dream": {"name":"粉彩梦境","lut":"pastel_dream","colors":["#FFB6C1","#87CEEB","#DDA0DD"],"mood":"梦幻","category":"soft","contrast":0.8,"saturation":0.6,"temp":3,"transition":"fade","bgm":"lofi","pace":"slow","voice":"gentle_female_03","subtitle_font":"PingFang SC","subtitle_color":"#DDA0DD","subtitle_size":28},

    # ── 清冷 ──
    "cool_moonlight": {"name":"清冷月光","lut":"cool_moonlight","colors":["#1E90FF","#483D8B"],"mood":"清冷","category":"cool","contrast":1.1,"saturation":0.9,"temp":-12,"transition":"dissolve","bgm":"ambient","pace":"slow","voice":"clear_female_02","subtitle_font":"PingFang SC","subtitle_color":"#87CEEB","subtitle_size":28},
    "arctic_blue": {"name":"极地冰蓝","lut":"arctic_blue","colors":["#00CED1","#E0FFFF"],"mood":"冷静","category":"cool","contrast":1.15,"saturation":0.8,"temp":-20,"transition":"smooth_cut","bgm":"ambient","pace":"medium","voice":"clear_female_02","subtitle_font":"PingFang SC","subtitle_color":"#E0FFFF","subtitle_size":28},
    "documentary_neutral": {"name":"纪录中性","lut":"documentary_neutral","colors":["#808080","#F5F5DC"],"mood":"客观","category":"documentary","contrast":1.05,"saturation":1.0,"temp":0,"transition":"smooth_cut","bgm":"ambient","pace":"slow","voice":"clear_male_01","subtitle_font":"PingFang SC","subtitle_color":"#FFFFFF","subtitle_size":28},

    # ── 美食 ──
    "food_warm": {"name":"美食暖调","lut":"food_warm","colors":["#FF6347","#FFD700"],"mood":"食欲","category":"food","contrast":1.1,"saturation":1.25,"temp":8,"transition":"zoom_in","bgm":"chill","pace":"medium","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":30},
    "bakery_fresh": {"name":"烘焙鲜香","lut":"bakery_fresh","colors":["#DEB887","#FFF8DC"],"mood":"甜蜜","category":"food","contrast":1.0,"saturation":1.1,"temp":12,"transition":"dissolve","bgm":"acoustic","pace":"slow","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#DEB887","subtitle_size":28},
    "japanese_cuisine": {"name":"日料雅致","lut":"japanese_cuisine","colors":["#8B0000","#F5DEB3"],"mood":"精致","category":"food","contrast":0.95,"saturation":0.9,"temp":3,"transition":"dissolve","bgm":"jazz","pace":"slow","voice":"clear_female_02","subtitle_font":"PingFang SC","subtitle_color":"#F5DEB3","subtitle_size":28},

    # ── 城市 ──
    "urban_grit": {"name":"都市硬朗","lut":"urban_grit","colors":["#2F4F4F","#A9A9A9"],"mood":"硬朗","category":"urban","contrast":1.3,"saturation":0.9,"temp":-5,"transition":"slide_right","bgm":"rock","pace":"fast","voice":"deep_male_03","subtitle_font":"PingFang SC","subtitle_color":"#A9A9A9","subtitle_size":32},
    "night_city": {"name":"夜色都市","lut":"night_city","colors":["#191970","#FFD700"],"mood":"都市夜","category":"urban","contrast":1.25,"saturation":1.2,"temp":-10,"transition":"fade","bgm":"electronic","pace":"medium","voice":"clear_male_01","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":32},
    "tokyo_drift": {"name":"东京漂移","lut":"tokyo_drift","colors":["#FF1493","#00FFFF"],"mood":"霓虹","category":"urban","contrast":1.2,"saturation":1.3,"temp":-3,"transition":"glitch","bgm":"electronic","pace":"fast","voice":"energetic_male_02","subtitle_font":"Impact","subtitle_color":"#FF1493","subtitle_size":36},

    # ── 旅行 ──
    "travel_bright": {"name":"旅行明快","lut":"travel_bright","colors":["#00BFFF","#FFD700"],"mood":"快乐","category":"travel","contrast":1.1,"saturation":1.25,"temp":5,"transition":"slide_left","bgm":"pop","pace":"fast","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":32},
    "tropical_vibe": {"name":"热带风情","lut":"tropical_vibe","colors":["#FF4500","#32CD32"],"mood":"热情","category":"travel","contrast":1.15,"saturation":1.4,"temp":8,"transition":"dissolve","bgm":"reggae","pace":"fast","voice":"warm_female_01","subtitle_font":"PingFang SC","subtitle_color":"#FF4500","subtitle_size":32},
    "european_summer": {"name":"欧洲夏日","lut":"european_summer","colors":["#87CEEB","#FFE4B5"],"mood":"惬意","category":"travel","contrast":1.05,"saturation":1.15,"temp":5,"transition":"dissolve","bgm":"indie","pace":"medium","voice":"clear_female_02","subtitle_font":"PingFang SC","subtitle_color":"#87CEEB","subtitle_size":30},

    # ── 自然 ──
    "nature_vivid": {"name":"自然鲜艳","lut":"nature_vivid","colors":["#228B22","#87CEEB"],"mood":"生机","category":"nature","contrast":1.15,"saturation":1.3,"temp":2,"transition":"dissolve","bgm":"ambient","pace":"medium","voice":"clear_female_02","subtitle_font":"PingFang SC","subtitle_color":"#FFFFFF","subtitle_size":30},
    "forest_green": {"name":"森林绿意","lut":"forest_green","colors":["#006400","#8FBC8F"],"mood":"自然","category":"nature","contrast":1.05,"saturation":1.2,"temp":0,"transition":"dissolve","bgm":"ambient","pace":"slow","voice":"clear_female_02","subtitle_font":"PingFang SC","subtitle_color":"#8FBC8F","subtitle_size":28},
    "ocean_depth": {"name":"深海幽蓝","lut":"ocean_depth","colors":["#000080","#00CED1"],"mood":"深邃","category":"nature","contrast":1.15,"saturation":1.1,"temp":-8,"transition":"fade","bgm":"ambient","pace":"slow","voice":"deep_male_03","subtitle_font":"PingFang SC","subtitle_color":"#00CED1","subtitle_size":28},
    "desert_dusk": {"name":"沙漠黄昏","lut":"desert_dusk","colors":["#D2691E","#FFD700"],"mood":"壮阔","category":"nature","contrast":1.1,"saturation":1.15,"temp":10,"transition":"dissolve","bgm":"world","pace":"slow","voice":"deep_male_03","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":30},

    # ── 人像 ──
    "portrait_soft": {"name":"人像柔肤","lut":"portrait_soft","colors":["#FFE4E1","#FFB6C1"],"mood":"柔美","category":"portrait","contrast":0.9,"saturation":0.85,"temp":3,"transition":"dissolve","bgm":"chill","pace":"slow","voice":"gentle_female_03","subtitle_font":"PingFang SC","subtitle_color":"#FFB6C1","subtitle_size":28},
    "fashion_editorial": {"name":"时尚大片","lut":"fashion_editorial","colors":["#000000","#FF4500"],"mood":"高级","category":"portrait","contrast":1.2,"saturation":0.8,"temp":-2,"transition":"flash","bgm":"electronic","pace":"medium","voice":"clear_female_02","subtitle_font":"Helvetica","subtitle_color":"#FFFFFF","subtitle_size":30},
    "street_portrait": {"name":"街头人像","lut":"street_portrait","colors":["#2F4F4F","#FF6347"],"mood":"街头","category":"portrait","contrast":1.15,"saturation":1.0,"temp":0,"transition":"slide_up","bgm":"hiphop","pace":"medium","voice":"clear_male_01","subtitle_font":"PingFang SC","subtitle_color":"#FF6347","subtitle_size":30},

    # ── 特殊 ──
    "sci_fi_cool": {"name":"科幻冷调","lut":"sci_fi_cool","colors":["#00CED1","#7B68EE"],"mood":"未来","category":"scifi","contrast":1.2,"saturation":0.85,"temp":-15,"transition":"glitch","bgm":"electronic","pace":"medium","voice":"clear_male_01","subtitle_font":"Courier New","subtitle_color":"#00CED1","subtitle_size":30},
    "horror_dark": {"name":"恐怖暗调","lut":"horror_dark","colors":["#2F0000","#4a0000"],"mood":"恐怖","category":"horror","contrast":1.2,"saturation":0.3,"temp":-15,"transition":"fade","bgm":"dark_ambient","pace":"slow","voice":"deep_male_03","subtitle_font":"Georgia","subtitle_color":"#FF0000","subtitle_size":26},
    "wedding_love": {"name":"婚礼爱情","lut":"wedding_love","colors":["#FFE4E1","#FFD700"],"mood":"浪漫","category":"wedding","contrast":1.0,"saturation":1.0,"temp":5,"transition":"dissolve","bgm":"piano","pace":"slow","voice":"gentle_female_03","subtitle_font":"PingFang SC","subtitle_color":"#FFD700","subtitle_size":28},
    "kids_cartoon": {"name":"儿童卡通","lut":"kids_cartoon","colors":["#FF69B4","#87CEEB","#98FB98"],"mood":"童趣","category":"kids","contrast":1.0,"saturation":1.3,"temp":3,"transition":"zoom_in","bgm":"children","pace":"slow","voice":"warm_female_01","subtitle_font":"Comic Sans MS","subtitle_color":"#FF69B4","subtitle_size":34},
    "sports_action": {"name":"运动激情","lut":"sports_action","colors":["#FF4500","#FFD700"],"mood":"热血","category":"sports","contrast":1.25,"saturation":1.2,"temp":0,"transition":"flash","bgm":"rock","pace":"fast","voice":"deep_male_03","subtitle_font":"Impact","subtitle_color":"#FF4500","subtitle_size":38},
    "music_performance": {"name":"音乐演出","lut":"music_performance","colors":["#FF0080","#00FFFF"],"mood":"激情","category":"music","contrast":1.3,"saturation":1.35,"temp":-5,"transition":"flash","bgm":"rock","pace":"fast","voice":"energetic_male_02","subtitle_font":"Impact","subtitle_color":"#FF0080","subtitle_size":40},
    "game_style": {"name":"游戏电竞","lut":"game_style","colors":["#FF0000","#00FF00","#0000FF"],"mood":"热血","category":"gaming","contrast":1.3,"saturation":1.4,"temp":-5,"transition":"glitch","bgm":"dubstep","pace":"fast","voice":"energetic_male_02","subtitle_font":"Impact","subtitle_color":"#FF0000","subtitle_size":42},
    "auto": {"name":"自动检测","lut":"auto","colors":["auto"],"mood":"auto","category":"auto","contrast":1.0,"saturation":1.0,"temp":0,"transition":"dissolve","bgm":"auto","pace":"medium","voice":"default","subtitle_font":"PingFang SC","subtitle_color":"#FFFFFF","subtitle_size":32},
}

STYLE_CATEGORIES = {
    "cinematic":"电影级","creative":"创意风格","chinese":"国风雅韵","vintage":"复古记忆",
    "anime":"二次元","modern":"现代简约","warm":"温暖柔情","soft":"温柔梦幻",
    "cool":"清冷高级","food":"美食美物","urban":"城市探索","travel":"旅行冒险",
    "nature":"自然风光","portrait":"人物肖像","scifi":"科幻未来","horror":"恐怖悬疑",
    "wedding":"婚礼爱情","kids":"儿童亲子","sports":"运动激情","music":"音乐演出","gaming":"游戏电竞",
    "auto":"自动检测","documentary":"纪录纪实",
}


def get_style(style_id: str) -> dict:
    """获取风格完整参数"""
    return STYLE_MAP.get(style_id, STYLE_MAP.get("auto", {}))


def list_styles(category: str = "") -> list:
    """列出所有风格"""
    styles = []
    for sid, info in STYLE_MAP.items():
        if sid == "auto": continue
        if category and info.get("category") != category: continue
        styles.append({"id": sid, "name": info["name"], "category": info.get("category",""),
                       "mood": info.get("mood",""), "colors": info.get("colors",[])})
    return styles


def list_categories_all() -> dict:
    """列出所有风格类别"""
    return STYLE_CATEGORIES


class StylizationAgent:
    """调色/风格化 Agent"""

    def __init__(self, context_bus=None, artifact_store=None, config: dict = None):
        self.bus = context_bus
        self.artifacts = artifact_store
        self.config = config or {}
        self.state = "IDLE"

    async def run(self):
        while True:
            event = await self.bus.wait_for('TASK_DISPATCH',
                filter=lambda e: e.payload.get('agent') in ('StylizationColorGrading','Styling'))
            await self._handle(event)

    async def _handle(self, event):
        task = event.payload
        style_id = task.get('input', {}).get('style', 'auto')
        style = get_style(style_id)
        result = {"style_id": style_id, **style, "applied": True}
        ref = await self.artifacts.put(task['project_id'], task['output_key'], result)
        await self.bus.publish('RESULT_PUBLISH', {'node_id': task['node_id'], 'output_key': task['output_key'], 'artifact_ref': ref})

    async def apply(self, storyboard: dict = None, style_id: str = "auto", **kwargs) -> 'StylizationResult':
        """应用风格化调色，返回 StylizationResult TypedDict"""
        return {"style_id": style_id, **get_style(style_id), "applied": True}


stylization = StylizationAgent()
