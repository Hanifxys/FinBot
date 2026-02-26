# Plan: Fix SyntaxError in Premium AI Module

## Problem Analysis
The application fails to start due to a `SyntaxError: unterminated triple-quoted string literal` in `modules/premium_ai.py`. The traceback indicates the error is detected at line 273, but the actual start of the unterminated string is likely earlier, around line 225 or in the `system_prompt` definition.

## Proposed Steps

1.  **Analyze Code**: Read `modules/premium_ai.py` around the reported lines (100-200) to locate the missing closing triple quotes `"""`.
    -   Suspect: The `system_prompt` definition might have lost its closing quotes during a previous edit.

2.  **Fix Syntax Error**:
    -   Add the missing `"""` to close the `system_prompt` string.
    -   Ensure `user_prompt` is also correctly defined and closed.

3.  **Verification**:
    -   Run a syntax check locally using `python -m py_compile modules/premium_ai.py` to ensure no other syntax errors exist.

4.  **Deployment**:
    -   Commit the fix to the git repository.
    -   Push to `main` branch to trigger Koyeb redeployment.

## Outcome
The application should start successfully without `SyntaxError`, allowing the new Gamification features to be active.
