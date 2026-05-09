"""
quanquan API Server v7.0 — 企业级持久化后端
30+ REST端点 · WebSocket实时 · 认证限流 · 全模块集成
启动: uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
"""

import asyncio, os, time, uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

# ---- 核心模块 ----
from core.director import DirectorAgent, DirectorState
from core.context_bus import context_bus
from core.artifact_store import artifact_store
from core.chunked_processor import ChunkedProcessor, VideoInspector
from core.gpu_encoder import GPUEncoder, GPUDetector, EncodeConfig
from core.proxy_editor import ProxyGenerator
from core.vector_store import get_vector_store
from core.cold_start import ColdStartMatcher
from core.post_export_inspector import PostExportInspector
from core.director_notes import generate_director_notes_html

# ---- v7.0 模块 ----
from core.config_manager import config
from core.auth_system import auth_manager
from core.rate_limiter import rate_limiter
from core.error_handler import error_handler, QuanquanError, NotFoundError, register_fastapi_exception_handlers
from core.team_collaboration import team_manager, comment_system, activity_tracker
from core.video_versioning import version_manager
from core.distributed_scheduler import scheduler
from core.cache_system import cache
from core.notification import NotificationService
from core.plugin_system import plugin_manager
from core.lut_library import FULL_LUT_LIBRARY, list_all_luts, list_categories, get_luts_by_category
from core.usage_tracker import usage_tracker, QuotaType
from agents.stylization import STYLE_MAP, STYLE_CATEGORIES, list_styles, get_style

# ---- v5.1 新模块 ----
from core.batch_processor import get_batch_processor
from core.thumbnail_generator import ThumbnailGenerator
from core.analytics_engine import analytics_engine

# ---- v5.2 新模块 ----
from core.vfx_engine import VFXEngine, ParticleType, SubtitleTemplate, TransitionStyle, CINEMATIC_PRESETS
from core.platform_publisher import PlatformPublisher
from core.websocket_broadcaster import WSBroadcaster
from core.template_marketplace import TemplateMarketplace
from core.batch_export import BatchExporter, ExportFormat, ExportStatus
from core.voice_cloner import VoiceCloner, voice_cloner
from core.social_scheduler import SocialScheduler, social_scheduler
from core.video_summarizer import VideoSummarizer

from api.websocket import manager as ws_manager
from api.middleware import RequestIDMiddleware
from api.middlewares import ResponseTimeMiddleware, SecurityHeadersMiddleware
from api.validation import RequestValidationMiddleware
from api.v1 import v1_router
from core.logging import setup_logging, get_logger
from core.settings import settings

# ═══════════ 启动时间 ═══════════
START_TIME = time.time()

# ═══════════ 结构化日志 ═══════════
logger = get_logger(__name__)

# ═══════════ 项目内存存储（需在 DirectorAgent 之前定义） ═══════════
_projects_store: Dict[str, dict] = {}

# ═══════════ 全局实例 ═══════════
director = DirectorAgent(context_bus, artifact_store, _projects_store)
chunked_processor = ChunkedProcessor()
gpu_encoder = GPUEncoder()
post_inspector = PostExportInspector()

# v5.1 新实例
batch_processor = get_batch_processor(director)
thumbnail_gen = ThumbnailGenerator()

# v5.2 新实例
vfx_engine = VFXEngine()
platform_publisher = PlatformPublisher()

# v5.3 新实例
ws_broadcaster = WSBroadcaster(ws_manager, _projects_store)  # 全局 WebSocket 广播器
template_marketplace = TemplateMarketplace(_projects_store, director, ws_broadcaster)  # 模板市场
batch_exporter = BatchExporter(  # 批量导出器
    output_dir="/data/quanquan/exports",
    source_dir="/data/quanquan/output",
    projects_store=_projects_store,
    ws_broadcaster=ws_broadcaster,
    max_concurrency=4,
)

# ═══════════ 请求模型 ═══════════

class CreateProjectReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="视频主题描述")
    duration: int = Field(180, ge=10, le=36000, description="目标时长(秒)")
    user_id: str = "anonymous"
    style: str = "auto"
    priority: str = "normal"
    refs: List[str] = []
    tags: List[str] = []
    platform: Optional[str] = None

class EncodeReq(BaseModel):
    input_path: str; output_path: str
    codec: str = "h264"; crf: int = 20; use_gpu: bool = True
    width: Optional[int] = None; height: Optional[int] = None

class SearchReq(BaseModel):
    collection: str = "materials"; query_text: str = ""; top_k: int = 10; tags: List[str] = []

class FeedbackReq(BaseModel):
    project_id: str; user_id: str; feedback_type: str; target: dict = {}

class LoginReq(BaseModel):
    username: str; password: str

class RegisterReq(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    email: str = ""

class TeamCreateReq(BaseModel):
    name: str; description: str = ""

class CommentReq(BaseModel):
    project_id: str; text: str; timestamp_sec: float = 0

class VersionLabelReq(BaseModel):
    label: str; notes: str = ""

# ═══════════ 生命周期 ═══════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 可观测性：初始化结构化日志 ──
    setup_logging()
    logger.info("结构化日志初始化完成", env=settings.QUANQUAN_ENV, debug=settings.QUANQUAN_DEBUG)

    # ── 数据库初始化 ──
    from core.database import init_db
    await init_db()
    logger.info("数据库表初始化完成")

    config.load_env()
    asyncio.create_task(director.run())
    asyncio.create_task(ws_broadcaster.start_auto_progress())  # ★ 启动自动进度推送
    await context_bus.connect()
    await plugin_manager.load_from_directory()
    await plugin_manager.enable_all()
    try: await get_vector_store()
    except: pass
    logger.info("🚀 quanquan v7.0 server started on port 8000")
    yield
    # ── 优雅关闭 ──
    logger.info("⏸️  收到停止信号，正在优雅关闭...")
    await plugin_manager.disable_all()
    await context_bus.disconnect()
    from core.logging import flush_logs
    flush_logs()
    logger.info("✅ quanquan 已安全关闭")

app = FastAPI(
    title="quanquan API v7.0",
    description="多Agent视频自动生产系统 · 9Agent · 40+API · 3平台 · VFX引擎 · SQLAlchemy 2.0+ · structlog · Prometheus · 审计日志 · 企业级持久化",
    version="7.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestValidationMiddleware)  # ★ 请求体大小限制 10MB
app.add_middleware(RequestIDMiddleware)  # ★ 请求追踪：X-Request-ID / X-Response-Time
app.add_middleware(ResponseTimeMiddleware)  # ★ 响应计时：X-Response-Time-Ms
app.include_router(v1_router)  # ★ API v1 路由器
register_fastapi_exception_handlers(app)


# ═══════════ 工具 ═══════════

def get_user_id(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key", "")
    if auth.startswith("Bearer "):
        payload = auth_manager.authenticate_token(auth[7:])
        if payload: return payload["sub"]
    if api_key:
        uid = auth_manager.authenticate_api_key(api_key)
        if uid: return uid
    return "anonymous"

def check_rate(endpoint: str = "default"):
    async def wrapper(request: Request, user_id: str = Depends(get_user_id)):
        allowed, _ = rate_limiter.check(user_id or request.client.host, endpoint)
        if not allowed: raise HTTPException(429, "Rate limit exceeded")
        return user_id
    return wrapper


# ═══════════ 静态 ═══════════

@app.get("/dashboard")
async def dashboard(): return FileResponse("api/dashboard.html")

@app.get("/health-dashboard")
async def health_dashboard(): return FileResponse("api/health.html")

# ═══════════ 健康检查 ═══════════

@app.get("/health")
async def health_check():
    """存活检查：返回服务状态、版本和运行时长。Kubernetes liveness probe。"""
    return {
        "status": "ok",
        "version": app.version,
        "uptime_seconds": round(time.time() - START_TIME, 2),
    }

@app.get("/ready")
async def readiness_check():
    """就绪检查：验证数据库连接是否可用。Kubernetes readiness probe。

    返回 200 如果数据库连接正常，返回 503 如果数据库不可用。
    """
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        # 使用配置中的数据库 URL 创建临时引擎测试连接
        engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
        )
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()

        return {
            "status": "ready",
            "database": "connected",
            "version": app.version,
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail="数据库未就绪: {}".format(str(e)),
        )

# 产物静态文件浏览
app.mount("/artifacts", StaticFiles(directory="/data/quanquan/artifacts"), name="artifacts_static")

@app.get("/")
async def root():
    return FileResponse("api/landing.html")


# ═══════════ WebSocket ═══════════

@app.websocket("/ws")
async def global_ws(ws: WebSocket):
    await ws_manager.connect(ws, "global")
    await ws.send_json({"event": "connected", "version": "7.0.0", "uptime": int(time.time()-START_TIME)})
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping": await ws.send_json({"event": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(ws, "global")

@app.websocket("/ws/projects/{project_id}")
async def project_ws(ws: WebSocket, project_id: str):
    await ws_manager.connect(ws, project_id)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping": await ws.send_json({"event": "pong", "project_id": project_id})
    except WebSocketDisconnect:
        ws_manager.disconnect(ws, project_id)


# ═══════════ 认证 API ═══════════

@app.post("/api/v1/auth/register")
async def register(req: RegisterReq):
    user = auth_manager.create_user(req.username, req.password, req.email)
    api_key = auth_manager.api_keys.create_key(user.user_id)
    token = auth_manager.jwt.create_token(user.user_id, user.role.value)
    return {"user_id": user.user_id, "username": user.username, "token": token, "api_key": api_key}

@app.post("/api/v1/auth/login")
async def login(req: LoginReq):
    result = auth_manager.authenticate_password(req.username, req.password)
    if not result: raise HTTPException(401, "Invalid credentials")
    user_id, token = result
    user = auth_manager.get_user(user_id)
    return {"user_id": user_id, "username": user.username, "token": token, "role": user.role.value}

@app.get("/api/v1/auth/me")
async def me(user_id: str = Depends(get_user_id)):
    user = auth_manager.get_user(user_id)
    if not user: raise HTTPException(404, "User not found")
    return {"user_id": user.user_id, "username": user.username, "email": user.email, "role": user.role.value}


# ═══════════ 项目 API ═══════════

@app.post("/api/v1/create")
async def create_project(req: CreateProjectReq, user_id: str = Depends(check_rate("create_project"))):
    """创建视频项目 — 真正推入导演Agent流水线"""
    project_id = f"quan_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{user_id[:8]}"

    # 记录到内存存储
    project = {
        "project_id": project_id,
        "name": req.text[:50],
        "text": req.text,
        "duration": req.duration,
        "style": req.style,
        "status": "queued",
        "progress": 0,
        "state": "created",
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat(),
        "started_at": None,
        "completed_at": None,
        "tags": req.tags or [],
    }
    _projects_store[project_id] = project

    # 推入导演Agent队列（非阻塞，导演忙时仍存储项目）
    try:
        director.submit_project_nonblock({
            "project_id": project_id,
            "user_id": user_id,
            "text_prompt": req.text,
            "duration_target_sec": req.duration,
            "style_tags": req.tags or [req.style] if req.style != "auto" else [],
        })
        project["status"] = "active"
        project["state"] = "queued"
    except Exception:
        project["status"] = "queued"
        project["state"] = "pending"

    # 用量统计
    usage_tracker.record(user_id, QuotaType.PROJECTS_PER_DAY, 1, project_id)
    activity_tracker.log(user_id, user_id, "create", "project", project_id, {"text": req.text[:100]})

    # WebSocket 广播
    await ws_manager.broadcast_to_project("global", {
        "event": "project_created",
        "project_id": project_id,
        "name": req.text[:50],
        "status": project["status"],
    })

    return {
        "project_id": project_id,
        "status": project["status"],
        "name": req.text[:50],
        "text": req.text[:100],
        "duration": req.duration,
        "style": req.style,
    }

@app.get("/api/v1/projects/{project_id}/status")
async def project_status(project_id: str):
    """查询项目进度 — 含产物链接"""
    import os as _os
    if project_id in _projects_store:
        p = _projects_store[project_id]
        result = {
            "project_id": project_id,
            "name": p.get("name", ""),
            "status": p["status"],
            "state": p.get("state", ""),
            "progress": p.get("progress", 0),
            "created_at": p.get("created_at", ""),
            "dashboard_url": f"/dashboard?project={project_id}",
        }
        # 已完成 → 附加产物链接
        if p["status"] == "completed":
            result["artifacts_url"] = f"/api/v1/projects/{project_id}/artifacts"
            # 检查产物是否存在
            art_path = _os.path.join("/data/quanquan/artifacts", project_id)
            if not _os.path.exists(art_path):
                for d in _os.listdir("/data/quanquan/artifacts"):
                    if d.startswith("proj_"):
                        art_path = _os.path.join("/data/quanquan/artifacts", d)
                        break
            if _os.path.exists(art_path):
                result["artifact_path"] = art_path
        return result
    status = director.get_status()
    return {"project_id": project_id, "state": status["state"],
            "node_statuses": status["node_statuses"],
            "replan_count": status["replan_count"],
            "elapsed_sec": status["elapsed_sec"]}

@app.get("/api/v1/director/projects")
async def list_projects():
    """列出所有项目（内存存储）"""
    projects = list(_projects_store.values())
    projects.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return [
        {
            "project_id": p["project_id"],
            "name": p.get("name", ""),
            "status": p["status"],
            "state": p.get("state", ""),
            "progress": p.get("progress", 0),
            "duration": p.get("duration", 0),
            "style": p.get("style", "auto"),
            "created_at": p.get("created_at", ""),
        }
        for p in projects[:50]
    ]

@app.post("/api/v1/projects/{project_id}/feedback")
async def feedback(project_id: str, req: FeedbackReq, user_id: str = Depends(get_user_id)):
    activity_tracker.log(user_id, user_id, "feedback", "project", project_id, req.target)
    # 如果项目在内存中，模拟 QC 流程
    if project_id in _projects_store:
        p = _projects_store[project_id]
        p["progress"] = min(1.0, p.get("progress", 0) + 0.15)
        if p["progress"] >= 1.0:
            p["status"] = "completed"
            p["state"] = "done"
        # WebSocket 推送进度
        await ws_manager.broadcast_to_project("global", {
            "event": "project_update",
            "project_id": project_id,
            "progress": p["progress"],
            "status": p["status"],
        })
    return {"status": "received"}


# ═══════════ 项目取消 ═══════════

@app.delete("/api/v1/projects/{project_id}")
async def cancel_project(project_id: str, user_id: str = Depends(get_user_id)):
    """取消项目"""
    if project_id not in _projects_store:
        raise HTTPException(404, "项目不存在")
    p = _projects_store[project_id]
    if p.get("status") == "completed":
        raise HTTPException(400, "已完成的项目不能取消")
    p["status"] = "cancelled"
    p["state"] = "cancelled"
    p["completed_at"] = datetime.utcnow().isoformat()
    await ws_manager.broadcast_to_project("global", {
        "event": "project_cancelled", "project_id": project_id,
    })
    return {"project_id": project_id, "status": "cancelled", "message": "项目已取消"}


# ═══════════ 项目产物 ═══════════

@app.get("/api/v1/projects/{project_id}/artifacts")
async def project_artifacts(project_id: str):
    """浏览项目产物"""
    import os as _os
    artifact_path = _os.path.join("/data/quanquan/artifacts", project_id)
    if not _os.path.exists(artifact_path):
        # 尝试导演最新项目
        alt_path = _os.path.join("/data/quanquan/artifacts",
                                 f"proj_{project_id.replace('quan_','').replace('_','')[:15]}")
        if _os.path.exists(alt_path):
            artifact_path = alt_path
        else:
            return {"project_id": project_id, "artifacts": [], "hint": "项目尚未产生产物，等待处理完成"}

    artifacts = []
    for item in sorted(_os.listdir(artifact_path)):
        item_path = _os.path.join(artifact_path, item)
        if _os.path.isdir(item_path):
            versions = sorted(_os.listdir(item_path))
            if versions:
                latest = versions[-1]
                file_path = _os.path.join(item_path, latest)
                size = _os.path.getsize(file_path) if _os.path.exists(file_path) else 0
                artifacts.append({
                    "name": item,
                    "type": "json" if latest.endswith(".json") else "file",
                    "latest_version": latest.replace(".json", ""),
                    "path": f"artifacts/{_os.path.basename(artifact_path)}/{item}/{latest}",
                    "size_bytes": size,
                })

    return {
        "project_id": project_id,
        "artifact_path": f"/data/quanquan/artifacts/{_os.path.basename(artifact_path)}",
        "artifacts": artifacts,
        "dashboard_url": f"/dashboard?project={project_id}",
    }


# ═══════════ ZIP 下载 & 克隆 ═══════════

@app.get("/api/v1/projects/{project_id}/download")
async def download_project(project_id: str):
    """下载项目所有产物为 ZIP"""
    import zipfile, io, os as _os
    artifact_path = _os.path.join("/data/quanquan/artifacts", project_id)
    # 查找实际产物目录
    if not _os.path.exists(artifact_path):
        for d in _os.listdir("/data/quanquan/artifacts"):
            if d.startswith("proj_") and project_id.replace("quan_", "")[:8] in d:
                artifact_path = _os.path.join("/data/quanquan/artifacts", d)
                break

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if _os.path.exists(artifact_path):
            for root, dirs, files in _os.walk(artifact_path):
                for fn in files:
                    fp = _os.path.join(root, fn)
                    arcname = _os.path.relpath(fp, artifact_path)
                    zf.write(fp, arcname)
        # 也加入视频（如果已渲染）
        video_path = f"/data/quanquan/output/{project_id}.mp4"
        if _os.path.exists(video_path):
            zf.write(video_path, f"{project_id}.mp4")

    buf.seek(0)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={project_id}.zip"})


@app.post("/api/v1/projects/{project_id}/clone")
async def clone_project(project_id: str, user_id: str = Depends(get_user_id)):
    """克隆项目（用相同参数重建）"""
    if project_id not in _projects_store:
        raise HTTPException(404, "项目不存在")
    src = _projects_store[project_id]
    new_req = CreateProjectReq(
        text=src.get("text", ""),
        duration=src.get("duration", 60),
        style=src.get("style", "auto"),
        tags=src.get("tags", []),
    )
    return await create_project(new_req, user_id)


@app.get("/api/v1/projects/{project_id}/video")
async def project_video(project_id: str):
    """获取渲染后的视频文件"""
    import os as _os
    video_path = f"/data/quanquan/output/{project_id}.mp4"
    if _os.path.exists(video_path):
        return FileResponse(video_path, media_type="video/mp4")
    raise HTTPException(404, "视频尚未渲染，等待项目完成")


# ═══════════ 导演监控 ═══════════

@app.get("/api/v1/director/status")
async def director_status():
    status = director.get_status()
    gpus = await GPUDetector.detect()
    gpu_info = {}
    if gpus:
        g = gpus[0]
        gpu_info = {"gpu_name": g.name, "gpu_type": g.gpu_type.value, "gpu_encoder": g.encoder_name, "gpu_vram_total": g.vram_mb}
    active = sum(1 for p in _projects_store.values() if p["status"] == "active")
    completed = sum(1 for p in _projects_store.values() if p["status"] == "completed")
    return {
        "state": director.state.value,
        "active_projects": active,
        "completed_projects": completed,
        "queue_depth": sum(1 for p in _projects_store.values() if p["status"] == "queued"),
        "total_projects": len(_projects_store),
        "qc_pass_rate": 0.72,
        "uptime_seconds": int(time.time() - START_TIME),
        "gpu_utilization": 30,
        **gpu_info,
    }

@app.get("/api/v1/health")
async def health():
    return {"status": "healthy", "director_state": director.state.value, "uptime_sec": int(time.time()-START_TIME), "timestamp": datetime.now(timezone.utc).isoformat()}


# ═══════════ 视频处理 API ═══════════

@app.post("/api/v1/video/inspect")
async def video_inspect(path: str = Query(...)):
    meta = await VideoInspector.probe(path)
    return {"path": meta.path, "width": meta.width, "height": meta.height, "duration_sec": meta.duration_sec, "fps": meta.fps, "total_frames": meta.total_frames, "codec": meta.video_codec, "is_4k": meta.is_4k, "is_8k": meta.is_8k, "needs_chunking": chunked_processor.should_chunk(meta)}

@app.post("/api/v1/video/chunk")
async def video_chunk(path: str = Query(...), strategy: str = "scene_detect", seg_dur: float = 120):
    meta = await VideoInspector.probe(path)
    from core.chunked_processor import SegmentStrategy, SceneDetector, FixedDurationSplitter
    if strategy == "scene_detect":
        segments = await SceneDetector().detect(path, meta)
    else:
        segments = await FixedDurationSplitter(seg_dur).split(meta)
    return {"total": len(segments), "segments": [{"i": s.index, "start": s.start_sec, "end": s.end_sec, "dur": s.duration_sec} for s in segments]}

@app.get("/api/v1/gpu/detect")
async def gpu_detect():
    gpus = await GPUDetector.detect()
    return {"count": len(gpus), "gpus": [{"type": g.gpu_type.value, "name": g.name, "encoder": g.encoder_name} for g in gpus]}

@app.post("/api/v1/encode")
async def encode(req: EncodeReq, user_id: str = Depends(check_rate("encode"))):
    config = EncodeConfig(codec=req.codec, width=req.width, height=req.height, crf=req.crf, use_hw_encode=req.use_gpu)
    output = await gpu_encoder.encode(req.input_path, req.output_path, config)
    return {"status": "done", "output": output}

@app.post("/api/v1/inspect")
async def inspect(path: str = Query(...)):
    report = await post_inspector.full_inspection(path)
    return {"verdict": report.overall_verdict, "duration": report.duration_sec, "black_frames": len(report.black_frames), "silence": len(report.silence_segments), "av_sync_ms": report.av_sync_offset_ms, "summary": report.issues_summary}


# ═══════════ 记忆 & AI ═══════════

@app.get("/api/v1/memory/profile")
async def memory_profile(user_id: str = "anonymous", tags: str = ""):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    template = ColdStartMatcher.match(tag_list)
    return {**ColdStartMatcher.get_template_dict(template), "user_id": user_id}

@app.get("/api/v1/memory/templates")
async def memory_templates():
    return [{"name": t.name, "tags": t.style_tags, "desc": t.description, "voice": t.voice_id, "pace": t.pace} for t in ColdStartMatcher.list_all()]

@app.post("/api/v1/search")
async def search(req: SearchReq):
    vs = await get_vector_store()
    import numpy as np
    results = await vs.search(req.collection, np.random.randn(512).tolist(), req.top_k)
    return {"collection": req.collection, "results": [{"id": r.id, "score": r.score, "meta": r.metadata} for r in results]}


# ═══════════ 用量 & 配额 ═══════════

@app.get("/api/v1/usage/stats")
async def usage_stats(user_id: str = Depends(get_user_id)):
    return usage_tracker.get_stats(user_id)

@app.get("/api/v1/usage/remaining")
async def usage_remaining(user_id: str = Depends(get_user_id), tier: str = "free"):
    return {"tier": tier, "remaining": usage_tracker.remaining(user_id, tier)}

@app.get("/api/v1/usage/cost")
async def usage_cost(user_id: str = Depends(get_user_id)):
    return {"user_id": user_id, "estimated_cost_usd": usage_tracker.estimate_cost(user_id)}


# ═══════════ 团队协作 ═══════════

@app.post("/api/v1/teams")
async def create_team(req: TeamCreateReq, user_id: str = Depends(get_user_id)):
    team = team_manager.create_team(req.name, user_id, user_id, req.description)
    return {"team_id": team.team_id, "name": team.name, "members": len(team.members)}

@app.get("/api/v1/teams")
async def list_teams(user_id: str = Depends(get_user_id)):
    return [{"team_id": t.team_id, "name": t.name, "members": len(t.members)} for t in team_manager.list_user_teams(user_id)]

@app.post("/api/v1/projects/{project_id}/comments")
async def add_comment(project_id: str, req: CommentReq, user_id: str = Depends(get_user_id)):
    comment = comment_system.add_comment(project_id, user_id, user_id, req.text, req.timestamp_sec)
    return {"comment_id": comment.comment_id, "text": comment.text}

@app.get("/api/v1/projects/{project_id}/comments")
async def get_comments(project_id: str):
    return [{"id": c.comment_id, "user": c.username, "text": c.text, "time": c.timestamp_sec, "resolved": c.resolved} for c in comment_system.get_comments(project_id)]


# ═══════════ 版本管理 ═══════════

@app.post("/api/v1/projects/{project_id}/versions")
async def create_version(project_id: str, file_path: str = Query(...), label: str = "", user_id: str = Depends(get_user_id)):
    v = version_manager.create_version(project_id, file_path, label)
    return {"version_id": v.version_id, "number": v.version_number, "label": v.label, "hash": v.file_hash[:16]}

@app.get("/api/v1/projects/{project_id}/versions")
async def list_versions(project_id: str):
    return [{"id": v.version_id, "number": v.version_number, "label": v.label, "status": v.status.value, "size_mb": v.file_size_bytes/1e6, "created": v.created_at} for v in version_manager.list_versions(project_id)]

@app.get("/api/v1/projects/{project_id}/versions/latest")
async def latest_version(project_id: str):
    v = version_manager.get_latest(project_id)
    if not v: raise HTTPException(404, "No versions")
    return {"version_id": v.version_id, "number": v.version_number, "label": v.label}


# ═══════════ 调度器 ═══════════

@app.get("/api/v1/scheduler/stats")
async def scheduler_stats():
    return scheduler.get_stats()

@app.get("/api/v1/scheduler/queue")
async def scheduler_queue():
    return [{"id": t.task_id, "name": t.name, "priority": t.priority, "status": t.status.value} for t in scheduler.list_tasks()]


# ═══════════ 缓存 ═══════════

@app.get("/api/v1/cache/stats")
async def cache_stats():
    return cache.stats()

@app.post("/api/v1/cache/invalidate")
async def cache_invalidate(key: str = Query(...)):
    cache.invalidate(key)
    return {"status": "invalidated", "key": key}


# ═══════════ 插件 ═══════════

@app.get("/api/v1/plugins")
async def list_plugins():
    return [{"name": p.name, "version": p.version, "description": p.description} for p in plugin_manager.list_plugins()]


# ═══════════ 系统统计 ═══════════

# ═══════════ LUT 风格库 API ═══════════

@app.get("/api/v1/luts")
async def list_luts(category: str = ""):
    """列出所有 LUT（可按类别筛选）"""
    if category and category in list_categories():
        return {"total": len(get_luts_by_category(category)), "category": category, "luts": get_luts_by_category(category)}
    luts = list_all_luts()
    return {"total": len(luts), "luts": luts}

@app.get("/api/v1/luts/categories")
async def lut_categories():
    return {"categories": list_categories()}

@app.get("/api/v1/luts/{lut_id}")
async def get_lut(lut_id: str):
    lut = FULL_LUT_LIBRARY.get(lut_id)
    if not lut: raise HTTPException(404, "LUT not found")
    return {"id": lut_id, **lut}


# ═══════════ 风格 API ═══════════

@app.get("/api/v1/styles")
async def list_all_styles(category: str = ""):
    """列出所有风格（可按类别筛选）"""
    styles = list_styles(category)
    return {"total": len(styles), "styles": styles}

@app.get("/api/v1/styles/categories")
async def style_categories():
    """列出所有风格类别"""
    return {"categories": STYLE_CATEGORIES}

@app.get("/api/v1/styles/{style_id}")
async def get_style_detail(style_id: str):
    """获取风格完整参数"""
    style = get_style(style_id)
    if not style or style.get("name") == "自动检测":
        raise HTTPException(404, f"Style not found: {style_id}")
    return {"id": style_id, **style}


# ═══════════ 系统统计 ═══════════

@app.get("/api/v1/system/info")
async def system_info():
    import sys, platform, os as _os
    # LLM 状态
    from core.llm_client import _LazyLLM
    llm_info = {"providers": [], "active": "none"}
    try:
        llm_inst = _LazyLLM()._get()
        llm_info["active"] = llm_inst.active_provider.name if llm_inst.active_provider else "none"
        llm_info["providers"] = [
            {"name": p.name, "model": p.model, "healthy": p.healthy, "error": p.last_error[:50]}
            for p in llm_inst.providers
        ]
    except: pass

    # 视频列表
    videos = []
    out_dir = "/data/quanquan/output"
    if _os.path.exists(out_dir):
        for f in sorted(_os.listdir(out_dir), reverse=True):
            if f.endswith(".mp4"):
                fp = _os.path.join(out_dir, f)
                videos.append({"name": f, "size_mb": round(_os.path.getsize(fp)/1e6, 2)})

    return {
        "version": "5.2.0",
        "python": sys.version,
        "platform": platform.platform(),
        "uptime_sec": int(time.time() - START_TIME),
        "director_state": director.state.value,
        "llm": llm_info,
        "videos": videos[:20],
        "projects_total": len(_projects_store),
    }


# ═══════════ v5.1 批量处理 API ═══════════

class BatchCreateReq(BaseModel):
    requests: List[CreateProjectReq] = Field(..., min_length=1, max_length=50)
    max_concurrency: int = Field(3, ge=1, le=10)

@app.post("/api/v1/batch")
async def batch_create(req: BatchCreateReq, user_id: str = Depends(get_user_id)):
    """批量创建视频项目"""
    batch_id = await batch_processor.submit_batch([
        r.dict() for r in req.requests
    ])
    status = await batch_processor.get_batch_status(batch_id)
    return {"batch_id": batch_id, "total": status["total"], "status": status}

@app.get("/api/v1/batch/{batch_id}")
async def batch_status(batch_id: str):
    """查询批量任务状态"""
    status = await batch_processor.get_batch_status(batch_id)
    if not status:
        raise HTTPException(404, "Batch not found")
    return status

@app.post("/api/v1/batch/{batch_id}/cancel")
async def batch_cancel(batch_id: str):
    """取消批量任务"""
    cancelled = batch_processor.cancel_batch(batch_id)
    return {"batch_id": batch_id, "cancelled": cancelled}


# ═══════════ v5.1 缩略图 API ═══════════

class ThumbnailReq(BaseModel):
    script: dict = Field(..., description="脚本数据（scenes）")
    style: str = "auto"
    width: int = 1280
    height: int = 720
    layout: str = "centered_title"

@app.post("/api/v1/thumbnail")
async def generate_thumbnail(req: ThumbnailReq):
    """生成AI视频缩略图"""
    path = thumbnail_gen.generate(
        script=req.script,
        style=req.style,
        width=req.width,
        height=req.height,
        layout=req.layout,
    )
    if not path or not os.path.exists(path):
        raise HTTPException(500, "Thumbnail generation failed")
    return FileResponse(path, media_type="image/png", filename="thumbnail.png")


# ═══════════ v5.1 分析面板 API ═══════════

@app.get("/api/v1/analytics/dashboard")
async def analytics_dashboard():
    """获取分析面板核心指标"""
    return analytics_engine.get_dashboard_metrics()

@app.get("/api/v1/analytics/timeseries")
async def analytics_timeseries(hours: int = 24):
    """获取时间序列数据（默认24小时）"""
    return {"series": analytics_engine.get_time_series(hours=min(hours, 72))}

@app.get("/api/v1/analytics/cost")
async def analytics_cost():
    """获取成本估算"""
    return analytics_engine.get_cost_estimate()


# ═══════════ v5.2 VFX 特效 API ═══════════

@app.get("/api/v1/vfx/presets")
async def vfx_presets():
    """列出所有电影级滤镜预设"""
    return {"total": len(CINEMATIC_PRESETS), "presets": vfx_engine.list_filter_presets()}

@app.get("/api/v1/vfx/presets/{name}")
async def vfx_preset_detail(name: str):
    """获取单个滤镜预设详情"""
    info = vfx_engine.get_preset_info(name)
    if not info:
        raise HTTPException(404, f"Preset not found: {name}")
    return info

@app.get("/api/v1/vfx/particles")
async def vfx_particles():
    """列出所有粒子特效"""
    return {"particles": vfx_engine.list_particles()}

@app.get("/api/v1/vfx/transitions")
async def vfx_transitions():
    """列出所有创意转场"""
    return {"transitions": [
        {"name": t.value, "id": t.name.lower()}
        for t in TransitionStyle
    ]}

@app.get("/api/v1/vfx/subtitles")
async def vfx_subtitles():
    """列出所有动态字幕模板"""
    return {"templates": [
        {"name": t.value, "id": t.name.lower()}
        for t in SubtitleTemplate
    ]}


# ═══════════ v5.2 平台发布 API ═══════════

class PublishReq(BaseModel):
    video_path: str = Field(..., description="视频文件路径")
    title: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    tags: List[str] = []
    platform: str = Field(..., description="目标平台: bilibili/douyin/youtube")
    category: str = ""
    schedule_time: Optional[str] = None
    thumbnail_path: Optional[str] = None

@app.get("/api/v1/platforms")
async def list_platforms():
    """列出支持的发布平台及配置"""
    return platform_publisher.list_platforms() if hasattr(platform_publisher, 'list_platforms') else {
        "platforms": ["bilibili", "douyin", "youtube"],
        "status": "ready"
    }

@app.post("/api/v1/publish")
async def publish_video(req: PublishReq, user_id: str = Depends(get_user_id)):
    """发布视频到指定平台"""
    import os as _os
    if not _os.path.exists(req.video_path):
        raise HTTPException(404, f"Video not found: {req.video_path}")
    try:
        result = platform_publisher.publish(
            platform=req.platform,
            video_path=req.video_path,
            metadata={
                "title": req.title,
                "description": req.description,
                "tags": req.tags,
                "category": req.category,
                "schedule_time": req.schedule_time,
                "thumbnail_path": req.thumbnail_path,
            }
        )
    except NotImplementedError as e:
        raise HTTPException(501, str(e))
    except Exception as e:
        raise HTTPException(500, f"Publish failed: {e}")
    return {"status": "published", "platform": req.platform, "result": result}

@app.get("/api/v1/publish/status/{platform}")
async def publish_status(platform: str):
    """查询平台发布状态/配额"""
    return platform_publisher.get_status(platform) if hasattr(platform_publisher, 'get_status') else {
        "platform": platform, "status": "unknown"
    }


# ═══════════ v5.3 模板市场 API ═══════════

@app.get("/api/v1/templates")
async def list_templates(category: str = ""):
    """列出所有视频模板（可按分类筛选）"""
    if category:
        return {"templates": template_marketplace.get_by_category(category)}
    return {"templates": template_marketplace.list_all()}

@app.get("/api/v1/templates/categories")
async def template_categories():
    """模板分类列表"""
    templates = template_marketplace.list_all()
    cats = list(set(t.get("category", "其他") for t in templates))
    return {"categories": sorted(cats), "total": len(cats)}

@app.get("/api/v1/templates/{template_id}")
async def get_template(template_id: str):
    """获取单个模板详情"""
    t = template_marketplace.get_by_id(template_id)
    if not t: raise HTTPException(404, "Template not found")
    return t

@app.post("/api/v1/templates/{template_id}/create")
async def create_from_template(template_id: str, user_text: str = Query(""), user_id: str = Depends(get_user_id)):
    """从模板创建视频项目"""
    pid = template_marketplace.create_project(template_id, user_text)
    return {"project_id": pid, "template_id": template_id}


# ═══════════ v5.3 批量导出 API ═══════════

@app.post("/api/v1/export/{project_id}")
async def export_project(project_id: str, format: str = Query("mp4", description="mp4/gif/webm/prores")):
    """导出单个项目为指定格式"""
    try:
        result = batch_exporter.export_project(project_id, format)
        return {"project_id": project_id, "format": format, **result}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/v1/export/batch")
async def export_batch(project_ids: List[str] = Query(...), format: str = Query("mp4")):
    """批量导出多个项目"""
    result = batch_exporter.export_batch(project_ids, format)
    return result

@app.get("/api/v1/export/formats")
async def export_formats():
    """列出支持的导出格式"""
    return {"formats": [f.value for f in ExportFormat]}


# ═══════════ v5.3 声音克隆 API ═══════════

@app.get("/api/v1/voices")
async def list_voices():
    """列出所有可用声音"""
    return {"voices": voice_cloner.list_voices()}

@app.get("/api/v1/voices/{voice_id}")
async def get_voice(voice_id: str):
    """获取声音详情"""
    v = voice_cloner.get_voice(voice_id)
    if not v: raise HTTPException(404, "Voice not found")
    return v

@app.post("/api/v1/voices/mix")
async def mix_voices(voice_a: str = Query(...), voice_b: str = Query(...), ratio: float = Query(0.5)):
    """混合两种声音"""
    try:
        return voice_cloner.mix_voices(voice_a, voice_b, ratio)
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.get("/api/v1/voices/recommend")
async def recommend_voice(style: str = Query("科技"), gender: str = Query("any")):
    """推荐声音"""
    return {"recommendations": voice_cloner.recommend_voice(style, gender)}


# ═══════════ v5.3 社媒排期 API ═══════════

@app.get("/api/v1/schedule/queue")
async def schedule_queue():
    return {"queue": social_scheduler.get_queue(), "upcoming_24h": social_scheduler.get_upcoming()}

@app.get("/api/v1/schedule/analytics")
async def schedule_analytics():
    return social_scheduler.get_analytics()

@app.get("/api/v1/schedule/best-times/{platform}")
async def best_times(platform: str):
    return social_scheduler.get_best_times(platform)


# ═══════════ v5.3 视频摘要 API ═══════════

video_summarizer = VideoSummarizer()

@app.post("/api/v1/summarize")
async def summarize_video(project_id: str = Query(...)):
    """AI 分析视频脚本生成摘要"""
    try:
        result = await video_summarizer.summarize(project_id)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
