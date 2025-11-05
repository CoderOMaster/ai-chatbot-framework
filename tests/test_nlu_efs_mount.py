from pathlib import Path


def test_efs_mount_doc_mentions_models():
    p = Path("ai-chatbot-framework/dockerfiles/nlu-efs-mount.md")
    assert p.exists()
    txt = p.read_text()
    assert "/models" in txt