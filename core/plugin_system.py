"""
quanquan 插件系统 (Plugin System)

功能：
- 动态加载/卸载插件
- 插件生命周期管理
- 钩子系统 (Hook System)
- 插件市场接口
"""

import os
import sys
import importlib
import inspect
import logging
from pathlib import Path
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from enum import Enum

logger = logging.getLogger(__name__)


class PluginHook(Enum):
    """插件钩子"""
    # 管线钩子
    ON_PROJECT_CREATE = "on_project_create"
    ON_AGENT_START = "on_agent_start"
    ON_AGENT_COMPLETE = "on_agent_complete"
    ON_PIPELINE_COMPLETE = "on_pipeline_complete"
    ON_QC_PASS = "on_qc_pass"
    ON_QC_FAIL = "on_qc_fail"

    # 视频处理钩子
    ON_VIDEO_ENCODE_START = "on_video_encode_start"
    ON_VIDEO_ENCODE_COMPLETE = "on_video_encode_complete"
    BEFORE_EXPORT = "before_export"
    AFTER_EXPORT = "after_export"

    # 系统钩子
    ON_STARTUP = "on_startup"
    ON_SHUTDOWN = "on_shutdown"
    ON_ERROR = "on_error"


@dataclass
class PluginInfo:
    """插件元信息"""
    name: str
    version: str
    author: str = ""
    description: str = ""
    homepage: str = ""
    dependencies: List[str] = field(default_factory=list)
    hooks: List[PluginHook] = field(default_factory=list)


class BasePlugin(ABC):
    """插件基类"""

    # 插件元信息（子类覆盖）
    info: PluginInfo = PluginInfo(name="base", version="0.1.0")

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def on_enable(self):
        """插件启用时调用"""
        self._enabled = True
        logger.info(f"Plugin enabled: {self.info.name}")

    async def on_disable(self):
        """插件禁用时调用"""
        self._enabled = False
        logger.info(f"Plugin disabled: {self.info.name}")

    # ---- 可覆盖的钩子方法 ----

    async def on_project_create(self, project_id: str, config: dict):
        pass

    async def on_agent_start(self, agent_name: str, task: dict):
        pass

    async def on_agent_complete(self, agent_name: str, result: dict):
        pass

    async def on_pipeline_complete(self, project_id: str, summary: dict):
        pass

    async def on_qc_pass(self, project_id: str, report: dict):
        pass

    async def on_qc_fail(self, project_id: str, report: dict):
        pass

    async def on_video_encode_start(self, input_path: str, config: dict):
        pass

    async def on_video_encode_complete(self, output_path: str):
        pass

    async def before_export(self, project_id: str, manifest: dict):
        pass

    async def after_export(self, project_id: str, result: dict):
        pass

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def on_error(self, error: Exception, context: dict):
        pass


class PluginManager:
    """插件管理器"""

    def __init__(self, plugin_dir: str = "plugins/"):
        self.plugin_dir = plugin_dir
        self._plugins: Dict[str, BasePlugin] = {}
        self._hook_handlers: Dict[PluginHook, List[Callable]] = {
            hook: [] for hook in PluginHook
        }

    def register(self, plugin: BasePlugin):
        """注册插件"""
        name = plugin.info.name
        if name in self._plugins:
            logger.warning(f"Plugin already registered: {name}")
            return

        self._plugins[name] = plugin

        # 注册钩子
        for hook in plugin.info.hooks:
            method_name = hook.value
            if hasattr(plugin, method_name):
                handler = getattr(plugin, method_name)
                self._hook_handlers[hook].append(handler)

        logger.info(f"Plugin registered: {name} v{plugin.info.version} "
                     f"({len(plugin.info.hooks)} hooks)")

    def unregister(self, name: str):
        """注销插件"""
        plugin = self._plugins.pop(name, None)
        if plugin:
            for hook in plugin.info.hooks:
                method = getattr(plugin, hook.value, None)
                if method in self._hook_handlers[hook]:
                    self._hook_handlers[hook].remove(method)
            logger.info(f"Plugin unregistered: {name}")

    async def enable_all(self):
        """启用所有插件"""
        for plugin in self._plugins.values():
            await plugin.on_enable()

    async def disable_all(self):
        """禁用所有插件"""
        for plugin in self._plugins.values():
            await plugin.on_disable()

    async def load_from_directory(self, directory: Optional[str] = None):
        """从目录加载插件"""
        target = directory or self.plugin_dir
        if not os.path.isdir(target):
            os.makedirs(target, exist_ok=True)
            return

        for item in os.listdir(target):
            item_path = os.path.join(target, item)
            if os.path.isdir(item_path):
                # Python 包
                init_file = os.path.join(item_path, "__init__.py")
                if os.path.exists(init_file):
                    await self._load_package(item, item_path)
            elif item.endswith(".py") and not item.startswith("_"):
                await self._load_module(item[:-3], item_path)

    async def _load_package(self, name: str, path: str):
        """加载插件包"""
        try:
            sys.path.insert(0, os.path.dirname(path))
            module = importlib.import_module(name)
            sys.path.pop(0)
            await self._register_from_module(module)
        except Exception as e:
            logger.error(f"Failed to load plugin package {name}: {e}")

    async def _load_module(self, name: str, path: str):
        """加载单文件插件"""
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            await self._register_from_module(module)
        except Exception as e:
            logger.error(f"Failed to load plugin {name}: {e}")

    async def _register_from_module(self, module):
        """从模块中注册所有插件类"""
        for name, obj in inspect.getmembers(module):
            if (inspect.isclass(obj) and
                issubclass(obj, BasePlugin) and
                obj is not BasePlugin):
                plugin = obj()
                self.register(plugin)

    # ---- 钩子触发 ----

    async def trigger(self, hook: PluginHook, *args, **kwargs):
        """触发钩子"""
        for handler in self._hook_handlers.get(hook, []):
            try:
                await handler(*args, **kwargs)
            except Exception as e:
                logger.error(f"Hook {hook.value} failed: {e}")

    def list_plugins(self) -> List[PluginInfo]:
        """列出所有插件"""
        return [p.info for p in self._plugins.values()]

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self._plugins.get(name)


# ═══════════ 内置插件示例 ═══════════

class WatermarkPlugin(BasePlugin):
    """水印插件"""
    info = PluginInfo(
        name="watermark",
        version="1.0.0",
        author="quanquan",
        description="自动添加水印",
        hooks=[PluginHook.AFTER_EXPORT],
    )

    async def after_export(self, project_id: str, result: dict):
        logger.info(f"WatermarkPlugin: adding watermark to {project_id}")


class TelegramNotifyPlugin(BasePlugin):
    """Telegram 通知插件"""
    info = PluginInfo(
        name="telegram_notify",
        version="1.0.0",
        author="quanquan",
        description="完成后发送 Telegram 通知",
        hooks=[PluginHook.ON_PIPELINE_COMPLETE],
    )

    async def on_pipeline_complete(self, project_id: str, summary: dict):
        logger.info(f"TelegramNotifyPlugin: project {project_id} complete")


class AutoThumbnailPlugin(BasePlugin):
    """自动封面插件"""
    info = PluginInfo(
        name="auto_thumbnail",
        version="1.0.0",
        author="quanquan",
        description="自动生成视频封面",
        hooks=[PluginHook.BEFORE_EXPORT],
    )

    async def before_export(self, project_id: str, manifest: dict):
        logger.info(f"AutoThumbnailPlugin: generating thumbnail for {project_id}")


# 全局单例
plugin_manager = PluginManager()
