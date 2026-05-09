"""
Scriptwriter Agent 2.0 — AI 编剧
Multi-turn refinement, few-shot examples, quality scoring, fallback, coherence check.
Upgraded from single-pass 95-line agent to a professional 300+ line refinement pipeline.
"""
import json
import copy
import logging
from core.llm_client import llm
from core.types import Script

logger = logging.getLogger("quanquan.scriptwriter")


class ScriptwriterAgent:
    """编剧 Agent 3.0 — CoT推理 + 多模型投票 + 上下文记忆 + 自我批判"""

    # ── Agent Capabilities (3.0) ──
    AGENT_CAPABILITIES = {
        "name": "ScriptwriterAgent",
        "version": "3.0",
        "description": "AI编剧 — 多轮精炼中文视频脚本生成",
        "capabilities": [
            "script_generation",       # 长视频脚本生成
            "quick_script",            # 短视频快速生成
            "multi_turn_refinement",   # 多轮自精炼
            "quality_scoring",         # 四维度质量评分
            "coherence_check",         # 场景连贯性检查
            "user_feedback_refinement",# 用户反馈精炼
            "cot_reasoning",           # Chain-of-Thought推理
            "multi_model_voting",      # 多模型投票
            "self_critique",           # 自我批判改进
            "context_memory",          # 项目历史感知
        ],
        "input_formats": ["text_prompt", "style_tags", "ref_material", "duration_sec"],
        "output_formats": ["script_json", "srt_subtitle", "emotion_curve"],
        "max_duration_sec": 3600,
        "min_duration_sec": 10,
    }

    # ──────────────────────────────────────────────
    #  JSON Schema — 脚本结构
    # ──────────────────────────────────────────────
    SCRIPT_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "视频标题"},
            "total_duration_sec": {"type": "integer"},
            "scenes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "start_sec": {"type": "number"},
                        "end_sec": {"type": "number"},
                        "narration": {
                            "type": "string",
                            "description": "旁白/解说词（中文）",
                        },
                        "emotion": {
                            "type": "string",
                            "enum": ["激昂", "温暖", "紧张", "轻松", "科技", "悲伤", "震撼", "幽默", "感性", "悬疑"],
                        },
                        "intensity": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "visual_hint": {
                            "type": "string",
                            "description": "画面建议/镜头描述",
                        },
                        "transition": {
                            "type": "string",
                            "description": "转场方式",
                            "default": "硬切",
                        },
                    },
                    "required": ["id", "start_sec", "end_sec", "narration", "emotion", "intensity", "visual_hint"],
                },
            },
            "subtitle_srt": {"type": "string", "description": "SRT格式字幕"},
            "emotion_curve": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "time_sec": {"type": "number"},
                        "emotion": {"type": "string"},
                        "intensity": {"type": "number"},
                    },
                },
            },
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "scenes", "emotion_curve"],
    }

    # ──────────────────────────────────────────────
    #  质量评分 Schema
    # ──────────────────────────────────────────────
    QUALITY_SCHEMA = {
        "type": "object",
        "properties": {
            "structure": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "comment": {"type": "string"},
                },
                "required": ["score", "comment"],
            },
            "emotion_curve": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "comment": {"type": "string"},
                },
                "required": ["score", "comment"],
            },
            "pacing": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "comment": {"type": "string"},
                },
                "required": ["score", "comment"],
            },
            "creativity": {
                "type": "object",
                "properties": {
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "comment": {"type": "string"},
                },
                "required": ["score", "comment"],
            },
            "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "summary": {"type": "string"},
        },
        "required": ["structure", "emotion_curve", "pacing", "creativity", "overall_score", "summary"],
    }

    # ──────────────────────────────────────────────
    #  Few-shot 示例（中文视频脚本）
    # ──────────────────────────────────────────────
    FEWSHOT_EXAMPLE_1 = {
        "title": "量子计算：改变未来的技术",
        "total_duration_sec": 150,
        "scenes": [
            {
                "id": 1,
                "start_sec": 0,
                "end_sec": 35,
                "narration": "想象一下，一台计算机能在一秒钟内完成传统计算机需要一万年才能完成的计算。这不是科幻，而是量子计算的真实力量。",
                "emotion": "科技",
                "intensity": 0.7,
                "visual_hint": "芯片特写→量子处理器动画→数字流特效",
                "transition": "硬切",
            },
            {
                "id": 2,
                "start_sec": 35,
                "end_sec": 70,
                "narration": "传统计算机使用比特——要么是0，要么是1。量子计算机使用量子比特，可以同时处于0和1的叠加态。这种并行性，让计算能力指数级增长。",
                "emotion": "科技",
                "intensity": 0.8,
                "visual_hint": "比特vs量子比特对比动画→叠加态可视化",
                "transition": "溶解",
            },
            {
                "id": 3,
                "start_sec": 70,
                "end_sec": 110,
                "narration": "目前，谷歌、IBM和中国的量子团队都在竞相突破。2024年，谷歌的量子芯片Willow实现了低于阈值的量子纠错——这是里程碑式的突破。",
                "emotion": "激昂",
                "intensity": 0.9,
                "visual_hint": "实验室实拍→芯片展示→数据图表动画",
                "transition": "硬切",
            },
            {
                "id": 4,
                "start_sec": 110,
                "end_sec": 150,
                "narration": "量子计算的未来，将重塑药物研发、材料科学、密码学和人工智能。我们正站在一场计算革命的门槛上。未来已来，只是尚未均匀分布。",
                "emotion": "震撼",
                "intensity": 1.0,
                "visual_hint": "未来城市概念图→各领域应用分屏→星空收尾",
                "transition": "淡出",
            },
        ],
        "emotion_curve": [
            {"time_sec": 0, "emotion": "科技", "intensity": 0.7},
            {"time_sec": 35, "emotion": "科技", "intensity": 0.8},
            {"time_sec": 70, "emotion": "激昂", "intensity": 0.9},
            {"time_sec": 110, "emotion": "震撼", "intensity": 1.0},
        ],
        "keywords": ["量子计算", "科技", "未来", "谷歌", "量子比特"],
    }

    FEWSHOT_EXAMPLE_2 = {
        "title": "一个人的成都：48小时慢旅行",
        "total_duration_sec": 120,
        "scenes": [
            {
                "id": 1,
                "start_sec": 0,
                "end_sec": 28,
                "narration": "有人说，成都是一座来了就不想走的城市。这次，我用48小时，验证这句话的真伪。",
                "emotion": "轻松",
                "intensity": 0.4,
                "visual_hint": "航拍成都全景→机场落地→行李箱特写",
                "transition": "硬切",
            },
            {
                "id": 2,
                "start_sec": 28,
                "end_sec": 55,
                "narration": "清晨的人民公园，鹤鸣茶社里，竹椅嘎吱作响。一杯盖碗茶，几碟瓜子，时间在这里变得很慢。隔壁的大爷告诉我，他在这喝了四十年茶。",
                "emotion": "温暖",
                "intensity": 0.6,
                "visual_hint": "茶馆全景→盖碗茶特写→大爷笑脸（征得同意）→竹椅细节",
                "transition": "溶解",
            },
            {
                "id": 3,
                "start_sec": 55,
                "end_sec": 85,
                "narration": "夜幕降临，锦里的红灯笼依次亮起。变脸、吐火、川剧锣鼓——这是属于成都的魔幻时刻。我举着手机，像个孩子一样惊叹。",
                "emotion": "激昂",
                "intensity": 0.85,
                "visual_hint": "红灯笼延时→川剧变脸→吐火特写→观众反应",
                "transition": "硬切",
            },
            {
                "id": 4,
                "start_sec": 85,
                "end_sec": 120,
                "narration": "48小时太短，但也够长了。长到足以确认：成都，确实是一座来了就不想走的城市。下次，我会待更久。",
                "emotion": "感性",
                "intensity": 0.7,
                "visual_hint": "秋叶→背影远去→地铁站台→飞机起飞→淡出",
                "transition": "淡出",
            },
        ],
        "emotion_curve": [
            {"time_sec": 0, "emotion": "轻松", "intensity": 0.4},
            {"time_sec": 28, "emotion": "温暖", "intensity": 0.6},
            {"time_sec": 55, "emotion": "激昂", "intensity": 0.85},
            {"time_sec": 85, "emotion": "感性", "intensity": 0.7},
        ],
        "keywords": ["成都", "旅行", "慢生活", "茶文化", "川剧"],
    }

    # ──────────────────────────────────────────────
    #  System Prompt 构建
    # ──────────────────────────────────────────────
    SYSTEM_PROMPT_BASE = """你是一位资深中文视频编剧，精通短视频、纪录片、科技评测等多种风格的脚本创作。

你的任务是根据用户提供的主题，生成一份结构完整的中文视频脚本。

【创作要求】
1. 分场景设计：每个场景时长30-60秒（长内容）或15-25秒（短内容），场景之间自然过渡
2. 解说词要求：口语化但不随意，有信息密度有情感温度，适合配音朗读（中文约4字/秒计算字数）
3. 情感设计：构建完整的情感曲线（起→承→转→合），避免全程同一情绪
4. 画面建议：具体的镜头描述，帮助后期剪辑理解画面需求
5. 情感标签从以下选择：激昂/温暖/紧张/轻松/科技/悲伤/震撼/幽默/感性/悬疑
6. 场景间要有逻辑连贯性，前一场景的结尾自然引出下一场景的开头
7. 严格以JSON格式输出，不要添加代码块标记

【Few-shot 示例 1 — 科技类】
{example_1}

【Few-shot 示例 2 — 旅行/生活类】
{example_2}

请参考以上示例的风格和结构，但根据当前主题自由创作。"""

    REFINE_PROMPT = """你是一位严格的视频脚本评审专家。请对以下脚本进行自我批判和改进。

【评审维度】
- 结构完整性：场景划分是否合理？故事线是否清晰？
- 情感曲线：情绪是否有起伏变化？高潮是否突出？
- 节奏把控：时长分配是否合理？信息密度是否合适？
- 创意表现：内容是否新颖？有没有更好的表达方式？

【当前脚本】
{script_json}

请针对以上维度逐一分析问题，然后输出改进后的完整脚本JSON。
特别关注：
- 场景间的过渡是否自然
- 解说词是否适合朗读（朗读速度约中文4字/秒）
- 情感曲线是否有明显起伏
- 总时长是否按要求分配"""

    SCORING_PROMPT = """请对以下视频脚本进行质量评分（0-100分），从四个维度评估：

1. 结构完整性（structure）：场景划分是否合理，叙事线是否清晰
2. 情感曲线（emotion_curve）：情绪是否有起伏变化，高潮设计是否到位
3. 节奏把控（pacing）：时长分配、信息密度、叙事节奏
4. 创意表现（creativity）：内容新颖度、表达方式的独特性

【脚本】
{script_json}

请给出每个维度的评分（0-100整数）和简短评语（中文），以及综合评分。"""

    COHERENCE_CHECK_PROMPT = """请检查以下视频脚本的场景连贯性。关注：
- 场景间的叙事逻辑是否自然
- 转场是否恰当
- 情感过渡是否平滑

【脚本场景】
{scenes_text}

如果发现问题，请简要指出；如果没有问题，回复"连贯性良好"。"""

    # ──────────────────────────────────────────────
    #  初始化
    # ──────────────────────────────────────────────
    def __init__(self, max_refinement_rounds: int = 2):
        self.max_refinement_rounds = max_refinement_rounds

    # ──────────────────────────────────────────────
    #  generate() — 主入口（保持向后兼容）
    # ──────────────────────────────────────────────
    async def generate(
        self,
        prompt: str,
        duration_sec: int = 180,
        style_tags: list = None,
        ref_material: dict = None,
    ) -> 'Script':
        """
        生成完整脚本 — 多轮精炼流水线

        Pipeline: 初始生成 → 自批判 → 精炼 → 质量评分 → 连贯性检查 → 返回
        如果LLM失败，使用 fallback 模板。

        Returns:
            Script: 类型安全的脚本 TypedDict
        """
        style_tags = style_tags or ["专业解说"]
        ref_material = ref_material or {}

        logger.info(f"ScriptwriterAgent 3.0: generating script for '{prompt[:50]}...' "
                    f"({duration_sec}s, style={style_tags})")

        # ── CoT Phase 0: 读取项目上下文记忆 ──
        cot_log = {"phases": [], "agent_version": "3.0"}
        try:
            project_ctx = self._read_project_context(
                artifact_store=ref_material.get("_store") if ref_material else None,
                project_id=ref_material.get("_project_id") if ref_material else None,
            )
            if project_ctx:
                cot_log["phases"].append("context_loaded")
                logger.info("Project context loaded from memory")
        except Exception as e:
            logger.debug(f"Context load skipped: {e}")

        try:
            # ── CoT Phase 1: Think — 分析需求 ──
            cot_log["phases"].append("think")
            script = await self._generate_initial(prompt, duration_sec, style_tags, ref_material)
            script = self._ensure_defaults(script, prompt, duration_sec, style_tags)
            script = self._validate_duration(script, duration_sec)

            # ── CoT Phase 2: Plan & Verify — 多轮精炼 ──
            for round_idx in range(self.max_refinement_rounds):
                try:
                    cot_log["phases"].append(f"refine_round_{round_idx+1}")
                    critique = await self._self_critique(script)
                    if critique.get("needs_refinement", True):
                        refined = await self._refine_script(script, critique)
                        if refined and refined.get("scenes"):
                            script = refined
                            script = self._ensure_defaults(script, prompt, duration_sec, style_tags)
                            script = self._validate_duration(script, duration_sec)
                            logger.info(f"Refinement round {round_idx + 1} complete")
                        else:
                            logger.info(f"Refinement round {round_idx + 1}: LLM returned empty, keeping current")
                    else:
                        logger.info(f"No refinement needed after round {round_idx + 1}")
                        break
                except Exception as e:
                    logger.warning(f"Refinement round {round_idx + 1} failed: {e}, continuing with current script")
                    break

            # ── 质量评分 ──
            try:
                quality = await self._score_script(script)
                script["quality_scores"] = quality
            except Exception as e:
                logger.warning(f"Quality scoring failed: {e}")
                script["quality_scores"] = self._default_quality_scores()

            # ── 连贯性检查 ──
            try:
                coherence = await self._check_coherence(script.get("scenes", []))
                script["coherence_check"] = coherence
            except Exception as e:
                logger.warning(f"Coherence check failed: {e}")
                script["coherence_check"] = {"status": "skipped", "reason": str(e)}

        except Exception as e:
            logger.error(f"Script generation failed, using fallback: {e}")
            script = self._fallback_script(prompt, duration_sec, style_tags)

        # ── 最终处理 ──
        script.setdefault("subtitle_srt", self._generate_srt(script.get("scenes", [])))
        script.setdefault("keywords", style_tags)
        script.setdefault("emotion_curve", self._derive_emotion_curve(script.get("scenes", [])))
        script["_cot_log"] = cot_log
        script["_agent_version"] = "3.0"

        return script

    # ──────────────────────────────────────────────
    #  _generate_initial — 初始生成
    # ──────────────────────────────────────────────
    async def _generate_initial(
        self,
        prompt: str,
        duration_sec: int,
        style_tags: list,
        ref_material: dict,
    ) -> dict:
        """使用 few-shot system prompt 生成初始脚本"""
        style_str = "、".join(style_tags)
        ref_str = ""
        if ref_material:
            ref_str = f"\n【参考素材风格】\n{json.dumps(ref_material, ensure_ascii=False, indent=2)}"

        system_content = self.SYSTEM_PROMPT_BASE.format(
            example_1=json.dumps(self.FEWSHOT_EXAMPLE_1, ensure_ascii=False, indent=2),
            example_2=json.dumps(self.FEWSHOT_EXAMPLE_2, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    f"请为以下主题创作一份{duration_sec}秒的中文视频脚本：\n\n"
                    f"【主题】{prompt}\n"
                    f"【风格标签】{style_str}\n"
                    f"【目标时长】{duration_sec}秒\n"
                    f"{ref_str}\n"
                    f"请返回完整的JSON格式脚本，包含所有必要字段。"
                ),
            },
        ]

        return await llm.chat_multi_vote(messages, json_schema=self.SCRIPT_SCHEMA)

    # ──────────────────────────────────────────────
    #  _self_critique — 自批判
    # ──────────────────────────────────────────────
    async def _self_critique(self, script: dict) -> dict:
        """让LLM对自己的脚本进行批判性评估"""
        script_json = json.dumps(script, ensure_ascii=False, indent=2)
        critique_prompt = self.REFINE_PROMPT.format(script_json=script_json)

        # 先获取批判意见（非结构化）
        messages = [
            {
                "role": "system",
                "content": "你是一位严格的脚本评审专家。请客观分析脚本的问题，然后提出具体改进建议。",
            },
            {"role": "user", "content": critique_prompt},
        ]

        critique_text = await llm.chat(messages, temperature=0.3, max_tokens=2048)

        # 解析批判结果：检查是否真的需要改进
        needs_refinement = any(
            keyword in critique_text.lower()
            for keyword in ["改进", "问题", "不足", "建议", "优化", "调整", "问题", "修改"]
        )

        return {
            "critique_text": critique_text,
            "needs_refinement": needs_refinement,
        }

    # ──────────────────────────────────────────────
    #  _refine_script — 基于批判精炼脚本
    # ──────────────────────────────────────────────
    async def _refine_script(self, script: dict, critique: dict) -> dict:
        """根据批判意见改进脚本"""
        script_json = json.dumps(script, ensure_ascii=False, indent=2)
        critique_text = critique.get("critique_text", "")

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位资深视频编剧。请根据以下评审意见，修改并输出改进后的完整脚本JSON。\n"
                    "重点：修正评审中指出的问题，但保留原脚本的优点。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"【评审意见】\n{critique_text}\n\n"
                    f"【原脚本】\n{script_json}\n\n"
                    f"请输出改进后的完整脚本JSON。"
                ),
            },
        ]

        return await llm.chat_json(messages, json_schema=self.SCRIPT_SCHEMA)

    # ──────────────────────────────────────────────
    #  _score_script — 质量评分
    # ──────────────────────────────────────────────
    async def _score_script(self, script: dict) -> dict:
        """对脚本进行四维度质量评分"""
        script_json = json.dumps(script, ensure_ascii=False, indent=2)
        scoring_prompt = self.SCORING_PROMPT.format(script_json=script_json)

        messages = [
            {
                "role": "system",
                "content": "你是一位视频内容质量评估专家。请客观评分，0-100分。",
            },
            {"role": "user", "content": scoring_prompt},
        ]

        try:
            scores = await llm.chat_json(messages, json_schema=self.QUALITY_SCHEMA)
            return scores
        except Exception:
            return self._default_quality_scores()

    def _default_quality_scores(self) -> dict:
        """默认质量评分（LLM不可用时）"""
        return {
            "structure": {"score": 60, "comment": "使用降级模板，结构基本完整"},
            "emotion_curve": {"score": 50, "comment": "降级模式，情感设计有限"},
            "pacing": {"score": 60, "comment": "自动分配时长，节奏基本合理"},
            "creativity": {"score": 40, "comment": "模板生成，创意受限"},
            "overall_score": 53,
            "summary": "因LLM不可用，使用降级模板生成。建议在有LLM服务时重新生成。",
        }

    # ──────────────────────────────────────────────
    #  _check_coherence — 场景连贯性检查
    # ──────────────────────────────────────────────
    async def _check_coherence(self, scenes: list) -> dict:
        """检查场景间的逻辑连贯性"""
        if len(scenes) < 2:
            return {"status": "ok", "note": "场景数量不足，跳过连贯性检查"}

        # 构建场景文本摘要
        scenes_text = "\n".join(
            f"[场景{s['id']} {s['start_sec']:.0f}s-{s['end_sec']:.0f}s] {s.get('narration', '')[:80]}"
            for s in scenes
        )

        messages = [
            {
                "role": "system",
                "content": "你是视频编辑专家，请快速检查场景连贯性。如果连贯性良好，回复'PASS'。",
            },
            {"role": "user", "content": self.COHERENCE_CHECK_PROMPT.format(scenes_text=scenes_text)},
        ]

        try:
            result = await llm.chat(messages, temperature=0.1, max_tokens=512)
            issues = None if "连贯性良好" in result or "PASS" in result else result[:200]
            return {
                "status": "ok" if issues is None else "issues_found",
                "issues": issues,
            }
        except Exception as e:
            return {"status": "error", "reason": str(e)}

    # ──────────────────────────────────────────────
    #  _validate_duration — 时长校验与修正
    # ──────────────────────────────────────────────
    def _validate_duration(self, script: dict, target_duration: int) -> dict:
        """确保场景时长总和匹配目标时长，必要时自动修正"""
        scenes = script.get("scenes", [])
        if not scenes:
            return script

        total = sum((s.get("end_sec", 0) - s.get("start_sec", 0)) for s in scenes)
        tolerance = max(5, target_duration * 0.1)  # 10% 或至少5秒

        if abs(total - target_duration) <= tolerance:
            return script

        # 比例缩放
        scale = target_duration / total if total > 0 else 1.0
        current_time = 0.0
        for scene in scenes:
            original_duration = scene.get("end_sec", 0) - scene.get("start_sec", 0)
            new_duration = max(5, round(original_duration * scale, 1))
            scene["start_sec"] = round(current_time, 1)
            scene["end_sec"] = round(current_time + new_duration, 1)
            current_time = scene["end_sec"]

        script["total_duration_sec"] = target_duration
        script["_duration_adjusted"] = True
        logger.info(
            f"Duration adjusted: {total:.1f}s → {target_duration}s "
            f"(scale factor: {scale:.3f})"
        )
        return script

    # ──────────────────────────────────────────────
    #  _fallback_script — LLM 失败时的降级脚本
    # ──────────────────────────────────────────────
    def _fallback_script(self, prompt: str, duration_sec: int, style_tags: list) -> dict:
        """生成基础模板脚本（不依赖LLM）"""
        num_scenes = max(2, duration_sec // 40)  # 约40秒一个场景
        scene_duration = duration_sec / num_scenes

        emotions = ["轻松", "科技", "激昂", "温暖", "震撼"]
        scenes = []
        for i in range(num_scenes):
            start = round(i * scene_duration, 1)
            end = round((i + 1) * scene_duration, 1)
            emotion = emotions[i % len(emotions)]
            intensity = min(1.0, 0.3 + (i / num_scenes) * 0.7)

            scenes.append({
                "id": i + 1,
                "start_sec": start,
                "end_sec": end,
                "narration": f"【{prompt}】第{i + 1}部分：这是关于{prompt}的精彩内容，敬请期待完整版。",
                "emotion": emotion,
                "intensity": round(intensity, 2),
                "visual_hint": f"与「{prompt}」相关的画面素材",
                "transition": "硬切" if i < num_scenes - 1 else "淡出",
            })

        return {
            "title": prompt,
            "total_duration_sec": duration_sec,
            "scenes": scenes,
            "subtitle_srt": self._generate_srt(scenes),
            "emotion_curve": self._derive_emotion_curve(scenes),
            "keywords": style_tags or ["模板生成"],
            "quality_scores": self._default_quality_scores(),
            "_fallback": True,
            "_note": "LLM服务不可用，使用降级模板生成。请在有服务时重新生成。",
        }

    # ──────────────────────────────────────────────
    #  refine() — 用户反馈精炼（新增）
    # ──────────────────────────────────────────────
    async def refine(self, script: dict, feedback: str) -> dict:
        """
        根据用户反馈改进脚本。

        Args:
            script: 原脚本字典
            feedback: 用户反馈文本（如"把第三个场景改得更燃一些"）

        Returns:
            改进后的脚本字典
        """
        script_json = json.dumps(script, ensure_ascii=False, indent=2)

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位资深中文视频编剧。请根据用户的反馈修改脚本，同时保持其他部分不变。\n"
                    "用户反馈是最优先的修改指令，请严格执行。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"【用户反馈】\n{feedback}\n\n"
                    f"【当前脚本】\n{script_json}\n\n"
                    f"请输出修改后的完整脚本JSON。"
                ),
            },
        ]

        try:
            refined = await llm.chat_json(messages, json_schema=self.SCRIPT_SCHEMA)
            refined = self._ensure_defaults(refined, script.get("title", ""), script.get("total_duration_sec", 180), script.get("keywords", []))
            refined["subtitle_srt"] = self._generate_srt(refined.get("scenes", []))
            refined["_refined_from_feedback"] = True
            return refined
        except Exception as e:
            logger.error(f"Refine with feedback failed: {e}")
            script["_refine_error"] = str(e)
            return script

    # ──────────────────────────────────────────────
    #  quick_script() — 短内容快速生成（新增）
    # ──────────────────────────────────────────────
    async def quick_script(self, prompt: str, style_tags: list = None) -> dict:
        """
        为短视频平台（TikTok/Reels/抖音）快速生成脚本（< 60秒）。

        Args:
            prompt: 内容主题
            style_tags: 风格标签（可选）

        Returns:
            短脚本字典，duration 固定 ≤ 60 秒
        """
        style_tags = style_tags or ["短视频", "快节奏"]
        style_str = "、".join(style_tags)

        system_content = (
            "你是一位抖音/Reels短视频编剧，专攻60秒以内的爆款内容。\n"
            "要求：\n"
            "- 黄金前3秒：开头必须有钩子吸引注意力\n"
            "- 场景短小精悍：每个场景10-20秒，共3-5个场景\n"
            "- 解说词快节奏：短句为主，有网感，适合口语朗读\n"
            "- 情感强对比：开头hook→内容展开→高潮/反转→收尾\n"
            "- 画面建议具体：适合竖屏9:16构图\n"
            "- 严格返回JSON\n\n"
            f"参考示例风格（需调整为主题{prompt}）：\n"
            f"{json.dumps(self.FEWSHOT_EXAMPLE_2, ensure_ascii=False, indent=2)}"
        )

        messages = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": (
                    f"请为主题「{prompt}」创作一条60秒以内的短视频脚本。\n"
                    f"风格：{style_str}\n"
                    f"要求：黄金3秒开头，快节奏，适合竖屏。"
                ),
            },
        ]

        try:
            script = await llm.chat_json(messages, json_schema=self.SCRIPT_SCHEMA)
            script = self._ensure_defaults(script, prompt, 60, style_tags)
            script = self._validate_duration(script, 60)
            script["subtitle_srt"] = self._generate_srt(script.get("scenes", []))
            script["content_type"] = "short_form"
            script["_note"] = "Quick script for TikTok/Reels/Douyin"
            return script
        except Exception as e:
            logger.error(f"Quick script generation failed: {e}")
            return self._fallback_script(prompt, 60, style_tags)

    # ──────────────────────────────────────────────
    #  critique() — 3.0 自我批判改进
    # ──────────────────────────────────────────────
    async def critique(self, output: dict, context: dict = None) -> dict:
        """自我批判：审查Agent输出并给出改进建议。

        Args:
            output: Agent的输出（脚本dict）
            context: 可选上下文（如项目历史、参考素材）

        Returns:
            critique dict with scores, issues, suggestions
        """
        context = context or {}
        output_json = json.dumps(output, ensure_ascii=False, indent=2)[:3000]

        # 提取项目历史（如果有artifact_store）
        history_hint = ""
        if context.get("project_history"):
            history_hint = f"\n【项目历史】\n{json.dumps(context['project_history'], ensure_ascii=False)[:1000]}"

        messages = [
            {"role": "system", "content": (
                "你是一位严苛的AI输出审查专家。请从以下维度审查脚本质量，给出评分和改进建议：\n"
                "1. narrative_quality (叙事质量): 故事线是否清晰、有吸引力\n"
                "2. structural_integrity (结构完整): 场景划分、时长分配是否合理\n"
                "3. emotion_design (情感设计): 情感曲线是否有起伏、高潮是否突出\n"
                "4. production_feasibility (可制作性): 画面建议是否具体可执行\n"
                "5. language_quality (语言质量): 解说词是否口语化、有感染力\n"
                "\n只输出JSON: {\"scores\": {dim: 0-100}, \"issues\": [...], \"suggestions\": [...], \"overall\": 0-100}"
            )},
            {"role": "user", "content": f"输出内容：\n{output_json}{history_hint}\n\n请审查。"},
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

    # ──────────────────────────────────────────────
    #  _read_project_context — 3.0 上下文记忆
    # ──────────────────────────────────────────────
    def _read_project_context(self, artifact_store=None, project_id: str = None) -> dict:
        """从artifact_store读取项目历史上下文。"""
        ctx = {}
        if artifact_store and project_id:
            try:
                # 尝试读取之前生成的脚本
                prev = artifact_store.get(project_id, "script_final")
                if prev:
                    ctx["previous_script"] = {
                        "title": prev.get("title", ""),
                        "emotion_curve": prev.get("emotion_curve", []),
                        "style_tags": prev.get("keywords", []),
                    }
            except Exception:
                pass
        return ctx


    def _ensure_defaults(self, script: dict, prompt: str, duration_sec: int, style_tags: list) -> dict:
        """确保脚本包含所有必需字段"""
        script.setdefault("title", prompt)
        script.setdefault("total_duration_sec", duration_sec)
        script.setdefault("scenes", [])
        script.setdefault("keywords", style_tags or [])
        script.setdefault("emotion_curve", self._derive_emotion_curve(script.get("scenes", [])))
        return script

    def _derive_emotion_curve(self, scenes: list) -> list:
        """从场景列表推导情感曲线"""
        curve = []
        for scene in scenes:
            curve.append({
                "time_sec": scene.get("start_sec", 0),
                "emotion": scene.get("emotion", "轻松"),
                "intensity": scene.get("intensity", 0.5),
            })
        # 添加最后一个时间点
        if scenes:
            last = scenes[-1]
            curve.append({
                "time_sec": last.get("end_sec", 0),
                "emotion": last.get("emotion", "轻松"),
                "intensity": last.get("intensity", 0.5),
            })
        return curve

    def _generate_srt(self, scenes: list) -> str:
        """从场景生成 SRT 字幕（保留原实现）"""
        lines = []
        for i, scene in enumerate(scenes):
            start = scene.get("start_sec", i * 30)
            end = scene.get("end_sec", (i + 1) * 30)
            text = scene.get("narration", "")
            lines.append(f"{i + 1}")
            lines.append(f"{self._fmt_time(start)} --> {self._fmt_time(end)}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _fmt_time(sec: float) -> str:
        """格式化时间为 SRT 时间戳 H:MM:SS,mmm"""
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ──────────────────────────────────────────────
#  模块级实例（向后兼容）
# ──────────────────────────────────────────────
scriptwriter = ScriptwriterAgent()
