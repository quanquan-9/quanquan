"""
StoryboardAgent 2.0 — AI 专业分镜师
多轮精炼 · 色调方案 · 构图细节 · 转场图谱 · CTA建议
"""
import json
import logging
from core.llm_client import llm
from core.types import Storyboard, Shot as ShotType

logger = logging.getLogger("quanquan.storyboard")

# ── Shot composition presets ──────────────────────────────────────────
COMPOSITION_TYPES = [
    "extreme-wide",      # 极远景 — 展示宏大环境
    "wide",              # 远景 — 人物与环境关系
    "full",              # 全景 — 人物全身
    "medium-wide",       # 中远景
    "medium",            # 中景 — 腰部以上
    "medium-close",      # 近景 — 胸部以上
    "close-up",          # 特写 — 面部/细节
    "extreme-close-up",  # 大特写 — 眼睛/关键物体
    "aerial",            # 航拍俯视
    "dutch-angle",       # 斜角 — 不安/动感
    "over-shoulder",     # 过肩镜头
    "pov",               # 主观视角
    "tracking",          # 跟拍
    "static",            # 静态固定
]

MOTION_TYPES = [
    "static", "pan_left", "pan_right", "tilt_up", "tilt_down",
    "zoom_in", "zoom_out", "dolly_in", "dolly_out",
    "track_left", "track_right", "crane_up", "crane_down",
    "drone_forward", "drone_orbit", "handheld", "steadicam",
]

TRANSITION_TYPES = [
    "cut", "dissolve", "fade_in", "fade_out", "fade_to_black",
    "fade_to_white", "wipe_left", "wipe_right", "slide_left",
    "slide_right", "zoom_transition", "match_cut", "j_cut",
    "l_cut", "smash_cut", "invisible_cut", "glitch", "flash",
]

TEXT_POSITIONS = [
    "bottom-center", "bottom-left", "bottom-right",
    "top-center", "top-left", "top-right",
    "center", "lower-third",
]

CTA_TYPES = [
    "subscribe", "like", "comment", "share", "follow",
    "click_link", "watch_next", "join_membership", "bell",
]


class StoryboardAgent:
    """StoryboardAgent 3.0 — CoT推理 + 多模型投票 + 上下文记忆

    核心能力：
    - 多轮精炼：初始方案 → 视觉一致性检查 → 精修
    - 每场景独立色调方案（hex色值 + 设计理由）
    - 镜头构图细节 + 摄像机运动曲线
    - 转场图谱：镜头间视觉衔接关系
    - 素材关键词提取（适配素材库搜索）
    - 文字叠加时机与位置建议
    - 行动号召（CTA）建议
    - 兼容旧版 plan() 接口 + 新增 plan_short() 竖屏短内容
    """

    # ── Agent Capabilities (3.0) ──
    AGENT_CAPABILITIES = {
        "name": "StoryboardAgent",
        "version": "3.0",
        "description": "AI分镜师 — 专业影视分镜方案生成",
        "capabilities": [
            "storyboard_planning",      # 横屏分镜方案
            "short_form_storyboard",    # 竖屏短视频分镜
            "shot_composition",         # 镜头构图设计
            "color_palette_design",     # 独立色调方案
            "camera_motion_curve",      # 摄像机运动曲线
            "transition_graph",         # 转场图谱
            "material_keywords",        # 素材搜索关键词
            "text_overlay_timing",      # 文字叠加时机
            "cta_suggestions",          # 行动号召建议
            "visual_coherence_check",   # 视觉一致性审核
            "cot_reasoning",            # Chain-of-Thought推理
            "multi_model_voting",       # 多模型投票
            "self_critique",            # 自我批判改进
            "context_memory",           # 项目历史感知
        ],
        "input_formats": ["script_json", "style_tags", "platform"],
        "output_formats": ["storyboard_json", "shots", "timeline", "transition_graph"],
        "supported_platforms": ["douyin", "tiktok", "reels", "kuaishou", "horizontal"],
    }

    # ── Shot composition presets (unchanged from 2.0) ──
    SHOT_SCHEMA = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "scene_id": {"type": "integer"},
            "start_sec": {"type": "number"},
            "end_sec": {"type": "number"},
            "duration_sec": {"type": "number"},
            "description": {"type": "string", "description": "镜头画面描述（画面内容、氛围、动作）"},
            "composition": {"type": "string",
                            "enum": COMPOSITION_TYPES,
                            "description": "构图类型"},
            "composition_detail": {"type": "string",
                                   "description": "构图详细说明：主体位置、景深、视角、画面层次"},
            "camera_movement": {
                "type": "object",
                "properties": {
                    "primary": {"type": "string", "enum": MOTION_TYPES},
                    "curve": {"type": "string",
                              "description": "运动曲线描述，如：0s静止 → 1s缓入右摇 → 2s加速 → 3s缓出停止"},
                    "keyframes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "t_sec": {"type": "number"},
                                "position": {"type": "string", "description": "画面位置/构图"},
                                "speed": {"type": "string", "enum": ["ease-in", "ease-out", "linear", "hold"]},
                            }
                        }
                    }
                }
            },
            "color_palette": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hex": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                        "name": {"type": "string", "description": "颜色名称（中文）"},
                        "role": {"type": "string",
                                 "enum": ["primary", "secondary", "accent", "background", "text", "highlight"]},
                        "rationale": {"type": "string", "description": "选择此颜色的设计理由"},
                    }
                },
                "minItems": 3,
                "maxItems": 8,
            },
            "transition_in": {"type": "string", "enum": TRANSITION_TYPES},
            "transition_out": {"type": "string", "enum": TRANSITION_TYPES},
            "material_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "素材搜索关键词（英文 + 中文）",
                "minItems": 3,
            },
            "text_overlays": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "position": {"type": "string", "enum": TEXT_POSITIONS},
                        "start_sec": {"type": "number"},
                        "end_sec": {"type": "number"},
                        "font_style": {"type": "string", "enum": ["bold", "regular", "light", "handwriting"]},
                        "animation": {"type": "string", "enum": ["fade", "slide_up", "typewriter", "pop", "none"]},
                    }
                }
            },
            "call_to_action": {
                "type": "object",
                "nullable": True,
                "properties": {
                    "type": {"type": "string", "enum": CTA_TYPES},
                    "text": {"type": "string"},
                    "position": {"type": "string", "enum": TEXT_POSITIONS},
                    "start_sec": {"type": "number"},
                    "animation": {"type": "string"},
                }
            },
            "emotion": {"type": "string"},
            "intensity": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["id", "scene_id", "start_sec", "end_sec", "description",
                     "composition", "material_keywords"],
    }

    STORYBOARD_SCHEMA = {
        "type": "object",
        "properties": {
            "project_style": {"type": "string", "description": "整体视觉风格概述"},
            "total_shots": {"type": "integer"},
            "shots": {"type": "array", "items": SHOT_SCHEMA},
            "timeline": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "time_sec": {"type": "number"},
                        "shot_id": {"type": "string"},
                    }
                }
            },
            "transition_graph": {
                "type": "object",
                "properties": {
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from_shot": {"type": "string"},
                                "to_shot": {"type": "string"},
                                "transition": {"type": "string", "enum": TRANSITION_TYPES},
                                "visual_bridge": {"type": "string",
                                                  "description": "两镜头间的视觉衔接元素（颜色/形状/运动/主题）"},
                                "rationale": {"type": "string", "description": "选择此转场的设计理由"},
                            }
                        }
                    }
                }
            },
            "global_color_scheme": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "整体色调方案名称（如：赛博暖金、冷峻科技蓝）"},
                    "mood": {"type": "string", "description": "整体色调传达的情绪"},
                    "base_palette": {
                        "type": "array",
                        "items": {"type": "object", "properties": {
                            "hex": {"type": "string"},
                            "name": {"type": "string"},
                            "role": {"type": "string"},
                        }}
                    }
                }
            },
            "coherence_score": {"type": "number", "minimum": 0, "maximum": 1,
                                "description": "视觉一致性评分"},
            "refinement_notes": {"type": "string", "description": "精修过程中的改进说明"},
        }
    }

    # ── Multi-turn system prompts (Chinese) ───────────────────────────

    SYSTEM_INITIAL = """你是一位资深影视分镜师，拥有20年广告和短视频制作经验。你的任务是根据脚本生
成详细的视觉分镜方案。

核心要求：
1. 每个场景设计 1-3 个镜头，确保节奏流畅
2. 为每个镜头指定精细构图：主体位置、景深、视角（CONSIDER: 画面层次感、引导线、三分法）
3. 设计摄像机运动曲线：描述起止状态、缓入缓出、关键帧速度变化
4. 为每个镜头生成独立色调方案：至少3个hex色值，说明每种颜色的设计理由
5. 转场设计：考虑前后镜头的视觉衔接元素（颜色/形状/运动/主题）
6. 素材搜索关键词：提供中英文关键词，便于在素材库检索
7. 文字叠加：指定文字内容、位置、时机、动画效果
8. 在合适的时机建议CTA（订阅、点赞等），标注位置和动画

输出规范：
- 严格返回 JSON 格式
- 所有时间单位为秒
- hex 颜色值必须为 #RRGGBB 格式
- 构图描述要具体可执行（如"人物居中偏右1/3处，浅景深虚化背景"）"""

    SYSTEM_COHERENCE = """你是资深视觉总监，负责审核分镜方案的视觉一致性与流畅度。

请检查以下分镜方案，从以下维度评估：
1. 色调连贯性：各场景色调是否和谐过渡，整体色彩情绪是否统一
2. 构图节奏：景别变化是否有呼吸感（远-中-近的合理交替）
3. 运动衔接：前后镜头的摄像机运动方向是否冲突
4. 转场逻辑：转场选择是否匹配情绪变化
5. 视觉引导：观众视线是否被合理引导

请指出具体问题，并给出明确的改进方向。返回JSON。"""

    SYSTEM_REFINE = """你是资深分镜精修师。根据视觉总监的审核意见，对分镜方案进行精修。

精修原则：
1. 优先修复色调连贯性问题，微调色值使整体更和谐
2. 调整问题镜头的构图或运动，消除视觉冲突
3. 优化转场选择，增强叙事流畅度
4. 补充缺失的素材关键词和文字叠加
5. 确保最终方案可直接交付后期制作

保持所有原有镜头的内容完整性，只修改需要改进的部分。返回最终的完整JSON分镜方案。"""

    SYSTEM_SHORT_INITIAL = """你是短视频（抖音/TikTok/Reels）专业分镜师，擅长9:16竖屏内容。

竖屏分镜要点：
- 主体居中或占画面上2/3，底部留空间给字幕/CTA
- 节奏快：平均每个镜头 2-5 秒
- 开场3秒内必须有视觉冲击力（hook）
- 多用 close-up / medium-close 强化人物表情
- 转场醒目：多用 zoom_transition / slide / glitch
- CTA 贯穿全程：前3秒吸引关注、中段引导互动、结尾强转化
- 色彩鲜明、对比度高，适合手机小屏观看
- 文字叠加要大字号、短文案、动态出现

严格返回JSON格式。"""

    # ── Public API ────────────────────────────────────────────────────

    async def plan(self, script: dict, style_tags: list = None) -> 'Storyboard':
        """根据脚本生成分镜计划（多轮精炼，向后兼容）

        Args:
            script: 脚本字典，需包含 scenes 或 segments 字段
            style_tags: 风格标签列表，如 ["科技", "快节奏"]

        Returns:
            Storyboard: 完整的分镜方案 TypedDict，包含 shots / timeline / transition_graph 等
        """
        if not isinstance(script, dict):
            script = {}

        # ── 1. Normalize input ────────────────────────────────────────
        raw_scenes = script.get("scenes") or script.get("segments") or []
        if not isinstance(raw_scenes, list):
            raw_scenes = []

        scenes_summary = []
        for s in raw_scenes:
            scenes_summary.append({
                "id": s.get("id", 0),
                "start_sec": s.get("start_sec", 0),
                "end_sec": s.get("end_sec", 0),
                "narration": s.get("narration", ""),
                "emotion": s.get("emotion", ""),
                "intensity": s.get("intensity", 0.5),
                "visual_hint": s.get("visual_hint", ""),
            })

        style_str = ", ".join(style_tags) if style_tags else "专业解说风格"
        total_duration = script.get("total_duration_sec",
                                    max((s.get("end_sec", 0) for s in raw_scenes), default=180))
        title = script.get("title", "未命名项目")

        # ── 2. Turn 1: Initial plan ──
        logger.info(f"Storyboard 3.0: initial plan for '{title}' ({len(scenes_summary)} scenes)")
        cot_log = {"phases": ["think"], "agent_version": "3.0"}
        initial = await self._generate_initial(scenes_summary, style_str, total_duration, title)
        if not initial or not initial.get("shots"):
            logger.warning("Initial plan returned empty — returning fallback")
            return self._empty_plan()

        # ── 3. Turn 2: Coherence check ──
        cot_log["phases"].append("coherence_check")
        logger.info("Storyboard 3.0: coherence check")
        coherence = await self._check_coherence(initial, scenes_summary, style_str)

        # ── 4. Turn 3: Refinement ──
        cot_log["phases"].append("refine")
        logger.info("Storyboard 3.0: refinement")
        refined = await self._refine_plan(initial, coherence, scenes_summary, style_str)

        # ── 5. Post-process & normalize ──
        result = self._normalize_output(refined or initial, coherence)
        result["_cot_log"] = cot_log
        result["_agent_version"] = "3.0"
        logger.info(f"Storyboard 3.0: done — {result.get('total_shots', 0)} shots, "
                     f"coherence={result.get('coherence_score', 0)}")
        return result

    async def plan_short(self, script: dict, style_tags: list = None,
                         platform: str = "douyin") -> dict:
        """为竖屏短视频生成分镜方案（9:16 竖屏优化）

        Args:
            script: 脚本字典
            style_tags: 风格标签
            platform: 目标平台 (douyin / tiktok / reels / kuaishou)

        Returns:
            完整分镜方案（竖屏优化）
        """
        if not isinstance(script, dict):
            script = {}

        raw_scenes = script.get("scenes") or script.get("segments") or []
        if not isinstance(raw_scenes, list):
            raw_scenes = []

        scenes_summary = []
        for s in raw_scenes:
            scenes_summary.append({
                "id": s.get("id", 0),
                "start_sec": s.get("start_sec", 0),
                "end_sec": s.get("end_sec", 0),
                "narration": s.get("narration", ""),
                "emotion": s.get("emotion", ""),
                "intensity": s.get("intensity", 0.5),
                "visual_hint": s.get("visual_hint", ""),
            })

        style_str = ", ".join(style_tags) if style_tags else "短视频快节奏"
        total_duration = script.get("total_duration_sec",
                                    max((s.get("end_sec", 0) for s in raw_scenes), default=60))
        title = script.get("title", "短视频")

        platform_style = {
            "douyin": "抖音风格：强节奏感、高饱和度、年轻化",
            "tiktok": "TikTok风格：国际潮流、快切、文字醒目",
            "reels": "Reels风格：简约高级、自然色调、故事感",
            "kuaishou": "快手风格：接地气、真实感、强互动",
        }.get(platform, "竖屏短视频风格")

        # ── Single-turn short generation (shorter = faster) ───────────
        logger.info(f"Storyboard 2.0 short: '{title}' for {platform}")
        messages = [
            {"role": "system", "content": self.SYSTEM_SHORT_INITIAL},
            {"role": "user", "content":
                f"项目：{title}\n"
                f"总时长：{total_duration}秒\n"
                f"目标平台：{platform}（{platform_style}）\n"
                f"风格：{style_str}\n"
                f"场景列表：{json.dumps(scenes_summary, ensure_ascii=False)}\n\n"
                f"请生成竖屏分镜方案。注意：\n"
                f"- 所有镜头为 9:16 竖屏构图\n"
                f"- 文字叠加放在画面中下部（留出 safe zone）\n"
                f"- CTA 至少3个：开场吸引关注、中段引导互动、结尾强转化\n"
                f"- 色调高对比度、适合手机小屏\n"
                f"- 转场快速有力，前3秒 hook 要够强"}
        ]

        result = await llm.chat_json(messages, json_schema=self.STORYBOARD_SCHEMA)
        result = self._normalize_output(result)
        result.setdefault("aspect_ratio", "9:16")
        result.setdefault("platform", platform)
        logger.info(f"Storyboard 2.0 short: done — {result.get('total_shots', 0)} shots")
        return result

    # ── Internal: three-turn pipeline ─────────────────────────────────

    async def _generate_initial(self, scenes_summary: list, style_str: str,
                                 total_duration: float, title: str) -> dict:
        """Turn 1: 生成初始分镜方案"""
        messages = [
            {"role": "system", "content": self.SYSTEM_INITIAL},
            {"role": "user", "content":
                f"项目：{title}\n"
                f"总时长：{total_duration}秒\n"
                f"风格：{style_str}\n"
                f"场景列表：{json.dumps(scenes_summary, ensure_ascii=False)}\n\n"
                f"请为每个场景设计详细的视觉分镜方案。"}
        ]
        return await llm.chat_multi_vote(messages, json_schema=self.STORYBOARD_SCHEMA)

    async def _check_coherence(self, plan: dict, scenes_summary: list,
                                style_str: str) -> dict:
        """Turn 2: 视觉一致性审核"""
        # Build a lightweight summary for the coherence check
        shots_summary = []
        for shot in plan.get("shots", []):
            shots_summary.append({
                "id": shot.get("id", ""),
                "scene_id": shot.get("scene_id", 0),
                "composition": shot.get("composition", ""),
                "motion": shot.get("camera_movement", {}).get("primary", ""),
                "transition_in": shot.get("transition_in", ""),
                "transition_out": shot.get("transition_out", ""),
            })

        coherence_schema = {
            "type": "object",
            "properties": {
                "overall_score": {"type": "number", "minimum": 0, "maximum": 1},
                "color_coherence_issues": {"type": "array", "items": {"type": "string"}},
                "composition_rhythm_issues": {"type": "array", "items": {"type": "string"}},
                "motion_conflicts": {"type": "array", "items": {"type": "string"}},
                "transition_issues": {"type": "array", "items": {"type": "string"}},
                "general_feedback": {"type": "string"},
                "fix_suggestions": {"type": "array", "items": {"type": "string"}},
            }
        }

        messages = [
            {"role": "system", "content": self.SYSTEM_COHERENCE},
            {"role": "user", "content":
                f"项目风格：{style_str}\n"
                f"场景：{json.dumps(scenes_summary, ensure_ascii=False)}\n"
                f"分镜方案（摘要）：{json.dumps(shots_summary, ensure_ascii=False)}\n\n"
                f"请审核视觉一致性并指出具体问题。"}
        ]
        result = await llm.chat_json(messages, json_schema=coherence_schema)
        result.setdefault("overall_score", 0.7)
        result.setdefault("color_coherence_issues", [])
        result.setdefault("composition_rhythm_issues", [])
        result.setdefault("motion_conflicts", [])
        result.setdefault("transition_issues", [])
        result.setdefault("general_feedback", "")
        result.setdefault("fix_suggestions", [])
        return result

    async def _refine_plan(self, initial_plan: dict, coherence: dict,
                            scenes_summary: list, style_str: str) -> dict:
        """Turn 3: 根据审核意见精修分镜方案"""
        issues_text = "\n".join([
            f"色调问题：{'; '.join(coherence.get('color_coherence_issues', []) or ['无'])}",
            f"构图节奏问题：{'; '.join(coherence.get('composition_rhythm_issues', []) or ['无'])}",
            f"运动冲突：{'; '.join(coherence.get('motion_conflicts', []) or ['无'])}",
            f"转场问题：{'; '.join(coherence.get('transition_issues', []) or ['无'])}",
            f"综合反馈：{coherence.get('general_feedback', '无')}",
            f"改进建议：{'; '.join(coherence.get('fix_suggestions', []) or ['无'])}",
        ])

        messages = [
            {"role": "system", "content": self.SYSTEM_REFINE},
            {"role": "user", "content":
                f"风格：{style_str}\n"
                f"场景：{json.dumps(scenes_summary, ensure_ascii=False)}\n"
                f"原始分镜方案：{json.dumps(initial_plan, ensure_ascii=False)}\n\n"
                f"审核意见：\n{issues_text}\n\n"
                f"请根据审核意见精修分镜方案，返回完整的最终JSON。"}
        ]
        result = await llm.chat_json(messages, json_schema=self.STORYBOARD_SCHEMA)
        result["coherence_score"] = coherence.get("overall_score", 0.7)
        result["refinement_notes"] = coherence.get("general_feedback", "")
        return result

    # ── Output normalization ──────────────────────────────────────────

    def _normalize_output(self, plan: dict, coherence: dict = None) -> dict:
        """Ensure all required fields exist with sensible defaults."""
        plan = plan or {}
        plan.setdefault("project_style", "")
        plan.setdefault("total_shots", len(plan.get("shots", [])))
        plan.setdefault("shots", [])
        plan.setdefault("timeline", [])
        plan.setdefault("transition_graph", {"edges": []})
        plan.setdefault("global_color_scheme", {
            "name": "默认方案", "mood": "中性",
            "base_palette": []
        })

        if coherence:
            plan.setdefault("coherence_score", coherence.get("overall_score", 0.0))
            plan.setdefault("refinement_notes",
                            coherence.get("general_feedback", ""))
        else:
            plan.setdefault("coherence_score", 0.0)
            plan.setdefault("refinement_notes", "")

        # Normalize each shot
        for shot in plan.get("shots", []):
            shot.setdefault("duration_sec",
                            shot.get("end_sec", 0) - shot.get("start_sec", 0))
            shot.setdefault("composition_detail", "")
            shot.setdefault("camera_movement", {
                "primary": "static", "curve": "", "keyframes": []
            })
            shot.setdefault("color_palette", [])
            shot.setdefault("material_keywords", [])
            shot.setdefault("text_overlays", [])
            shot.setdefault("call_to_action", None)
            shot.setdefault("emotion", "")
            shot.setdefault("intensity", 0.5)
            shot.setdefault("transition_in", "cut")
            shot.setdefault("transition_out", "cut")

        # Auto-generate timeline if missing
        if not plan["timeline"] and plan["shots"]:
            plan["timeline"] = [
                {"time_sec": s["start_sec"], "shot_id": s["id"]}
                for s in plan["shots"]
            ]
            # Add an end marker
            if plan["shots"]:
                last = plan["shots"][-1]
                plan["timeline"].append(
                    {"time_sec": last["end_sec"], "shot_id": "__end__"}
                )

        # Auto-generate transition graph edges if missing
        if not plan["transition_graph"]["edges"] and len(plan["shots"]) >= 2:
            edges = []
            for i in range(len(plan["shots"]) - 1):
                cur = plan["shots"][i]
                nxt = plan["shots"][i + 1]
                edges.append({
                    "from_shot": cur["id"],
                    "to_shot": nxt["id"],
                    "transition": cur.get("transition_out", "cut"),
                    "visual_bridge": "",
                    "rationale": "自动生成（未精修）",
                })
            plan["transition_graph"]["edges"] = edges

        return plan

    def _empty_plan(self) -> dict:
        """Return a minimal valid plan when LLM fails."""
        return {
            "project_style": "",
            "total_shots": 0,
            "shots": [],
            "timeline": [],
            "transition_graph": {"edges": []},
            "global_color_scheme": {"name": "", "mood": "", "base_palette": []},
            "coherence_score": 0.0,
            "refinement_notes": "LLM generation failed, empty plan returned.",
        }

    # ── 3.0 Features ──────────────────────────────────────────────────

    async def critique(self, output: dict, context: dict = None) -> dict:
        """自我批判：审查分镜方案质量。

        Args:
            output: 分镜方案dict
            context: 可选上下文

        Returns:
            critique dict with scores, issues, suggestions
        """
        context = context or {}
        output_json = json.dumps(output, ensure_ascii=False, indent=2)[:3000]
        history_hint = ""
        if context.get("project_history"):
            history_hint = f"\n【项目历史】\n{json.dumps(context['project_history'], ensure_ascii=False)[:800]}"

        messages = [
            {"role": "system", "content": (
                "你是资深视觉总监。请审查分镜方案质量，从以下维度评分(0-100)：\n"
                "1. visual_coherence: 色调/构图/运动是否连贯\n"
                "2. composition_variety: 景别变化是否有呼吸感\n"
                "3. transition_logic: 转场是否匹配情绪变化\n"
                "4. production_readiness: 是否可直接交付后期\n"
                "5. creativity: 视觉创意是否出彩\n"
                "\n只输出JSON: {\"scores\": {dim: 0-100}, \"issues\": [...], \"suggestions\": [...], \"overall\": 0-100}"
            )},
            {"role": "user", "content": f"分镜方案：\n{output_json}{history_hint}\n\n请审查。"},
        ]
        try:
            result = await llm.chat_json(messages, temperature=0.3, max_tokens=1024)
            result.setdefault("overall", 70)
            result.setdefault("scores", {})
            result.setdefault("issues", [])
            result.setdefault("suggestions", [])
            return result
        except Exception as e:
            return {"overall": 60, "scores": {}, "issues": [f"critique failed: {e}"], "suggestions": []}

    def _read_project_context(self, artifact_store=None, project_id: str = None) -> dict:
        """从artifact_store读取项目历史上下文。"""
        ctx = {}
        if artifact_store and project_id:
            try:
                prev = artifact_store.get(project_id, "storyboard_final")
                if prev:
                    ctx["previous_storyboard"] = {
                        "project_style": prev.get("project_style", ""),
                        "total_shots": prev.get("total_shots", 0),
                        "coherence_score": prev.get("coherence_score", 0),
                    }
            except Exception:
                pass
        return ctx


# ── Module-level instance (backward compatible) ───────────────────────
storyboard = StoryboardAgent()
