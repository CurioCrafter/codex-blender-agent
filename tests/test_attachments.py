from __future__ import annotations

from codex_blender_agent.attachments import build_attachment_payload, classify_attachment


def test_classify_attachment():
    assert classify_attachment("example.png") == "image"
    assert classify_attachment("example.md") == "text"
    assert classify_attachment("example.blend") == "file"


def test_build_attachment_payload_reads_text_file(tmp_path):
    text_file = tmp_path / "note.md"
    text_file.write_text("hello", encoding="utf-8")
    payload = build_attachment_payload([str(text_file)])
    assert payload.image_paths == []
    assert "hello" in payload.text_context
