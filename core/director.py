"""Director Agent — UniVA Planner + 调度器 — 11状态机 v3.0 (FIXED)"""
import asyncio, logging, time, uuid, traceback
from enum import Enum
from typing import Dict, List, Optional, Any
from core.context_bus import ContextBus
from core.artifact_store import ArtifactStore
from core.dag_executor import DAGExecutor, NodeStatus

logger = logging.getLogger("quanquan.director")

class DirectorState(str, Enum):
    IDLE="idle"; ANALYZING="analyzing"; RETRIEVING="retrieving"; PLANNING="planning"
    DISPATCHING="dispatching"; MONITORING="monitoring"; REFLECTING="reflecting"
    REPLANNING="replanning"; REWORKING="reworking"; FINALIZING="finalizing"; REPORTING="reporting"

class DirectorAgent:
    def __init__(self, context_bus: ContextBus, artifact_store: ArtifactStore,
                 projects_store: dict = None):
        self.bus = context_bus; self.artifacts = artifact_store
        self.executor = DAGExecutor(context_bus, artifact_store)
        self.state = DirectorState.IDLE
        self.current_dag = None; self.current_project_id = None
        self.node_status = {}; self.intent_profile = None; self.memory_profile = None
        self.replan_count = 0; self.max_replan = 3
        self.raw_input = None; self.pending_warnings = []; self.start_time = None
        self._project_queue = asyncio.Queue(maxsize=100)
        self._dag_results: Dict[str, Any] = {}
        self._dag_done = asyncio.Event()
        self._dag_task: Optional[asyncio.Task] = None
        self._projects_store = projects_store if projects_store is not None else {}
        self._handlers = {
            DirectorState.IDLE: self._idle, DirectorState.ANALYZING: self._analyzing,
            DirectorState.RETRIEVING: self._retrieving, DirectorState.PLANNING: self._planning,
            DirectorState.DISPATCHING: self._dispatching, DirectorState.MONITORING: self._monitoring,
            DirectorState.REFLECTING: self._reflecting, DirectorState.REPLANNING: self._replanning,
            DirectorState.REWORKING: self._reworking, DirectorState.FINALIZING: self._finalizing,
            DirectorState.REPORTING: self._reporting,
        }

    def _safe(self, d, k, default=None):
        return (d or {}).get(k, default)

    def _gen_id(self): return f"proj_{uuid.uuid4().hex[:12]}"

    def _trans(self, ns: DirectorState):
        logger.info(f"[Director] {self.state.value} → {ns.value}")
        self.state = ns

    def _update_project(self, state: str, progress: float = None):
        """★ 更新外部项目存储的进度"""
        if self.current_project_id and self._projects_store:
            p = self._projects_store.get(self.current_project_id)
            if p:
                p["state"] = state
                if progress is not None:
                    p["progress"] = round(progress, 2)

    # ── 主循环 ──
    async def run(self):
        await self.bus.connect()
        logger.info("[Director] Started — v3.0")
        while True:
            try:
                handler = self._handlers.get(self.state)
                if handler is None:
                    logger.error(f"[Director] Unknown state: {self.state}, resetting to IDLE")
                    self.state = DirectorState.IDLE
                    continue
                await handler()
            except Exception as e:
                logger.error(f"[Director] CRASH in state {self.state}: {e}\n{traceback.format_exc()}")
                # 防卡死：异常时重置到 IDLE
                self._dag_done.set()
                self.state = DirectorState.IDLE
                await asyncio.sleep(1)

    # ── 提交项目 ──
    async def submit_project(self, data: dict) -> str:
        pid = data.get("project_id", self._gen_id())
        self.current_project_id = pid
        await self._project_queue.put(data)
        return pid

    def submit_project_nonblock(self, data: dict) -> str:
        pid = data.get("project_id", self._gen_id())
        self.current_project_id = pid
        try: self._project_queue.put_nowait(data)
        except asyncio.QueueFull: pass
        return pid

    def get_status(self) -> dict:
        node_statuses = [{"node": k, "status": v.value} for k, v in self.node_status.items()]
        return {
            "state": self.state.value,
            "project_id": self.current_project_id or "",
            "node_statuses": node_statuses,
            "replan_count": self.replan_count,
            "elapsed_sec": time.time() - self.start_time if self.start_time else 0,
            "dag_results_count": len(self._dag_results),
        }

    # ── 状态处理器 ──
    async def _idle(self):
        try:
            self.raw_input = await asyncio.wait_for(self._project_queue.get(), timeout=60)
        except asyncio.TimeoutError:
            return
        self.current_project_id = self.raw_input.get("project_id", self._gen_id())
        self.replan_count = 0; self.start_time = time.time()
        self._dag_results = {}; self.node_status = {}
        self._dag_done.clear()
        self._update_project("analyzing", 0.0)
        self._trans(DirectorState.ANALYZING)

    async def _analyzing(self):
        text = self._safe(self.raw_input, "text_prompt", "")
        self.intent_profile = {
            "text": text,
            "style_tags": self._safe(self.raw_input, "style_tags", []),
            "duration_target_sec": self._safe(self.raw_input, "duration_target_sec", 180),
            "mood": self._guess_mood(text),
        }
        self._update_project("retrieving", 0.05)
        self._trans(DirectorState.RETRIEVING)

    async def _retrieving(self):
        # ── v6.0: 偏好衰减引擎 ──
        user_id = self._safe(self.raw_input, "user_id", "anonymous")
        try:
            from core.preference_decay import preference_engine
            # 应用时间衰减
            preference_engine.apply_decay(user_id)
            # 冷启动检测
            profile = preference_engine.get_profile_summary(user_id)
            if profile.get("cold_start"):
                tags = self._safe(self.raw_input, "style_tags", [])
                text = self._safe(self.raw_input, "text_prompt", "")
                keywords = tags + [w for w in text[:60].split() if len(w) >= 2][:3]
                preference_engine.cold_start(user_id, keywords)
                profile = preference_engine.get_profile_summary(user_id)
            # 提取顶级偏好
            top_picks = profile.get("top_picks", {})
            self.memory_profile = {
                "voice_id": (top_picks.get("voice", {}) or {}).get("key", "default"),
                "filter": (top_picks.get("filter", {}) or {}).get("key", "standard"),
                "transition": (top_picks.get("transition", {}) or {}).get("key", "dissolve"),
                "bgm_genre": (top_picks.get("bgm", {}) or {}).get("key", "ambient"),
                "pace": (top_picks.get("pace", {}) or {}).get("key", "medium"),
            }
            logger.info(f"[Director] Memory profile loaded for {user_id}: {self.memory_profile}")
        except Exception as e:
            logger.warning(f"[Director] Preference engine unavailable: {e}")
            self.memory_profile = {
                "voice_id": "default", "filter": "standard",
                "transition": "dissolve", "bgm_genre": "ambient", "pace": "medium",
            }
        self._update_project("planning", 0.10)
        self._trans(DirectorState.PLANNING)

    async def _planning(self):
        dur = self._safe(self.intent_profile, "duration_target_sec", 180)
        text = self._safe(self.intent_profile, "text", "")
        mood = self._safe(self.intent_profile, "mood", "中立")
        tags = self._safe(self.intent_profile, "style_tags", [])
        style_id = tags[0] if tags else "auto"

        self.current_dag = {
            "dag_id": self.current_project_id,
            "nodes": [
                {"node_id": "script_gen", "agent": "Scriptwriter", "depends_on": [],
                 "input": {"prompt": text, "duration_sec": dur, "style_tags": tags}},
                {"node_id": "storyboard", "agent": "Storyboard", "depends_on": ["script_gen"],
                 "input": {"script": "${dag:script_gen}", "style_tags": tags}},
                {"node_id": "bgm", "agent": "BGM", "depends_on": ["script_gen"],
                 "input": {"script": "${dag:script_gen}", "mood": mood, "duration_sec": dur}},
                {"node_id": "voiceover", "agent": "Voiceover", "depends_on": ["script_gen", "storyboard"],
                 "input": {"script": "${dag:script_gen}", "voice_id": self._safe(self.memory_profile, "voice_id", "default")}},
                {"node_id": "styling", "agent": "Styling", "depends_on": ["storyboard"],
                 "input": {"storyboard": "${dag:storyboard}", "filter_name": style_id}},
                {"node_id": "qc", "agent": "QC", "depends_on": ["script_gen", "voiceover"],
                 "input": {"artifacts": {"script": "${dag:script_gen}", "voiceover": "${dag:voiceover}"}}},
                {"node_id": "delivery", "agent": "Delivery", "depends_on": ["qc", "bgm", "styling"],
                 "input": {"project_id": self.current_project_id}},
                {"node_id": "render", "agent": "VideoRender", "depends_on": ["delivery", "script_gen", "storyboard"],
                 "input": {"project_id": self.current_project_id, "style": style_id}},
            ]
        }
        self._update_project("dispatching", 0.15)
        self._trans(DirectorState.DISPATCHING)

    async def _dispatching(self):
        self._dag_done.clear()
        self._dag_task = asyncio.create_task(self._run_dag())
        self._trans(DirectorState.MONITORING)

    # ── DAG 执行（核心修复） ──
    async def _run_dag(self):
        """执行 DAG，遵循依赖拓扑，存储结果到 _dag_results"""
        try:
            nodes = self.current_dag.get("nodes", [])
            completed = set()
            total = len(nodes)

            while len(completed) < total:
                any_progress = False
                for node in nodes:
                    nid = node["node_id"]
                    if nid in completed:
                        continue
                    # 检查依赖
                    deps = node.get("depends_on", [])
                    if not all(d in completed for d in deps):
                        continue

                    # 解析输入（替换占位符）
                    resolved_input = self._resolve_input(node)

                    self.node_status[nid] = NodeStatus.RUNNING
                    self._update_project(f"running:{nid}", 0.15 + 0.10 * len(completed) / total)
                    logger.info(f"[Director] Dispatching {node['agent']} ({nid})")

                    try:
                        result = await self._dispatch_agent(node, resolved_input)
                        self._dag_results[nid] = result
                        self.node_status[nid] = NodeStatus.SUCCESS
                        logger.info(f"[Director] {node['agent']} ({nid}) → SUCCESS")
                    except Exception as e:
                        logger.error(f"[Director] {node['agent']} ({nid}) FAILED: {e}")
                        self.node_status[nid] = NodeStatus.FAILED
                        self._dag_results[nid] = {"error": str(e)}

                    completed.add(nid)
                    any_progress = True

                if not any_progress:
                    # 有循环依赖或所有剩余节点被阻塞
                    remaining = [n["node_id"] for n in nodes if n["node_id"] not in completed]
                    logger.warning(f"[Director] No progress, blocked nodes: {remaining}")
                    for rid in remaining:
                        self.node_status[rid] = NodeStatus.FAILED
                        self._dag_results[rid] = {"error": "dependency not met"}
                    break

            self._update_project("reflecting", 0.95)
        except Exception as e:
            logger.error(f"[Director] DAG execution error: {e}\n{traceback.format_exc()}")
        finally:
            self._dag_done.set()

    def _resolve_input(self, node: dict) -> dict:
        """解析输入中的占位符 ${dag:node_id} """
        resolved = {}
        for key, value in node.get("input", {}).items():
            if isinstance(value, str) and value.startswith("${dag:"):
                ref_id = value[len("${dag:"):-1]  # 取出 node_id
                ref_data = self._dag_results.get(ref_id)
                resolved[key] = ref_data if ref_data is not None else {}
            elif isinstance(value, dict):
                # 递归解析嵌套 dict
                resolved[key] = {k: self._dag_results.get(v[len("${dag:"):-1], v)
                                if isinstance(v, str) and v.startswith("${dag:") else v
                                for k, v in value.items()}
            else:
                resolved[key] = value
        return resolved

    # ── Agent 调度（修复所有签名不匹配） ──
    async def _dispatch_agent(self, node: dict, inp: dict) -> dict:
        agent = node["agent"]

        if agent == "Scriptwriter":
            from agents.scriptwriter import scriptwriter
            return await scriptwriter.generate(
                prompt=str(inp.get("prompt", "")),
                duration_sec=int(inp.get("duration_sec", 180)),
                style_tags=inp.get("style_tags", []),
            )

        elif agent == "Storyboard":
            from agents.storyboard import storyboard
            script = inp.get("script", {})
            if isinstance(script, str):
                script = {}
            return await storyboard.plan(script, inp.get("style_tags", []))

        elif agent == "BGM":
            from agents.all_agents import bgm
            script = inp.get("script", {})
            if isinstance(script, str):
                script = {}
            return await bgm.select(
                script=script,
                mood=str(inp.get("mood", "neutral")),
                duration_sec=int(inp.get("duration_sec", 180)),
            )

        elif agent == "Voiceover":
            from agents.all_agents import voiceover
            script = inp.get("script", {})
            if isinstance(script, str):
                script = {}
            return await voiceover.generate(
                script=script,
                voice_id=str(inp.get("voice_id", "default")),
            )

        elif agent in ("StylizationColorGrading", "Styling"):
            from agents.all_agents import styling
            storyboard = inp.get("storyboard", {})
            if isinstance(storyboard, str):
                storyboard = {}
            return await styling.apply(
                storyboard=storyboard,
                filter_name=str(inp.get("filter_name", "standard")),
            )

        elif agent in ("QualityControl", "QC"):
            from agents.all_agents import qc
            artifacts = inp.get("artifacts", inp)  # 兼容两种调用方式
            if isinstance(artifacts, str):
                artifacts = {}
            return await qc.inspect(artifacts)

        elif agent == "Delivery":
            from agents.all_agents import delivery
            # 组装所有 DAG 产出的制品
            return await delivery.assemble(
                all_artifacts={
                    "script": self._dag_results.get("script_gen", {}),
                    "storyboard": self._dag_results.get("storyboard", {}),
                    "voiceover": self._dag_results.get("voiceover", {}),
                    "bgm": self._dag_results.get("bgm", {}),
                    "styling": self._dag_results.get("styling", {}),
                    "qc_report": self._dag_results.get("qc", {}),
                    "project_id": self.current_project_id,
                },
                memory_profile=self.memory_profile or {},
            )

        elif agent == "VideoRender":
            from core.video_renderer import renderer
            script = self._dag_results.get("script_gen", {})
            storyboard = self._dag_results.get("storyboard", {})
            style = str(inp.get("style", "auto"))
            scenes = script.get("scenes", []) or script.get("segments", [])
            if not scenes:
                logger.info(f"[Director] VideoRender skipped — no scenes")
                return {"status": "ok", "agent": agent, "video_path": ""}
            try:
                output = await asyncio.wait_for(
                    renderer.render(project_id=self.current_project_id, script=script,
                                    storyboard=storyboard, style=style),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                logger.warning(f"[Director] VideoRender timeout")
                output = None
            return {"status": "ok", "agent": agent, "video_path": output or ""}

        return {"status": "ok", "agent": agent}

    async def _monitoring(self):
        """等待 DAG 完成（事件驱动 + 保底超时）"""
        try:
            await asyncio.wait_for(self._dag_done.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            # 兜底：检查是否所有节点都已完成（以防 _dag_done 信号丢失）
            if self.node_status:
                all_finished = all(
                    s in (NodeStatus.SUCCESS, NodeStatus.FAILED)
                    for s in self.node_status.values()
                )
                if all_finished:
                    logger.info("[Director] All nodes finished (fallback detection)")
                    self._dag_done.set()  # 补偿信号
            return

        all_ok = all(
            s == NodeStatus.SUCCESS
            for s in self.node_status.values()
        ) if self.node_status else False

        if all_ok:
            self._trans(DirectorState.FINALIZING)
        else:
            self._trans(DirectorState.REFLECTING)

    async def _reflecting(self):
        failed = [k for k, v in self.node_status.items() if v == NodeStatus.FAILED]
        logger.info(f"[Director] Reflecting — failed nodes: {failed}")

        if self.replan_count < self.max_replan and failed:
            self._trans(DirectorState.REPLANNING)
        else:
            self._trans(DirectorState.REPORTING)

    async def _replanning(self):
        self.replan_count += 1
        self._update_project("replanning", 0.5)
        if self.replan_count > self.max_replan:
            self._trans(DirectorState.REPORTING)
        else:
            self._trans(DirectorState.DISPATCHING)

    async def _reworking(self):
        self._trans(DirectorState.MONITORING)

    async def _finalizing(self):
        self._update_project("finalizing", 0.97)
        self._trans(DirectorState.REPORTING)

    async def _reporting(self):
        elapsed = time.time() - self.start_time if self.start_time else 0
        success_count = sum(1 for s in self.node_status.values() if s == NodeStatus.SUCCESS)
        total = len(self.node_status)
        logger.info(f"[Director] Project {self.current_project_id} done — "
                    f"{success_count}/{total} OK in {elapsed:.1f}s")

        # ★ 持久化所有 DAG 产物到磁盘
        if self.current_project_id:
            for node_id, result in self._dag_results.items():
                try:
                    await self.artifacts.put(self.current_project_id, node_id, 
                                     result if isinstance(result, dict) else {"data": str(result)})
                except Exception as e:
                    logger.warning(f"Failed to store artifact {node_id}: {e}")
            logger.info(f"[Director] Stored {len(self._dag_results)} artifacts for {self.current_project_id}")

        # 存储导演笔记
        try:
            from core.director_notes import generate_director_notes_html
            notes = generate_director_notes_html(self.current_project_id, self._dag_results)
            await self.artifacts.put(self.current_project_id, "director_notes",
                             {"html": notes, "dag_results": {k: str(v)[:500] for k, v in self._dag_results.items()}})
        except Exception:
            pass

        self._update_project("completed", 1.0)
        if self.current_project_id in self._projects_store:
            self._projects_store[self.current_project_id]["status"] = "completed"
            self._projects_store[self.current_project_id]["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        self.current_project_id = None
        self.node_status = {}
        self._dag_results = {}
        self.intent_profile = None
        self.memory_profile = None
        self.raw_input = None
        self._dag_done.clear()
        self._trans(DirectorState.IDLE)

    def _guess_mood(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ["赛博", "酷", "炫", "燃", "爆"]): return "激昂"
        if any(w in t for w in ["恐怖", "鬼", "暗黑", "阴森"]): return "紧张"
        if any(w in t for w in ["美", "萌", "可爱", "甜"]): return "温馨"
        if any(w in t for w in ["悲伤", "忧伤", "感人"]): return "悲伤"
        return "中立"
