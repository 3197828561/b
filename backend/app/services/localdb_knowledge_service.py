import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from ..config import settings


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

    当前实现：使用本地关键词 overlap 检索，不依赖向量库/embedding。
    这样可以先把“AI 能利用你上传的内容”跑通。
    """

    KNOWLEDGE_DIR = os.path.join(settings.upload_dir, "localdb")
    KNOWLEDGE_FILE = os.path.join(KNOWLEDGE_DIR, "knowledge.json")

    def __init__(self) -> None:
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

    def _remove_chunks(self, index: dict[str, Any], source_kind: str, source_file: str) -> None:
        index["chunks"] = [
            c
            for c in index.get("chunks", [])
            if not (c.get("source_kind") == source_kind and c.get("source_file") == source_file)
        ]

    def upsert_upload_chunks(
        self,
        source_kind: str,  # tender / bid
        source_file: str,
        extracted_text: str,
        mtime: str,
    ) -> None:
        index = self.load_index()
        self._remove_chunks(index, source_kind=source_kind, source_file=source_file)

        chunks = _chunk_text(extracted_text)
        for ch in chunks:
            tokens = _tokenize_for_match(ch)
            if not tokens:
                continue
            chunk_obj = KnowledgeChunk(
                id=uuid.uuid4().hex,
                source_kind=source_kind,
                source_file=source_file,
                mtime=mtime,
                text=ch,
                tokens=tokens,
            )
            index["chunks"].append(chunk_obj.__dict__)

        self.save_index(index)

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
        self._remove_chunks(index, source_kind=source_kind, source_file=source_file)

        chunks = _chunk_text(extracted_text)
        for ch in chunks:
            tokens = _tokenize_for_match(ch)
            if not tokens:
                continue
            index["chunks"].append(
                KnowledgeChunk(
                    id=uuid.uuid4().hex,
                    source_kind=source_kind,
                    source_file=source_file,
                    mtime=mtime,
                    text=ch,
                    tokens=tokens,
                ).__dict__
            )
        self.save_index(index)

    def delete_upload_chunks(self, source_kind: str, source_file: str) -> None:
        index = self.load_index()
        self._remove_chunks(index, source_kind=source_kind, source_file=source_file)
        self.save_index(index)

    def get_company_materials(self, max_chunks: int = 2) -> list[dict[str, Any]]:
        index = self.load_index()
        company_chunks = [c for c in index.get("chunks", []) if c.get("source_kind") == "company"]
        # 简单按 mtime 倒序展示
        company_chunks = sorted(company_chunks, key=lambda x: x.get("mtime", ""), reverse=True)
        return company_chunks[:max_chunks]

    def retrieve_relevant_chunks(
        self,
        query: str,
        top_k: int = 4,
        include_company: bool = True,
    ) -> list[dict[str, Any]]:
        """
        overlap 计分：query_tokens 与 chunk.tokens 的交集大小。
        """
        index = self.load_index()
        chunks = index.get("chunks", [])
        if not chunks:
            return []

        query_tokens = _tokenize_for_match(query)
        if not query_tokens:
            return self.get_company_materials() if include_company else []

        # 为了性能，用 set 做 overlap 计数（忽略重复 token）
        qset = set(query_tokens)

        scored: list[tuple[int, dict[str, Any]]] = []
        for c in chunks:
            if include_company is False and c.get("source_kind") == "company":
                continue
            tokens = c.get("tokens") or []
            if not tokens:
                continue
            overlap = qset.intersection(set(tokens))
            score = len(overlap)
            if score <= 0:
                continue
            scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [c for _, c in scored[:top_k]]

        if include_company:
            picked_company = self.get_company_materials(max_chunks=2)
            # 去重（id）
            picked_ids = {c.get("id") for c in picked}
            for c in picked_company:
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
            label = (
                "【公司基本信息】"
                if source_kind == "company"
                else f"【{source_kind}文件】{source_file}"
            )
            refs.append(f"{label}\n{text}")
        return refs


def now_mtime_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

