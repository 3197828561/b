"""本地库向量检索：OpenAI Embedding + 磁盘索引（按公司隔离）。"""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from typing import Any

from ..config import settings
from ..utils.localdb_paths import localdb_company_root

logger = logging.getLogger(__name__)


def _embeddings_file(company_id: str) -> str:
    return os.path.join(localdb_company_root(company_id), "knowledge_embeddings.json")


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


class EmbeddingIndexService:
    """管理 chunk_id -> vector 的本地 JSON 索引。"""

    def __init__(self, company_id: str) -> None:
        self.company_id = company_id
        self.path = _embeddings_file(company_id)

    def load(self) -> dict[str, Any]:
        if not os.path.isfile(self.path):
            return {"version": 1, "model": settings.embedding_model, "vectors": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"version": 1, "model": settings.embedding_model, "vectors": {}}

    def save(self, index: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = f"{self.path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        os.replace(tmp, self.path)

    def remove_chunk_ids(self, chunk_ids: set[str]) -> None:
        if not chunk_ids:
            return
        index = self.load()
        vectors = index.get("vectors") or {}
        for cid in chunk_ids:
            vectors.pop(cid, None)
        index["vectors"] = vectors
        self.save(index)


async def is_embedding_available() -> bool:
    if not settings.embedding_enabled:
        return False
    try:
        from ..utils.config_manager import config_manager

        cfg = config_manager.load_config()
        return bool(cfg.get("api_key"))
    except Exception:
        return False


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """调用 OpenAI 兼容接口生成向量。"""
    if not texts:
        return []
    from ..utils.openai_util import OpenAIUtil

    ai = OpenAIUtil()
    inputs = [(t or "")[:6000] for t in texts]
    response = await ai.client.embeddings.create(
        model=settings.embedding_model,
        input=inputs,
    )
    return [list(item.embedding) for item in response.data]


async def sync_embeddings_for_chunks(
    company_id: str,
    chunks: list[dict[str, Any]],
) -> int:
    """为给定切片写入/更新向量，返回成功数量。"""
    if not chunks or not await is_embedding_available():
        return 0
    store = EmbeddingIndexService(company_id)
    index = store.load()
    vectors: dict[str, list[float]] = index.get("vectors") or {}

    texts = [str(c.get("text") or "") for c in chunks]
    ids = [str(c.get("id") or "") for c in chunks]
    valid = [(i, t) for i, t in zip(ids, texts) if i and t.strip()]
    if not valid:
        return 0

    try:
        emb = await embed_texts([t for _, t in valid])
    except Exception as exc:
        logger.warning("向量生成失败: %s", exc)
        return 0

    for (cid, _), vec in zip(valid, emb):
        vectors[cid] = vec
    index["vectors"] = vectors
    index["model"] = settings.embedding_model
    store.save(index)
    return len(emb)


async def vector_search(
    company_id: str,
    query: str,
    top_k: int = 12,
) -> list[tuple[float, dict[str, Any]]]:
    """返回 (相似度, chunk) 列表。"""
    if not await is_embedding_available():
        return []
    q = (query or "").strip()
    if not q:
        return []

    from .localdb_knowledge_service import LocalDbKnowledgeService

    knowledge = LocalDbKnowledgeService(company_id)
    all_chunks = knowledge.load_index().get("chunks") or []
    if not all_chunks:
        return []

    store = EmbeddingIndexService(company_id)
    vectors: dict[str, list[float]] = store.load().get("vectors") or {}

    try:
        q_vec = (await embed_texts([q[:6000]]))[0]
    except Exception as exc:
        logger.warning("查询向量失败: %s", exc)
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for c in all_chunks:
        cid = str(c.get("id") or "")
        vec = vectors.get(cid)
        if not vec:
            continue
        sim = _cosine(q_vec, vec)
        if sim > 0.05:
            scored.append((sim, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]
