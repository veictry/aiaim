"""
AgentCLI - Base class and implementations for agent execution.

Provides a unified interface for executing agent commands via CLI or API.
"""

import subprocess
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union, Callable


class AgentType(str, Enum):
    """Supported agent types."""

    CURSOR_CLI = "cursor-cli"
    # Future: Add more agent types like "openai-api", "anthropic-api", etc.


@dataclass
class AgentResponse:
    """Response from an agent execution."""

    success: bool
    output: str
    raw_output: Optional[str] = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "output": self.output,
            "raw_output": self.raw_output,
            "error": self.error,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class AgentCLI(ABC):
    """
    Abstract base class for agent CLI execution.

    All agent implementations should inherit from this class and implement
    the execute and create_chat methods.
    """

    def __init__(
        self,
        model: str = "claude-4.5-opus-high-thinking",
        timeout: Optional[int] = None,
        working_dir: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        """
        Initialize the agent CLI.

        Args:
            model: The model name to use for the agent.
            timeout: Optional timeout in seconds for command execution.
            working_dir: Optional working directory for command execution.
            chat_id: Optional chat ID for resuming a conversation.
        """
        self.model = model
        self.timeout = timeout
        self.working_dir = working_dir
        self.chat_id = chat_id

    @abstractmethod
    def create_chat(self) -> str:
        """
        Create a new chat session and return the chat ID.

        Returns:
            The chat ID for the new session.
        """
        pass

    @abstractmethod
    def execute(
        self,
        prompt: str,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> AgentResponse:
        """
        Execute the agent with the given prompt.

        Args:
            prompt: The prompt/context to send to the agent.
            on_output: Optional callback for real-time output streaming.

        Returns:
            AgentResponse containing the execution result.
        """
        pass

    @classmethod
    def create(
        cls,
        agent_type: Union[AgentType, str] = AgentType.CURSOR_CLI,
        model: str = "claude-4.5-opus-high-thinking",
        **kwargs,
    ) -> "AgentCLI":
        """
        Factory method to create an agent CLI instance.

        Args:
            agent_type: The type of agent to create.
            model: The model name to use.
            **kwargs: Additional arguments passed to the agent constructor.

        Returns:
            An instance of the appropriate AgentCLI subclass.
        """
        if isinstance(agent_type, str):
            agent_type = AgentType(agent_type)

        if agent_type == AgentType.CURSOR_CLI:
            return CursorCLI(model=model, **kwargs)
        else:
            raise ValueError(f"Unsupported agent type: {agent_type}")


class CursorCLI(AgentCLI):
    """
    Cursor CLI agent implementation.

    Executes prompts using the cursor-cli command.
    """

    def __init__(
        self,
        model: str = "claude-4.5-opus-high-thinking",
        timeout: Optional[int] = None,
        working_dir: Optional[str] = None,
        chat_id: Optional[str] = None,
        cursor_command: str = "cursor-cli",
    ):
        """
        Initialize the Cursor CLI agent.

        Args:
            model: The model name to use.
            timeout: Optional timeout in seconds.
            working_dir: Optional working directory.
            chat_id: Optional chat ID for resuming conversation.
            cursor_command: The cursor CLI command (default: "cursor-cli").
        """
        super().__init__(model=model, timeout=timeout, working_dir=working_dir, chat_id=chat_id)
        self.cursor_command = cursor_command

    def create_chat(self) -> str:
        """
        Create a new chat session using cursor-cli.

        Returns:
            The chat ID for the new session.
        """
        try:
            cmd = [self.cursor_command, "create-chat"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.working_dir,
            )

            if result.returncode == 0:
                # Assume the output is the chat ID (stripped)
                chat_id = result.stdout.strip()
                self.chat_id = chat_id
                return chat_id
            else:
                raise RuntimeError(f"Failed to create chat: {result.stderr or result.stdout}")
        except FileNotFoundError:
            raise RuntimeError(
                f"Command not found: {self.cursor_command}. "
                "Please ensure cursor-cli is installed and in PATH."
            )

    def execute(
        self,
        prompt: str,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> AgentResponse:
        """
        Execute the prompt using cursor-cli with real-time output streaming.

        Args:
            prompt: The prompt to send to the agent.
            on_output: Optional callback for real-time output.
                       If None, prints to stdout directly.

        Returns:
            AgentResponse with the execution result.
        """
        try:
            # Build the command
            cmd = [self.cursor_command]

            # Add --resume if we have a chat_id
            if self.chat_id:
                cmd.extend(["--resume", self.chat_id])

            cmd.append(prompt)

            # Use Popen for real-time output streaming
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.working_dir,
                bufsize=1,  # Line buffered
            )

            output_lines = []

            # Stream stdout in real-time
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if line:
                        output_lines.append(line)
                        # Real-time output: use callback or print directly
                        if on_output:
                            on_output(line)
                        else:
                            print(line, end="", flush=True)

            # Wait for process to complete
            process.wait(timeout=self.timeout)

            # Collect stderr
            stderr_output = process.stderr.read() if process.stderr else None
            error = stderr_output.strip() if stderr_output else None

            output = "".join(output_lines)

            return AgentResponse(
                success=process.returncode == 0,
                output=output.strip(),
                raw_output=output,
                error=error,
                metadata={
                    "return_code": process.returncode,
                    "model": self.model,
                    "command": self.cursor_command,
                    "chat_id": self.chat_id,
                },
            )

        except subprocess.TimeoutExpired:
            process.kill()
            return AgentResponse(
                success=False,
                output="",
                error=f"Command timed out after {self.timeout} seconds",
                metadata={"timeout": self.timeout, "chat_id": self.chat_id},
            )
        except FileNotFoundError:
            return AgentResponse(
                success=False,
                output="",
                error=f"Command not found: {self.cursor_command}. "
                "Please ensure cursor-cli is installed and in PATH.",
                metadata={"command": self.cursor_command},
            )
        except Exception as e:
            return AgentResponse(
                success=False,
                output="",
                error=str(e),
                metadata={"exception_type": type(e).__name__, "chat_id": self.chat_id},
            )
