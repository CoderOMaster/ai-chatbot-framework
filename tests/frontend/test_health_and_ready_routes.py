import re
from pathlib import Path


def read(p):
    return Path(p).read_text(encoding="utf-8")


def test_health_route_exports_get_and_returns_status_ok():
    content = read("frontend/app/api/health/route.ts")
    assert "export async function GET()" in content
    # Basic check that NextResponse.json is called with { status: "ok" }
    assert "NextResponse.json" in content
    assert re.search(r"\{\s*status\s*:\s*['\"]ok['\"]\s*\}", content), content


def test_ready_route_exports_get_and_returns_ready_true():
    content = read("frontend/app/api/ready/route.ts")
    assert "export async function GET()" in content
    assert "NextResponse.json" in content
    assert re.search(r"\{\s*ready\s*:\s*true\s*\}", content), content