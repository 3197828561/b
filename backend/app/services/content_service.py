"""正文生成服务。"""

from typing import Any, AsyncGenerator, Optional

from ..utils.openai_util import OpenAIUtil
from ..utils.prompts.content_prompts import (
    build_chapter_content_messages,
    diversity_temperature,
)
from .localdb_knowledge_service import LocalDbKnowledgeService


class ContentService:
    """负责目录叶子章节的正文生成。"""

    def __init__(self, ai: OpenAIUtil | None = None):
        self.ai = ai or OpenAIUtil()

    async def stream_chapter_content(
        self,
        chapter: dict[str, Any],
        parent_chapters: list[dict[str, Any]] | None = None,
        sibling_chapters: list[dict[str, Any]] | None = None,
        project_overview: str = "",
        chapter_word_count_min: int = 800,
        chapter_word_count_max: int = 2500,
        book_word_count_min: Optional[int] = None,
        book_word_count_max: Optional[int] = None,
        leaf_chapter_index: Optional[int] = None,
        leaf_chapter_total: Optional[int] = None,
        localdb_company_id: str = "default",
        company_display_name: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """流式生成单章节内容。"""
        cn = (company_display_name or "").strip()
        chapter_title = str(chapter.get("title") or "")
        chapter_desc = str(chapter.get("description") or "")
        query_parts: list[str] = []
        if cn:
            query_parts.append(cn)
        if chapter_title.strip():
            query_parts.append(chapter_title)
        if chapter_desc.strip():
            query_parts.append(chapter_desc)
        if project_overview.strip():
            query_parts.append(project_overview)
        query = "\n".join(query_parts).strip()

        knowledge = LocalDbKnowledgeService(localdb_company_id)
        reference_chunks = await knowledge.retrieve_relevant_chunks_async(
            query=query,
            top_k=6,
            include_company=True,
        )
        reference_materials = knowledge.format_reference_materials(reference_chunks)

        messages = build_chapter_content_messages(
            chapter=chapter,
            parent_chapters=parent_chapters,
            sibling_chapters=sibling_chapters,
            project_overview=project_overview,
            reference_materials=reference_materials,
            chapter_word_count_min=chapter_word_count_min,
            chapter_word_count_max=chapter_word_count_max,
            book_word_count_min=book_word_count_min,
            book_word_count_max=book_word_count_max,
            leaf_chapter_index=leaf_chapter_index,
            leaf_chapter_total=leaf_chapter_total,
            company_display_name=cn,
            localdb_company_id=localdb_company_id,
        )
        ch_id = str(chapter.get("id") or "unknown")
        temp = diversity_temperature(0.7, localdb_company_id, ch_id)
        async for chunk in self.ai.stream_chat_completion(messages, temperature=temp):
            yield chunk

    async def generate_chapter_content(
        self,
        chapter: dict[str, Any],
        parent_chapters: list[dict[str, Any]] | None = None,
        sibling_chapters: list[dict[str, Any]] | None = None,
        project_overview: str = "",
        chapter_word_count_min: int = 800,
        chapter_word_count_max: int = 2500,
        book_word_count_min: Optional[int] = None,
        book_word_count_max: Optional[int] = None,
        leaf_chapter_index: Optional[int] = None,
        leaf_chapter_total: Optional[int] = None,
        localdb_company_id: str = "default",
        company_display_name: Optional[str] = None,
    ) -> str:
        """生成单章节完整正文。"""
        cn = (company_display_name or "").strip()
        chapter_title = str(chapter.get("title") or "")
        chapter_desc = str(chapter.get("description") or "")
        query_parts: list[str] = []
        if cn:
            query_parts.append(cn)
        if chapter_title.strip():
            query_parts.append(chapter_title)
        if chapter_desc.strip():
            query_parts.append(chapter_desc)
        if project_overview.strip():
            query_parts.append(project_overview)
        query = "\n".join(query_parts).strip()

        knowledge = LocalDbKnowledgeService(localdb_company_id)
        reference_chunks = await knowledge.retrieve_relevant_chunks_async(
            query=query,
            top_k=6,
            include_company=True,
        )
        reference_materials = knowledge.format_reference_materials(reference_chunks)

        ch_id = str(chapter.get("id") or "unknown")
        temp = diversity_temperature(0.7, localdb_company_id, ch_id)
        return await self.ai.collect_chat_completion(
            build_chapter_content_messages(
                chapter=chapter,
                parent_chapters=parent_chapters,
                sibling_chapters=sibling_chapters,
                project_overview=project_overview,
                reference_materials=reference_materials,
                chapter_word_count_min=chapter_word_count_min,
                chapter_word_count_max=chapter_word_count_max,
                book_word_count_min=book_word_count_min,
                book_word_count_max=book_word_count_max,
                leaf_chapter_index=leaf_chapter_index,
                leaf_chapter_total=leaf_chapter_total,
                company_display_name=cn,
                localdb_company_id=localdb_company_id,
            ),
            temperature=temp,
        )
