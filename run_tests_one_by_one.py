#!/usr/bin/env python3
"""
Helper script to run tests one by one in the ai-chatbot-framework.

Usage:
    python run_tests_one_by_one.py                    # List all test files
    python run_tests_one_by_one.py <test_file>        # Run a specific test file
    python run_tests_one_by_one.py <test_file>::<test_function>  # Run a specific test
"""

import subprocess
import sys
import os
from pathlib import Path

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent
TESTS_DIR = SCRIPT_DIR / "tests"


def list_all_tests():
    """List all test files in the tests directory."""
    print("Available test files:\n")
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    for i, test_file in enumerate(test_files, 1):
        print(f"{i}. {test_file.name}")
    print(f"\nTotal: {len(test_files)} test files")
    print("\nTo run a specific test file:")
    print("  pytest tests/test_api.py")
    print("\nTo run a specific test function:")
    print("  pytest tests/test_api.py::test_health_when_not_loaded")


def run_test(test_target):
    """Run a specific test file or test function."""
    # Check if it's a test file path or a test function
    if "::" in test_target:
        # It's a test file with a specific function
        test_file, test_func = test_target.split("::", 1)
        if not test_file.startswith("tests/"):
            test_file = f"tests/{test_file}"
        cmd = ["pytest", "-v", f"{test_file}::{test_func}"]
    else:
        # It's just a test file
        if not test_target.startswith("tests/"):
            test_file = f"tests/{test_target}"
        else:
            test_file = test_target
        
        # Check if file exists
        full_path = SCRIPT_DIR / test_file
        if not full_path.exists():
            print(f"Error: Test file '{test_file}' not found!")
            list_all_tests()
            return
        
        cmd = ["pytest", "-v", test_file]
    
    print(f"Running: {' '.join(cmd)}\n")
    try:
        result = subprocess.run(cmd, cwd=SCRIPT_DIR)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\nTest run interrupted by user.")
        sys.exit(1)


def main():
    if len(sys.argv) == 1:
        # No arguments - list all tests
        list_all_tests()
    else:
        # Run the specified test
        test_target = sys.argv[1]
        run_test(test_target)


if __name__ == "__main__":
    main()

