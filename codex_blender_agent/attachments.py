from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .constants import MAX_TEXT_ATTACHMENT_BYTES


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".py",
    ".csv",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".obj",
    ".mtl",
    ".svg",
}


@dataclass
class AttachmentPayload:
    text_context: str = ""
    image_paths: list[str] = field(default_factory=list)


def classify_attachment(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    return "file"


def build_attachment_payload(paths: list[str]) -> AttachmentPayload:
    image_paths: list[str] = []
    text_blocks: list[str] = []

    for raw_path in paths:
        path = Path(raw_path).expanduser()
        kind = classify_attachment(str(path))
        if not path.exists():
            text_blocks.append(f"Attachment missing: {path}")
            continue

        if kind == "image":
            image_paths.append(str(path))
            text_blocks.append(f"Attached image: {path}")
            continue

        if kind == "text":
            text_blocks.append(_read_text_attachment(path))
            continue

        text_blocks.append(f"Attached file path: {path}\nThis file is not a supported text or image attachment, so only its path was provided.")

    return AttachmentPayload(text_context="\n\n".join(text_blocks), image_paths=image_paths)


def _read_text_attachment(path: Path) -> str:
    raw = path.read_bytes()
    truncated = len(raw) > MAX_TEXT_ATTACHMENT_BYTES
    raw = raw[:MAX_TEXT_ATTACHMENT_BYTES]
    text = raw.decode("utf-8", errors="replace")
    suffix = "\n\n[Attachment truncated.]" if truncated else ""
    return f"Attached text file: {path}\n```text\n{text}\n```{suffix}"
