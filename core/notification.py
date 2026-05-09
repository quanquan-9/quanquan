"""
通知系统 (Notification System)

功能：
- 邮件通知 (SMTP)
- Webhook (企业微信/钉钉/飞书/Slack/Discord)
- 项目完成/失败通知
- 系统告警
"""

import asyncio
import json
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class NotificationLevel(Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class NotificationConfig:
    """通知配置"""
    email_enabled: bool = False
    email_smtp_host: str = "smtp.qq.com"
    email_smtp_port: int = 587
    email_user: str = ""
    email_password: str = ""
    email_to: List[str] = None

    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_type: str = "feishu"  # feishu / dingtalk / wecom / slack / discord

    def __post_init__(self):
        self.email_to = self.email_to or []


class NotificationService:
    """统一通知服务"""

    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or NotificationConfig()

    async def notify(
        self,
        title: str,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
        project_id: str = "",
        extra: Optional[Dict] = None,
    ):
        """发送通知（邮件 + Webhook）"""
        tasks = []

        if self.config.email_enabled and self.config.email_to:
            tasks.append(self._send_email(title, message, level))

        if self.config.webhook_enabled and self.config.webhook_url:
            tasks.append(self._send_webhook(title, message, level, project_id, extra))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_email(self, title: str, message: str, level: NotificationLevel):
        """发送邮件"""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[quanquan] {level.value.upper()}: {title}"
            msg["From"] = self.config.email_user
            msg["To"] = ", ".join(self.config.email_to)

            # HTML 邮件
            color = {
                NotificationLevel.SUCCESS: "#22c55e",
                NotificationLevel.WARNING: "#f59e0b",
                NotificationLevel.ERROR: "#ef4444",
                NotificationLevel.CRITICAL: "#dc2626",
                NotificationLevel.INFO: "#3b82f6",
            }[level]

            html = f"""
            <div style="font-family:sans-serif;max-width:600px;margin:0 auto;">
              <h2 style="color:{color};">[{level.value.upper()}] {title}</h2>
              <p>{message}</p>
              <hr style="border:1px solid #eee;">
              <p style="color:#999;font-size:12px;">quanquan 全自动剪辑系统</p>
            </div>"""

            msg.attach(MIMEText(html, "html"))

            # 发送
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._smtp_send(msg)
            )
            logger.info(f"Email sent: {title}")
        except Exception as e:
            logger.error(f"Email failed: {e}")

    def _smtp_send(self, msg: MIMEMultipart):
        with smtplib.SMTP(self.config.email_smtp_host, self.config.email_smtp_port) as server:
            server.starttls()
            server.login(self.config.email_user, self.config.email_password)
            server.send_message(msg)

    async def _send_webhook(
        self, title: str, message: str, level: NotificationLevel,
        project_id: str = "", extra: Optional[Dict] = None,
    ):
        """发送 Webhook"""
        import aiohttp

        payloads = {
            "feishu": self._feishu_payload(title, message, level),
            "dingtalk": self._dingtalk_payload(title, message, level),
            "slack": self._slack_payload(title, message, level),
            "discord": self._discord_payload(title, message, level),
        }

        payload = payloads.get(self.config.webhook_type, self._feishu_payload(title, message, level))

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.config.webhook_url,
                    json=payload,
                    timeout=10,
                ) as resp:
                    if resp.status >= 400:
                        logger.warning(f"Webhook failed: {resp.status}")
        except Exception as e:
            logger.error(f"Webhook error: {e}")

    def _feishu_payload(self, title: str, message: str, level: NotificationLevel) -> dict:
        color = {"success": "green", "warning": "yellow", "error": "red", "critical": "red"}.get(level.value, "blue")
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"[quanquan] {title}"},
                    "template": color,
                },
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": message}}],
            },
        }

    def _dingtalk_payload(self, title: str, message: str, level: NotificationLevel) -> dict:
        return {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": f"## [{level.value}] {title}\n{message}"},
        }

    def _slack_payload(self, title: str, message: str, level: NotificationLevel) -> dict:
        color = {"success": "good", "warning": "warning", "error": "danger"}.get(level.value, "#3b82f6")
        return {
            "attachments": [{"color": color, "title": title, "text": message}],
        }

    def _discord_payload(self, title: str, message: str, level: NotificationLevel) -> dict:
        colors = {"success": 0x22c55e, "warning": 0xf59e0b, "error": 0xef4444, "critical": 0xdc2626}
        return {
            "embeds": [{"title": title, "description": message, "color": colors.get(level.value, 0x3b82f6)}],
        }


# 便捷函数
async def notify_project_complete(project_id: str, video_url: str = ""):
    """通知：项目完成"""
    svc = NotificationService()
    await svc.notify(
        title=f"项目完成: {project_id}",
        message=f"视频已生成{'，下载链接: ' + video_url if video_url else ''}",
        level=NotificationLevel.SUCCESS,
        project_id=project_id,
    )


async def notify_project_failed(project_id: str, error: str):
    """通知：项目失败"""
    svc = NotificationService()
    await svc.notify(
        title=f"项目失败: {project_id}",
        message=f"错误: {error}",
        level=NotificationLevel.ERROR,
        project_id=project_id,
    )
