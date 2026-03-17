"""
Web Agent - Specialized agent for browsing and web data extraction.
Part of the Manus Architecture for Dzeck AI.
"""
from typing import Dict, Any, List

from server.agent.agents.base_agent import BaseSpecializedAgent
from server.agent.prompts.web_agent import WEB_AGENT_SYSTEM_PROMPT


class WebAgent(BaseSpecializedAgent):
    """
    Specialized agent for web browsing and online data extraction.
    Has access to browser tools and search tools.
    """

    agent_type: str = "web"
    system_prompt: str = WEB_AGENT_SYSTEM_PROMPT

    _WEB_TOOLS = [
        "browser_navigate", "browser_view", "browser_click", "browser_input",
        "browser_move_mouse", "browser_press_key", "browser_select_option",
        "browser_scroll_up", "browser_scroll_down", "browser_console_exec",
        "browser_console_view", "browser_save_image",
        "info_search_web", "web_search", "web_browse",
        "message_notify_user", "idle",
    ]

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        from server.agent.tools.registry import get_all_tool_schemas
        all_schemas = get_all_tool_schemas()
        allowed = set(self._WEB_TOOLS)
        filtered = [
            s for s in all_schemas
            if (s.get("function", s).get("name", "") in allowed)
        ]
        idle_schema = {
            "name": "idle",
            "description": "Tandai bahwa tugas Web Agent telah selesai.",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "Apakah tugas berhasil"},
                    "result": {"type": "string", "description": "Ringkasan hasil"},
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
