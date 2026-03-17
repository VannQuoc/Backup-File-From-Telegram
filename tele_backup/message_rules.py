from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ARCHIVE_EXTENSIONS = {".zip", ".rar"}


@dataclass(frozen=True)
class FileDecision:
    extension: str
    topic_id: int
    preserve_caption: bool
    dedupe_txt: bool


def normalize_filename(filename: str | None) -> str:
    if not filename:
        return ""
    return Path(filename).name.lower().strip()


def detect_extension(filename: str | None) -> str:
    normalized = normalize_filename(filename)
    if not normalized:
        return ""
    return Path(normalized).suffix


def decide_file_handling(
    filename: str | None,
    default_topic_id: int,
    archive_topic_id: int,
) -> FileDecision:
    extension = detect_extension(filename)
    if extension in ARCHIVE_EXTENSIONS:
        return FileDecision(
            extension=extension,
            topic_id=archive_topic_id,
            preserve_caption=True,
            dedupe_txt=False,
        )
    return FileDecision(
        extension=extension,
        topic_id=default_topic_id,
        preserve_caption=False,
        dedupe_txt=extension == ".txt",
    )


def build_txt_fingerprint(
    document_id: int | None,
    size: int | None,
    normalized_filename: str,
) -> str | None:
    if document_id is None or size is None:
        return None
    return f"{document_id}:{size}:{normalized_filename}"
