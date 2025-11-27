import re
from pathlib import Path
import pytest

FILE_PATH = Path("frontend/app/lib/api-client.ts")

@pytest.fixture(scope="module")
def file_content() -> str:
    """Load the TypeScript source for inspection by tests."""
    if not FILE_PATH.exists():
        pytest.skip(f"Source file not found: {FILE_PATH}")
    return FILE_PATH.read_text(encoding="utf-8")


def test_file_contains_imports(file_content: str) -> None:
    """Ensure required imports and top-level comments exist in the file."""
    assert "getSession" in file_content, "Expected getSession import from next-auth/react"
    assert "API client utility for making authenticated requests" in file_content


def test_constants_defined(file_content: str) -> None:
    """Verify that API_BASE_URL, DEFAULT_TIMEOUT and DEFAULT_RETRY constants are present with expected defaults."""
    assert re.search(r"const\s+API_BASE_URL\s*=\s*process\.env\.NEXT_PUBLIC_API_BASE_URL\s*\|\|\s*\"/api\"", file_content)
    assert re.search(r"const\s+DEFAULT_TIMEOUT\s*=\s*30000", file_content)
    assert re.search(r"const\s+DEFAULT_RETRY\s*=\s*3", file_content)


def test_interfaces_present(file_content: str) -> None:
    """Check that RequestOptions and ApiResponse interfaces are declared."""
    assert "interface RequestOptions" in file_content
    assert "interface ApiResponse" in file_content
    assert "data?: T;" in file_content and "error?: string;" in file_content and "status: number;" in file_content


def test_apiRequest_core_flow_present(file_content: str) -> None:
    """Verify apiRequest contains session retrieval, headers population and fetch usage."""
    assert "export async function apiRequest" in file_content
    assert "const session = await getSession()" in file_content
    # headers population
    assert "\"Content-Type\": \"application/json\"" in file_content
    assert "Authorization" in file_content
    # fetch invocation
    assert re.search(r"await fetch\(url, \{[\s\S]*headers,[\s\S]*signal: controller\.signal[\s\S]*\}\)", file_content), \
        "Expected fetch call using headers and AbortController.signal"


def test_abortcontroller_and_timeout_handling(file_content: str) -> None:
    """Ensure AbortController is used for timeouts and timeout is handled as AbortError returning 408."""
    assert "new AbortController()" in file_content
    assert "setTimeout(() => controller.abort(), timeout)" in file_content
    assert "if (error instanceof Error && error.name === \"AbortError\")" in file_content
    assert "Request timeout" in file_content
    assert "status: 408" in file_content
    assert "clearTimeout(timeoutId)" in file_content


def test_retry_logic_and_backoff(file_content: str) -> None:
    """Verify retry loop exists and uses incremental backoff between attempts."""
    # for loop for retry attempts
    assert re.search(r"for \(let attempt = 0; attempt < retry; attempt\+\+\)", file_content)
    # backoff sleep uses attempt+1 * 1000
    assert re.search(r"setTimeout\(resolve, 1000 \* \(attempt \+ 1\)\)", file_content)
    # final return when retries exhausted
    assert "return {\n    error: lastError?.message || \"Request failed\",\n    status: 0,\n  };" in file_content or "Request failed" in file_content


def test_non_ok_response_handling(file_content: str) -> None:
    """Check handling of non-2xx responses and usage of response.json().catch to avoid crash."""
    assert "if (!response.ok)" in file_content
    assert "const error = await response.json().catch(() => ({}))" in file_content
    assert "error.message || `HTTP ${response.status}`" in file_content


def test_method_wrappers_exist(file_content: str) -> None:
    """Validate convenience methods apiGet, apiPost, apiPut, apiDelete exist and POST/PUT stringify bodies."""
    assert "export async function apiGet" in file_content
    assert "export async function apiPost" in file_content
    assert "export async function apiPut" in file_content
    assert "export async function apiDelete" in file_content
    # Check that apiPost and apiPut JSON.stringify the body when data present
    assert re.search(r"body: data \? JSON\.stringify\(data\) : undefined", file_content)


def test_headers_default_and_merge(file_content: str) -> None:
    """Ensure Content-Type default header is merged with any provided headers from fetch options."""
    assert re.search(r"const headers: HeadersInit = \{[\s\S]*'Content-Type'\: \"application/json\",[\s\S]*\.\.\.fetchOptions\.headers,\s*\}\;", file_content) or \
           re.search(r"const headers: HeadersInit = \{\s*\"Content-Type\": \"application/json\",\s*\.\.\.fetchOptions.headers,\s*\}\;", file_content)


def test_file_structure_is_typescript(file_content: str) -> None:
    """Sanity: ensure file appears to be TypeScript (presence of type annotations and exports)."""
    assert "RequestOptions extends RequestInit" in file_content
    assert "export" in file_content


if __name__ == '__main__':
    pytest.main([__file__])