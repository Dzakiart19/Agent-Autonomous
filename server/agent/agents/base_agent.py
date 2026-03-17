"""
Base class for all Specialized Agents in Manus Architecture.
"""
import os
import sys
import json
import time
import asyncio
import urllib.request
import urllib.error
import concurrent.futures
from typing import AsyncGenerator, Dict, Any, List, Optional


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


CF_API_KEY = os.environ.get("CF_API_KEY", "")


def _cf_api_call(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    url = _get_cf_url()
    body: Dict[str, Any] = {"messages": messages, "max_tokens": max_tokens, "stream": False}
    if tools:
        body["tools"] = tools
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer {}".format(CF_API_KEY),
            "User-Agent": "DzeckAI/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _cf_call_with_retry(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    max_retries: int = 3,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            return _cf_api_call(messages, tools=tools, max_tokens=max_tokens)
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** attempt)
            else:
                raise
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM call failed after {} retries".format(max_retries))


def _extract_response(api_result: Dict[str, Any]):
    cf_result = api_result.get("result", api_result)
    if not isinstance(cf_result, dict):
        cf_result = api_result
    text = cf_result.get("response", "")
    if isinstance(text, dict):
        text = json.dumps(text)
    elif not isinstance(text, str):
        text = str(text) if text is not None else ""
    tool_calls = cf_result.get("tool_calls")
    if not text and not tool_calls:
        choices = api_result.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            text = msg.get("content", "") or ""
            oa_calls = msg.get("tool_calls")
            if oa_calls:
                tool_calls = []
                for tc in oa_calls:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    tool_calls.append({"name": fn.get("name", ""), "arguments": args})
    return text or "", tool_calls


class BaseSpecializedAgent:
    """
    Base class for specialized agents in the Manus architecture.
    Each agent has a role, system prompt, tool set, and can execute tasks.
    """

    agent_type: str = "base"
    system_prompt: str = ""

    def __init__(self) -> None:
        self._loop = None

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("Subclasses must implement get_tool_schemas()")

    def execute_tool(self, tool_name: str, tool_args: Dict[str, Any]):
        from server.agent.tools.registry import execute_tool as registry_execute_tool
        return registry_execute_tool(tool_name, tool_args)

    async def execute_async(
        self,
        task: str,
        context: Optional[str] = None,
        shared_data: Optional[Dict[str, Any]] = None,
        max_iterations: int = 15,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute a task asynchronously, yielding events as they happen.

        Yields dicts with type:
        - "agent_start": Agent begins working on task
        - "tool_call": Agent calls a tool
        - "tool_result": Tool result returned
        - "agent_done": Agent has completed with final result
        - "agent_error": Agent encountered a fatal error
        """
        yield {"type": "agent_start", "agent": self.agent_type, "task": task}

        context_section = ""
        if context:
            context_section = "\n\nKonteks dari agent sebelumnya:\n{}".format(context)
        if shared_data:
            shared_summary = json.dumps(shared_data, ensure_ascii=False, default=str)[:2000]
            context_section += "\n\nData bersama:\n{}".format(shared_summary)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": (
                    "Tugas: {}\n{}\n\n"
                    "Jalankan tugas ini menggunakan tools yang tersedia. "
                    "Setelah selesai, panggil idle dengan success=true dan ringkasan hasil."
                ).format(task, context_section),
            },
        ]

        tool_schemas = self.get_tool_schemas()
        loop = asyncio.get_event_loop()
        result_summary = ""
        success = False

        for iteration in range(max_iterations):
            try:
                _msgs = list(messages)
                _tools = list(tool_schemas)

                api_result = await loop.run_in_executor(
                    None,
                    lambda: _cf_call_with_retry(_msgs, tools=_tools),
                )
                text, tool_calls = _extract_response(api_result)

                if tool_calls:
                    for tc in tool_calls:
                        fn_name = tc.get("name", "")
                        fn_args = tc.get("arguments", {})
                        if isinstance(fn_args, str):
                            try:
                                fn_args = json.loads(fn_args)
                            except Exception:
                                fn_args = {}

                        if fn_name in ("idle", "task_complete"):
                            success = fn_args.get("success", True)
                            if isinstance(success, str):
                                success = success.lower() not in ("false", "0", "no")
                            result_summary = fn_args.get("result", "Selesai")
                            yield {
                                "type": "agent_done",
                                "agent": self.agent_type,
                                "success": success,
                                "result": result_summary,
                            }
                            return

                        yield {
                            "type": "tool_call",
                            "agent": self.agent_type,
                            "tool": fn_name,
                            "args": fn_args,
                        }

                        tool_result = await loop.run_in_executor(
                            None,
                            lambda: self.execute_tool(fn_name, fn_args),
                        )

                        result_msg = str(tool_result.message)[:3000] if tool_result.message else ""
                        yield {
                            "type": "tool_result",
                            "agent": self.agent_type,
                            "tool": fn_name,
                            "success": tool_result.success,
                            "result": result_msg,
                        }

                        messages.append({
                            "role": "user",
                            "content": "Result of {}: {}\n\nLanjutkan. Panggil idle saat selesai.".format(
                                fn_name, result_msg
                            ),
                        })

                elif text:
                    try:
                        parsed = json.loads(text.strip())
                        if parsed.get("done") or parsed.get("success") is not None:
                            success = parsed.get("success", True)
                            result_summary = parsed.get("result", text[:500])
                            yield {
                                "type": "agent_done",
                                "agent": self.agent_type,
                                "success": success,
                                "result": result_summary,
                            }
                            return
                    except (json.JSONDecodeError, AttributeError):
                        pass
                    messages.append({"role": "assistant", "content": text})
                    messages.append({
                        "role": "user",
                        "content": "Lanjutkan menggunakan tools. Panggil idle saat tugas selesai.",
                    })
                else:
                    messages.append({
                        "role": "user",
                        "content": "Tidak ada response. Gunakan tool untuk melanjutkan atau panggil idle.",
                    })

            except Exception as e:
                yield {
                    "type": "agent_error",
                    "agent": self.agent_type,
                    "error": str(e),
                }
                return

        yield {
            "type": "agent_done",
            "agent": self.agent_type,
            "success": False,
            "result": "Max iterations reached without completion",
        }
