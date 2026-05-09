"""
Milvus 向量检索引擎

功能：
- 素材语义搜索（CLIP embedding）
- 用户偏好锚点存储与检索
- 混合搜索（标量过滤 + 向量相似度）
- 近实时更新（HNSW 图索引）
"""

import asyncio
import json
import logging
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Milvus 是可选的：如果不可用，使用内存向量搜索回退
try:
    from pymilvus import (
        connections, Collection, CollectionSchema,
        FieldSchema, DataType, utility,
    )
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False
    logger.warning("pymilvus not installed, using in-memory fallback")


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    score: float
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None


class VectorStore:
    """向量存储抽象层（Milvus / 内存回退）"""

    def __init__(self, host: str = "localhost", port: int = 19530,
                 dim: int = 512):
        self.host = host
        self.port = port
        self.dim = dim
        self._milvus_connected = False
        self._collections: Dict[str, Any] = {}

        # 内存回退存储
        self._inmem_vectors: Dict[str, np.ndarray] = {}
        self._inmem_metadata: Dict[str, Dict] = {}

    async def connect(self):
        """连接 Milvus"""
        if not MILVUS_AVAILABLE:
            logger.info("Using in-memory vector store (pymilvus not available)")
            return False

        try:
            connections.connect("default", host=self.host, port=str(self.port))
            self._milvus_connected = True
            logger.info(f"Milvus connected: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.warning(f"Milvus connection failed: {e}, using in-memory fallback")
            self._milvus_connected = False
            return False

    async def create_collection(self, name: str, description: str = "") -> bool:
        """创建向量集合"""
        if self._milvus_connected:
            try:
                if utility.has_collection(name):
                    self._collections[name] = Collection(name)
                    self._collections[name].load()
                    return True

                fields = [
                    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="vector_id", dtype=DataType.VARCHAR, max_length=128),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
                    FieldSchema(name="metadata_json", dtype=DataType.VARCHAR, max_length=4096),
                ]
                schema = CollectionSchema(fields, description=description)
                collection = Collection(name, schema=schema)

                # HNSW 索引（适合频繁更新和近实时检索）
                index_params = {
                    "metric_type": "COSINE",
                    "index_type": "HNSW",
                    "params": {"M": 16, "efConstruction": 200},
                }
                collection.create_index(field_name="embedding", index_params=index_params)
                collection.load()
                self._collections[name] = collection
                logger.info(f"Milvus collection created: {name}")
                return True
            except Exception as e:
                logger.error(f"Failed to create Milvus collection {name}: {e}")
                return False
        else:
            # 内存回退
            self._inmem_vectors.setdefault(name, {})
            self._inmem_metadata.setdefault(name, {})
            return True

    async def insert(
        self,
        collection_name: str,
        vector_id: str,
        embedding: List[float],
        metadata: Dict[str, Any],
    ):
        """插入向量"""
        if self._milvus_connected and collection_name in self._collections:
            try:
                collection = self._collections[collection_name]
                collection.insert([
                    [vector_id],
                    [embedding],
                    [json.dumps(metadata, ensure_ascii=False)],
                ])
                collection.flush()
            except Exception as e:
                logger.error(f"Milvus insert failed: {e}")

        # 始终写内存回退
        self._inmem_vectors.setdefault(collection_name, {})[vector_id] = np.array(embedding)
        self._inmem_metadata.setdefault(collection_name, {})[vector_id] = metadata

    async def search(
        self,
        collection_name: str,
        query_embedding: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[SearchResult]:
        """向量搜索"""
        if self._milvus_connected and collection_name in self._collections:
            try:
                collection = self._collections[collection_name]
                search_params = {"metric_type": "COSINE", "params": {"ef": 64}}
                results = collection.search(
                    data=[query_embedding],
                    anns_field="embedding",
                    param=search_params,
                    limit=top_k,
                    expr=filter_expr,
                    output_fields=["vector_id", "metadata_json"],
                )
                if results and results[0]:
                    return [
                        SearchResult(
                            id=r.entity.get('vector_id', ''),
                            score=r.distance,
                            metadata=json.loads(r.entity.get('metadata_json', '{}')),
                        )
                        for r in results[0]
                    ]
            except Exception as e:
                logger.warning(f"Milvus search failed, falling back to in-memory: {e}")

        # 内存回退搜索
        return self._inmem_search(collection_name, query_embedding, top_k)

    def _inmem_search(
        self, collection_name: str, query_vec: List[float], top_k: int
    ) -> List[SearchResult]:
        """内存余弦相似度搜索"""
        vectors = self._inmem_vectors.get(collection_name, {})
        if not vectors:
            return []

        query = np.array(query_vec)
        scores = []
        for vec_id, vec in vectors.items():
            # 余弦相似度
            dot = np.dot(query, vec)
            norm = np.linalg.norm(query) * np.linalg.norm(vec)
            sim = dot / (norm + 1e-8)
            scores.append((vec_id, float(sim)))

        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:top_k]

        return [
            SearchResult(
                id=vec_id,
                score=score,
                metadata=self._inmem_metadata.get(collection_name, {}).get(vec_id, {}),
            )
            for vec_id, score in top
        ]

    async def get_collection_info(self, name: str) -> dict:
        """获取集合信息"""
        if self._milvus_connected and name in self._collections:
            try:
                collection = self._collections[name]
                return {
                    'name': name,
                    'num_entities': collection.num_entities,
                    'backend': 'milvus',
                }
            except Exception:
                pass
        return {
            'name': name,
            'num_entities': len(self._inmem_vectors.get(name, {})),
            'backend': 'in_memory',
        }


# ============================================================
# 便捷函数
# ============================================================

_vector_store_instance: Optional[VectorStore] = None


async def get_vector_store(dim: int = 512) -> VectorStore:
    """获取全局向量存储（单例）"""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore(dim=dim)
        await _vector_store_instance.connect()
        # 创建核心集合
        await _vector_store_instance.create_collection(
            "materials", "Material library embeddings")
        await _vector_store_instance.create_collection(
            "user_anchors", "User preference anchors")
        await _vector_store_instance.create_collection(
            "project_anchors", "Project style anchors")
    return _vector_store_instance
