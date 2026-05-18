"""本地库导出图片：列出内嵌图并按章节匹配插入 Word。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from ..utils.localdb_paths import LOCALDB_EXTRACTED_DIR, localdb_company_root


# 章节标题含以下词时，导出 Word 尝试插入本地库图片
CHAPTER_IMAGE_KEYWORDS = (
    "资质",
    "业绩",
    "证书",
    "荣誉",
    "人员",
    "团队",
    "社保",
    "执照",
    "许可",
    "证明",
    "信用",
    "获奖",
    "资格",
    "简介",
    "公司",
    "法人",
    "授权",
    "承诺",
    "安全生产",
    "体系认证",
)


@dataclass
class LocalDbImageAsset:
    abs_path: str
    rel_path: str
    source_file: str
    image_name: str
    image_index: int


def _tokenize(text: str) -> set[str]:
    if not text:
        return set()
    lower = text.lower()
    words = set(re.findall(r"[a-z0-9]+", lower))
    han = set(re.findall(r"[\u4e00-\u9fff]", text))
    for i in range(len(text) - 1):
        pair = text[i : i + 2]
        if re.match(r"[\u4e00-\u9fff]{2}", pair):
            han.add(pair)
    return words | han


def list_company_extracted_images(company_id: str) -> list[LocalDbImageAsset]:
    """扫描该公司 _extracted 下全部内嵌图。"""
    root = localdb_company_root(company_id)
    extracted_root = os.path.join(root, LOCALDB_EXTRACTED_DIR)
    if not os.path.isdir(extracted_root):
        return []

    assets: list[LocalDbImageAsset] = []
    for folder in os.listdir(extracted_root):
        folder_path = os.path.join(extracted_root, folder)
        if not os.path.isdir(folder_path):
            continue
        source_file = folder  # 文件夹名由源文件名 stem 而来
        for fn in sorted(os.listdir(folder_path)):
            if not re.match(r"img_\d+\.(png|jpg|jpeg|gif|bmp|webp)$", fn, re.I):
                continue
            full = os.path.join(folder_path, fn)
            if not os.path.isfile(full):
                continue
            m = re.match(r"img_(\d+)", fn, re.I)
            idx = int(m.group(1)) if m else 0
            rel = os.path.relpath(full, root).replace("\\", "/")
            assets.append(
                LocalDbImageAsset(
                    abs_path=full,
                    rel_path=rel,
                    source_file=source_file,
                    image_name=fn,
                    image_index=idx,
                )
            )
    return assets


def chapter_wants_images(chapter_title: str, chapter_description: str = "") -> bool:
    blob = f"{chapter_title} {chapter_description}"
    return any(kw in blob for kw in CHAPTER_IMAGE_KEYWORDS)


def pick_images_for_chapter(
    chapter_title: str,
    chapter_description: str,
    assets: list[LocalDbImageAsset],
    max_images: int = 4,
) -> list[LocalDbImageAsset]:
    """按章节标题与资料文件名相关性选取图片。"""
    if not assets or max_images <= 0:
        return []
    if not chapter_wants_images(chapter_title, chapter_description):
        return []

    query = f"{chapter_title} {chapter_description}".strip()
    q_tokens = _tokenize(query)

    scored: list[tuple[int, LocalDbImageAsset]] = []
    for asset in assets:
        stem_tokens = _tokenize(asset.source_file)
        score = len(q_tokens.intersection(stem_tokens)) if q_tokens else 0
        scored.append((score, asset))

    scored.sort(key=lambda x: (-x[0], x[1].source_file, x[1].image_index))
    with_match = [asset for score, asset in scored if score > 0]
    if with_match:
        return with_match[:max_images]
    return [asset for _, asset in scored[:max_images]]
