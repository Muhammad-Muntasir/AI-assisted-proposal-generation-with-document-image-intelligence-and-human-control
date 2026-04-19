"""
Bug Condition Exploration Report

This script documents all counterexamples found in the unfixed infrastructure.
"""

import sys
from pathlib import Path

# Add parent directory to path to import test functions
sys.path.insert(0, str(Path(__file__).parent))

from test_bug_condition_exploration import (
    count_lambda_functions_in_cdk,
    count_lambda_updates_in_workflow,
    check_cleanup_preserves_unified_handler,
    check_handler_file_exists,
)


def generate_bug_report():
    """Generate a detailed report of all bug conditions found."""
    
    print("=" * 70)
    print("BUG CONDITION EXPLORATION REPORT")
    print("=" * 70)
    print()
    print("This report documents counterexamples that prove the bug exists.")
    print()
    
    # Test 1: CDK Stack Lambda Count
    print("1. CDK Stack Lambda Function Count")
    print("-" * 70)
    cdk_lambda_count = count_lambda_functions_in_cdk("infrastructure/src/stack.ts")
    print(f"   Expected: 1 Lambda function")
    print(f"   Actual:   {cdk_lambda_count} Lambda functions")
    print(f"   Status:   {'✓ PASS' if cdk_lambda_count == 1 else '✗ FAIL (Bug detected)'}")
    print()
    
    # Test 2: Workflow Lambda Update Count
    print("2. GitHub Actions Workflow Lambda Update Commands")
    print("-" * 70)
    workflow_update_count = count_lambda_updates_in_workflow(".github/workflows/main.yml")
    print(f"   Expected: 1 update command")
    print(f"   Actual:   {workflow_update_count} update commands")
    print(f"   Status:   {'✓ PASS' if workflow_update_count == 1 else '✗ FAIL (Bug detected)'}")
    print()
    
    # Test 3: Cleanup Preservation
    print("3. Deployment Cleanup File Preservation")
    print("-" * 70)
    preserves_unified = check_cleanup_preserves_unified_handler(".github/workflows/main.yml")
    print(f"   Expected: Preserves 'handler.py' (not 'generate.py' or 'proposals.py')")
    print(f"   Actual:   {'Preserves handler.py' if preserves_unified else 'Preserves generate.py and proposals.py'}")
    print(f"   Status:   {'✓ PASS' if preserves_unified else '✗ FAIL (Bug detected)'}")
    print()
    
    # Test 4: Handler File Existence
    print("4. Unified Handler File Existence")
    print("-" * 70)
    handler_exists = check_handler_file_exists("backend/")
    print(f"   Expected: handler.py exists")
    print(f"   Actual:   {'handler.py exists' if handler_exists else 'handler.py does NOT exist'}")
    print(f"   Status:   {'✓ PASS' if handler_exists else '✗ FAIL (Bug detected)'}")
    print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    all_pass = (
        cdk_lambda_count == 1 and
        workflow_update_count == 1 and
        preserves_unified and
        handler_exists
    )
    
    if all_pass:
        print("✓ All checks passed - Bug is FIXED")
        print()
        print("The infrastructure now:")
        print("  - Creates only 1 Lambda function")
        print("  - Updates only 1 Lambda function in CI/CD")
        print("  - Preserves only the unified handler.py")
        print("  - Has the unified handler.py file in place")
    else:
        print("✗ Bug condition detected - Bug EXISTS in current infrastructure")
        print()
        print("Counterexamples found:")
        if cdk_lambda_count != 1:
            print(f"  - CDK creates {cdk_lambda_count} Lambda functions (expected 1)")
        if workflow_update_count != 1:
            print(f"  - Workflow updates {workflow_update_count} Lambda functions (expected 1)")
        if not preserves_unified:
            print(f"  - Cleanup preserves obsolete files instead of handler.py")
        if not handler_exists:
            print(f"  - Unified handler.py does not exist")
        print()
        print("These counterexamples confirm the bug exists and needs to be fixed.")
    
    print("=" * 70)
    
    return all_pass


if __name__ == "__main__":
    bug_fixed = generate_bug_report()
    sys.exit(0 if bug_fixed else 1)
