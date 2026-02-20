from framework.graph import NodeSpec

observe_node = NodeSpec(
    id="observe",
    name="Observe",
    description="Increment the iteration counter and check halt condition.",
    node_type="event_loop",
    client_facing=False,
    input_keys=["iteration"],
    output_keys=["iteration", "halt"],
    tools=["check_signal"],
    system_prompt="""\
You are executing ONE step of a monitoring loop. Follow these steps in order:
1. Call check_signal EXACTLY ONCE with the current 'iteration' value from context (use 0 if missing).
2. Call set_output with key "iteration" and the returned new_iteration as a string.
3. Call set_output with key "halt" and the returned halt as "true" or "false".
Do NOT call check_signal more than once. Stop immediately after step 3.
""",
)