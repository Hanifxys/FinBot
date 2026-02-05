import sys
import io
import traceback
import contextlib

def execute_code(code_str: str) -> str:
    """
    Executes Python code and returns the output or error message.
    Note: This is a simplified sandbox for internal bot tasks.
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    
    # Pre-defined locals for convenience in bot interaction
    local_vars = {}
    
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            # We use exec here as it's meant for internal bot configuration/scripting
            # For a real public sandbox, more security (e.g. Docker) would be needed
            exec(code_str, {}, local_vars)
    except Exception:
        return traceback.format_exc()
    
    output = stdout.getvalue()
    error = stderr.getvalue()
    
    if error:
        return f"Output:\n{output}\nErrors:\n{error}"
    return output if output else "Execution successful (no output)."
