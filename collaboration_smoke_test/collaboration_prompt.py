"""The only collaboration guidance appended to benchmark task prompts."""

COLLABORATION_NOTE = (
    "You are in a shared environment with other agents and you are all working "
    "together to complete the task. You can use the file system to send messages "
    "to each other."
)


def with_collaboration(prompt: str) -> str:
    """Preserve the original prompt exactly, then append the requested note."""
    return prompt + "\n\n" + COLLABORATION_NOTE
