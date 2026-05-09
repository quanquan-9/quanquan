"""冷启动模板库 — 18种预设风格模板"""

import json, logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ColdStartTemplate:
    name: str; style_tags: List[str]; voice_id: str = "default"
    transitions: List[str] = None; filters: List[str] = None
    bgm_genres: List[str] = None; subtitle_style: dict = None
    pace: str = "medium"; description: str = ""
    def __post_init__(self):
        self.transitions = self.transitions or ["dissolve"]
        self.filters = self.filters or ["original"]
        self.bgm_genres = self.bgm_genres or ["ambient"]
        self.subtitle_style = self.subtitle_style or {"font":"PingFang SC","size":32,"color":"#FFFFFF","outline_color":"#000000","outline_width":2}

COLD_START_TEMPLATES: Dict[str, ColdStartTemplate] = {
    "tech_explainer": ColdStartTemplate(name="科技解说",style_tags=["科技","解说","技术","产品","评测","数码","AI"],voice_id="clear_male_01",transitions=["smooth_cut","slide_left","dissolve"],filters=["modern_clean","tech_blue"],bgm_genres=["corporate","electronic","ambient"],pace="medium",description="科技产品评测、技术科普、AI话题"),
    "vlog_lifestyle": ColdStartTemplate(name="生活Vlog",style_tags=["vlog","生活","日常","旅行","美食","开箱","探店"],voice_id="warm_female_01",transitions=["dissolve","fade","zoom_in"],filters=["warm_sunshine","vintage_light"],bgm_genres=["acoustic","chill","lofi","indie"],pace="fast",description="日常Vlog、旅行记录、美食探店"),
    "cinematic_epic": ColdStartTemplate(name="电影感大片",style_tags=["电影","大片","宣传","品牌","高端","炫酷","赛博朋克"],voice_id="deep_male_03",transitions=["glitch_dissolve","flash","smooth_cut"],filters=["cyberpunk_purple","cinematic_teal"],bgm_genres=["epic","cinematic","trailer","orchestral"],pace="medium",description="品牌宣传片、电影感短片、赛博朋克风格"),
    "education_course": ColdStartTemplate(name="教育培训",style_tags=["教育","教程","课程","学习","知识","科普","讲座"],voice_id="clear_female_02",transitions=["smooth_cut","dissolve"],filters=["clean_white","soft_focus"],bgm_genres=["ambient","classical","piano"],pace="slow",description="在线课程、知识科普、教育培训"),
    "social_short": ColdStartTemplate(name="短视频快剪",style_tags=["短视频","抖音","快手","小红书","快节奏","卡点"],voice_id="energetic_male_02",transitions=["flash","slide_up","zoom_out","glitch"],filters=["vibrant_pop","high_contrast"],bgm_genres=["electronic","pop","hiphop","edm"],pace="fast",description="抖音快手短视频、卡点混剪"),
    "artistic_creative": ColdStartTemplate(name="艺术创意",style_tags=["艺术","创意","水墨","国风","文艺","摄影","视觉"],voice_id="gentle_female_03",transitions=["dissolve","fade","smooth_cut"],filters=["ink_wash","film_grain","vintage"],bgm_genres=["classical","jazz","ambient","world"],pace="slow",description="艺术展示、水墨国风、文艺创作"),
    "gaming_montage": ColdStartTemplate(name="游戏高光",style_tags=["游戏","电竞","高光","击杀","集锦","montage","LOL","吃鸡"],voice_id="energetic_male_02",transitions=["flash","glitch","zoom_in","slide_up"],filters=["cyberpunk_neon","high_contrast_bw"],bgm_genres=["electronic","dubstep","rock","trap"],subtitle_style={"font":"Impact","size":44,"color":"#FF4444","outline_width":3},pace="fast",description="游戏精彩集锦、击杀高光、电竞混剪"),
    "beauty_makeup": ColdStartTemplate(name="美妆时尚",style_tags=["美妆","化妆","护肤","穿搭","时尚","种草","测评"],voice_id="warm_female_01",transitions=["dissolve","zoom_in","slide_left"],filters=["soft_blush","portrait_soft"],bgm_genres=["pop","chill","lofi","rnb"],subtitle_style={"font":"PingFang SC","size":30,"color":"#FF69B4","outline_width":2},pace="medium",description="美妆教程、护肤分享、穿搭种草"),
    "sports_action": ColdStartTemplate(name="运动激情",style_tags=["运动","健身","篮球","足球","跑步","极限","户外"],voice_id="deep_male_03",transitions=["flash","slide_up","zoom_out","glitch"],filters=["travel_bright","nature_vivid"],bgm_genres=["rock","hiphop","electronic","epic"],subtitle_style={"font":"PingFang SC","size":38,"color":"#FF6600","outline_width":3},pace="fast",description="运动集锦、健身教程、极限运动"),
    "pet_animal": ColdStartTemplate(name="萌宠日常",style_tags=["宠物","猫","狗","萌宠","动物","可爱","猫咪"],voice_id="warm_female_01",transitions=["dissolve","fade","zoom_in"],filters=["pastel_dream","soft_blush"],bgm_genres=["acoustic","ukulele","lofi","indie"],subtitle_style={"font":"PingFang SC","size":32,"color":"#FFD700","outline_width":2},pace="medium",description="宠物日常、萌宠合集、可爱动物"),
    "wedding_love": ColdStartTemplate(name="婚礼爱情",style_tags=["婚礼","爱情","情侣","求婚","纪念","浪漫","甜蜜"],voice_id="gentle_female_03",transitions=["dissolve","fade","zoom_in"],filters=["golden_hour","pastel_dream"],bgm_genres=["piano","acoustic","classical","indie"],subtitle_style={"font":"PingFang SC","size":28,"color":"#FFB6C1","outline_width":1},pace="slow",description="婚礼视频、爱情纪念、情侣Vlog"),
    "business_presentation": ColdStartTemplate(name="商务演示",style_tags=["商务","企业","演示","PPT","汇报","年会","金融"],voice_id="clear_male_01",transitions=["smooth_cut","slide_left","dissolve"],filters=["documentary_neutral","modern_clean"],bgm_genres=["corporate","ambient","cinematic","piano"],pace="slow",description="企业宣传、商务演示、年会视频"),
    "car_automotive": ColdStartTemplate(name="汽车评测",style_tags=["汽车","赛车","车评","试驾","超跑","改装","摩托车"],voice_id="deep_male_03",transitions=["slide_right","zoom_in","flash"],filters=["urban_grit","cinematic_teal"],bgm_genres=["rock","electronic","cinematic","metal"],subtitle_style={"font":"PingFang SC","size":32,"color":"#FF4500","outline_width":2},pace="medium",description="汽车评测、试驾体验、赛车集锦"),
    "music_performance": ColdStartTemplate(name="音乐演出",style_tags=["音乐","演出","演唱会","乐器","弹奏","翻唱","DJ"],voice_id="clear_male_01",transitions=["flash","glitch","dissolve"],filters=["night_city","synthwave"],bgm_genres=["electronic","rock","pop","jazz"],subtitle_style={"font":"PingFang SC","size":36,"color":"#FF0080","outline_width":3},pace="fast",description="音乐演出、乐器演奏、翻唱视频"),
    "health_medical": ColdStartTemplate(name="健康医疗",style_tags=["健康","医疗","养生","中医","心理","科普","医院"],voice_id="clear_female_02",transitions=["dissolve","fade","smooth_cut"],filters=["documentary_neutral","morning_dew"],bgm_genres=["ambient","classical","piano","chill"],pace="slow",description="健康科普、医疗知识、养生内容"),
    "kids_education": ColdStartTemplate(name="儿童教育",style_tags=["儿童","早教","动画","绘本","儿歌","启蒙","亲子"],voice_id="warm_female_01",transitions=["zoom_in","dissolve","slide_left"],filters=["pastel_dream","retro_pop"],bgm_genres=["children","acoustic","ukulele","pop"],subtitle_style={"font":"PingFang SC","size":36,"color":"#FF69B4","outline_width":2},pace="slow",description="儿童教育、早教动画、亲子内容"),
    "real_estate": ColdStartTemplate(name="房产看房",style_tags=["房产","看房","楼盘","装修","家居","室内","样板间"],voice_id="clear_female_02",transitions=["slide_left","zoom_in","dissolve"],filters=["documentary_neutral","portrait_soft"],bgm_genres=["corporate","ambient","piano","chill"],pace="medium",description="房产看房、装修展示、家居介绍"),
    "comedy_fun": ColdStartTemplate(name="搞笑娱乐",style_tags=["搞笑","娱乐","段子","整蛊","挑战","沙雕","鬼畜"],voice_id="energetic_male_02",transitions=["glitch","zoom_in","flash","slide_up"],filters=["retro_pop","vaporwave"],bgm_genres=["electronic","funk","pop","comedy"],subtitle_style={"font":"PingFang SC","size":42,"color":"#FFFF00","outline_width":3},pace="fast",description="搞笑段子、娱乐整蛊、鬼畜视频"),
}

class ColdStartMatcher:
    @staticmethod
    def match(intent_tags: List[str]) -> ColdStartTemplate:
        if not intent_tags: return COLD_START_TEMPLATES["tech_explainer"]
        best, best_score = None, 0
        for t in COLD_START_TEMPLATES.values():
            score = sum(1 for tag in intent_tags for st in t.style_tags if tag.lower() in st.lower() or st.lower() in tag.lower())
            if score > best_score: best_score, best = score, t
        return best or COLD_START_TEMPLATES["tech_explainer"]

    @staticmethod
    def match_by_style(style_name: str) -> Optional[ColdStartTemplate]:
        sl = style_name.lower()
        for t in COLD_START_TEMPLATES.values():
            if t.name.lower() == sl or any(sl in tag.lower() for tag in t.style_tags): return t
        return None

    @staticmethod
    def list_all() -> List[ColdStartTemplate]: return list(COLD_START_TEMPLATES.values())

    @staticmethod
    def list_names() -> List[str]: return [t.name for t in COLD_START_TEMPLATES.values()]

    @staticmethod
    def get_template_dict(template: ColdStartTemplate) -> dict:
        return {"is_cold_start":True,"preferred_voice_id":template.voice_id,"preferred_transitions":template.transitions,"preferred_filters":template.filters,"preferred_bgm_genres":template.bgm_genres,"preferred_subtitle_style":template.subtitle_style,"preferred_pace":template.pace,"template_name":template.name}
