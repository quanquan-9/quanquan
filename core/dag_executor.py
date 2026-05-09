"""
DAG Executor — 有向无环图并行执行引擎
=====================================
读取导演生成的 DAG 定义，按依赖拓扑排序，并行执行独立节点。
- 拓扑排序 + asyncio.gather 并行
- 节点超时 / 重试 / 失败降级
- 集成 ContextBus（发布事件）+ ArtifactStore（存储产出）
"""

import asyncio
import time
import uuid
import logging
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field

from core.context_bus import ContextBus, EventType
from core.artifact_store import ArtifactStore

logger = logging.getLogger("quanquan.dag_executor")


class NodeStatus(str, Enum):
    PENDING    = "PENDING"
    RUNNING    = "RUNNING"
    COMPLETED  = "COMPLETED"
    SUCCESS    = "COMPLETED"   # 别名：兼容 Director 旧代码
    FAILED     = "FAILED"
    TIMEOUT    = "TIMEOUT"
    SKIPPED    = "SKIPPED"


@dataclass
class DAGNode:
    """DAG 节点运行时状态"""
    node_id: str
    agent: str
    depends_on: List[str] = field(default_factory=list)
    task: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    output_key: str = ""
    timeout_seconds: int = 300
    status: NodeStatus = NodeStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class DAGResult:
    """DAG 执行结果"""
    dag_id: str
    project_id: str
    total_nodes: int
    completed: int
    failed: int
    timed_out: int
    skipped: int
    elapsed_sec: float
    node_results: Dict[str, Any] = field(default_factory=dict)


AgentExecutor = Callable[[DAGNode, ArtifactStore], Awaitable[Any]]


class DAGExecutor:
    """DAG 并行执行引擎。

    用法:
        executor = DAGExecutor(bus, artifacts)
        executor.register_agent("Scriptwriter", my_scriptwriter_handler)
        result = await executor.execute(dag_definition, "proj_001")
    """

    DEFAULT_TIMEOUT = 300
    DEFAULT_MAX_RETRIES = 3

    def __init__(self, context_bus: ContextBus, artifact_store: ArtifactStore):
        self.bus = context_bus
        self.artifacts = artifact_store
        self._agent_registry: Dict[str, AgentExecutor] = {}

    def register_agent(self, agent_name: str, executor: AgentExecutor) -> None:
        """注册 Agent 执行器。"""
        self._agent_registry[agent_name] = executor
        logger.info("Agent registered: %s", agent_name)

    def unregister_agent(self, agent_name: str) -> None:
        """注销 Agent。"""
        self._agent_registry.pop(agent_name, None)

    # ── DAG 执行 ──

    async def execute(self, dag_definition: Dict[str, Any], project_id: str) -> DAGResult:
        """执行 DAG。

        dag_definition = {"dag_id": "...", "nodes": [{node_id, agent, depends_on, ...}]}
        """
        dag_id = dag_definition.get("dag_id", f"dag_{uuid.uuid4().hex[:8]}")
        nodes_raw = dag_definition.get("nodes", [])

        if not nodes_raw:
            logger.warning("DAG has no nodes: %s", dag_id)
            return DAGResult(dag_id=dag_id, project_id=project_id,
                           total_nodes=0, completed=0, failed=0,
                           timed_out=0, skipped=0, elapsed_sec=0)

        # 构建节点对象
        nodes: Dict[str, DAGNode] = {}
        for raw in nodes_raw:
            node = DAGNode(
                node_id=raw.get("node_id", f"n{uuid.uuid4().hex[:6]}"),
                agent=raw.get("agent", "unknown"),
                depends_on=raw.get("depends_on", []),
                task=raw.get("task", ""),
                input=raw.get("input", {}),
                output_key=raw.get("output_key", raw.get("node_id", "")),
                timeout_seconds=raw.get("timeout_seconds", self.DEFAULT_TIMEOUT),
            )
            nodes[node.node_id] = node

        # 拓扑排序
        try:
            execution_order = self._topological_sort(nodes)
        except ValueError as e:
            logger.error("DAG circular dependency: %s error=%s", dag_id, str(e))
            return DAGResult(dag_id=dag_id, project_id=project_id,
                           total_nodes=len(nodes), completed=0,
                           failed=len(nodes), timed_out=0, skipped=0,
                           elapsed_sec=0,
                           node_results={nid: {"status": "FAILED", "error": str(e)} for nid in nodes})

        start_time = time.time()
        completed_nodes: set = set()
        failed_nodes: set = set()

        order_flat = [n for batch in execution_order for n in batch]
        logger.info("DAG started: %s project=%s nodes=%s order=%s", dag_id, project_id, len(nodes), order_flat)

        # 逐层并行执行
        for batch in execution_order:
            batch_tasks = []
            for node_id in batch:
                node = nodes[node_id]
                deps_ok = all(nodes[dep].status == NodeStatus.COMPLETED
                            for dep in node.depends_on if dep in nodes)
                if not deps_ok:
                    node.status = NodeStatus.SKIPPED
                    node.error = "Dependency failed"
                    failed_nodes.add(node_id)
                    continue

                if node.agent not in self._agent_registry:
                    logger.warning("Agent not registered, using mock: %s node=%s", node.agent, node_id)
                    batch_tasks.append(self._execute_node_mock(node, project_id))
                else:
                    batch_tasks.append(self._execute_node(node, project_id))

            if not batch_tasks:
                continue

            results = await asyncio.gather(*batch_tasks, return_exceptions=True)

            for i, result in enumerate(results):
                nid = batch[i]
                node = nodes[nid]
                if isinstance(result, Exception):
                    node.status = NodeStatus.FAILED
                    node.error = str(result)
                    failed_nodes.add(nid)
                    logger.error("Node exception: %s error=%s", nid, str(result))
                elif isinstance(result, dict) and result.get("status") == "FAILED":
                    node.status = NodeStatus.FAILED
                    node.error = result.get("error", "unknown")
                    failed_nodes.add(nid)
                elif isinstance(result, dict) and result.get("status") == "TIMEOUT":
                    node.status = NodeStatus.TIMEOUT
                    node.error = "timeout"
                    failed_nodes.add(nid)
                else:
                    node.status = NodeStatus.COMPLETED
                    node.result = result
                    completed_nodes.add(nid)

                    if node.output_key and node.result:
                        try:
                            await self.artifacts.put(project_id, node.output_key, node.result)
                        except Exception as e:
                            logger.error("Store artifact failed: %s %s error=%s", project_id, node.output_key, str(e))

                    await self.bus.publish(
                        EventType.NODE_COMPLETE,
                        {"dag_id": dag_id, "node_id": node.node_id, "agent": node.agent, "output_key": node.output_key},
                        agent_id=node.agent,
                    )

        elapsed = time.time() - start_time
        result = DAGResult(
            dag_id=dag_id, project_id=project_id,
            total_nodes=len(nodes), completed=len(completed_nodes),
            failed=len(failed_nodes),
            timed_out=sum(1 for n in nodes.values() if n.status == NodeStatus.TIMEOUT),
            skipped=sum(1 for n in nodes.values() if n.status == NodeStatus.SKIPPED),
            elapsed_sec=round(elapsed, 2),
            node_results={
                nid: {
                    "status": node.status.value, "agent": node.agent, "error": node.error,
                    "elapsed": round((node.completed_at - node.started_at), 3)
                    if node.started_at and node.completed_at else None,
                }
                for nid, node in nodes.items()
            },
        )

        await self.bus.publish(EventType.PIPELINE_COMPLETE, result.node_results, agent_id="dag_executor")
        logger.info("DAG completed: %s done=%s failed=%s elapsed=%.2fs", dag_id, result.completed, result.failed, elapsed)

        return result

    async def cancel(self) -> None:
        """取消所有运行中任务。"""
        logger.info("DAG executor cancelled")

    # ── 内部 ──

    async def _execute_node(self, node: DAGNode, project_id: str) -> Any:
        executor = self._agent_registry[node.agent]
        node.status = NodeStatus.RUNNING
        node.started_at = time.time()

        try:
            result = await asyncio.wait_for(executor(node, self.artifacts), timeout=node.timeout_seconds)
            node.completed_at = time.time()
            return result
        except asyncio.TimeoutError:
            node.completed_at = time.time()
            if node.retry_count < node.max_retries:
                node.retry_count += 1
                logger.warning("Node timeout retry: %s attempt=%s", node.node_id, node.retry_count)
                node.status = NodeStatus.PENDING
                return await self._execute_node(node, project_id)
            return {"status": "TIMEOUT", "error": f"exceeded {node.timeout_seconds}s"}
        except asyncio.CancelledError:
            node.completed_at = time.time()
            node.status = NodeStatus.FAILED
            node.error = "cancelled"
            raise
        except Exception as e:
            node.completed_at = time.time()
            if node.retry_count < node.max_retries:
                node.retry_count += 1
                logger.warning("Node failed retry: %s error=%s attempt=%s", node.node_id, str(e), node.retry_count)
                node.status = NodeStatus.PENDING
                return await self._execute_node(node, project_id)
            return {"status": "FAILED", "error": str(e)}

    async def _execute_node_mock(self, node: DAGNode, project_id: str) -> Any:
        node.status = NodeStatus.RUNNING
        node.started_at = time.time()
        await asyncio.sleep(0.05)
        node.completed_at = time.time()
        return {
            "node_id": node.node_id, "agent": node.agent, "task": node.task,
            "mock": True, "output": f"Mock result for {node.agent}/{node.task}",
            "generated_at": time.time(),
        }

    def _topological_sort(self, nodes: Dict[str, DAGNode]) -> List[List[str]]:
        """Kahn 算法拓扑排序，返回分层执行顺序。"""
        in_degree: Dict[str, int] = {nid: 0 for nid in nodes}
        adjacency: Dict[str, List[str]] = {nid: [] for nid in nodes}

        for nid, node in nodes.items():
            for dep in node.depends_on:
                if dep not in nodes:
                    logger.warning("Dependency missing: %s -> %s", nid, dep)
                    continue
                adjacency[dep].append(nid)
                in_degree[nid] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        layers = []
        visited_count = 0

        while queue:
            layers.append(list(queue))
            next_queue = []
            for nid in queue:
                visited_count += 1
                for neighbor in adjacency[nid]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue

        if visited_count != len(nodes):
            raise ValueError(f"DAG circular: visited {visited_count}/{len(nodes)} nodes")

        return layers
