"""
quanquan 压力测试 — Locust 脚本

测试场景：
- 创建视频任务 (create_video_from_text)
- 查询项目状态 (query_project_status)
- 查询记忆画像 (get_memory_profile)
- 模拟用户反馈 (submit_feedback)
"""

from locust import HttpUser, task, between
import random
import uuid
import json


class QuanquanUser(HttpUser):
    """模拟 quanquan 用户行为"""
    wait_time = between(1, 10)
    user_id_prefix = "stress_test_"

    def on_start(self):
        """每个虚拟用户启动时"""
        self.user_id = f"{self.user_id_prefix}{uuid.uuid4().hex[:8]}"
        self.project_ids = []

    @task(3)
    def create_video_from_text(self):
        """提交文字创建视频任务（高频）"""
        themes = [
            "大模型技术发展回顾",
            "赛博朋克风格的未来城市",
            "中国传统水墨画的魅力",
            "美食探店：隐藏在小巷里的日料",
            "一分钟看懂量子计算",
            "旅行 Vlog：冰岛极光之旅",
            "手机摄影技巧：夜景拍摄教程",
            "AI 如何改变我们的日常生活",
        ]

        payload = {
            "text": random.choice(themes),
            "duration": random.choice([60, 120, 180, 300]),
            "user_id": self.user_id,
            "style": random.choice(["auto", "cyberpunk", "ink_wash", "modern"]),
        }

        with self.client.post(
            "/api/v1/create",
            json=payload,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                data = response.json()
                pid = data.get("project_id")
                if pid:
                    self.project_ids.append(pid)
                response.success()
            elif response.status_code == 429:
                # 限流，标记成功（不视为失败）
                response.success()
            else:
                response.failure(f"Status {response.status_code}")

    @task(2)
    def query_project_status(self):
        """查询项目进度（中频）"""
        if not self.project_ids:
            return

        pid = random.choice(self.project_ids)
        with self.client.get(
            f"/api/v1/projects/{pid}/status",
            name="/api/v1/projects/[id]/status",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 404):
                response.success()

    @task(1)
    def get_memory_profile(self):
        """查询记忆画像（低频）"""
        with self.client.get(
            f"/api/v1/memory/profile?user_id={self.user_id}",
            name="/api/v1/memory/profile",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()

    @task(1)
    def get_director_status(self):
        """查询导演状态"""
        with self.client.get(
            "/api/v1/director/status",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()

    @task(0.5)
    def submit_feedback(self):
        """提交用户反馈（低频）"""
        if not self.project_ids:
            return

        pid = random.choice(self.project_ids)
        feedback_type = random.choice(["like", "dislike", "override"])

        payload = {
            "project_id": pid,
            "user_id": self.user_id,
            "type": feedback_type,
            "feature": random.choice(["voice", "bgm", "transition", "filter"]),
            "value": random.choice(["deep_male_03", "epic", "glitch_dissolve", "cyberpunk_purple"]),
        }

        with self.client.post(
            "/api/v1/feedback",
            json=payload,
            catch_response=True,
        ) as response:
            if response.status_code in (200, 404):
                response.success()


class QuanquanHighLoad(HttpUser):
    """高负载场景：短时间大量创建"""
    wait_time = between(0.01, 0.1)

    @task
    def rapid_create(self):
        """极速创建"""
        payload = {
            "text": f"Stress test video {uuid.uuid4().hex[:6]}",
            "duration": random.choice([30, 60]),
            "user_id": f"highload_{uuid.uuid4().hex[:6]}",
        }
        self.client.post("/api/v1/create", json=payload)


class QuanquanEndurance(HttpUser):
    """耐久测试：正常负载长时间运行"""
    wait_time = between(5, 30)

    @task(3)
    def normal_create(self):
        payload = {
            "text": "Endurance test video",
            "duration": 180,
            "user_id": f"endurance_{uuid.uuid4().hex[:6]}",
        }
        self.client.post("/api/v1/create", json=payload)

    @task(1)
    def health_check(self):
        self.client.get("/api/v1/director/health")


# ============================================================
# 使用方法：
#   locust -f tests/locust_stress_test.py --host=http://localhost:8000
#   locust -f tests/locust_stress_test.py --host=http://localhost:8000 --users 100 --spawn-rate 10
# ============================================================
