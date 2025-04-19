from llama_index.core.workflow import Context
from llama_index.core.llms import ChatMessage

async def stringify_scratchpad(ctx: Context) -> str:
    """
    Convert the scratchpad to a string.
    
    Args:
        ctx (Context): The context object containing the scratchpad.

    Returns:
        str: The string representation of the scratchpad.
    """
    scratchpad: list[ChatMessage] = await ctx.get("scratchpad", default=[])
    
    scratchpad_str = ""

    for message in scratchpad:
        message_str = f"{message.role}: "
        if message.content is not None:
            message_str += message.content
        else:
            message_str += "No content, presumably tool usage."
        scratchpad_str += message_str + "\n\n"

    return scratchpad_str.strip()