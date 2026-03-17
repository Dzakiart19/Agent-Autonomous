"""
Code Agent - Specialized agent for Python execution and automation in E2B Sandbox.
Part of the Manus Architecture for Dzeck AI.
"""
from typing import Dict, Any, List

from server.agent.agents.base_agent import BaseSpecializedAgent
from server.agent.prompts.code_agent import CODE_AGENT_SYSTEM_PROMPT


class CodeAgent(BaseSpecializedAgent):
    """
    Specialized agent for writing and executing Python code in E2B Sandbox.
    Has access to shell and file tools for code execution.
    """

    agent_type: str = "code"
    system_prompt: str = CODE_AGENT_SYSTEM_PROMPT

    _CODE_TOOLS = [
        "shell_exec", "shell_view", "shell_wait", "shell_write_to_process", "shell_kill_process",
        "file_read", "file_write", "file_str_replace",
        "file_find_by_name", "file_find_in_content",
        "message_notify_user", "idle",
    ]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        from server.agent.tools.registry import get_all_tool_schemas
        all_schemas = get_all_tool_schemas()
        allowed = set(self._CODE_TOOLS)
        filtered = [
            s for s in all_schemas
            if (s.get("function", s).get("name", "") in allowed)
        ]
        idle_schema = {
            "name": "idle",
            "description": "Tandai bahwa tugas Code Agent telah selesai.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "Apakah kode berhasil dieksekusi"},
                    "result": {"type": "string", "description": "Ringkasan hasil eksekusi kode"},
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
