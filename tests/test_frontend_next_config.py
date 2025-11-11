from pathlib import Path

NEXT_CONFIG = Path("frontend/next.config.ts")


def test_next_config_output_standalone():
    src = NEXT_CONFIG.read_text(encoding="utf-8")
    assert 'output: "standalone"' in src or "output: 'standalone'" in src