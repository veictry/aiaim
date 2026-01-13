"""
CLI - Command line interface for AIAIM.

Provides a command-line interface for running tasks with the supervisor/worker pattern.
"""

import json
import sys
from typing import Optional, Callable

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import print as rprint

from aiaim.agent_cli import AgentType
from aiaim.task_runner import TaskRunner, IterationLog


console = Console()


def create_status_callback() -> Callable[[str], None]:
    """Create a status callback for rich console output."""

    def callback(message: str) -> None:
        if message.startswith("==="):
            console.print(f"\n[bold blue]{message}[/bold blue]")
        elif message.startswith("✅"):
            console.print(f"[bold green]{message}[/bold green]")
        elif message.startswith("⚠️"):
            console.print(f"[bold yellow]{message}[/bold yellow]")
        elif "失败" in message or "错误" in message:
            console.print(f"[red]{message}[/red]")
        else:
            console.print(f"[dim]{message}[/dim]")

    return callback


def create_iteration_callback() -> Callable[[IterationLog], None]:
    """Create an iteration complete callback."""

    def callback(log: IterationLog) -> None:
        if log.supervisor_result and not log.supervisor_result.is_complete:
            if log.supervisor_result.pending_items:
                console.print("\n[yellow]待完成项目:[/yellow]")
                for i, item in enumerate(log.supervisor_result.pending_items, 1):
                    console.print(f"  [dim]{i}.[/dim] {item}")

    return callback


def create_agent_output_callback() -> Callable[[str], None]:
    """Create a callback for real-time agent output streaming."""

    def callback(line: str) -> None:
        # Print agent output in real-time with a subtle style
        console.print(line, end="", style="cyan", highlight=False)

    return callback


@click.group()
@click.version_option()
def main():
    """AIAIM - AI Agent Iterative Manager

    A supervisor/worker agent pattern for iterative task completion.
    """
    pass


@main.command()
@click.argument("task")
@click.option(
    "--agent-type",
    "-a",
    type=click.Choice(["cursor-cli"]),
    default="cursor-cli",
    help="Agent type to use (default: cursor-cli)",
)
@click.option(
    "--model",
    "-m",
    default="claude-4.5-opus-high-thinking",
    help="Model name to use",
)
@click.option(
    "--max-iterations",
    "-n",
    default=10,
    type=int,
    help="Maximum number of iterations (default: 10)",
)
@click.option(
    "--delay",
    "-d",
    default=1.0,
    type=float,
    help="Delay between iterations in seconds (default: 1.0)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output file for results (JSON format)",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Quiet mode - minimal output",
)
@click.option(
    "--chat-id",
    "-c",
    default=None,
    help="Resume an existing chat session (skip creating new chat)",
)
def run(
    task: str,
    agent_type: str,
    model: str,
    max_iterations: int,
    delay: float,
    output: Optional[str],
    quiet: bool,
    chat_id: Optional[str],
):
    """Run a task with the supervisor/worker loop.

    TASK is the task description to execute.

    Example:
        aiaim run "Create a Python function that calculates fibonacci numbers"
    """
    console.print(
        Panel.fit(
            f"[bold]任务:[/bold] {task}",
            title="AIAIM Task Runner",
            border_style="blue",
        )
    )

    console.print(f"\n[dim]配置:[/dim]")
    console.print(f"  Agent类型: {agent_type}")
    console.print(f"  模型: {model}")
    console.print(f"  最大迭代次数: {max_iterations}")
    console.print(f"  迭代间隔: {delay}秒")
    if chat_id:
        console.print(f"  恢复会话: {chat_id}")

    # Create runner
    runner = TaskRunner(
        agent_type=AgentType(agent_type),
        model=model,
        max_iterations=max_iterations,
        delay_between_iterations=delay,
        chat_id=chat_id,
        on_status_update=None if quiet else create_status_callback(),
        on_iteration_complete=None if quiet else create_iteration_callback(),
        on_agent_output=None if quiet else create_agent_output_callback(),
    )

    # Run the task
    console.print("\n[bold]开始执行...[/bold]\n")

    try:
        result = runner.run(task)

        # Display results
        console.print("\n")
        console.print(
            Panel.fit(
                f"[bold]完成状态:[/bold] {'✅ 成功' if result.completed else '❌ 未完成'}\n"
                f"[bold]迭代次数:[/bold] {result.iterations}\n"
                f"[bold]总耗时:[/bold] {result.total_time:.2f}秒\n"
                f"[bold]摘要:[/bold] {result.final_summary}",
                title="执行结果",
                border_style="green" if result.completed else "yellow",
            )
        )

        # Save to file if requested
        if output:
            with open(output, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
            console.print(f"\n[dim]结果已保存到: {output}[/dim]")

        # Exit with appropriate code
        sys.exit(0 if result.completed else 1)

    except KeyboardInterrupt:
        console.print("\n[yellow]任务被用户中断[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]执行错误: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("task")
@click.option(
    "--agent-type",
    "-a",
    type=click.Choice(["cursor-cli"]),
    default="cursor-cli",
    help="Agent type to use",
)
@click.option(
    "--model",
    "-m",
    default="claude-4.5-opus-high-thinking",
    help="Model name to use",
)
@click.option(
    "--chat-id",
    "-c",
    default=None,
    help="Resume an existing chat session (skip creating new chat)",
)
def check(task: str, agent_type: str, model: str, chat_id: Optional[str]):
    """Check if a task is complete without executing.

    TASK is the task description to check.

    Example:
        aiaim check "Create a Python function that calculates fibonacci numbers"
    """
    console.print(
        Panel.fit(
            f"[bold]任务:[/bold] {task}",
            title="AIAIM Status Check",
            border_style="blue",
        )
    )

    runner = TaskRunner(
        agent_type=AgentType(agent_type),
        model=model,
        chat_id=chat_id,
        on_agent_output=create_agent_output_callback(),
    )

    console.print("\n[dim]检查任务状态...[/dim]\n")
    result = runner.run_check_only(task)

    # Display results
    status_color = "green" if result.is_complete else "yellow"
    console.print(
        Panel.fit(
            f"[bold]状态:[/bold] [{status_color}]{result.status.value}[/{status_color}]\n"
            f"[bold]完成:[/bold] {'是' if result.is_complete else '否'}\n"
            f"[bold]摘要:[/bold] {result.summary}",
            title="检查结果",
            border_style=status_color,
        )
    )

    if result.pending_items:
        table = Table(title="待完成项目")
        table.add_column("#", style="dim")
        table.add_column("项目")

        for i, item in enumerate(result.pending_items, 1):
            table.add_row(str(i), item)

        console.print(table)

    sys.exit(0 if result.is_complete else 1)


@main.command()
@click.argument("task")
@click.option(
    "--agent-type",
    "-a",
    type=click.Choice(["cursor-cli"]),
    default="cursor-cli",
    help="Agent type to use",
)
@click.option(
    "--model",
    "-m",
    default="claude-4.5-opus-high-thinking",
    help="Model name to use",
)
@click.option(
    "--pending",
    "-p",
    multiple=True,
    help="Pending items to work on (can be specified multiple times)",
)
@click.option(
    "--chat-id",
    "-c",
    default=None,
    help="Resume an existing chat session (skip creating new chat)",
)
def step(task: str, agent_type: str, model: str, pending: tuple, chat_id: Optional[str]):
    """Run a single iteration of worker + supervisor.

    TASK is the task description to execute.

    Example:
        aiaim step "Create a Python function" -p "Add error handling" -p "Add docstring"
    """
    console.print(
        Panel.fit(
            f"[bold]任务:[/bold] {task}",
            title="AIAIM Single Step",
            border_style="blue",
        )
    )

    pending_items = list(pending) if pending else None

    if pending_items:
        console.print("\n[yellow]待完成项目:[/yellow]")
        for i, item in enumerate(pending_items, 1):
            console.print(f"  {i}. {item}")

    runner = TaskRunner(
        agent_type=AgentType(agent_type),
        model=model,
        chat_id=chat_id,
        on_agent_output=create_agent_output_callback(),
    )

    console.print("\n[bold]执行单步迭代...[/bold]\n")

    try:
        worker_result, supervisor_result = runner.run_single_iteration(task, pending_items)

        # Display worker result
        console.print(
            Panel.fit(
                f"[bold]成功:[/bold] {'是' if worker_result.success else '否'}\n"
                f"[bold]输出:[/bold]\n{worker_result.output[:500] if worker_result.output else '(无输出)'}",
                title="Worker 结果",
                border_style="green" if worker_result.success else "red",
            )
        )

        # Display supervisor result
        status_color = "green" if supervisor_result.is_complete else "yellow"
        console.print(
            Panel.fit(
                f"[bold]完成:[/bold] {'是' if supervisor_result.is_complete else '否'}\n"
                f"[bold]摘要:[/bold] {supervisor_result.summary}",
                title="Supervisor 检查结果",
                border_style=status_color,
            )
        )

        if supervisor_result.pending_items:
            table = Table(title="仍待完成项目")
            table.add_column("#", style="dim")
            table.add_column("项目")

            for i, item in enumerate(supervisor_result.pending_items, 1):
                table.add_row(str(i), item)

            console.print(table)

        sys.exit(0 if supervisor_result.is_complete else 1)

    except Exception as e:
        console.print(f"\n[red]执行错误: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
