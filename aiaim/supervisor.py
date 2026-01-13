"""
SupervisorAgent - Agent responsible for checking task completion status.

The supervisor agent polls to check if all tasks are completed and provides
feedback on what remains to be done.
"""

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

from aiaim.agent_cli import AgentCLI, AgentType, AgentResponse


class TaskStatus(str, Enum):
    """Status of task completion."""

    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"


@dataclass
class SupervisorResult:
    """Result from supervisor agent evaluation."""

    is_complete: bool
    status: TaskStatus
    pending_items: list[str]
    summary: str
    raw_response: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "is_complete": self.is_complete,
            "status": self.status.value,
            "pending_items": self.pending_items,
            "summary": self.summary,
        }


class SupervisorAgent:
    """
    Supervisor agent that checks task completion status.

    The supervisor polls the current state and determines if the task is complete,
    or provides a list of pending items that still need to be done.
    """

    # Default prompt template for checking task status
    DEFAULT_CHECK_PROMPT = """请检查以下任务是否已经全部完成。

## 原始任务
{task}

## 当前上下文
{context}

请按照以下JSON格式回复（只返回JSON，不要有其他内容）：
{{
    "is_complete": true/false,
    "status": "completed" | "in_progress" | "pending",
    "pending_items": ["未完成项1", "未完成项2", ...],
    "summary": "当前状态的简要总结"
}}

注意：
- 如果任务已全部完成，设置 is_complete 为 true，pending_items 为空数组
- 如果任务未完成，设置 is_complete 为 false，并列出所有未完成的具体项目
- summary 应简明扼要地描述当前进度
"""

    def __init__(
        self,
        agent_cli: Optional[AgentCLI] = None,
        agent_type: AgentType = AgentType.CURSOR_CLI,
        model: str = "claude-4.5-opus-high-thinking",
        check_prompt_template: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the supervisor agent.

        Args:
            agent_cli: Optional pre-configured AgentCLI instance.
            agent_type: The type of agent to use if agent_cli is not provided.
            model: The model name to use.
            check_prompt_template: Optional custom prompt template for status checks.
            on_output: Optional callback for real-time output streaming.
        """
        self.agent_cli = agent_cli or AgentCLI.create(agent_type=agent_type, model=model)
        self.check_prompt_template = check_prompt_template or self.DEFAULT_CHECK_PROMPT
        self.on_output = on_output

    def check_completion(
        self,
        task: str,
        context: str = "",
        on_output: Optional[Callable[[str], None]] = None,
    ) -> SupervisorResult:
        """
        Check if the task is complete.

        Args:
            task: The original task description.
            context: Additional context about current state (e.g., pending items from previous check).
            on_output: Optional callback for real-time output (overrides instance callback).

        Returns:
            SupervisorResult indicating completion status and pending items.
        """
        # Build the prompt
        prompt = self.check_prompt_template.format(
            task=task,
            context=context if context else "这是首次检查，暂无历史上下文。",
        )

        # Use provided callback or instance callback
        output_callback = on_output or self.on_output

        # Execute via agent CLI
        response = self.agent_cli.execute(prompt, on_output=output_callback)

        # Parse the response
        return self._parse_response(response)

    def _parse_response(self, response: AgentResponse) -> SupervisorResult:
        """
        Parse the agent response into a SupervisorResult.

        Args:
            response: The raw agent response.

        Returns:
            Parsed SupervisorResult.
        """
        if not response.success:
            return SupervisorResult(
                is_complete=False,
                status=TaskStatus.PENDING,
                pending_items=[f"Agent执行失败: {response.error}"],
                summary="无法检查任务状态，agent执行出错",
                raw_response=response.output,
            )

        try:
            # Try to extract JSON from the response
            output = response.output

            # Try to find JSON in the response (might be wrapped in markdown code blocks)
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", output)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r"\{[\s\S]*\}", output)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = output

            data = json.loads(json_str)

            is_complete = data.get("is_complete", False)
            status_str = data.get("status", "pending")
            pending_items = data.get("pending_items", [])
            summary = data.get("summary", "")

            # Convert status string to enum
            try:
                status = TaskStatus(status_str)
            except ValueError:
                status = TaskStatus.PENDING

            return SupervisorResult(
                is_complete=is_complete,
                status=status,
                pending_items=pending_items,
                summary=summary,
                raw_response=output,
            )

        except json.JSONDecodeError:
            # If we can't parse JSON, treat as incomplete and use the raw output
            return SupervisorResult(
                is_complete=False,
                status=TaskStatus.PENDING,
                pending_items=["无法解析agent响应，请手动检查"],
                summary=response.output[:200] if response.output else "无输出",
                raw_response=response.output,
            )

    def generate_pending_document(self, result: SupervisorResult, task: str) -> str:
        """
        Generate a document describing pending items.

        Args:
            result: The supervisor result with pending items.
            task: The original task.

        Returns:
            A formatted document describing what's pending.
        """
        lines = [
            "# 任务完成状态报告",
            "",
            f"## 原始任务",
            task,
            "",
            f"## 当前状态: {result.status.value}",
            "",
            f"## 摘要",
            result.summary,
            "",
        ]

        if result.pending_items:
            lines.append("## 待完成项目")
            lines.append("")
            for i, item in enumerate(result.pending_items, 1):
                lines.append(f"{i}. {item}")
            lines.append("")

        if result.is_complete:
            lines.append("✅ 所有任务已完成！")
        else:
            lines.append("⏳ 任务仍在进行中，请继续处理上述待完成项目。")

        return "\n".join(lines)
