"""
ManusCoordinator - Coordination Layer for Manus Agent Architecture.

Responsibilities:
1. Memory/Knowledge: Access and maintain Memory across sessions
2. Task Decomposition: Break user tasks into sub-tasks with agent type
3. Agent Orchestration: Route sub-tasks to the correct Specialized Agent

This is the brain of the Manus Architecture. It receives the user message,
analyzes it, and decides which specialized agents need to handle which sub-tasks.
"""
import os
import sys
import json
import time
import asyncio
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, AsyncGenerator

from server.agent.models.memory import Memory


class SubTask:
    """Represents a sub-task to be handled by a specific agent."""

    AGENT_TYPES = ("web", "data", "code", "files")

    def __init__(
        self,
        task_id: str,
        description: str,
        agent_type: str,
        depends_on: Optional[List[str]] = None,
        priority: int = 1,
    ) -> None:
        self.task_id = task_id
        self.description = description
        self.agent_type = agent_type if agent_type in self.AGENT_TYPES else "code"
        self.depends_on: List[str] = depends_on or []
        self.priority = priority
        self.result: Optional[str] = None
        self.success: bool = False
        self.completed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "agent_type": self.agent_type,
            "depends_on": self.depends_on,
            "priority": self.priority,
            "result": self.result,
            "success": self.success,
            "completed": self.completed,
        }


class DecompositionResult:
    """Result of task decomposition by the coordinator."""

    def __init__(
        self,
        subtasks: List[SubTask],
        needs_single_agent: bool = False,
        single_agent_type: Optional[str] = None,
        summary: str = "",
    ) -> None:
        self.subtasks = subtasks
        self.needs_single_agent = needs_single_agent
        self.single_agent_type = single_agent_type
        self.summary = summary


def _get_cf_url() -> str:
    account_id = os.environ.get("CF_ACCOUNT_ID", "")
    gateway_name = os.environ.get("CF_GATEWAY_NAME", "")
    model = (
        os.environ.get("CF_AGENT_MODEL")
        or os.environ.get("CF_MODEL")
        or "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )
    return (
        "https://gateway.ai.cloudflare.com/v1/"
        "{}/{}/workers-ai/run/{}".format(account_id, gateway_name, model)
    )


_CF_API_KEY = os.environ.get("CF_API_KEY", "")


def _cf_text_call(messages: List[Dict[str, Any]], max_tokens: int = 1024) -> str:
    """Call Cloudflare API and return text response."""
    url = _get_cf_url()
    body: Dict[str, Any] = {"messages": messages, "max_tokens": max_tokens, "stream": False}
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(_CF_API_KEY),
            "User-Agent": "DzeckAI/2.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
        result = json.loads(raw)
        cf_result = result.get("result", result)
        if not isinstance(cf_result, dict):
            cf_result = result
        text = cf_result.get("response", "")
        if isinstance(text, dict):
            text = json.dumps(text)
        elif not isinstance(text, str):
            text = ""
        if not text:
            choices = result.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                text = msg.get("content", "") or ""
        return text
    except Exception as e:
        sys.stderr.write("[Coordinator] CF API call failed: {}\n".format(e))
        sys.stderr.flush()
        return ""


_COORDINATOR_SYSTEM_PROMPT = """
Kamu adalah koordinator untuk sistem AI multi-agent. Tugasmu adalah menganalisis permintaan user
dan mendekomposisi tugas menjadi sub-tugas yang akan dikerjakan oleh agent-agent spesialis.

Ada 4 jenis agent yang tersedia:
1. **web** - Browsing internet, ekstraksi data dari web, search online, screenshot halaman
2. **data** - Analisis data, akses API eksternal, transformasi dan pemrosesan data, statistik
3. **code** - Eksekusi Python, otomasi, pembuatan file/laporan, komputasi, instalasi package
4. **files** - Manajemen file, baca/tulis dokumen, pencarian konten file, organisasi file

Kamu HARUS merespons HANYA dengan JSON yang valid dalam format ini:
{
    "needs_single_agent": false,
    "single_agent_type": null,
    "summary": "Penjelasan singkat tentang bagaimana tugas akan diselesaikan",
    "subtasks": [
        {
            "task_id": "t1",
            "description": "Deskripsi sub-tugas yang spesifik dan dapat dieksekusi",
            "agent_type": "web|data|code|files",
            "depends_on": [],
            "priority": 1
        }
    ]
}

Aturan dekomposisi:
- Jika tugas bisa diselesaikan oleh SATU agent saja, set needs_single_agent=true dan single_agent_type ke tipe agent yang tepat
- Jika perlu beberapa agent, buat sub-tugas dengan depends_on yang benar (gunakan task_id dari sub-tugas yang harus selesai dulu)
- Maksimal 5 sub-tugas
- Setiap sub-tugas harus spesifik, jelas, dan dapat dieksekusi oleh agent tanpa konteks tambahan
- priority: 1=tinggi, 2=sedang, 3=rendah
- Untuk tugas sederhana: langsung set needs_single_agent=true
"""


class ManusCoordinator:
    """
    Coordination Layer implementing Manus Agent Architecture.

    Responsible for:
    1. Memory access and context management
    2. Task decomposition into typed sub-tasks
    3. Agent routing and orchestration
    """

    def __init__(self, memory: Optional[Memory] = None) -> None:
        self.memory = memory or Memory()
        self._decomposition_cache: Dict[str, DecompositionResult] = {}

    def _classify_simple_task(self, user_message: str) -> Optional[str]:
        """
        Quick heuristic to classify clearly single-agent tasks.
        Returns agent type string or None if needs full decomposition.
        """
        msg = user_message.lower().strip()

        web_signals = [
            "browsing", "browse", "search internet", "cari di internet", "cari online",
            "buka website", "buka url", "kunjungi", "visit", "screenshot website",
            "scrape", "crawl", "download dari web",
        ]
        data_signals = [
            "analisis data", "analyze data", "api", "fetch data", "ambil data",
            "statistik", "statistics", "csv", "json data", "database query",
            "akses api", "rest api", "parse",
        ]
        code_signals = [
            "buat script", "buat kode", "tulis program", "write code", "execute",
            "eksekusi python", "run python", "jalankan script", "install package",
            "buat laporan", "generate report", "buat file", "buat pdf",
        ]
        file_signals = [
            "baca file", "read file", "tulis file", "edit file", "cari file",
            "find file", "list file", "rename file", "copy file",
        ]

        web_count = sum(1 for s in web_signals if s in msg)
        data_count = sum(1 for s in data_signals if s in msg)
        code_count = sum(1 for s in code_signals if s in msg)
        file_count = sum(1 for s in file_signals if s in msg)

        counts = {"web": web_count, "data": data_count, "code": code_count, "files": file_count}
        max_type = max(counts, key=lambda k: counts[k])
        if counts[max_type] >= 2:
            return max_type

        return None

    def _get_memory_context(self) -> str:
        """Get relevant context from memory for the coordinator."""
        if self.memory.empty:
            return ""
        messages = self.memory.get_messages()
        recent = messages[-6:] if len(messages) > 6 else messages
        context_parts = []
        for msg in recent:
            role = msg.get("role", "")
            content = str(msg.get("content", ""))[:300]
            if role in ("user", "assistant") and content:
                context_parts.append("{}: {}".format(role.capitalize(), content))
        return "\n".join(context_parts) if context_parts else ""

    async def decompose_task(
        self,
        user_message: str,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> DecompositionResult:
        """
        Decompose user message into sub-tasks for specialized agents.
        Uses LLM to understand and break down complex requests.
        """
        quick_type = self._classify_simple_task(user_message)
        if quick_type:
            subtask = SubTask(
                task_id="t1",
                description=user_message,
                agent_type=quick_type,
                priority=1,
            )
            return DecompositionResult(
                subtasks=[subtask],
                needs_single_agent=True,
                single_agent_type=quick_type,
                summary="Tugas akan dikerjakan langsung oleh {} agent.".format(quick_type),
            )

        memory_context = self._get_memory_context()
        history_context = ""
        if chat_history:
            history_parts = []
            for h in chat_history[-4:]:
                role = h.get("role", "")
                content = h.get("content", "")
                if role in ("user", "assistant") and content:
                    history_parts.append("{}: {}".format(role.capitalize(), str(content)[:200]))
            if history_parts:
                history_context = "\nRiwayat chat:\n" + "\n".join(history_parts)

        messages = [
            {"role": "system", "content": _COORDINATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Permintaan user: \"{}\"\n{}{}\n\n"
                    "Analisis dan dekomposisi tugas ini. Balas HANYA dengan JSON yang valid."
                ).format(user_message, history_context, "\n\nKonteks sebelumnya:\n" + memory_context if memory_context else ""),
            },
        ]

        loop = asyncio.get_event_loop()
        try:
            response_text = await loop.run_in_executor(
                None,
                lambda: _cf_text_call(messages, max_tokens=800),
            )
        except Exception as e:
            sys.stderr.write("[Coordinator] Decomposition LLM call failed: {}\n".format(e))
            sys.stderr.flush()
            response_text = ""

        if response_text:
            text = response_text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
            try:
                parsed = json.loads(text)
                subtasks = []
                for s in parsed.get("subtasks", []):
                    subtasks.append(SubTask(
                        task_id=str(s.get("task_id", "t{}".format(len(subtasks) + 1))),
                        description=s.get("description", user_message),
                        agent_type=s.get("agent_type", "code"),
                        depends_on=[str(d) for d in s.get("depends_on", [])],
                        priority=int(s.get("priority", 1)),
                    ))
                if not subtasks:
                    subtasks = [SubTask("t1", user_message, "code")]
                return DecompositionResult(
                    subtasks=subtasks,
                    needs_single_agent=bool(parsed.get("needs_single_agent", len(subtasks) == 1)),
                    single_agent_type=parsed.get("single_agent_type"),
                    summary=parsed.get("summary", ""),
                )
            except (json.JSONDecodeError, Exception) as e:
                sys.stderr.write("[Coordinator] Failed to parse decomposition: {}\n".format(e))
                sys.stderr.flush()

        subtask = SubTask("t1", user_message, "code")
        return DecompositionResult(
            subtasks=[subtask],
            needs_single_agent=True,
            single_agent_type="code",
            summary="Fallback: executing as single code task.",
        )

    def update_memory(self, role: str, content: str) -> None:
        """Update the coordinator's memory with a new message."""
        self.memory.add_message({"role": role, "content": content})

    def get_agent_for_type(self, agent_type: str):
        """Get the appropriate specialized agent instance for a given type."""
        from server.agent.agents.web_agent import WebAgent
        from server.agent.agents.data_agent import DataAgent
        from server.agent.agents.code_agent import CodeAgent
        from server.agent.agents.files_agent import FilesAgent

        agent_map = {
            "web": WebAgent,
            "data": DataAgent,
            "code": CodeAgent,
            "files": FilesAgent,
        }
        agent_class = agent_map.get(agent_type, CodeAgent)
        return agent_class()
