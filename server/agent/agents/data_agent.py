"""
Data Agent - Specialized agent for data analysis and API access.
Part of the Manus Architecture for Dzeck AI.
"""
from typing import Dict, Any, List

from server.agent.agents.base_agent import BaseSpecializedAgent
from server.agent.prompts.data_agent import DATA_AGENT_SYSTEM_PROMPT


class DataAgent(BaseSpecializedAgent):
    """
    Specialized agent for data analysis, processing, and external API access.
    Has access to shell, search, and file tools.
    """

    agent_type: str = "data"
    system_prompt: str = DATA_AGENT_SYSTEM_PROMPT

    _DATA_TOOLS = [
        "shell_exec", "shell_view", "shell_wait", "shell_write_to_process", "shell_kill_process",
        "info_search_web", "web_search", "web_browse",
        "file_read", "file_write", "file_str_replace",
        "message_notify_user", "idle",
    ]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        from server.agent.tools.registry import get_all_tool_schemas
        all_schemas = get_all_tool_schemas()
        allowed = set(self._DATA_TOOLS)
        filtered = [
            s for s in all_schemas
            if (s.get("function", s).get("name", "") in allowed)
        ]
        idle_schema = {
            "name": "idle",
            "description": "Tandai bahwa tugas Data Agent telah selesai.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "Apakah tugas berhasil"},
                    "result": {"type": "string", "description": "Ringkasan hasil analisis data"},
                },
                "required": ["success", "result"],
            },
        }
        schemas = [idle_schema]
        for s in filtered:
            fn = s.get("function", s)
            if fn.get("name", "") != "idle":
                schemas.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {"type": "object"}),
                })
        return schemas
