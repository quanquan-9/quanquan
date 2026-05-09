"""
quanquan 配置管理中心

功能：
- 统一配置加载（YAML + 环境变量）
- 运行时动态更新
- 配置热重载
- 多环境支持（dev/staging/prod）
"""

import os
import yaml
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from threading import RLock

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "director": {
        "max_replan_attempts": 3,
        "dag_timeout_sec": 300,
        "heartbeat_interval_sec": 15,
    },
    "llm": {
        "provider": "deepseek",
        "model": "deepseek-v3",
        "temperature": 0.8,
        "max_tokens": 4096,
    },
    "tts": {
        "provider": "edge",
        "default_voice": "zh-CN-YunxiNeural",
        "sample_rate": 48000,
        "default_speed": 1.0,
    },
    "video": {
        "chunk_threshold_duration_sec": 300,
        "chunk_threshold_size_bytes": 2 * 1024**3,
        "max_workers": 4,
        "segment_duration_sec": 120,
    },
    "gpu": {
        "enabled": True,
        "preferred_type": "nvidia",
        "max_concurrent_encodes": 2,
    },
    "proxy": {
        "enabled": True,
        "proxy_resolution": 720,
        "auto_proxy_threshold_width": 1920,
        "proxy_codec": "h264",
        "proxy_crf": 28,
    },
    "qc": {
        "subtitle_timing_fatal": 2.0,
        "subtitle_timing_major": 0.5,
        "black_frame_min_dur": 0.5,
        "silence_min_dur": 1.0,
        "av_sync_fatal_ms": 200,
    },
    "delivery": {
        "auto_export": False,
        "output_format": "mp4",
        "output_resolution": "1920x1080",
        "generate_notes": True,
    },
    "memory": {
        "short_term_ttl_sec": 86400,
        "decay_half_life_days": 90,
        "cold_start_enabled": True,
    },
    "api": {
        "host": "0.0.0.0",
        "port": 8000,
        "cors_origins": ["*"],
    },
    "redis": {
        "host": "localhost",
        "port": 6379,
        "db": 0,
    },
    "milvus": {
        "host": "localhost",
        "port": 19530,
        "dim": 512,
    },
    "monitoring": {
        "prometheus_enabled": True,
        "prometheus_port": 9090,
        "grafana_enabled": True,
        "log_level": "INFO",
    },
}


class ConfigManager:
    """统一配置管理器"""

    _instance: Optional["ConfigManager"] = None
    _lock = RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._config = dict(DEFAULT_CONFIG)
        self._config_file: Optional[str] = None
        self._env_prefix = "QUANQUAN_"
        self._watchers = []
        self._initialized = True

    # ---- 加载 ----

    def load_yaml(self, filepath: str):
        """从 YAML 文件加载配置（合并到已有配置）"""
        if not os.path.exists(filepath):
            logger.warning(f"Config file not found: {filepath}")
            return

        with open(filepath, "r") as f:
            yaml_config = yaml.safe_load(f) or {}

        self._deep_merge(self._config, yaml_config)
        self._config_file = filepath
        logger.info(f"Config loaded from {filepath}")

    def load_env(self):
        """从环境变量覆盖配置"""
        for key, value in os.environ.items():
            if not key.startswith(self._env_prefix):
                continue

            # QUANQUAN_LLM__PROVIDER=openai → config["llm"]["provider"] = "openai"
            config_key = key[len(self._env_prefix):].lower().replace("__", ".")
            keys = config_key.split(".")

            target = self._config
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]

            # 类型转换
            last_key = keys[-1]
            target[last_key] = self._cast_value(value)

        logger.debug("Environment variables loaded")

    def _cast_value(self, value: str) -> Any:
        """尝试智能类型转换"""
        if value.lower() in ("true", "yes"):
            return True
        if value.lower() in ("false", "no"):
            return False
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            pass
        return value

    def _deep_merge(self, base: dict, override: dict):
        """深度合并配置"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    # ---- 访问 ----

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（点分隔路径）

        Example: config.get("llm.provider") → "deepseek"
        """
        keys = key.split(".")
        target = self._config
        for k in keys:
            if isinstance(target, dict) and k in target:
                target = target[k]
            else:
                return default
        return target

    def set(self, key: str, value: Any):
        """运行时设置配置值"""
        keys = key.split(".")
        target = self._config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

        # 通知 watchers
        for watcher in self._watchers:
            try:
                watcher(key, value)
            except Exception:
                pass

    def all(self) -> Dict[str, Any]:
        """获取全部配置快照"""
        return dict(self._config)

    def export_yaml(self, filepath: str):
        """导出当前配置到 YAML"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)

    # ---- 监控 ----

    def watch(self, callback):
        """注册配置变更回调"""
        self._watchers.append(callback)

    # ---- 预设环境 ----

    @classmethod
    def dev(cls) -> "ConfigManager":
        cm = cls()
        cm.set("api.port", 8000)
        cm.set("monitoring.log_level", "DEBUG")
        cm.set("gpu.enabled", False)
        return cm

    @classmethod
    def prod(cls) -> "ConfigManager":
        cm = cls()
        cm.set("monitoring.log_level", "WARNING")
        cm.set("gpu.enabled", True)
        cm.set("delivery.auto_export", True)
        return cm


# 全局单例
config = ConfigManager()
