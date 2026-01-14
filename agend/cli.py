"""
CLI - Command line interface for AGEND.

Provides a command-line interface for running tasks with the supervisor/worker pattern.
"""

import json
import sys
from typing import Optional, Callable

import click
from rich.console import Console
from rich.panel import Panel

from agend.agent_cli import AgentType
from agend.task_runner import TaskRunner, IterationLog
from agend import session as sess


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


def _run_task(
    task: str,
    agent_type: str,
    model: str,
    max_iterations: int,
    delay: float,
    output: Optional[str],
    quiet: bool,
    session_id: Optional[str] = None,
    start_iteration: int = 1,
    pending_items: Optional[list[str]] = None,
    chat_id: Optional[str] = None,
):
    """
    Internal function to run a task with the supervisor/worker loop.
    """
    # Get or create session
    if session_id:
        session_info = sess.get_session(session_id)
        if not session_info:
            console.print(f"[red]错误: 找不到 session {session_id}[/red]")
            sys.exit(1)
        # Use provided chat_id, or fall back to session's stored chat_id
        if not chat_id:
            chat_id = session_info.get("agent_chat_id")
    else:
        # Create new session with optional chat_id binding
        session_id = sess.create_session(task, agent_chat_id=chat_id)

    # Update shell's last session
    sess.set_last_session_id(session_id)

    console.print(
        Panel.fit(
            f"[bold]任务:[/bold] {task}",
            title="AGEND Task Runner",
            border_style="blue",
        )
    )

    console.print(f"\n[dim]配置:[/dim]")
    console.print(f"  Session: {session_id}")
    console.print(f"  Agent类型: {agent_type}")
    console.print(f"  模型: {model}")
    console.print(f"  最大迭代次数: {max_iterations}")
    console.print(f"  迭代间隔: {delay}秒")
    if start_iteration > 1:
        console.print(f"  起始迭代: {start_iteration}")
    if chat_id:
        console.print(f"  恢复 Agent Chat: {chat_id}")

    # Results directory for this session
    results_dir = str(sess.get_agend_dir() / session_id)

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
        results_dir=results_dir,
        start_iteration=start_iteration,
        initial_pending_items=pending_items,
    )

    # Run the task
    console.print("\n[bold]开始执行...[/bold]\n")

    try:
        result = runner.run(task)

        # Bind agent chat_id to session if we got one
        if result.chat_id and not chat_id:
            sess.bind_agent_chat_id(session_id, result.chat_id)

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
        raise


# ============================================================================
# CLI
# ============================================================================

class TaskOrSubcommandGroup(click.Group):
    """Custom Click group that handles optional TASK argument + subcommands.
    
    When a user runs:
      - `agend create-chat` -> should invoke create-chat subcommand
      - `agend "some task"` -> should run task
      - `agend --chat-id xxx create-chat` -> should invoke create-chat with option
    
    The challenge is that Click parses positional args before subcommands,
    so 'create-chat' would be captured as TASK. This class fixes that by
    checking if the would-be TASK is actually a known subcommand name.
    """
    
    def invoke(self, ctx):
        """Override invoke to handle TASK vs subcommand ambiguity."""
        # Check if task is actually a subcommand name
        task = ctx.params.get("task")
        if task and task in self.commands:
            # It's a subcommand, not a task
            # First, ensure ctx.obj is set up with chat_id from parent context
            ctx.ensure_object(dict)
            ctx.obj["chat_id"] = ctx.params.get("chat_id")
            
            # Clear task and mark as subcommand invocation
            ctx.params["task"] = None
            ctx.invoked_subcommand = task
            cmd = self.commands[task]
            
            # Get remaining args (could include --help for subcommand)
            # In Click 8.x, protected_args contains unprocessed tokens like --help
            # In Click 9.x, args will contain them directly
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                remaining_args = getattr(ctx, 'protected_args', None) or ctx.args
            
            with ctx:
                sub_ctx = cmd.make_context(task, remaining_args, parent=ctx)
                with sub_ctx:
                    return cmd.invoke(sub_ctx)
        
        return super().invoke(ctx)


@click.group(cls=TaskOrSubcommandGroup, invoke_without_command=True)
@click.argument("task", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Read task from file")
@click.option("--continue", "continue_iterations", type=int, is_flag=False, flag_value=10, default=None,
              help="Continue last session (optionally specify iterations, default: 10)")
@click.option("--resume", "-r", default=None, help="Resume a specific session by ID")
@click.option("--chat-id", default=None, help="Bind to an agent chat ID")
@click.option("--session", "-s", "session_id", type=str, default=None, help="Use/create agend session")
@click.option("--agent-type", "-a", type=click.Choice(["cursor-cli"]), default="cursor-cli",
              help="Agent type (default: cursor-cli)")
@click.option("--model", "-m", default="claude-4.5-opus-high-thinking", help="Model name")
@click.option("--max-iterations", "-n", default=10, type=int, help="Maximum iterations (default: 10)")
@click.option("--delay", "-d", default=1.0, type=float, help="Delay between iterations in seconds (default: 1.0)")
@click.option("--output", "-o", type=click.Path(), help="Output file for results (JSON)")
@click.option("--quiet", "-q", is_flag=True, help="Quiet mode")
@click.pass_context
def cli(
    ctx,
    task: Optional[str],
    file: Optional[str],
    continue_iterations: Optional[int],
    resume: Optional[str],
    chat_id: Optional[str],
    session_id: Optional[str],
    agent_type: str,
    model: str,
    max_iterations: int,
    delay: float,
    output: Optional[str],
    quiet: bool,
):
    """AGEND - AI Agent Iterative Manager

    A supervisor/worker agent pattern for iterative task completion.
    """
    # Store chat_id in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["chat_id"] = chat_id

    # If subcommand is invoked, skip main logic
    if ctx.invoked_subcommand is not None:
        return

    # Handle --session only (show session info or set current session)
    if session_id and not task and not file and continue_iterations is None:
        session_info = sess.get_session(session_id)
        if not session_info:
            console.print(f"[red]错误: 找不到 session {session_id}[/red]")
            sys.exit(1)
        sess.set_last_session_id(session_id)
        # Clear any existing lock and set new lock to this session
        sess.clear_session_lock()
        sess.set_session_lock(session_id)
        console.print(f"[green]✅ 已切换到会话: {session_id}[/green]")
        console.print(f"[dim]初始任务: {session_info.get('initial_prompt', 'N/A')}[/dim]")
        if session_info.get("agent_chat_id"):
            console.print(f"[dim]Agent Chat ID: {session_info.get('agent_chat_id')}[/dim]")
        return

    # Handle --chat-id only (bind to session)
    if chat_id and not task and not file and continue_iterations is None:
        use_session_id = session_id or sess.get_last_session_id()
        if not use_session_id:
            use_session_id = sess.create_session(
                initial_prompt="(session created, awaiting task)",
                agent_chat_id=chat_id,
            )
            sess.set_last_session_id(use_session_id)
            console.print(f"[green]✅ 创建新会话并绑定: {use_session_id}[/green]")
        else:
            sess.bind_agent_chat_id(use_session_id, chat_id)
            console.print(f"[green]✅ 已绑定 Agent Chat 到会话: {use_session_id}[/green]")
        console.print(f"[dim]Agent Chat ID: {chat_id}[/dim]")
        return

    # Handle --continue mode
    if continue_iterations is not None:
        cont_session_id = resume
        if not cont_session_id:
            cont_session_id = sess.get_last_session_id()
            if not cont_session_id:
                sessions = sess.list_sessions(limit=1)
                if sessions:
                    cont_session_id = sessions[0]["id"]

        if not cont_session_id:
            console.print("[red]错误: 没有找到可以继续的会话[/red]")
            sys.exit(1)

        session_info = sess.get_session(cont_session_id)
        if not session_info:
            console.print(f"[red]错误: 找不到 session {cont_session_id}[/red]")
            sys.exit(1)

        start_iteration, pending_items = sess.get_continue_state(cont_session_id)

        task_content = sess.read_task(cont_session_id)
        if task_content:
            task = task_content.replace("# Task\n\n", "").strip()
        else:
            task = session_info.get("initial_prompt", "")

        max_iterations = continue_iterations

        console.print(f"[dim]继续会话: {cont_session_id}[/dim]")
        console.print(f"[dim]从第 {start_iteration} 轮开始[/dim]")
        if pending_items:
            console.print(f"[dim]待完成项目: {len(pending_items)} 项[/dim]")

        _run_task(
            task=task,
            agent_type=agent_type,
            model=model,
            max_iterations=max_iterations,
            delay=delay,
            output=output,
            quiet=quiet,
            session_id=cont_session_id,
            start_iteration=start_iteration,
            pending_items=pending_items,
            chat_id=chat_id,
        )
        return

    # Handle --file
    if file:
        with open(file, "r", encoding="utf-8") as f:
            task = f.read().strip()

    # No task provided, show help
    if not task:
        click.echo(ctx.get_help())
        return

    # If explicit session_id provided, clear any session lock to avoid confusion
    if session_id:
        sess.clear_session_lock()
    else:
        # If no explicit session_id, check if shell has a locked session from create-chat
        locked_session = sess.get_locked_session_id()
        if locked_session:
            session_id = locked_session

    # Run task
    _run_task(
        task=task,
        agent_type=agent_type,
        model=model,
        max_iterations=max_iterations,
        delay=delay,
        output=output,
        quiet=quiet,
        session_id=session_id,
        chat_id=chat_id,
    )


@cli.command("create-chat")
@click.pass_context
def create_chat_cmd(ctx):
    """Create a new agend chat session and bind to current shell."""
    chat_id = ctx.obj.get("chat_id") if ctx.obj else None

    created_session_id = sess.create_session(
        initial_prompt="(session created, awaiting task)",
        agent_chat_id=chat_id,
    )
    sess.set_last_session_id(created_session_id)
    # Lock this shell to use this session for subsequent commands
    sess.set_session_lock(created_session_id)
    console.print(f"[green]✅ 创建新会话: {created_session_id}[/green]")
    if chat_id:
        console.print(f"[dim]绑定 Agent Chat: {chat_id}[/dim]")
    console.print(f"[dim]后续命令将自动使用此会话[/dim]")


def main():
    """Entry point."""
    cli()


if __name__ == "__main__":
    # When running as module (python -m agend.cli), use main() for preprocessing
    main()
