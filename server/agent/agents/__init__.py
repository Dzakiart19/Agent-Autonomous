"""
Specialized agents for Manus Architecture.
"""
from server.agent.agents.web_agent import WebAgent
from server.agent.agents.data_agent import DataAgent
from server.agent.agents.code_agent import CodeAgent
from server.agent.agents.files_agent import FilesAgent

__all__ = ["WebAgent", "DataAgent", "CodeAgent", "FilesAgent"]
