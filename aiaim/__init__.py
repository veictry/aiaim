"""
AIAIM - AI Agent Iterative Manager

A supervisor/worker agent pattern for iterative task completion.
"""

__version__ = "0.1.1"

from aiaim.agent_cli import AgentCLI, CursorCLI, AgentType
from aiaim.supervisor import SupervisorAgent
from aiaim.worker import WorkerAgent
from aiaim.task_runner import TaskRunner

__all__ = [
    "AgentCLI",
    "CursorCLI",
    "AgentType",
    "SupervisorAgent",
    "WorkerAgent",
    "TaskRunner",
]
