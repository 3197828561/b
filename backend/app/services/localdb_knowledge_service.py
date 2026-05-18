import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from ..config import settings
from ..utils.localdb_paths import localdb_company_root, sanitize_company_id

logger = logging.getLogger(__name__)


def _tokenize_for_match(text: str) -> list[str]:
    """
    简单可用的“词”切分：中文按单字符，英文/数字按连续 token。
    不追求语言学准确，但适合做本地关键词检索。
    """
    if not text:
        return []
    lower = text.lower()
    word_tokens = re.findall(r"[a-z0-9]+", lower)
    han_tokens = re.findall(r"[\u4e00-\u9fff]", text)
    tokens = word_tokens + han_tokens
    # 去重但保留数量权重（用于 overlap 计分），因此这里不做集合去重
    return tokens


def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 200) -> list[str]:
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    start = 0
    stride = max_chars - overlap
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        chunks.append(normalized[start:end])
        if end >= len(normalized):
            break
        start += stride
        if stride <= 0:
            break
    return chunks


@dataclass
class KnowledgeChunk:
    id: str
    source_kind: str  # tender / bid / company
    source_file: str  # filename or "company"
    mtime: str
    text: str
    tokens: list[str]


class LocalDbKnowledgeService:
    """
    本地知识库（文件抽取文本 -> 切片 -> 保存 -> 检索 -> 注入提示词）。

    检索：关键词 overlap + 可选 OpenAI 向量混合检索。

    company_id：与前端选择的公司一致；default 使用旧版 uploads/localdb 扁平目录。
    """

    def __init__(self, company_id: str = "default") -> None:
        self.company_id = sanitize_company_id(company_id)
        self.KNOWLEDGE_DIR = localdb_company_root(self.company_id)
        self.KNOWLEDGE_FILE = os.path.join(self.KNOWLEDGE_DIR, "knowledge.json")
        os.makedirs(self.KNOWLEDGE_DIR, exist_ok=True)

    def _empty_index(self) -> dict[str, Any]:
        return {"version": 1, "chunks": []}

    def load_index(self) -> dict[str, Any]:
        if not os.path.exists(self.KNOWLEDGE_FILE):
            return self._empty_index()
        try:
            with open(self.KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return self._empty_index()

    def save_index(self, index: dict[str, Any]) -> None:
        tmp = f"{self.KNOWLEDGE_FILE}.{uuid.uuid4().hex}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        os.replace(tmp, self.KNOWLEDGE_FILE)

    def _remove_chunks(self, index: dict[str, Any], source_kind: str, source_file: str) -> list[str]:
        removed_ids: list[str] = []
        kept: list[dict[str, Any]] = []
        for c in index.get("chunks", []):
            if c.get("source_kind") == source_kind and c.get("source_file") == source_file:
                if c.get("id"):
                    removed_ids.append(str(c["id"]))
            else:
                kept.append(c)
        index["chunks"] = kept
        return removed_ids

    def upsert_upload_chunks(
        self,
        source_kind: str,  # tender / bid
        source_file: str,
        extracted_text: str,
        mtime: str,
    ) -> None:
        self.upsert_chunks_for_kind(
            source_kind=source_kind,
            source_file=source_file,
            extracted_text=extract_text,
            mtime=mtime,
        )

    def upsert_company_chunks(self, company_text: str, mtime: str) -> None:
        # 公司基本信息作为固定 source_file="company"
        self.upsert_chunks_for_kind(source_kind="company", source_file="company", extracted_text=company_text, mtime=mtime)

    def upsert_chunks_for_kind(
        self,
        source_kind: str,
        source_file: str,
        extracted_text: str,
        mtime: str,
    ) -> None:
        index = self.load_index()
        removed_ids = self._remove_chunks(index, source_kind=source_kind, source_file=source_file)
        if removed_ids:
            self._purge_embedding_ids(set(removed_ids))

        new_chunks: list[dict[str, Any]] = []
        chunks = _chunk_text(extracted_text)
        for ch in chunks:
            tokens = _tokenize_for_match(ch)
            if not tokens:
                continue
            obj = KnowledgeChunk(
                id=uuid.uuid4().hex,
                source_kind=source_kind,
                source_file=source_file,
                mtime=mtime,
                text=ch,
                tokens=tokens,
            )
            new_chunks.append(obj.__dict__)
            index["chunks"].append(obj.__dict__)
        self.save_index(index)
        if new_chunks:
            self._schedule_embedding_sync(new_chunks)

    def delete_upload_chunks(self, source_kind: str, source_file: str) -> None:
        index = self.load_index()
        self._remove_chunks(index, source_kind=source_kind, source_file=source_file)
        self.save_index(index)

    def clear_document_chunks(self, source_kinds: Iterable[str] | None = None) -> int:
        """清除资料类切片，保留公司基本信息（company）。"""
        kinds = set(source_kinds or ("file", "tender", "bid"))
        index = self.load_index()
        before = len(index.get("chunks", []))
        index["chunks"] = [
            c for c in index.get("chunks", []) if c.get("source_kind") not in kinds
        ]
        removed = before - len(index["chunks"])
        self.save_index(index)
        return removed

    def get_company_materials(self, max_chunks: int = 2) -> list[dict[str, Any]]:
        index = self.load_index()
        company_chunks = [c for c in index.get("chunks", []) if c.get("source_kind") == "company"]
        # 简单按 mtime 倒序展示
        company_chunks = sorted(company_chunks, key=lambda x: x.get("mtime", ""), reverse=True)
        return company_chunks[:max_chunks]

    def _purge_embedding_ids(self, chunk_ids: set[str]) -> None:
        try:
            from .embedding_service import EmbeddingIndexService

            EmbeddingIndexService(self.company_id).remove_chunk_ids(chunk_ids)
        except Exception as exc:
            logger.debug("清理向量索引失败: %s", exc)

    def _schedule_embedding_sync(self, chunks: list[dict[str, Any]]) -> None:
        if not settings.embedding_enabled:
            return
        try:
            import asyncio
            from .embedding_service import sync_embeddings_for_chunks

            asyncio.create_task(sync_embeddings_for_chunks(self.company_id, chunks))
        except Exception as exc:
            logger.debug("调度向量同步失败: %s", exc)

    def _keyword_scores(
        self, query: str, chunks: list[dict[str, Any]], include_company: bool
    ) -> dict[str, float]:
        query_tokens = _tokenize_for_match(query)
        if not query_tokens:
            return {}
        qset = set(query_tokens)
        out: dict[str, float] = {}
        for c in chunks:
            if include_company is False and c.get("source_kind") == "company":
                continue
            cid = str(c.get("id") or "")
            tokens = c.get("tokens") or []
            if not tokens or not cid:
                continue
            overlap = qset.intersection(set(tokens))
            score = float(len(overlap))
            if score <= 0:
                continue
            source_file = str(c.get("source_file") or "")
            score += float(len(qset.intersection(set(_tokenize_for_match(source_file)))))
            if c.get("source_kind") == "company":
                score += 1.0
            out[cid] = score
        return out

    async def retrieve_relevant_chunks_async(
        self,
        query: str,
        top_k: int = 6,
        include_company: bool = True,
    ) -> list[dict[str, Any]]:
        return await self._retrieve_hybrid(query, top_k, include_company)

    def retrieve_relevant_chunks(
        self,
        query: str,
        top_k: int = 6,
        include_company: bool = True,
    ) -> list[dict[str, Any]]:
        """同步入口：仅关键词；异步生成正文时请用 retrieve_relevant_chunks_async。"""
        index = self.load_index()
        chunks = index.get("chunks", [])
        if not chunks:
            return []
        kw = self._keyword_scores(query, chunks, include_company)
        if not kw:
            return self.get_company_materials() if include_company else []
        by_id = {str(c.get("id")): c for c in chunks if c.get("id")}
        ranked = sorted(kw.items(), key=lambda x: x[1], reverse=True)[:top_k]
        picked = [by_id[cid] for cid, _ in ranked if cid in by_id]
        if include_company:
            picked_ids = {c.get("id") for c in picked}
            for c in self.get_company_materials(max_chunks=2):
                if c.get("id") not in picked_ids:
                    picked.append(c)
        return picked

    async def _retrieve_hybrid(
        self,
        query: str,
        top_k: int = 6,
        include_company: bool = True,
    ) -> list[dict[str, Any]]:
        index = self.load_index()
        chunks = index.get("chunks", [])
        if not chunks:
            return []

        query_tokens = _tokenize_for_match(query)
        if not query_tokens:
            return self.get_company_materials() if include_company else []

        by_id = {str(c.get("id")): c for c in chunks if c.get("id")}
        kw = self._keyword_scores(query, chunks, include_company)

        vec_scores: dict[str, float] = {}
        if settings.embedding_enabled:
            try:
                from .embedding_service import vector_search

                for sim, c in await vector_search(self.company_id, query, top_k=top_k * 3):
                    cid = str(c.get("id") or "")
                    if cid:
                        vec_scores[cid] = sim
            except Exception as exc:
                logger.debug("向量检索失败，回退关键词: %s", exc)

        if not kw and not vec_scores:
            return self.get_company_materials() if include_company else []

        max_kw = max(kw.values()) if kw else 1.0
        max_vec = max(vec_scores.values()) if vec_scores else 1.0
        wv = settings.embedding_hybrid_weight
        wk = 1.0 - wv

        combined: dict[str, float] = {}
        for cid in set(kw) | set(vec_scores):
            s = 0.0
            if cid in kw:
                s += wk * (kw[cid] / max_kw)
            if cid in vec_scores:
                s += wv * (vec_scores[cid] / max_vec)
            combined[cid] = s

        ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]
        picked = [by_id[cid] for cid, _ in ranked if cid in by_id]

        if include_company:
            picked_ids = {c.get("id") for c in picked}
            for c in self.get_company_materials(max_chunks=2):
                if c.get("id") not in picked_ids:
                    picked.append(c)
        return picked

    def format_reference_materials(self, chunks: Iterable[dict[str, Any]]) -> list[str]:
        refs: list[str] = []
        for c in chunks:
            source_kind = c.get("source_kind", "unknown")
            source_file = c.get("source_file", "")
            text = c.get("text", "")
            # 截断，避免 prompt 过长
            if len(text) > 900:
                text = text[:900] + "..."
            if source_kind == "company":
                label = "【公司基本信息】"
            elif source_kind in ("file", "tender", "bid"):
                label = f"【资料】{source_file}"
            else:
                label = f"【{source_kind}】{source_file}"
            refs.append(f"{label}\n{text}")
        return refs


def now_mtime_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

