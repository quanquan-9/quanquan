"""
Celery 分布式任务队列 — 视频渲染 + Agent调用 + GPU调度
"""
import os
from celery import Celery

# ═══════════ Celery App 配置 ═══════════

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "quanquan",
    broker=redis_url,
    backend=redis_url,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 三队列，差异化超时
    task_routes={
        "worker.celery_app.render_video_task": {"queue": "video_long"},
        "worker.celery_app.render_short_task": {"queue": "video_short"},
        "worker.celery_app.run_agent_task": {"queue": "video_long"},
        "worker.celery_app.run_qc_task": {"queue": "video_short"},
    },
    task_annotations={
        "worker.celery_app.render_video_task": {
            "time_limit": 600,   # 10分钟
            "soft_time_limit": 480,
            "max_retries": 2,
        },
        "worker.celery_app.render_short_task": {
            "time_limit": 180,   # 3分钟
            "soft_time_limit": 120,
            "max_retries": 1,
        },
        "worker.celery_app.run_agent_task": {
            "time_limit": 300,
            "soft_time_limit": 240,
            "max_retries": 3,
        },
        "worker.celery_app.run_qc_task": {
            "time_limit": 120,
            "soft_time_limit": 90,
            "max_retries": 2,
        },
    },
)


# ═══════════ 任务定义 ═══════════

@app.task(bind=True, name="render_video_task")
def render_video_task(self, project_id: str, draft_data: dict, output_path: str) -> dict:
    """视频渲染任务（长任务）"""
    try:
        # TODO: 调用剪映或FFmpeg渲染
        return {"status": "success", "project_id": project_id, "output": output_path}
    except Exception as e:
        self.retry(exc=e, countdown=30)


@app.task(bind=True, name="render_short_task")
def render_short_task(self, project_id: str, clip_data: dict) -> dict:
    """短视频/片段渲染（短任务）"""
    try:
        return {"status": "success", "project_id": project_id, "clip": clip_data.get("id")}
    except Exception as e:
        self.retry(exc=e, countdown=10)


@app.task(bind=True, name="run_agent_task")
def run_agent_task(self, agent_name: str, node_id: str, input_data: dict) -> dict:
    """通用 Agent 调用任务"""
    try:
        result = {"agent": agent_name, "node_id": node_id, "status": "success"}
        # Agent 调度由 Director 的 DAG Executor 完成
        return result
    except Exception as e:
        self.retry(exc=e, countdown=15)


@app.task(bind=True, name="run_qc_task")
def run_qc_task(self, project_id: str, video_path: str) -> dict:
    """QC 检测任务"""
    try:
        from adapters.ffmpeg_inspector import ffmpeg_inspector
        return ffmpeg_inspector.run_full_inspection(video_path)
    except Exception as e:
        self.retry(exc=e, countdown=20)
