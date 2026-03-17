"""
ExecutionCombiner - Execution & Combination Layer for Manus Agent Architecture.

Responsibilities:
1. Execute sub-tasks via specialized agents (sequentially or in parallel based on dependencies)
2. Facilitate data sharing between agents (output of A -> input of B)
3. Combine all results into a coherent final output

The combiner accepts an optional external subtask_executor callback so callers
can plug in their own execution logic (e.g. routing through agent_flow's
_run_tool_streaming for full SSE parity). When no executor is given, falls back
to the built-in BaseSpecializedAgent.execute_async() path.
"""
import os
import sys
import json
import asyncio
from typing import Callable, Dict, Any, List, Optional, AsyncGenerator, Set

from server.agent.coordinator import SubTask, DecompositionResult, ManusCoordinator


class ExecutionResult:
    """Result from a single agent's execution of a sub-task."""

    def __init__(
        self,
        task_id: str,
        agent_type: str,
        success: bool,
        result: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.task_id = task_id
        self.agent_type = agent_type
        self.success = success
        self.result = result
        self.data: Dict[str, Any] = data or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_type": self.agent_type,
            "success": self.success,
            "result": self.result,
            "data": self.data,
        }


class CombinedResult:
    """Combined result from all agent executions."""

    def __init__(self, results: List[ExecutionResult]) -> None:
        self.results = results
        self.all_success = all(r.success for r in results)
        self.failed_tasks = [r for r in results if not r.success]

    def get_context_for_agent(self, current_task_id: str, depends_on: List[str]) -> str:
        """Build context string from results of dependency tasks."""
        context_parts = []
        for dep_id in depends_on:
            dep_result = next((r for r in self.results if r.task_id == dep_id), None)
            if dep_result:
                status = "Berhasil" if dep_result.success else "Gagal"
                context_parts.append(
                    "Hasil dari {} agent (task {}): {}\nStatus: {}".format(
                        dep_result.agent_type, dep_id, dep_result.result[:1000], status
                    )
                )
        return "\n\n".join(context_parts) if context_parts else ""

    def get_shared_data(self, depends_on: List[str]) -> Dict[str, Any]:
        """Get shared data dict from dependency task results."""
        shared: Dict[str, Any] = {}
        for dep_id in depends_on:
            dep_result = next((r for r in self.results if r.task_id == dep_id), None)
            if dep_result and dep_result.data:
                shared.update(dep_result.data)
        return shared

    def get_final_summary(self) -> str:
        """Build a final summary from all results."""
        parts = []
        for r in self.results:
            status = "✓" if r.success else "✗"
            parts.append("{} [{}] {}: {}".format(
                status, r.agent_type, r.task_id, r.result[:500]
            ))
        return "\n".join(parts)


class ExecutionCombiner:
    """
    Execution & Combination Layer for the Manus Agent Architecture.

    Manages execution of sub-tasks via specialized agents and combines results.
    Supports dependency-aware ordering and data sharing between agents.

    Args:
        coordinator: ManusCoordinator instance for agent routing.
        subtask_executor: Optional async callable with signature
            (subtask, context, shared_data) -> AsyncGenerator[dict, None].
            When provided, this callback is used for every subtask instead of
            the built-in BaseSpecializedAgent.execute_async() path. This allows
            callers to inject full SSE streaming infrastructure (e.g. routing
            through DzeckAgent._run_tool_streaming).
            The generator MUST yield a __manus_done__ sentinel as its last event
            with keys: success (bool), result (str), data (dict, optional).
    """

    def __init__(
        self,
        coordinator: Optional[ManusCoordinator] = None,
        subtask_executor: Optional[Callable] = None,
    ) -> None:
        self.coordinator = coordinator or ManusCoordinator()
        self._results: List[ExecutionResult] = []
        self._subtask_executor = subtask_executor

    def _build_execution_order(self, subtasks: List[SubTask]) -> List[List[SubTask]]:
        """
        Build an ordered list of batches of sub-tasks based on dependencies.
        Tasks with no dependencies execute first (or in parallel).
        Returns list of batches where each batch can be executed in parallel.
        """
        completed: Set[str] = set()
        batches: List[List[SubTask]] = []
        remaining = list(subtasks)

        max_passes = len(subtasks) + 1
        for _ in range(max_passes):
            if not remaining:
                break
            ready = [
                t for t in remaining
                if all(dep in completed for dep in t.depends_on)
            ]
            if not ready:
                ready = remaining[:]

            batches.append(sorted(ready, key=lambda t: t.priority))
            for t in ready:
                remaining.remove(t)
                completed.add(t.task_id)

        return batches

    async def _execute_single(
        self,
        subtask: SubTask,
        combined: "CombinedResult",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute one subtask, building its context/shared_data from completed results.
        Routes to the external executor (if provided) or the built-in agent path.

        Yields events from the agent and emits a __manus_done__ sentinel
        (from the external executor) or builds one from agent_done events
        (built-in path). After the generator finishes, stores an ExecutionResult.
        """
        context = combined.get_context_for_agent(subtask.task_id, subtask.depends_on)
        shared_data = combined.get_shared_data(subtask.depends_on)

        step_success = False
        step_result = "Agent did not complete"
        step_data: Dict[str, Any] = {}

        if self._subtask_executor is not None:
            async for event in self._subtask_executor(subtask, context, shared_data):
                if event.get("type") == "__manus_done__":
                    step_success = bool(event.get("success", False))
                    step_result = str(event.get("result", ""))
                    step_data = event.get("data") or {
                        "collected_outputs": event.get("collected_results", []),
                        "step_result": step_result,
                        "agent_type": subtask.agent_type,
                    }
                else:
                    yield event
        else:
            agent = self.coordinator.get_agent_for_type(subtask.agent_type)
            async for event in agent.execute_async(
                task=subtask.description,
                context=context,
                shared_data=shared_data if shared_data else None,
            ):
                if event.get("type") == "agent_done":
                    step_success = bool(event.get("success", False))
                    step_result = str(event.get("result", ""))
                    step_data = {
                        "step_result": step_result,
                        "agent_type": subtask.agent_type,
                    }
                elif event.get("type") == "agent_error":
                    step_result = "Agent error: {}".format(event.get("error", "Unknown"))
                    step_success = False
                else:
                    yield event

        exec_result = ExecutionResult(
            task_id=subtask.task_id,
            agent_type=subtask.agent_type,
            success=step_success,
            result=step_result,
            data=step_data,
        )
        subtask.result = step_result
        subtask.success = step_success
        subtask.completed = True
        combined.results.append(exec_result)
        self._results.append(exec_result)

    async def run_all(
        self,
        decomposition: DecompositionResult,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute all sub-tasks in dependency order, sharing data between agents.
        Yields events from all agents as they execute.

        Uses the injected subtask_executor (if any) for each subtask, enabling
        full SSE parity when called from agent_flow._run_with_manus_async.
        """
        combined = CombinedResult([])
        batches = self._build_execution_order(decomposition.subtasks)

        yield {
            "type": "execution_start",
            "total_tasks": len(decomposition.subtasks),
            "batches": len(batches),
        }

        for batch_idx, batch in enumerate(batches):
            yield {
                "type": "batch_start",
                "batch": batch_idx + 1,
                "tasks": [t.task_id for t in batch],
            }

            if len(batch) == 1:
                async for event in self._execute_single(batch[0], combined):
                    yield event
            else:
                queues: List[asyncio.Queue] = [asyncio.Queue() for _ in batch]

                async def _run_to_queue(subtask, q):
                    async for event in self._execute_single(subtask, combined):
                        await q.put(event)
                    await q.put(None)

                agent_tasks = [
                    asyncio.create_task(_run_to_queue(st, q))
                    for st, q in zip(batch, queues)
                ]

                active_queues = list(queues)
                while active_queues:
                    done_queues = []
                    for q in active_queues:
                        try:
                            event = q.get_nowait()
                            if event is None:
                                done_queues.append(q)
                            else:
                                yield event
                        except asyncio.QueueEmpty:
                            pass
                    for q in done_queues:
                        active_queues.remove(q)
                    if active_queues:
                        await asyncio.sleep(0.05)

                await asyncio.gather(*agent_tasks, return_exceptions=True)

            yield {"type": "batch_done", "batch": batch_idx + 1}

        yield {
            "type": "execution_done",
            "all_success": combined.all_success,
            "summary": combined.get_final_summary(),
            "results": [r.to_dict() for r in combined.results],
        }

    def get_combined_result(self) -> CombinedResult:
        """Get the combined result after execution."""
        return CombinedResult(self._results)

    def get_result_summary(self) -> str:
        """Get a summary of all execution results."""
        if not self._results:
            return "No results."
        return CombinedResult(self._results).get_final_summary()
