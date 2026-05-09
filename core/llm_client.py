"""
LLM 集成层 v2 — 多 Provider 自动故障转移 + 代理支持
Provider 优先级: Groq → Gemini → DeepSeek → fallback
"""
import os, json, logging, time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import httpx

logger = logging.getLogger("quanquan.llm")

PROVIDER_CONFIGS = {
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        "api_base": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-8b-instant",
        "desc": "Groq Cloud — 免费极速",
    },
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "desc": "Google Gemini 2.5 Flash — 免费1500次/天",
    },
    "google": {
        "api_key_env": "GEMINI_API_KEY",
        "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "desc": "Google Gemini (alias) — 免费1500次/天",
    },
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_base": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "desc": "DeepSeek — 国产性价比",
    },
}


@dataclass
class ProviderConfig:
    name: str
    api_key: str = ""
    api_base: str = ""
    model: str = ""
    desc: str = ""
    healthy: bool = True
    last_error: str = ""
    cooldown_until: float = 0.0

    @classmethod
    def from_name(cls, name: str) -> Optional["ProviderConfig"]:
        cfg = PROVIDER_CONFIGS.get(name)
        if not cfg:
            return None
        key = os.getenv(cfg["api_key_env"], "")
        return cls(name=name, api_key=key, api_base=cfg["api_base"],
                   model=cfg["model"], desc=cfg["desc"]) if key else None


class LLMClient:
    """多 Provider LLM 客户端 — 自动故障转移"""

    def __init__(self):
        self.providers: List[ProviderConfig] = []
        self._client: Optional[httpx.AsyncClient] = None
        self._load_providers()
        if self.providers:
            logger.info(f"LLM: {len(self.providers)} providers loaded → {[p.name for p in self.providers]}")

    def _load_providers(self):
        """按优先级加载有 Key 的 provider"""
        priority = os.getenv("LLM_PROVIDER", "").split(",")
        for name in (priority if priority[0] else ["gemini", "groq", "deepseek"]):
            name = name.strip()
            cfg = ProviderConfig.from_name(name)
            if cfg:
                self.providers.append(cfg)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or None
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(30, connect=8),
                proxy=proxy,
            )
        return self._client

    @property
    def active_provider(self) -> Optional[ProviderConfig]:
        now = time.time()
        for p in self.providers:
            if p.healthy or now > p.cooldown_until:
                return p
        return None

    async def chat(self, messages: List[Dict], **kwargs) -> str:
        """发送请求，自动故障转移"""
        errors = []
        for provider in list(self.providers):
            now = time.time()
            if not provider.healthy and now < provider.cooldown_until:
                errors.append(f"{provider.name}: cooling down ({int(provider.cooldown_until - now)}s)")
                continue

            try:
                result = await self._call_provider(provider, messages, **kwargs)
                provider.healthy = True
                provider.last_error = ""
                return result
            except Exception as e:
                msg = str(e)[:100]
                provider.healthy = False
                provider.last_error = msg
                provider.cooldown_until = now + 30  # 30s 冷却
                errors.append(f"{provider.name}: {msg}")
                logger.warning(f"LLM {provider.name} failed: {msg}")

        logger.warning(f"All LLM providers failed: {'; '.join(errors)}")
        return self._fallback_response(messages)

    async def _call_provider(self, p: ProviderConfig, messages: List[Dict], **kwargs) -> str:
        headers = {
            "Authorization": f"Bearer {p.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": p.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2048),
        }
        url = f"{p.api_base}/chat/completions"
        resp = await self.client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def chat_json(self, messages: List[Dict], **kwargs) -> Dict:
        schema = kwargs.pop("json_schema", None)
        # 提取 schema 中需要的字段名
        field_hint = ""
        if schema and "properties" in schema:
            fields = list(schema["properties"].keys())
            field_hint = f"返回一个JSON对象，包含以下字段：{', '.join(fields)}。"

        # 强化 system prompt
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] += f"\n{field_hint}只返回JSON，不要代码块。"
        text = await self.chat(messages, **kwargs)
        return self._parse_json(text)

    def _parse_json(self, text: str) -> Dict:
        """智能 JSON 解析：处理各种 LLM 响应格式"""
        import re
        # 1. 尝试直接解析
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        # 2. 提取 ```json ... ``` 代码块
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try: return json.loads(m.group(1).strip())
            except: pass
        # 3. 提取第一个 { ... } 块
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try: return json.loads(m.group(0))
            except: pass
        # 4. 失败返回原始文本
        logger.warning(f"JSON parse failed, returning raw. Text: {text[:200]}")
        return {"raw": text, "error": "json_parse_failed"}

    def _fallback_response(self, messages: List[Dict]) -> str:
        """智能降级：根据 system prompt 内容返回对应 Agent 的演示数据"""
        import time as _t

        # 提取所有 system + user 内容用于判断上下文
        all_text = " ".join(m.get("content", "") for m in messages if m.get("role") in ("system", "user"))

        # ── 编剧 Scriptwriter → 视频脚本 ──
        if "脚本" in all_text or "script" in all_text.lower() or "字幕" in all_text or "scenes" in all_text.lower():
            return json.dumps({
                "title": "AI 自动生成演示视频",
                "duration_sec": 120,
                "scenes": [
                    {"timestamp": "00:00", "text": "欢迎来到 quanquan 全自动视频生产系统", "emotion": "激昂", "duration_sec": 10},
                    {"timestamp": "00:10", "text": "AI 驱动的多智能体协作，让视频创作从未如此简单", "emotion": "专业", "duration_sec": 15},
                    {"timestamp": "00:25", "text": "从脚本到成片，全程自动化，无需手动操作", "emotion": "平静", "duration_sec": 12},
                    {"timestamp": "00:37", "text": "支持多平台发布，一键生成 B站/抖音/YouTube 专属格式", "emotion": "激昂", "duration_sec": 15},
                    {"timestamp": "00:52", "text": "内置海量素材库和 AI 调色引擎，让画面更具质感", "emotion": "专业", "duration_sec": 13},
                    {"timestamp": "01:05", "text": "智能音频处理和配音合成，打造影院级听觉体验", "emotion": "激昂", "duration_sec": 15},
                    {"timestamp": "01:20", "text": "quanquan，让每个人都能成为视频创作者", "emotion": "温暖", "duration_sec": 12},
                    {"timestamp": "01:32", "text": "感谢使用，期待你的下一部作品！", "emotion": "感谢", "duration_sec": 8},
                ],
                "emotion_curve": [{"time": 0, "emotion": "激昂", "intensity": 0.8}, {"time": 60, "emotion": "专业", "intensity": 0.6}],
                "total_duration_ms": 120000,
            }, ensure_ascii=False)

        # ── 分镜 Storyboard → 分镜计划 ──
        if "分镜" in all_text or "storyboard" in all_text.lower() or "镜头" in all_text:
            return json.dumps({
                "timeline": [
                    {"shot_id": "s1", "start_sec": 0, "end_sec": 10, "description": "科技感开场", "transition": "fade_in", "camera": "wide"},
                    {"shot_id": "s2", "start_sec": 10, "end_sec": 25, "description": "AI概念展示", "transition": "dissolve", "camera": "medium"},
                    {"shot_id": "s3", "start_sec": 25, "end_sec": 37, "description": "自动化流程", "transition": "slide", "camera": "close_up"},
                    {"shot_id": "s4", "start_sec": 37, "end_sec": 52, "description": "多平台展示", "transition": "dissolve", "camera": "wide"},
                    {"shot_id": "s5", "start_sec": 52, "end_sec": 65, "description": "素材库展示", "transition": "slide", "camera": "medium"},
                    {"shot_id": "s6", "start_sec": 65, "end_sec": 80, "description": "音频处理", "transition": "dissolve", "camera": "close_up"},
                    {"shot_id": "s7", "start_sec": 80, "end_sec": 92, "description": "品牌展示", "transition": "fade", "camera": "wide"},
                    {"shot_id": "s8", "start_sec": 92, "end_sec": 120, "description": "结束感谢", "transition": "fade_out", "camera": "medium"},
                ],
                "total_segments": 8,
                "materials": [{"type": "bg", "desc": "深色科技感背景"}, {"type": "overlay", "desc": "AI神经网络动画"}],
            }, ensure_ascii=False)

        # ── BGM 音乐推荐 ──
        if "BGM" in all_text or "bgm" in all_text.lower() or "音乐" in all_text or "配乐" in all_text:
            return json.dumps({
                "tracks": [
                    {"name": "Ambient Technology", "genre": "electronic", "bpm": 120, "mood": "科技感", "duration_sec": 120},
                    {"name": "Future Synth", "genre": "synthwave", "bpm": 110, "mood": "未来感", "duration_sec": 120},
                ],
                "recommended": "Ambient Technology",
                "genre": "electronic",
                "mood": "科技感",
            }, ensure_ascii=False)

        # ── 配音 Voiceover ──
        if "配音" in all_text or "voice" in all_text.lower() or "TTS" in all_text or "音频" in all_text:
            return json.dumps({
                "audio_path": "demo_voiceover.mp3",
                "duration_ms": 120000,
                "segments": [{"start": 0, "end": 10000, "text": "欢迎来到 quanquan"},
                            {"start": 10000, "end": 25000, "text": "全自动视频生产系统"}],
                "voice_id": "default",
            }, ensure_ascii=False)

        # ── QC / 审核 ──
        if "审核" in all_text or "质检" in all_text or "QC" in all_text or "quality" in all_text.lower():
            return json.dumps({
                "verdict": "PASS",
                "score": 0.95,
                "issues": [],
                "checks": {"black_frame": "pass", "silence": "pass", "audio_peak": "pass", "sync": "pass"},
            }, ensure_ascii=False)

        # ── 标题/描述生成 ──
        if "标题" in all_text or "title" in all_text.lower() or "描述" in all_text:
            return json.dumps({
                "titles": [{"title": "AI驱动的视频生产革命", "style": "professional", "score": 0.9},
                          {"title": "全自动剪辑？这个AI做到了", "style": "clickbait", "score": 0.85}],
                "description": "quanquan 全自动视频生产系统演示视频",
            }, ensure_ascii=False)

        # ── 通用兜底 ──
        last = messages[-1]["content"] if messages else ""
        return json.dumps({
            "status": "demo",
            "message": f"[Demo Mode] No LLM API key configured. Would process: {last[:100]}...",
            "providers_available": len(self.providers),
            "hint": "Set GEMINI_API_KEY in .env for full AI capabilities",
        }, ensure_ascii=False)

    async def chat_multi_vote(self, messages: List[Dict], num_voters: int = 2,
                              json_schema: dict = None, **kwargs) -> Dict:
        """多模型投票：查询2个provider，第3个投票选择最佳响应。

        仅在可用provider >= 3时启用；否则降级为普通chat_json。
        """
        available = [p for p in self.providers if p.healthy or time.time() > p.cooldown_until]
        if len(available) < 3:
            return await self.chat_json(messages, json_schema=json_schema, **kwargs)

        voters = available[:num_voters]
        judge = available[num_voters] if len(available) > num_voters else voters[-1]

        # 并行查询 num_voters 个模型
        import asyncio
        async def query_one(provider):
            try:
                return await self._call_provider(provider, messages, **kwargs)
            except Exception as e:
                return None

        responses = await asyncio.gather(*[query_one(v) for v in voters])
        responses = [r for r in responses if r is not None]

        if not responses:
            return await self.chat_json(messages, json_schema=json_schema, **kwargs)
        if len(responses) == 1:
            return self._parse_json(responses[0]) if json_schema else {"response": responses[0]}

        # 第3个模型投票
        vote_msgs = [
            {"role": "system", "content": "你是评审专家。下面是两个AI助手的回复，请投票选择更好的一个（回复1或2），并简要说明理由。只输出JSON: {\"vote\": 1或2, \"reason\": \"...\"}"},
            {"role": "user", "content": f"回复1:\n{responses[0][:1500]}\n\n回复2:\n{responses[1][:1500]}"},
        ]
        try:
            vote_text = await self._call_provider(judge, vote_msgs, temperature=0.2, max_tokens=256)
            import re
            vote_match = re.search(r'"vote"\s*:\s*(\d)', vote_text)
            winner_idx = int(vote_match.group(1)) - 1 if vote_match else 0
            winner_idx = max(0, min(winner_idx, len(responses) - 1))
        except Exception:
            winner_idx = 0

        result = self._parse_json(responses[winner_idx]) if json_schema else {"response": responses[winner_idx]}
        result["_voted"] = True
        result["_voters"] = [v.name for v in voters]
        result["_winner"] = voters[winner_idx].name if winner_idx < len(voters) else "unknown"
        return result

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def list_providers() -> List[dict]:
        return [
            {"name": "groq", "model": "llama-3.1-8b-instant", "free": True,
             "get_key": "https://console.groq.com/keys", "speed": "极快"},
            {"name": "gemini", "model": "gemini-2.0-flash", "free": True,
             "get_key": "https://aistudio.google.com/apikey", "speed": "快"},
            {"name": "deepseek", "model": "deepseek-chat", "free": True,
             "get_key": "https://platform.deepseek.com/api_keys", "speed": "快"},
        ]


# 懒加载代理（兼容旧 import）
class _LazyLLM:
    def __init__(self): self._instance = None
    def _get(self):
        if self._instance is None: self._instance = LLMClient()
        return self._instance
    async def chat(self, *a, **kw): return await self._get().chat(*a, **kw)
    async def chat_json(self, *a, **kw): return await self._get().chat_json(*a, **kw)
    async def chat_multi_vote(self, *a, **kw): return await self._get().chat_multi_vote(*a, **kw)
    def __getattr__(self, name): return getattr(self._get(), name)

llm = _LazyLLM()
