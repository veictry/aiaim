"""
WorkerAgent - Agent responsible for executing tasks.

The worker agent receives task instructions and executes them to make progress
toward task completion.
"""

from dataclasses import dataclass
from typing import Optional, Callable

from aiaim.agent_cli import AgentCLI, AgentType, AgentResponse


@dataclass
class WorkerResult:
    """Result from worker agent execution."""

    success: bool
    output: str
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }


class WorkerAgent:
    """
    Worker agent that executes tasks.

    The worker receives instructions (either the original task or pending items)
    and executes them to make progress toward completion.
    """

    # Default prompt template for task execution
    DEFAULT_EXECUTE_PROMPT = """请完成以下任务。

## 任务描述
{task}

{pending_section}

请开始执行任务，确保完成所有要求的内容。
"""

    # Template for pending items section
    PENDING_SECTION_TEMPLATE = """## 待完成项目清单
以下是上一轮检查后发现仍需完成的项目，请优先处理：

{pending_items}

请确保完成上述所有待完成项目。
"""

    def __init__(
        self,
        agent_cli: Optional[AgentCLI] = None,
        agent_type: AgentType = AgentType.CURSOR_CLI,
        model: str = "claude-4.5-opus-high-thinking",
        execute_prompt_template: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the worker agent.

        Args:
            agent_cli: Optional pre-configured AgentCLI instance.
            agent_type: The type of agent to use if agent_cli is not provided.
            model: The model name to use.
            execute_prompt_template: Optional custom prompt template for execution.
            on_output: Optional callback for real-time output streaming.
        """
        self.agent_cli = agent_cli or AgentCLI.create(agent_type=agent_type, model=model)
        self.execute_prompt_template = execute_prompt_template or self.DEFAULT_EXECUTE_PROMPT
        self.on_output = on_output

    def execute_task(
        self,
        task: str,
        pending_items: Optional[list[str]] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> WorkerResult:
        """
        Execute the task.

        Args:
            task: The original task description.
            pending_items: Optional list of pending items from supervisor check.
            on_output: Optional callback for real-time output (overrides instance callback).

        Returns:
            WorkerResult with execution outcome.
        """
        # Build pending section if there are pending items
        if pending_items:
            pending_list = "\n".join(f"- {item}" for item in pending_items)
            pending_section = self.PENDING_SECTION_TEMPLATE.format(pending_items=pending_list)
        else:
            pending_section = ""

        # Build the full prompt
        prompt = self.execute_prompt_template.format(
            task=task,
            pending_section=pending_section,
        )

        # Use provided callback or instance callback
        output_callback = on_output or self.on_output

        # Execute via agent CLI
        response = self.agent_cli.execute(prompt, on_output=output_callback)

        return self._process_response(response)

    def execute_with_context(
        self,
        task: str,
        context: str,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> WorkerResult:
        """
        Execute the task with additional context.

        Args:
            task: The original task description.
            context: Additional context (e.g., pending document from supervisor).
            on_output: Optional callback for real-time output (overrides instance callback).

        Returns:
            WorkerResult with execution outcome.
        """
        prompt = f"""请完成以下任务。

## 任务描述
{task}

## 上下文信息
{context}

请根据上述信息继续执行任务，确保完成所有要求的内容。
"""
        # Use provided callback or instance callback
        output_callback = on_output or self.on_output

        response = self.agent_cli.execute(prompt, on_output=output_callback)
        return self._process_response(response)

    def _process_response(self, response: AgentResponse) -> WorkerResult:
        """
        Process the agent response into a WorkerResult.

        Args:
            response: The raw agent response.

        Returns:
            Processed WorkerResult.
        """
        return WorkerResult(
            success=response.success,
            output=response.output,
            error=response.error,
        )
