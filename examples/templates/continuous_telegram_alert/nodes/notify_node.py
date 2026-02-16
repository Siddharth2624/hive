from framework.graph.node import NodeSpec

async def notify_handler(**kwargs):
    done = kwargs.get("done", False)
    iteration = kwargs.get("iteration", 0)
    if not done:
        print("Sending Telegram alert...")
    return {"done": done, "iteration": iteration}

notify_node = NodeSpec(
    id="notify",
    name="Notify",
    description="Send Telegram alert.",
    client_facing=False,
    node_type="function",
    execution_type="function",
    function_name="notify_handler",
    handler=notify_handler,
    max_visits=5,
)
