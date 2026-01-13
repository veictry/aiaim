"""
TaskRunner - Main orchestrator for the supervisor/worker agent loop.

Coordinates the iterative process of:
1. Worker executes task
2. Supervisor checks completion
3. If not complete, worker continues with pending items
4. Repeat until complete or max iterations reached
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable

from aiaim.agent_cli import AgentCLI, AgentType
from aiaim.supervisor import SupervisorAgent, SupervisorResult
from aiaim.worker import WorkerAgent, WorkerResult


@dataclass
class IterationLog:
    """Log entry for a single iteration."""

    iteration: int
    timestamp: str
    worker_result: Optional[WorkerResult] = None
    supervisor_result: Optional[SupervisorResult] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "iteration": self.iteration,
            "timestamp": self.timestamp,
            "worker_result": self.worker_result.to_dict() if self.worker_result else None,
            "supervisor_result": (
                self.supervisor_result.to_dict() if self.supervisor_result else None
            ),
        }


@dataclass
class TaskRunResult:
    """Result from running a complete task."""

    success: bool
    completed: bool
    iterations: int
    total_time: float
    chat_id: Optional[str] = None
    logs: list[IterationLog] = field(default_factory=list)
    final_summary: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "completed": self.completed,
            "iterations": self.iterations,
            "total_time": self.total_time,
            "chat_id": self.chat_id,
            "logs": [log.to_dict() for log in self.logs],
            "final_summary": self.final_summary,
            "error": self.error,
        }


class TaskRunner:
    """
    Main task runner that orchestrates the supervisor/worker loop.

    The runner coordinates the iterative process of executing tasks,
    checking completion, and continuing until the task is complete
    or the maximum number of iterations is reached.
    """

    def __init__(
        self,
        agent_type: AgentType = AgentType.CURSOR_CLI,
        model: str = "claude-4.5-opus-high-thinking",
        max_iterations: int = 10,
        delay_between_iterations: float = 1.0,
        chat_id: Optional[str] = None,
        supervisor_agent: Optional[SupervisorAgent] = None,
        worker_agent: Optional[WorkerAgent] = None,
        on_iteration_complete: Optional[Callable[[IterationLog], None]] = None,
        on_status_update: Optional[Callable[[str], None]] = None,
        on_agent_output: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the task runner.

        Args:
            agent_type: The type of agent to use for both supervisor and worker.
            model: The model name to use.
            max_iterations: Maximum number of worker iterations before stopping.
            delay_between_iterations: Delay in seconds between iterations.
            chat_id: Optional chat ID to resume an existing conversation.
                     If provided, skip creating a new chat session.
            supervisor_agent: Optional pre-configured supervisor agent.
            worker_agent: Optional pre-configured worker agent.
            on_iteration_complete: Optional callback after each iteration.
            on_status_update: Optional callback for status updates.
            on_agent_output: Optional callback for real-time agent output streaming.
        """
        self.agent_type = agent_type
        self.model = model
        self.max_iterations = max_iterations
        self.delay_between_iterations = delay_between_iterations
        self.chat_id = chat_id

        # Store provided agents (may be None)
        self._provided_supervisor = supervisor_agent
        self._provided_worker = worker_agent

        # These will be set in run() with shared chat_id
        self.supervisor: Optional[SupervisorAgent] = None
        self.worker: Optional[WorkerAgent] = None

        self.on_iteration_complete = on_iteration_complete
        self.on_status_update = on_status_update
        self.on_agent_output = on_agent_output

        # Worker agent CLI instance (with chat_id)
        self._worker_agent_cli: Optional[AgentCLI] = None

    def _log_status(self, message: str) -> None:
        """Log a status update."""
        if self.on_status_update:
            self.on_status_update(message)

    def _initialize_agents(self) -> str:
        """
        Initialize agent CLIs for worker and supervisor.

        Worker uses chat_id if provided (--resume mode), supervisor is independent.

        Returns:
            The chat_id for the worker session.
        """
        # Create worker agent CLI with chat_id if provided
        worker_agent_cli = AgentCLI.create(
            agent_type=self.agent_type,
            model=self.model,
            chat_id=self.chat_id,
        )

        # If chat_id was provided, use it directly; otherwise create new chat for worker
        if self.chat_id:
            chat_id = self.chat_id
        else:
            # Create chat session and get chat_id
            chat_id = worker_agent_cli.create_chat()

        # Supervisor uses independent agent CLI (no chat_id, no shared session)
        supervisor_agent_cli = AgentCLI.create(
            agent_type=self.agent_type,
            model=self.model,
        )

        # Create supervisor with independent agent CLI
        self.supervisor = self._provided_supervisor or SupervisorAgent(
            agent_cli=supervisor_agent_cli,
            on_output=self.on_agent_output,
        )
        # If provided supervisor, update its agent_cli
        if self._provided_supervisor:
            self._provided_supervisor.agent_cli = supervisor_agent_cli

        # Create worker with chat_id-enabled agent CLI
        self.worker = self._provided_worker or WorkerAgent(
            agent_cli=worker_agent_cli,
            on_output=self.on_agent_output,
        )
        # If provided worker, update its agent_cli
        if self._provided_worker:
            self._provided_worker.agent_cli = worker_agent_cli

        # Store worker's agent CLI for reference
        self._worker_agent_cli = worker_agent_cli

        return chat_id

    def run(self, task: str) -> TaskRunResult:
        """
        Run the task to completion.

        Args:
            task: The task description to execute.

        Returns:
            TaskRunResult with the outcome of the task run.
        """
        start_time = time.time()
        logs: list[IterationLog] = []
        current_pending_items: list[str] = []
        chat_id: Optional[str] = None

        self._log_status(f"开始执行任务: {task[:100]}...")

        # Initialize agents with shared chat session
        if self.chat_id:
            self._log_status(f"恢复会话: {self.chat_id}")
        else:
            self._log_status("创建会话...")
        try:
            chat_id = self._initialize_agents()
            if not self.chat_id:
                self._log_status(f"会话创建成功, chat_id: {chat_id}")
        except Exception as e:
            self._log_status(f"创建会话失败: {e}")
            return TaskRunResult(
                success=False,
                completed=False,
                iterations=0,
                total_time=time.time() - start_time,
                chat_id=None,
                logs=[],
                final_summary="",
                error=f"Failed to create chat session: {e}",
            )

        for iteration in range(1, self.max_iterations + 1):
            timestamp = datetime.now().isoformat()
            self._log_status(f"\n=== 第 {iteration} 轮迭代 ===")

            # Create iteration log
            log = IterationLog(iteration=iteration, timestamp=timestamp)

            try:
                # Step 1: Worker executes task
                self._log_status("Worker正在执行任务...")

                if iteration == 1:
                    # First iteration: execute the original task
                    worker_result = self.worker.execute_task(task, on_output=self.on_agent_output)
                else:
                    # Subsequent iterations: include pending items
                    worker_result = self.worker.execute_task(
                        task, current_pending_items, on_output=self.on_agent_output
                    )

                log.worker_result = worker_result

                if not worker_result.success:
                    self._log_status(f"Worker执行失败: {worker_result.error}")
                    # Continue anyway to let supervisor check the state
                else:
                    self._log_status("Worker执行完成")

                # Step 2: Supervisor checks completion
                self._log_status("Supervisor正在检查任务完成状态...")

                # Build context for supervisor
                context = ""
                if current_pending_items:
                    context = "上一轮未完成项目:\n" + "\n".join(
                        f"- {item}" for item in current_pending_items
                    )

                supervisor_result = self.supervisor.check_completion(
                    task, context, on_output=self.on_agent_output
                )
                log.supervisor_result = supervisor_result

                self._log_status(f"检查结果: {supervisor_result.summary}")

                # Step 3: Check if complete
                if supervisor_result.is_complete:
                    self._log_status("✅ 任务已完成!")
                    logs.append(log)

                    if self.on_iteration_complete:
                        self.on_iteration_complete(log)

                    return TaskRunResult(
                        success=True,
                        completed=True,
                        iterations=iteration,
                        total_time=time.time() - start_time,
                        chat_id=chat_id,
                        logs=logs,
                        final_summary=supervisor_result.summary,
                    )

                # Task not complete, update pending items for next iteration
                current_pending_items = supervisor_result.pending_items
                self._log_status(f"待完成项目: {len(current_pending_items)} 项")

                for i, item in enumerate(current_pending_items, 1):
                    self._log_status(f"  {i}. {item}")

            except Exception as e:
                self._log_status(f"迭代 {iteration} 发生错误: {e}")
                log.worker_result = WorkerResult(
                    success=False,
                    output="",
                    error=str(e),
                )

            logs.append(log)

            if self.on_iteration_complete:
                self.on_iteration_complete(log)

            # Delay before next iteration
            if iteration < self.max_iterations:
                self._log_status(f"等待 {self.delay_between_iterations} 秒后继续...")
                time.sleep(self.delay_between_iterations)

        # Max iterations reached
        self._log_status(f"⚠️ 达到最大迭代次数 ({self.max_iterations})，任务未完成")

        return TaskRunResult(
            success=False,
            completed=False,
            iterations=self.max_iterations,
            total_time=time.time() - start_time,
            chat_id=chat_id,
            logs=logs,
            final_summary=f"达到最大迭代次数({self.max_iterations})，任务未完成",
            error="Max iterations reached without task completion",
        )

    def run_check_only(self, task: str) -> SupervisorResult:
        """
        Only run the supervisor to check task status without executing.

        Args:
            task: The task description to check.

        Returns:
            SupervisorResult with the current status.
        """
        # Initialize agents if not already done
        if self.supervisor is None:
            self._initialize_agents()

        return self.supervisor.check_completion(task, on_output=self.on_agent_output)

    def run_single_iteration(
        self,
        task: str,
        pending_items: Optional[list[str]] = None,
    ) -> tuple[WorkerResult, SupervisorResult]:
        """
        Run a single iteration of worker + supervisor.

        Args:
            task: The task description.
            pending_items: Optional list of pending items to work on.

        Returns:
            Tuple of (WorkerResult, SupervisorResult).
        """
        # Initialize agents if not already done
        if self.worker is None or self.supervisor is None:
            self._initialize_agents()

        # Worker executes
        if pending_items:
            worker_result = self.worker.execute_task(
                task, pending_items, on_output=self.on_agent_output
            )
        else:
            worker_result = self.worker.execute_task(task, on_output=self.on_agent_output)

        # Supervisor checks
        context = ""
        if pending_items:
            context = "上一轮未完成项目:\n" + "\n".join(f"- {item}" for item in pending_items)

        supervisor_result = self.supervisor.check_completion(
            task, context, on_output=self.on_agent_output
        )

        return worker_result, supervisor_result
