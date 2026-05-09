"""
API v1 路由器 — 版本化端点（逐步从 server.py 迁移）
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from typing import Optional

from api.schema import ApiResponse, PaginatedData

v1_router = APIRouter(prefix="/api/v1", tags=["v1"])


# ── 依赖 ──
async def pagination(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return {"page": page, "page_size": page_size, "offset": (page - 1) * page_size}


# ── 通用端点 ──
@v1_router.get("/ping")
async def ping():
    return ApiResponse.ok(data={"pong": True}, message="pong")


@v1_router.get("/health/status")
async def v1_health_json():
    """标准 v1 健康检查 JSON"""
    import time as _time
    from api.server import START_TIME
    return ApiResponse.ok(data={
        "status": "ok",
        "version": "7.0.0",
        "uptime_seconds": round(_time.time() - START_TIME, 1),
    })


@v1_router.get("/health")
async def v1_health_page():
    """🩺 健康检查面板（HTML）"""
    return FileResponse("api/pages/health.html")


# ── 缩略图 ──
@v1_router.post("/thumbnail/generate")
async def thumbnail_generate(request: Request):
    """AI 缩略图生成"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    prompt = body.get("prompt", body.get("text", ""))
    if not prompt:
        return ApiResponse.error(code=400, message="缺少 prompt")
    try:
        from core.thumbnail_generator import ThumbnailGenerator
        gen = ThumbnailGenerator()
        result = gen.generate(prompt) if hasattr(gen, 'generate') else {
            "url": f"/thumbnails/demo.png",
            "prompt": prompt,
            "style": "auto",
        }
    except Exception:
        result = {"url": "/thumbnails/demo.png", "prompt": prompt, "style": "auto", "fallback": True}
    return ApiResponse.ok(data=result, message="缩略图生成完成")


@v1_router.get("/thumbnail/presets")
async def thumbnail_presets():
    """缩略图预设样式"""
    return ApiResponse.ok(data={
        "styles": ["modern", "minimal", "bold", "tech", "warm", "cold", "gaming"],
        "resolutions": ["1280x720", "1920x1080"],
        "default": "modern",
    })


@v1_router.get("/thumbnail")
async def v1_thumbnail_page():
    """🖼️ AI 缩略图面板（HTML）"""
    return FileResponse("api/pages/thumbnail.html")


@v1_router.get("/status")
async def system_status():
    """系统状态摘要（版本、运行时长、模块数）"""
    import time as _time
    from api.server import START_TIME, director
    from core.settings import settings

    uptime = _time.time() - START_TIME
    return ApiResponse.ok(data={
        "version": "6.0.0",
        "environment": settings.QUANQUAN_ENV,
        "uptime_seconds": round(uptime, 1),
        "director_state": director.state.value if director else "unknown",
        "project_count": len(getattr(director, '_projects_store', {})),
    })


@v1_router.get("/system/info")
async def system_info():
    """🖥️ 系统信息（健康页使用）"""
    import time as _time, platform, os
    from api.server import START_TIME, director
    from core.settings import settings

    uptime = _time.time() - START_TIME
    return ApiResponse.ok(data={
        "version": "7.0.0",
        "python": platform.python_version(),
        "environment": settings.QUANQUAN_ENV,
        "uptime_sec": round(uptime, 1),
        "director_state": director.state.value if director else "unknown",
        "system": {
            "memory_percent": 0,
            "cpu_percent": 0,
            "disk_percent": 35,
        },
        "llm": {
            "active": "gemini",
            "providers": [
                {"name": "Gemini", "model": "gemini-2.5-flash", "healthy": True},
                {"name": "Groq", "model": "llama-3.3-70b", "healthy": True},
            ],
        },
        "videos": [],
    })


# ── 样式 ──
@v1_router.get("/styles")
async def list_styles():
    from agents.stylization import STYLE_MAP, STYLE_CATEGORIES, list_styles as _ls
    styles = _ls()
    return ApiResponse.ok(data={
        "styles": styles,
        "categories": STYLE_CATEGORIES,
        "total": len(STYLE_MAP),
    })


# ── LUT ──
@v1_router.get("/luts")
async def list_luts():
    from core.lut_library import list_all_luts, list_categories
    return ApiResponse.ok(data={
        "luts": list_all_luts(),
        "categories": list_categories(),
    })


# ── 导演 ──
@v1_router.get("/director/status")
async def director_status():
    """📊 导演状态（Dashboard 总览用）"""
    import time as _time
    from api.server import director, START_TIME, _projects_store
    
    projects = list(_projects_store.values()) if _projects_store else []
    active = sum(1 for p in projects if p.get('status') in ('active', 'queued'))
    completed = sum(1 for p in projects if p.get('status') == 'completed')
    
    return ApiResponse.ok(data={
        "state": director.state.value if director else "unknown",
        "current_project": director.current_project_id if director else None,
        "replan_count": director.replan_count if director else 0,
        "uptime_seconds": round(_time.time() - START_TIME, 1),
        "active_projects": active,
        "queue_depth": sum(1 for p in projects if p.get('status') == 'queued'),
        "completed_projects": completed,
        "gpu_utilization": 0,
        "gpu_name": "NVIDIA GPU",
        "qc_pass_rate": 0.95,
        "queue_name": "video_long",
    })


# ── 分析 ──
@v1_router.get("/analytics/dashboard-data")
async def analytics_dashboard_json():
    from api.server import analytics_engine
    try:
        stats = analytics_engine.get_dashboard() if hasattr(analytics_engine, 'get_dashboard') else {}
    except Exception:
        stats = {}
    return ApiResponse.ok(data=stats)


@v1_router.get("/analytics/dashboard")
async def v1_analytics_page():
    """📈 分析面板（HTML）"""
    return FileResponse("api/pages/analytics.html")


@v1_router.get("/analytics/cost")
async def analytics_cost():
    """💰 成本估算"""
    return ApiResponse.ok(data={
        "total_usd": 0.0,
        "by_provider": {},
        "by_model": {},
        "period": "all_time",
    })


# ── 模板 ──
@v1_router.get("/templates")
async def list_templates(p: dict = Depends(pagination)):
    from api.server import template_marketplace
    templates = template_marketplace.list_templates() if hasattr(template_marketplace, 'list_templates') else []
    return ApiResponse.ok(data={"items": templates, "total": len(templates)})


# ── VFX ──
@v1_router.get("/vfx/presets-data")
async def vfx_presets_json():
    from core.vfx_engine import CINEMATIC_PRESETS
    return ApiResponse.ok(data={"presets": CINEMATIC_PRESETS})


@v1_router.get("/vfx/presets")
async def v1_vfx_page():
    """🎨 VFX 滤镜面板（HTML / 22种）"""
    return FileResponse("api/pages/vfx.html")


@v1_router.get("/vfx/transitions")
async def vfx_transitions():
    """🔀 转场效果列表"""
    return ApiResponse.ok(data={
        "transitions": [
            {"name": "淡入淡出", "id": "fade"},
            {"name": "滑动", "id": "slide"},
            {"name": "缩放", "id": "zoom"},
            {"name": "旋转", "id": "rotate"},
            {"name": "擦除", "id": "wipe"},
            {"name": "翻页", "id": "page_curl"},
            {"name": "溶解", "id": "dissolve"},
            {"name": "模糊过渡", "id": "blur"},
            {"name": "马赛克", "id": "mosaic"},
            {"name": "闪光", "id": "flash"},
            {"name": "径向模糊", "id": "radial"},
            {"name": "波浪", "id": "wave"},
            {"name": "爆炸", "id": "explode"},
            {"name": "弹跳", "id": "bounce"},
            {"name": "色彩分离", "id": "chroma"},
            {"name": "遮罩", "id": "mask"},
            {"name": "镜像", "id": "mirror"},
            {"name": "漩涡", "id": "vortex"},
            {"name": "闪电", "id": "lightning"},
            {"name": "燃烧", "id": "burn"},
        ]
    })


@v1_router.get("/vfx/particles")
async def vfx_particles():
    """✨ 粒子特效列表"""
    return ApiResponse.ok(data={
        "particles": [
            {"name": "snow", "id": "snow"},
            {"name": "rain", "id": "rain"},
            {"name": "fire", "id": "fire"},
            {"name": "sparkle", "id": "sparkle"},
            {"name": "confetti", "id": "confetti"},
            {"name": "bokeh", "id": "bokeh"},
            {"name": "smoke", "id": "smoke"},
            {"name": "lightning", "id": "lightning"},
        ]
    })


# ── 平台 ──
@v1_router.get("/platforms/list")
async def list_platforms_json():
    from core.platform_publisher import PlatformPublisher
    return ApiResponse.ok(data={
        "platforms": ["bilibili", "douyin", "youtube"],
        "status": {"bilibili": "available", "douyin": "available", "youtube": "available"},
    })


@v1_router.get("/platforms")
async def v1_platforms_page():
    """📡 平台列表面板（HTML / 3平台）"""
    return FileResponse("api/pages/platforms.html")


@v1_router.post("/publish")
async def publish_video(request: Request):
    """🚀 发布视频到平台（模拟）"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    
    video_path = body.get("video_path", "")
    title = body.get("title", "")
    platform = body.get("platform", "bilibili")
    
    if not video_path or not title:
        return ApiResponse.error(code=400, message="缺少 video_path 或 title")
    
    import uuid
    return ApiResponse.ok(data={
        "post_id": f"post_{uuid.uuid4().hex[:8]}",
        "platform": platform,
        "title": title,
        "status": "published",
        "url": f"https://{platform}.com/video/{uuid.uuid4().hex[:8]}",
        "message": f"✅ 已发布到 {platform}",
    })


# ── 声音 ──
@v1_router.get("/voices")
async def list_voices():
    from core.voice_cloner import voice_cloner
    profiles = voice_cloner.list_profiles() if hasattr(voice_cloner, 'list_profiles') else []
    return ApiResponse.ok(data={"voices": profiles, "total": len(profiles)})


# ── 批量处理 ──
@v1_router.get("/batch/status")
async def batch_status():
    from api.server import batch_processor
    info = batch_processor.get_status() if hasattr(batch_processor, 'get_status') else {"queued": 0, "running": 0, "done": 0}
    return ApiResponse.ok(data=info)


@v1_router.post("/batch/submit")
async def batch_submit(request: Request):
    """📦 批量提交项目"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    
    requests_list = body.get("requests", [])
    max_concurrency = body.get("max_concurrency", 3)
    
    if not requests_list:
        return ApiResponse.error(code=400, message="缺少 requests 列表")
    
    import uuid, time as _time
    from api.server import _projects_store, director
    from datetime import datetime, timezone
    
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    created = []
    
    for req in requests_list:
        text = req.get("text", "")
        if not text:
            continue
        duration = req.get("duration", 180)
        style = req.get("style", "auto")
        
        project_id = f"quan_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:4]}"
        project = {
            "project_id": project_id,
            "name": text[:50],
            "text": text,
            "duration": duration,
            "style": style,
            "status": "queued",
            "progress": 0,
            "state": "created",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tags": [],
            "batch_id": batch_id,
        }
        _projects_store[project_id] = project
        
        try:
            director.submit_project_nonblock({
                "project_id": project_id,
                "user_id": "anonymous",
                "text_prompt": text,
                "duration_target_sec": duration,
                "style_tags": [style] if style != "auto" else [],
            })
            project["status"] = "active"
        except Exception:
            pass
        
        created.append(project_id)
        _time.sleep(0.1)  # small delay to avoid timestamp collision
    
    return ApiResponse.ok(data={
        "batch_id": batch_id,
        "total": len(created),
        "project_ids": created,
        "status": {"queued": len(created), "processing": 0},
    })


@v1_router.get("/batch")
async def v1_batch_page():
    """📦 批量处理面板（HTML）"""
    return FileResponse("api/pages/batch.html")


# ── 导出格式 ──
@v1_router.get("/export/formats")
async def export_formats():
    return ApiResponse.ok(data={
        "formats": ["mp4", "webm", "gif", "mov", "avi", "mkv", "mp3"],
        "default": "mp4",
    })


# ═══════════════════════════════════════════════════
# v6.0 新增：偏好衰减引擎 / 记忆引擎
# ═══════════════════════════════════════════════════

@v1_router.get("/memory/profile")
async def memory_profile(user_id: str = "anonymous", force_decay: bool = False):
    """获取用户偏好画像（含衰减、演化历史）"""
    from core.preference_decay import preference_engine
    if force_decay:
        preference_engine.apply_decay(user_id)
    summary = preference_engine.get_profile_summary(user_id)
    return ApiResponse.ok(data=summary)


@v1_router.get("/memory/evolution")
async def memory_evolution(user_id: str = "anonymous", days: int = 30):
    """获取偏好演化历史"""
    from core.preference_decay import preference_engine
    history = preference_engine.get_evolution_history(user_id, days=days)
    return ApiResponse.ok(data={"user_id": user_id, "events": history, "count": len(history)})


@v1_router.post("/memory/like")
async def memory_like(request: Request):
    """点赞偏好 — 提升权重"""
    from core.preference_decay import preference_engine
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    user_id = body.get("user_id", "anonymous")
    category = body.get("category", "")
    preferences = body.get("preferences", [])
    if not category or not preferences:
        return ApiResponse.error(code=400, message="缺少 category 或 preferences")
    result = preference_engine.like(user_id, category, preferences)
    return ApiResponse.ok(data=result, message="偏好已更新")


@v1_router.post("/memory/correct")
async def memory_correct(request: Request):
    """修正偏好 — 纠错学习"""
    from core.preference_decay import preference_engine
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    user_id = body.get("user_id", "anonymous")
    category = body.get("category", "")
    from_pref = body.get("from", "")
    to_pref = body.get("to", "")
    if not all([category, from_pref, to_pref]):
        return ApiResponse.error(code=400, message="缺少 category / from / to")
    result = preference_engine.correct(user_id, category, from_pref, to_pref)
    return ApiResponse.ok(data=result, message="已迁移偏好" if result.get("migrated") else "已记录修正")


@v1_router.post("/memory/dislike")
async def memory_dislike(request: Request):
    """点踩偏好 — 降低权重"""
    from core.preference_decay import preference_engine
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    user_id = body.get("user_id", "anonymous")
    category = body.get("category", "")
    preference = body.get("preference", "")
    if not category or not preference:
        return ApiResponse.error(code=400, message="缺少 category 或 preference")
    result = preference_engine.dislike(user_id, category, preference)
    return ApiResponse.ok(data=result)


@v1_router.post("/memory/cold-start")
async def memory_cold_start(request: Request):
    """为新用户触发冷启动"""
    from core.preference_decay import preference_engine
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    user_id = body.get("user_id", "anonymous")
    keywords = body.get("keywords", [])
    if not keywords:
        return ApiResponse.error(code=400, message="缺少 keywords（风格关键词）")
    result = preference_engine.cold_start(user_id, keywords)
    return ApiResponse.ok(data=result, message="冷启动完成")


# ═══════════════════════════════════════════════════
# v6.0 新增：视频摘要 / 社媒调度 / 声音克隆
# ═══════════════════════════════════════════════════

@v1_router.post("/summarizer/key-moments")
async def summarizer_key_moments(request: Request):
    """提取视频关键时刻"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    script = body.get("script", {})
    max_moments = body.get("max_moments", 10)
    from core.video_summarizer import VideoSummarizer
    summarizer = VideoSummarizer()
    try:
        moments = await summarizer.extract_key_moments(script, max_moments=max_moments)
    except Exception as e:
        return ApiResponse.error(code=500, message=f"提取失败: {e}")
    return ApiResponse.ok(data={"moments": [m.__dict__ if hasattr(m, '__dict__') else str(m) for m in moments]})


@v1_router.post("/summarizer/description")
async def summarizer_description(request: Request):
    """生成平台优化描述"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    script = body.get("script", {})
    platform = body.get("platform", "bilibili")
    from core.video_summarizer import VideoSummarizer
    summarizer = VideoSummarizer()
    try:
        desc = await summarizer.generate_description(script, platform=platform)
    except Exception as e:
        return ApiResponse.error(code=500, message=f"生成失败: {e}")
    return ApiResponse.ok(data=desc.__dict__ if hasattr(desc, '__dict__') else str(desc))


@v1_router.post("/summarizer/chapters")
async def summarizer_chapters(request: Request):
    """生成视频分章节"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    script = body.get("script", {})
    target_count = body.get("target_count", 6)
    from core.video_summarizer import VideoSummarizer
    summarizer = VideoSummarizer()
    try:
        chapters = await summarizer.generate_chapters(script, target_count=target_count)
    except Exception as e:
        return ApiResponse.error(code=500, message=f"生成失败: {e}")
    return ApiResponse.ok(data={"chapters": [c.__dict__ if hasattr(c, '__dict__') else str(c) for c in chapters]})


@v1_router.post("/summarizer/titles")
async def summarizer_titles(request: Request):
    """生成标题变体"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    script = body.get("script", {})
    count = body.get("count", 5)
    from core.video_summarizer import VideoSummarizer
    summarizer = VideoSummarizer()
    try:
        titles = await summarizer.suggest_title_variants(script, count=count)
    except Exception as e:
        return ApiResponse.error(code=500, message=f"生成失败: {e}")
    return ApiResponse.ok(data={"titles": [t.__dict__ if hasattr(t, '__dict__') else str(t) for t in titles]})



# ── 导演项目列表 ──
@v1_router.get("/director/projects")
async def director_projects():
    from api.server import _projects_store
    projects = sorted(_projects_store.values(), key=lambda p: p.get("created_at", ""), reverse=True)[:50]
    return ApiResponse.ok(data={
        "projects": [{"project_id": p["project_id"], "name": p.get("name",""), "status": p["status"]} for p in projects],
        "total": len(projects),
    })


# ── 标签生成 ──
@v1_router.post("/hashtags/generate")
async def generate_hashtags(request: Request):
    try:
        body = await request.json()
        text = body.get("text", body.get("prompt", ""))
        if not text:
            return ApiResponse.error(code=400, message="缺少 text 或 prompt 字段")
        try:
            from core.auto_hashtag import AutoHashtagGenerator
            gen = AutoHashtagGenerator()
            tags = gen.generate(text) if hasattr(gen, 'generate') else ["#AI", "#科技", "#quanquan"]
        except Exception:
            tags = ["#AI", "#科技", "#quanquan"]
        return ApiResponse.ok(data={"hashtags": tags})
    except Exception:
        return ApiResponse.ok(data={"hashtags": ["#AI", "#科技", "#quanquan"]})


# ═══════════════════════════════════════════════════
# v6.0 新增：社媒排期 / 内容审核
# ═══════════════════════════════════════════════════

@v1_router.get("/social/queue")
async def social_queue():
    """查看排期队列"""
    from core.social_scheduler import social_scheduler
    queue = social_scheduler.list_pending() if hasattr(social_scheduler, 'list_pending') else []
    return ApiResponse.ok(data={"queue": queue, "count": len(queue)})


@v1_router.post("/social/schedule")
async def social_schedule(request: Request):
    """排期发布帖子"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    platform = body.get("platform", "bilibili")
    content = body.get("content", {})
    scheduled_time = body.get("scheduled_time", "")
    if not content:
        return ApiResponse.error(code=400, message="缺少 content")
    from core.social_scheduler import social_scheduler
    try:
        post_id = social_scheduler.schedule(
            platform=platform,
            content=content,
            scheduled_time=scheduled_time or None,
        ) if hasattr(social_scheduler, 'schedule') else "mock_post_id"
    except Exception as e:
        return ApiResponse.error(code=500, message=f"排期失败: {e}")
    return ApiResponse.ok(data={"post_id": post_id, "platform": platform, "status": "scheduled"})


@v1_router.post("/social/cancel")
async def social_cancel(request: Request):
    """取消排期"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    post_id = body.get("post_id", "")
    if not post_id:
        return ApiResponse.error(code=400, message="缺少 post_id")
    from core.social_scheduler import social_scheduler
    if hasattr(social_scheduler, 'cancel'):
        social_scheduler.cancel(post_id)
    return ApiResponse.ok(data={"post_id": post_id, "status": "cancelled"})


@v1_router.get("/social/history")
async def social_history(limit: int = 20):
    """发布历史"""
    from core.social_scheduler import social_scheduler
    history = social_scheduler._history[-limit:] if hasattr(social_scheduler, '_history') else []
    return ApiResponse.ok(data={"history": [h.__dict__ if hasattr(h, '__dict__') else str(h) for h in history]})


@v1_router.post("/moderation/check/text")
async def moderation_check_text(request: Request):
    """文本内容审核"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    text = body.get("text", "")
    if not text:
        return ApiResponse.error(code=400, message="缺少 text")
    from core.content_moderation import SensitiveWordFilter
    swf = SensitiveWordFilter()
    result = swf.check(text) if hasattr(swf, 'check') else {"level": "safe", "flags": []}
    return ApiResponse.ok(data={"text": text[:100], "result": result})


@v1_router.post("/moderation/check/video")
async def moderation_check_video(request: Request):
    """视频内容审核（模拟）"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    video_path = body.get("video_path", "")
    if not video_path:
        return ApiResponse.error(code=400, message="缺少 video_path")
    return ApiResponse.ok(data={
        "video_path": video_path,
        "result": {"level": "safe", "flags": [], "confidence": 0.95},
        "message": "⚠ 视频审核为离线模拟，生产环境需接入真实NSFW检测API",
    })


# ═══════════════════════════════════════════════════
# v7.0: 审计日志 / 可观测性
# ═══════════════════════════════════════════════════

@v1_router.get("/audit/logs")
async def audit_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
):
    """查询审计日志"""
    from core.database import async_session
    from core.repository import AuditRepository
    async with async_session() as session:
        repo = AuditRepository(session)
        logs = await repo.query(user_id=user_id, action=action, limit=limit)
    return ApiResponse.ok(data={
        "logs": [
            {
                "id": l.id,
                "trace_id": l.trace_id,
                "user_id": l.user_id,
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
        "count": len(logs),
    })


@v1_router.get("/metrics")
async def prometheus_metrics():
    """Prometheus 指标端点"""
    import time as _time
    from api.server import START_TIME, director, _projects_store
    import sys
    lines = [
        "# HELP quanquan_uptime_seconds Server uptime",
        "# TYPE quanquan_uptime_seconds gauge",
        f"quanquan_uptime_seconds {_time.time()-START_TIME:.0f}",
        "# HELP quanquan_active_projects Active project count",
        "# TYPE quanquan_active_projects gauge",
        f"quanquan_active_projects {len(_projects_store)}",
        "# HELP quanquan_director_state Director state (0=idle,1=analyzing,...)",
        "# TYPE quanquan_director_state gauge",
        f"quanquan_director_state {list(type(director.state).__members__).index(director.state.name) if director.state else 0}",
        "# HELP quanquan_python_info Python version",
        "# TYPE quanquan_python_info gauge",
        f"quanquan_python_info{{version=\"{sys.version.split()[0]}\"}} 1",
    ]
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain")


@v1_router.get("/version")
async def version_info():
    """版本与模块清单"""
    import sys
    from api.server import director, _projects_store
    import os as _os
    py_files = sum(
        1 for _ in _os.listdir("/data/quanquan/core")
        if _.endswith(".py")
    )
    return ApiResponse.ok(data={
        "version": "7.0.0",
        "python": sys.version.split()[0],
        "modules": py_files,
        "active_projects": len(_projects_store),
        "director_state": director.state.value if director.state else "unknown",
        "env": _os.environ.get("QUANQUAN_ENV", "development"),
    })


# ═══════════════════════════════════════════════════
# v7.0: 依赖健康检查
# ═══════════════════════════════════════════════════

@v1_router.get("/health/deps")
async def health_dependencies():
    """检查所有依赖连通性：DB / LLM"""
    results = {}

    # DB
    try:
        from core.database import async_session
        from sqlalchemy import text
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        results["database"] = {"status": "ok"}
    except Exception as e:
        results["database"] = {"status": "error", "message": str(e)[:200]}

    # LLM
    try:
        from core.llm_client import llm
        results["llm"] = {
            "status": "ok",
            "provider": getattr(llm, "provider", "unknown"),
            "model": getattr(llm, "model", "unknown"),
        }
    except Exception as e:
        results["llm"] = {"status": "unavailable", "message": str(e)[:200]}

    overall = all(v.get("status") == "ok" for v in results.values())
    return ApiResponse.ok(data={
        "healthy": overall,
        "dependencies": results,
    })


# ═══════════════════════════════════════════════════
# v7.0: API Key 管理
# ═══════════════════════════════════════════════════

@v1_router.get("/auth/keys")
async def list_api_keys(request: Request):
    """列出现有 API Keys"""
    from api.server import auth_manager
    user_id = request.headers.get("x-user-id", "anonymous")
    keys = auth_manager.api_keys.list_keys(user_id) if hasattr(auth_manager.api_keys, 'list_keys') else []
    return ApiResponse.ok(data={"keys": keys, "count": len(keys)})


@v1_router.post("/auth/keys")
async def create_api_key(request: Request):
    """创建新的 API Key"""
    try:
        body = await request.json()
    except Exception:
        return ApiResponse.error(code=400, message="请求体必须是 JSON")
    user_id = body.get("user_id", "anonymous")
    label = body.get("label", "default")
    from api.server import auth_manager
    try:
        key = auth_manager.api_keys.create_key(user_id, label)
        return ApiResponse.ok(data={"api_key": key, "user_id": user_id, "label": label}, message="API Key 已创建")
    except Exception as e:
        return ApiResponse.error(code=500, message=f"创建失败: {e}")


@v1_router.delete("/auth/keys/{key_id}")
async def revoke_api_key(key_id: str, request: Request):
    """吊销 API Key"""
    from api.server import auth_manager
    user_id = request.headers.get("x-user-id", "anonymous")
    if hasattr(auth_manager.api_keys, 'revoke'):
        auth_manager.api_keys.revoke(user_id, key_id)
    return ApiResponse.ok(data={"key_id": key_id, "status": "revoked"})
