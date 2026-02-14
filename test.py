from backend.agent_v3.tools import TOOL_REGISTRY

tool_description = {name: tool.description for name, tool in TOOL_REGISTRY.items()}

print(tool_description)
