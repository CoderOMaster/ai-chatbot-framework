from pathlib import Path
import re


def test_server_js_has_health_and_standalone_delegation():
    p = Path("frontend/server.js")
    assert p.exists(), "frontend/server.js should exist"
    content = p.read_text()

    # Check for standalone delegation logic
    assert "const standalonePath" in content
    assert "spawn(process.execPath" in content or "child = spawn(process.execPath" in content

    # Check for health endpoints
    assert "/_health" in content or "/health" in content

    # Check for serving index from public
    assert "publicDir" in content
    assert "fs.createReadStream(indexPath)" in content or "createReadStream(indexPath)" in content

    # Check for server.listen and log message
    assert re.search(r"server.listen\(PORT, \(\) => \{[\s\S]*console.log\(", content)

    # Ensure fallback 404 handling exists
    assert "res.writeHead(404" in content and "Not Found" in content