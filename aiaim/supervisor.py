"""
SupervisorAgent - Agent responsible for checking task completion status.

The supervisor agent polls to check if all tasks are completed and provides
feedback on what remains to be done. It maintains a todo list file to track
progress across iterations.
"""

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable
from pathlib import Path

from aiaim.agent_cli import AgentCLI, AgentType, AgentResponse


class TaskStatus(str, Enum):
    """Status of task completion."""

    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"


@dataclass
class TodoItem:
    """A single todo item with completion status."""

    content: str
    completed: bool = False

    def to_dict(self) -> dict:
        return {"content": self.content, "completed": self.completed}


@dataclass
class TodoList:
    """Todo list that can be persisted to a file."""

    items: list[TodoItem] = field(default_factory=list)
    task_description: str = ""

    def to_dict(self) -> dict:
        return {
            "task_description": self.task_description,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoList":
        items = [
            TodoItem(content=item["content"], completed=item.get("completed", False))
            for item in data.get("items", [])
        ]
        return cls(items=items, task_description=data.get("task_description", ""))

    def get_pending_items(self) -> list[str]:
        """Return list of pending (not completed) item contents."""
        return [item.content for item in self.items if not item.completed]

    def get_completed_items(self) -> list[str]:
        """Return list of completed item contents."""
        return [item.content for item in self.items if item.completed]

    def mark_completed(self, item_content: str) -> bool:
        """Mark an item as completed by content. Returns True if found."""
        for item in self.items:
            if item.content == item_content:
                item.completed = True
                return True
        return False

    def add_item(self, content: str, completed: bool = False) -> None:
        """Add a new item if it doesn't already exist."""
        if not any(item.content == content for item in self.items):
            self.items.append(TodoItem(content=content, completed=completed))

    def save(self, filepath: Path) -> None:
        """Save todo list to JSON file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: Path) -> "TodoList":
        """Load todo list from JSON file. Returns empty list if file doesn't exist."""
        if not filepath.exists():
            return cls()
        with open(filepath, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


@dataclass
class SupervisorResult:
    """Result from supervisor agent evaluation."""

    is_complete: bool
    status: TaskStatus
    pending_items: list[str]
    summary: str
    raw_response: str = ""
    newly_completed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "is_complete": self.is_complete,
            "status": self.status.value,
            "pending_items": self.pending_items,
            "newly_completed": self.newly_completed,
            "summary": self.summary,
        }


class SupervisorAgent:
    """
    Supervisor agent that checks task completion status.

    The supervisor polls the current state and determines if the task is complete,
    or provides a list of pending items that still need to be done.

    It maintains a todo list file to track progress across iterations.
    """

    # Default prompt template for checking task status
    DEFAULT_CHECK_PROMPT = """请检查以下任务是否已经全部完成。

## 原始任务
{task}

## 已完成的项目
{completed_items}

## 当前上下文
{context}

请按照以下JSON格式回复（只返回JSON，不要有其他内容）：
{{
    "is_complete": true/false,
    "status": "completed" | "in_progress" | "pending",
    "pending_items": ["未完成项1", "未完成项2", ...],
    "newly_completed": ["本次新完成的项1", ...],
    "summary": "当前状态的简要总结"
}}

注意：
- 如果任务已全部完成，设置 is_complete 为 true，pending_items 为空数组
- 如果任务未完成，设置 is_complete 为 false，并列出所有未完成的具体项目
- newly_completed 应列出相比上次检查新完成的项目
- summary 应简明扼要地描述当前进度
"""

    def __init__(
        self,
        agent_cli: Optional[AgentCLI] = None,
        agent_type: AgentType = AgentType.CURSOR_CLI,
        model: str = "claude-4.5-opus-high-thinking",
        check_prompt_template: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
        todo_file: Optional[str] = None,
    ):
        """
        Initialize the supervisor agent.

        Args:
            agent_cli: Optional pre-configured AgentCLI instance.
            agent_type: The type of agent to use if agent_cli is not provided.
            model: The model name to use.
            check_prompt_template: Optional custom prompt template for status checks.
            on_output: Optional callback for real-time output streaming.
            todo_file: Optional path to the todo list file. If None, uses ".aiaim/todo.json".
        """
        self.agent_cli = agent_cli or AgentCLI.create(agent_type=agent_type, model=model)
        self.check_prompt_template = check_prompt_template or self.DEFAULT_CHECK_PROMPT
        self.on_output = on_output
        self.todo_file = Path(todo_file) if todo_file else Path(".aiaim/todo.json")
        self._todo_list: Optional[TodoList] = None

    @property
    def todo_list(self) -> TodoList:
        """Get or load the todo list."""
        if self._todo_list is None:
            self._todo_list = TodoList.load(self.todo_file)
        return self._todo_list

    def _save_todo_list(self) -> None:
        """Save the current todo list to file."""
        if self._todo_list is not None:
            self._todo_list.save(self.todo_file)

    def check_completion(
        self,
        task: str,
        context: str = "",
        on_output: Optional[Callable[[str], None]] = None,
    ) -> SupervisorResult:
        """
        Check if the task is complete.

        Uses todo list to track completed items across iterations.
        The check compares the task requirements against completed items
        to determine what's still pending.

        Args:
            task: The original task description.
            context: Additional context about current state (e.g., pending items from previous check).
            on_output: Optional callback for real-time output (overrides instance callback).

        Returns:
            SupervisorResult indicating completion status and pending items.
        """
        # Update task description in todo list
        self.todo_list.task_description = task

        # Format completed items for the prompt
        completed_items = self.todo_list.get_completed_items()
        if completed_items:
            completed_str = "\n".join(f"- ✅ {item}" for item in completed_items)
        else:
            completed_str = "（暂无已完成项目）"

        # Build the prompt
        prompt = self.check_prompt_template.format(
            task=task,
            completed_items=completed_str,
            context=context if context else "这是首次检查，暂无历史上下文。",
        )

        # Use provided callback or instance callback
        output_callback = on_output or self.on_output

        # Execute via agent CLI
        response = self.agent_cli.execute(prompt, on_output=output_callback)

        # Parse the response and update todo list
        result = self._parse_response(response)

        # Update todo list with newly completed and pending items
        self._update_todo_list(result)

        return result

    def _update_todo_list(self, result: SupervisorResult) -> None:
        """
        Update the todo list based on supervisor result.

        Marks newly completed items and adds any new pending items.
        """
        # Mark newly completed items
        newly_completed = getattr(result, "newly_completed", [])
        for item in newly_completed:
            self.todo_list.mark_completed(item)

        # Add any new pending items that aren't already in the list
        for item in result.pending_items:
            self.todo_list.add_item(item, completed=False)

        # Save the updated todo list
        self._save_todo_list()

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
            newly_completed = data.get("newly_completed", [])
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
                newly_completed=newly_completed,
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
