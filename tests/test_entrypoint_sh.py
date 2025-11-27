import subprocess
import textwrap
import tempfile
from pathlib import Path
import pytest


def _prepare_functions_script(original_path: Path, tmp_dir: Path) -> Path:
    """Create a modified copy of the entrypoint.sh without the final main invocation
    and with reduced timeouts suitable for fast testing.
    Returns the path to the modified script file.
    """
    content = original_path.read_text()
    # Remove the final main call to avoid running the service on source
    content = content.replace('\nmain "\$@"\n', '\n')

    # Reduce timeouts and delays for tests
    content = content.replace('HEALTH_CHECK_TIMEOUT=300', 'HEALTH_CHECK_TIMEOUT=2')
    content = content.replace('HEALTH_CHECK_INTERVAL=5', 'HEALTH_CHECK_INTERVAL=1')
    content = content.replace('MAX_RETRIES=3', 'MAX_RETRIES=3')
    content = content.replace('RETRY_DELAY=10', 'RETRY_DELAY=1')

    tmp_file = tmp_dir / "entrypoint_functions.sh"
    tmp_file.write_text(content)
    tmp_file.chmod(0o700)
    return tmp_file


@pytest.fixture
def functions_script(tmp_path: Path) -> Path:
    """Fixture that provides a path to a modified, safe-to-source copy of entrypoint.sh"""
    original = Path('scripts/ollama/entrypoint.sh')
    assert original.exists(), "Expected scripts/ollama/entrypoint.sh to exist"
    return _prepare_functions_script(original, tmp_path)


def _run_bash(script: str) -> subprocess.CompletedProcess:
    """Run a bash -c script and return CompletedProcess with stdout/stderr/text."""
    return subprocess.run(['bash', '-c', script], capture_output=True, text=True)


def test_download_model_success(functions_script: Path):
    """download_model should succeed when ollama pull returns success on first attempt.

    This test defines a mock ollama function that returns success immediately,
    sources the functions-only entrypoint script and invokes download_model.
    """
    script = textwrap.dedent(f"""
    # Mock ollama to succeed for pull
    function ollama() {{
        if [ "$1" = "pull" ]; then
            echo "mock pull $2"
            return 0
        fi
        if [ "$1" = "list" ]; then
            echo "{{ 'llama2' }}"
            return 0
        fi
        return 0
    }}

    source "{functions_script}"
    download_model "test-model"
    exit $?
    """)

    res = _run_bash(script)
    assert res.returncode == 0, f"Expected success but got rc={res.returncode}, stderr={res.stderr}"
    assert "downloaded successfully" in res.stdout.lower() or "downloaded" in res.stdout.lower()


def test_download_model_retry_then_success(functions_script: Path):
    """download_model should retry when ollama pull fails initially and succeed later.

    Mock ollama increments a counter and fails for the first two attempts, then succeeds.
    """
    script = textwrap.dedent(f"""
    CALLS=0
    function ollama() {{
        if [ "$1" = "pull" ]; then
            CALLS=$((CALLS+1))
            if [ $CALLS -lt 3 ]; then
                echo "simulated failure" >&2
                return 1
            else
                echo "simulated success"
                return 0
            fi
        fi
        if [ "$1" = "list" ]; then
            echo "test-model"
            return 0
        fi
        return 0
    }}

    source "{functions_script}"
    download_model "test-model"
    exit $?
    """)

    res = _run_bash(script)
    assert res.returncode == 0, f"Expected eventual success but got rc={res.returncode}, stderr={res.stderr}"
    # Ensure we saw retry warning text
    assert "retrying" in res.stdout.lower() or "retry" in res.stdout.lower()


def test_download_model_fail_after_retries(functions_script: Path):
    """download_model should fail after exhausting all retries when ollama always fails."""
    script = textwrap.dedent(f"""
    function ollama() {{
        if [ "$1" = "pull" ]; then
            echo "permanent failure" >&2
            return 1
        fi
        return 1
    }}

    source "{functions_script}"
    download_model "test-model"
    exit $?
    """)

    res = _run_bash(script)
    assert res.returncode != 0
    assert "failed to download model" in res.stderr.lower() or "failed to download" in res.stdout.lower() or "failed to download" in res.stderr.lower()


def test_verify_model_found_and_not_found(functions_script: Path):
    """verify_model should return success when model in list and failure otherwise."""
    # Case: model present
    script_present = textwrap.dedent(f"""
    function ollama() {{
        if [ "$1" = "list" ]; then
            echo "llama2"
            return 0
        fi
        return 0
    }}

    source "{functions_script}"
    verify_model "llama2"
    exit $?
    """)

    res_present = _run_bash(script_present)
    assert res_present.returncode == 0
    assert "verified" in res_present.stdout.lower() or "verified" in res_present.stderr.lower()

    # Case: model absent
    script_absent = textwrap.dedent(f"""
    function ollama() {{
        if [ "$1" = "list" ]; then
            echo "other-model"
            return 0
        fi
        return 0
    }}

    source "{functions_script}"
    verify_model "llama2"
    exit $?
    """)

    res_absent = _run_bash(script_absent)
    assert res_absent.returncode != 0
    assert "not found" in res_absent.stderr.lower() or "not found" in res_absent.stdout.lower()


def test_health_check_success_and_timeout(functions_script: Path):
    """health_check should succeed when curl returns success and fail on timeout when curl always fails."""
    # Success case: curl returns success immediately
    script_success = textwrap.dedent(f"""
    function curl() {{
        # Simulate -sf behavior; success
        return 0
    }}

    source "{functions_script}"
    health_check
    exit $?
    """)

    res_success = _run_bash(script_success)
    assert res_success.returncode == 0
    assert "healthy" in res_success.stdout.lower()

    # Timeout case: curl fails always
    script_timeout = textwrap.dedent(f"""
    function curl() {{
        return 1
    }}

    source "{functions_script}"
    health_check
    exit $?
    """)

    res_timeout = _run_bash(script_timeout)
    assert res_timeout.returncode != 0
    assert "health check failed" in res_timeout.stderr.lower() or "health check failed" in res_timeout.stdout.lower()


def test_monitor_memory_low_and_high(functions_script: Path):
    """monitor_memory should parse memory from curl output and warn when above threshold.

    The function greps for '"memory":<digits>' and converts to GB.
    We test a low value (1GB) and a high value (16GB) to exercise the warning branch.
    """
    # Low memory (1GB)
    low_json = '{"name":"test-model","memory":1073741824}'
    script_low = textwrap.dedent(f"""
    function curl() {{
        echo '{low_json}'
        return 0
    }}

    source "{functions_script}"
    monitor_memory "test-model"
    exit $?
    """)

    res_low = _run_bash(script_low)
    assert res_low.returncode == 0
    assert "memory usage" in res_low.stdout.lower()
    assert "high memory usage" not in res_low.stdout.lower()

    # High memory (16GB)
    high_json = '{"name":"test-model","memory":17179869184}'
    script_high = textwrap.dedent(f"""
    function curl() {{
        echo '{high_json}'
        return 0
    }}

    source "{functions_script}"
    monitor_memory "test-model"
    exit $?
    """)

    res_high = _run_bash(script_high)
    assert res_high.returncode == 0
    assert "memory usage" in res_high.stdout.lower()
    assert "high memory usage" in res_high.stdout.lower()