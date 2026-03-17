"""
Files Agent - Specialized agent for file management and processing.
Part of the Manus Architecture for Dzeck AI.
"""
from typing import Dict, Any, List

from server.agent.agents.base_agent import BaseSpecializedAgent
from server.agent.prompts.files_agent import FILES_AGENT_SYSTEM_PROMPT


class FilesAgent(BaseSpecializedAgent):
    """
    Specialized agent for file management and document processing.
    Has access to file tools for reading, writing, and searching files.
    """

    agent_type: str = "files"
    system_prompt: str = FILES_AGENT_SYSTEM_PROMPT

    _FILE_TOOLS = [
        "file_read", "file_write", "file_str_replace",
        "file_find_by_name", "file_find_in_content",
        "message_notify_user", "idle",
    ]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        from server.agent.tools.registry import get_all_tool_schemas
        all_schemas = get_all_tool_schemas()
        allowed = set(self._FILE_TOOLS)
        filtered = [
            s for s in all_schemas
            if (s.get("function", s).get("name", "") in allowed)
        ]
        idle_schema = {
            "name": "idle",
            "description": "Tandai bahwa tugas Files Agent telah selesai.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "Apakah operasi file berhasil"},
                    "result": {"type": "string", "description": "Ringkasan operasi file yang dilakukan"},
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
