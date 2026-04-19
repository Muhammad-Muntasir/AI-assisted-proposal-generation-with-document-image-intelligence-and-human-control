"""
Bug Condition Exploration Test for Duplicate Lambda Functions

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

This test verifies the EXPECTED BEHAVIOR (single Lambda function deployment).
When run on UNFIXED code, this test MUST FAIL, proving the bug exists.
When run on FIXED code, this test MUST PASS, proving the bug is resolved.

CRITICAL: This test encodes the expected behavior. DO NOT attempt to fix
the test or code when it fails - failure on unfixed code is the SUCCESS case
for bug condition exploration.
"""

import os
import re
from pathlib import Path
from hypothesis import given, strategies as st, settings


# ── Test Data Strategies ──────────────────────────────────────────────────

@st.composite
def infrastructure_deployment(draw):
    """
    Strategy that generates infrastructure deployment scenarios.
    For this scoped PBT approach, we use the actual concrete files.
    """
    # We're testing the actual infrastructure files, not generated data
    # This ensures reproducibility and tests the real bug condition
    return {
        "cdk_stack_path": "infrastructure/src/stack.ts",
        "workflow_path": ".github/workflows/main.yml",
        "backend_path": "backend/",
    }


# ── Helper Functions ──────────────────────────────────────────────────────

def count_lambda_functions_in_cdk(stack_path: str) -> int:
    """
    Parse CDK stack TypeScript file and count lambda.Function constructs.
    
    Expected behavior: Should find exactly 1 Lambda function resource.
    Bug condition: Finds 2 Lambda function resources (GenerateLambda and ProposalsLambda).
    """
    repo_root = Path(__file__).parent.parent.parent
    full_path = repo_root / stack_path
    
    if not full_path.exists():
        raise FileNotFoundError(f"CDK stack not found at {full_path}")
    
    content = full_path.read_text()
    
    # Count occurrences of "new lambda.Function(" which creates Lambda resources
    lambda_function_pattern = r'new\s+lambda\.Function\s*\('
    matches = re.findall(lambda_function_pattern, content)
    
    return len(matches)


def count_lambda_updates_in_workflow(workflow_path: str) -> int:
    """
    Parse GitHub Actions workflow YAML and count 'aws lambda update-function-code' commands.
    
    Expected behavior: Should find exactly 1 update command.
    Bug condition: Finds 2 update commands (one for generate, one for proposals).
    """
    repo_root = Path(__file__).parent.parent.parent
    full_path = repo_root / workflow_path
    
    if not full_path.exists():
        raise FileNotFoundError(f"Workflow not found at {full_path}")
    
    content = full_path.read_text()
    
    # Count occurrences of "aws lambda update-function-code"
    update_pattern = r'aws\s+lambda\s+update-function-code'
    matches = re.findall(update_pattern, content)
    
    return len(matches)


def check_cleanup_preserves_unified_handler(workflow_path: str) -> bool:
    """
    Parse GitHub Actions workflow and check if cleanup step preserves handler.py.
    
    Expected behavior: Cleanup should preserve 'handler.py' (not generate.py/proposals.py).
    Bug condition: Cleanup preserves 'generate.py' and 'proposals.py' instead.
    """
    repo_root = Path(__file__).parent.parent.parent
    full_path = repo_root / workflow_path
    
    if not full_path.exists():
        raise FileNotFoundError(f"Workflow not found at {full_path}")
    
    content = full_path.read_text()
    
    # Check if cleanup step preserves handler.py (expected behavior)
    # and does NOT preserve generate.py or proposals.py (bug condition)
    preserves_handler = "! -name 'handler.py'" in content
    preserves_generate = "! -name 'generate.py'" in content
    preserves_proposals = "! -name 'proposals.py'" in content
    
    # Expected: preserves handler.py, NOT generate.py or proposals.py
    # Bug: preserves generate.py and proposals.py, NOT handler.py
    return preserves_handler and not preserves_generate and not preserves_proposals


def check_handler_file_exists(backend_path: str) -> bool:
    """
    Check if unified handler.py exists in backend directory.
    
    Expected behavior: handler.py should exist.
    Bug condition: handler.py does not exist (only generate.py and proposals.py exist).
    """
    repo_root = Path(__file__).parent.parent.parent
    handler_path = repo_root / backend_path / "handler.py"
    
    return handler_path.exists()


# ── Property 1: Bug Condition - Single Lambda Function Deployment ─────────

@given(deployment=infrastructure_deployment())
@settings(max_examples=10, deadline=None)
def test_single_lambda_function_deployment(deployment):
    """
    Property 1: Bug Condition - Single Lambda Function Deployment
    
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    
    For any infrastructure deployment where the backend code is being deployed,
    the system SHALL create and update only one Lambda function resource with
    a unified handler, eliminating duplicate function costs.
    
    EXPECTED OUTCOME ON UNFIXED CODE: This test WILL FAIL
    - CDK stack creates 2 Lambda functions (not 1)
    - Workflow updates 2 Lambda functions (not 1)
    - Cleanup preserves generate.py and proposals.py (not handler.py)
    - handler.py does not exist
    
    EXPECTED OUTCOME ON FIXED CODE: This test WILL PASS
    - CDK stack creates 1 Lambda function
    - Workflow updates 1 Lambda function
    - Cleanup preserves handler.py (not obsolete files)
    - handler.py exists
    
    This confirms the bug is resolved and expected behavior is satisfied.
    """
    cdk_stack_path = deployment["cdk_stack_path"]
    workflow_path = deployment["workflow_path"]
    backend_path = deployment["backend_path"]
    
    # ── Assertion 1: CDK stack creates exactly ONE Lambda function ────────
    lambda_count = count_lambda_functions_in_cdk(cdk_stack_path)
    assert lambda_count == 1, (
        f"Expected CDK stack to create 1 Lambda function, but found {lambda_count}. "
        f"Bug condition: Multiple Lambda functions exist (GenerateLambda and ProposalsLambda). "
        f"Expected behavior: Single unified Lambda function."
    )
    
    # ── Assertion 2: Workflow updates exactly ONE Lambda function ─────────
    update_count = count_lambda_updates_in_workflow(workflow_path)
    assert update_count == 1, (
        f"Expected workflow to update 1 Lambda function, but found {update_count} update commands. "
        f"Bug condition: Workflow deploys to multiple Lambda functions. "
        f"Expected behavior: Single Lambda function update."
    )
    
    # ── Assertion 3: Cleanup preserves handler.py (not obsolete files) ────
    preserves_unified = check_cleanup_preserves_unified_handler(workflow_path)
    assert preserves_unified, (
        f"Expected cleanup to preserve 'handler.py' (not 'generate.py' or 'proposals.py'). "
        f"Bug condition: Cleanup preserves obsolete separate handler files. "
        f"Expected behavior: Cleanup preserves only unified handler.py."
    )
    
    # ── Assertion 4: Unified handler.py exists ────────────────────────────
    handler_exists = check_handler_file_exists(backend_path)
    assert handler_exists, (
        f"Expected unified handler.py to exist in {backend_path}. "
        f"Bug condition: Only separate generate.py and proposals.py exist. "
        f"Expected behavior: Unified handler.py exists."
    )


# ── Run Tests Directly ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running Bug Condition Exploration Test...")
    print("=" * 70)
    print("CRITICAL: This test encodes EXPECTED BEHAVIOR.")
    print("On UNFIXED code: Test MUST FAIL (proves bug exists)")
    print("On FIXED code: Test MUST PASS (proves bug is resolved)")
    print("=" * 70)
    print()
    
    try:
        test_single_lambda_function_deployment()
        print("\n✓ TEST PASSED: Expected behavior is satisfied (bug is fixed)")
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: Bug condition detected")
        print(f"\nCounterexample found:")
        print(f"{e}")
        print("\nThis failure confirms the bug exists in the current infrastructure.")
