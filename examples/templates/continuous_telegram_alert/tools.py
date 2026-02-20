"""Custom tools for Continuous Telegram Alert Agent."""


def tool(func):
    """Minimal @tool decorator — marks a function for auto-discovery by ToolRegistry."""
    func._tool_metadata = {"name": func.__name__}
    return func


@tool
def check_signal(iteration: int) -> dict:
    """
    Increment the iteration counter and determine whether monitoring should halt.

    Args:
        iteration: Current iteration count (integer).

    Returns:
        Dict with new_iteration (int) and halt (bool).
    """
    new_iteration = int(iteration) + 1
    halt = new_iteration >= 3
    return {"new_iteration": new_iteration, "halt": halt}


@tool
def send_alert(iteration: int, halt: bool) -> dict:
    """
    Send a monitoring alert for the current iteration.

    Args:
        iteration: Current iteration number.
        halt: Whether this is the final alert.

    Returns:
        Dict with status and message confirming the alert was sent.
    """
    status = "final" if halt else "ongoing"
    message = f"[Monitoring Alert] Iteration {iteration} — status: {status}"
    print(message)
    return {"sent": True, "message": message, "iteration": iteration, "halt": halt}
