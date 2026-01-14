"""
Session management module for agend.

Uses SQLite for efficient indexing and shell session tracking.
Task content is stored in individual files for easy access and readability.

Storage structure:
    .agend/
    ├── sessions.db                    # SQLite for index, shell tracking, and chat_id bindings
    └── {session_id}/                  # Session directory (uuid)
        ├── task.md                    # Original task content
        └── {YYYY_MM_DD_HH_mm_ss}.md   # Iteration logs
"""

import os
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from contextlib import contextmanager


# Directory and database names
AGEND_DIR = ".agend"
DATABASE_FILE = "sessions.db"


def get_agend_dir(workspace: Optional[str] = None) -> Path:
    """
    Get the .agend directory path.

    Args:
        workspace: Workspace directory (default: current directory)

    Returns:
        Path to .agend directory
    """
    if workspace is None:
        workspace = os.getcwd()
    return Path(workspace) / AGEND_DIR


def get_database_path(workspace: Optional[str] = None) -> Path:
    """
    Get the path to the SQLite database.

    Args:
        workspace: Workspace directory

    Returns:
        Path to sessions.db
    """
    return get_agend_dir(workspace) / DATABASE_FILE


@contextmanager
def get_db_connection(workspace: Optional[str] = None):
    """
    Context manager for database connections.

    Ensures the database and tables exist before returning a connection.

    Args:
        workspace: Workspace directory

    Yields:
        sqlite3.Connection object
    """
    db_path = get_database_path(workspace)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row  # Enable column access by name

    try:
        _ensure_tables(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """
    Ensure all required tables exist in the database.

    Args:
        conn: Database connection
    """
    cursor = conn.cursor()

    # Sessions table - stores session metadata/index
    # session_id: agend session uuid
    # agent_chat_id: cursor-agent chat_id bound to this session
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            agent_chat_id TEXT,
            created_at TEXT NOT NULL,
            initial_prompt TEXT,
            workspace TEXT,
            iteration_count INTEGER DEFAULT 0
        )
    """
    )

    # Shell sessions table - maps shell PID to last used session
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shell_sessions (
            shell_pid TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            locked_session_id TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """
    )

    # Add locked_session_id column if not exists (migration)
    try:
        cursor.execute(
            "ALTER TABLE shell_sessions ADD COLUMN locked_session_id TEXT"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Create index for common queries
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sessions_created
        ON sessions(created_at DESC)
    """
    )

    conn.commit()


# ============================================================================
# Session Directory Management
# ============================================================================


def create_session_id() -> str:
    """
    Create a new unique session ID.

    Returns:
        A UUID string for the new session
    """
    return str(uuid.uuid4())


def ensure_session_dir(session_id: str, workspace: Optional[str] = None) -> Path:
    """
    Ensure the session directory exists.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        Path to the session directory
    """
    agend_dir = get_agend_dir(workspace)
    session_dir = agend_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_task_file_path(session_id: str, workspace: Optional[str] = None) -> Path:
    """
    Get the path for the task file.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        Path to the task.md file
    """
    session_dir = ensure_session_dir(session_id, workspace)
    return session_dir / "task.md"


def get_iteration_file_path(
    session_id: str, workspace: Optional[str] = None
) -> Path:
    """
    Get the path for a new iteration file with timestamp.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        Path to the iteration file
    """
    session_dir = ensure_session_dir(session_id, workspace)
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    return session_dir / f"{timestamp}.md"


# ============================================================================
# Session Index Management (SQLite)
# ============================================================================


def create_session(
    initial_prompt: str,
    workspace: Optional[str] = None,
    agent_chat_id: Optional[str] = None,
) -> str:
    """
    Create a new session and return the session ID.

    Args:
        initial_prompt: The initial prompt for this session
        workspace: Workspace directory
        agent_chat_id: Optional agent chat ID to bind to this session

    Returns:
        The new session ID (uuid)
    """
    session_id = create_session_id()

    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        workspace_str = str(workspace) if workspace else os.getcwd()

        cursor.execute(
            """
            INSERT INTO sessions (id, agent_chat_id, created_at, initial_prompt, workspace, iteration_count)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (session_id, agent_chat_id, timestamp, initial_prompt, workspace_str),
        )

    # Create session directory and save initial task
    task_file = get_task_file_path(session_id, workspace)
    task_file.write_text(f"# Task\n\n{initial_prompt}\n", encoding="utf-8")

    return session_id


def bind_agent_chat_id(
    session_id: str,
    agent_chat_id: str,
    workspace: Optional[str] = None,
) -> None:
    """
    Bind an agent chat ID to an existing session.

    Args:
        session_id: The agend session ID
        agent_chat_id: The cursor-agent chat ID to bind
        workspace: Workspace directory
    """
    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sessions
            SET agent_chat_id = ?
            WHERE id = ?
            """,
            (agent_chat_id, session_id),
        )


def get_session(session_id: str, workspace: Optional[str] = None) -> Optional[dict]:
    """
    Get session information by ID.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        Dict with session info, or None if not found
    """
    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None


def get_agent_chat_id(session_id: str, workspace: Optional[str] = None) -> Optional[str]:
    """
    Get the agent chat ID bound to a session.

    Args:
        session_id: The agend session ID
        workspace: Workspace directory

    Returns:
        The agent chat ID, or None if not bound
    """
    session = get_session(session_id, workspace)
    if session:
        return session.get("agent_chat_id")
    return None


def increment_iteration_count(session_id: str, workspace: Optional[str] = None) -> None:
    """
    Increment the iteration count for a session.

    Args:
        session_id: The session ID
        workspace: Workspace directory
    """
    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sessions
            SET iteration_count = iteration_count + 1
            WHERE id = ?
            """,
            (session_id,),
        )


def list_sessions(
    workspace: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[dict]:
    """
    List sessions ordered by creation time (newest first).

    Args:
        workspace: Workspace directory
        limit: Maximum number of sessions to return
        offset: Number of sessions to skip

    Returns:
        List of session dicts
    """
    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM sessions
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]


def search_sessions(
    query: str,
    workspace: Optional[str] = None,
    limit: int = 20,
) -> List[dict]:
    """
    Search sessions by initial prompt.

    Args:
        query: Search query string
        workspace: Workspace directory
        limit: Maximum results to return

    Returns:
        List of matching session dicts
    """
    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        search_pattern = f"%{query}%"

        cursor.execute(
            """
            SELECT * FROM sessions
            WHERE initial_prompt LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (search_pattern, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


# ============================================================================
# Iteration File Management
# ============================================================================


class IterationWriter:
    """
    A writer for streaming iteration content to a file.

    Creates the file immediately and allows real-time appending of content.
    """

    def __init__(
        self,
        session_id: str,
        iteration: int,
        workspace: Optional[str] = None,
    ):
        """
        Create a new iteration file and write the header.

        Args:
            session_id: The session ID
            iteration: The iteration number
            workspace: Workspace directory
        """
        self.session_id = session_id
        self.iteration = iteration
        self.workspace = workspace
        self.file_path = get_iteration_file_path(session_id, workspace)
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._closed = False

        # Create and open the file immediately
        self._file = open(self.file_path, "w", encoding="utf-8")

        # Write the header
        header = f"""# Iteration {iteration} - {self.timestamp}

"""
        self._file.write(header)
        self._file.flush()

    def write(self, content: str) -> None:
        """
        Append content to the iteration file.

        Args:
            content: Content to append
        """
        if self._closed:
            return
        self._file.write(content)
        self._file.flush()

    def write_section(self, title: str, content: str) -> None:
        """
        Write a section with a title.

        Args:
            title: Section title
            content: Section content
        """
        self.write(f"\n## {title}\n\n{content}\n")

    def close(self) -> Path:
        """
        Close the file and update the iteration count.

        Returns:
            Path to the saved file
        """
        if self._closed:
            return self.file_path

        self._closed = True
        self._file.close()

        # Update iteration count in index
        increment_iteration_count(self.session_id, self.workspace)

        return self.file_path

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def save_iteration(
    session_id: str,
    iteration: int,
    content: str,
    workspace: Optional[str] = None,
) -> Path:
    """
    Save an iteration to a timestamped file (one-shot version).

    Args:
        session_id: The session ID
        iteration: The iteration number
        content: The iteration content
        workspace: Workspace directory

    Returns:
        Path to the saved file
    """
    with IterationWriter(session_id, iteration, workspace) as writer:
        writer.write(content)
    return writer.file_path


def get_iteration_files(
    session_id: str, workspace: Optional[str] = None
) -> List[Path]:
    """
    Get all iteration files for a session.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        List of iteration file paths (sorted by name, newest first)
    """
    session_dir = get_agend_dir(workspace) / session_id
    if not session_dir.exists():
        return []

    # Exclude task.md, only get timestamped files
    files = [f for f in session_dir.glob("*.md") if f.name != "task.md"]
    return sorted(files, reverse=True)  # Newest first


def read_task(session_id: str, workspace: Optional[str] = None) -> Optional[str]:
    """
    Read the task file for a session.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        Task content, or None if file doesn't exist
    """
    task_file = get_task_file_path(session_id, workspace)
    if not task_file.exists():
        return None

    with open(task_file, "r", encoding="utf-8") as f:
        return f.read()


def read_iteration(file_path: Path) -> Optional[str]:
    """
    Read an iteration file.

    Args:
        file_path: Path to the iteration file

    Returns:
        File content, or None if file doesn't exist
    """
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================================
# Shell Session Tracking (SQLite)
# ============================================================================


def get_shell_pid() -> str:
    """
    Get a stable identifier for the current shell session.

    We cannot rely on os.getppid() because each command execution may have
    a different parent process (e.g., the shell forks for each command).
    
    Priority order:
    1. AGEND_SHELL_ID environment variable (explicit, most reliable)
    2. TTY name (stable within a terminal session, most reliable automatic method)
    3. Terminal session IDs (macOS Terminal, iTerm2, etc.)
    4. Interactive shell PID from process tree (grandparent PID)
    5. os.getppid() as last resort

    Returns:
        String identifier for the shell session
    """
    # 1. Check for explicit shell ID set via environment variable
    #    Users can add `export AGEND_SHELL_ID="$$"` to their .bashrc/.zshrc
    shell_id = os.environ.get("AGEND_SHELL_ID")
    if shell_id:
        return shell_id
    
    # 2. Try to get the TTY name - most stable within a terminal session
    #    Try multiple file descriptors as some may be redirected
    tty_name = None
    
    # Try stdin, stdout, stderr in order
    for fd in (0, 1, 2):
        try:
            tty_name = os.ttyname(fd)
            break
        except (OSError, AttributeError):
            pass
    
    # If none of the standard FDs are TTYs, try opening /dev/tty which always
    # refers to the controlling terminal of the current process (if one exists)
    if not tty_name:
        try:
            with open("/dev/tty", "r") as f:
                tty_name = os.ttyname(f.fileno())
        except (OSError, IOError):
            pass
    
    if tty_name:
        return f"tty:{tty_name}"
    
    # 3. Check terminal-specific session IDs
    for env_var in ("TERM_SESSION_ID", "ITERM_SESSION_ID", "KITTY_WINDOW_ID", 
                    "WEZTERM_PANE", "ALACRITTY_WINDOW_ID", "WINDOWID"):
        session_id = os.environ.get(env_var)
        if session_id:
            return f"{env_var}:{session_id}"
    
    # 4. Try to find the interactive shell's PID by walking up the process tree
    #    When user runs `agend`, the process tree typically looks like:
    #    zsh (interactive shell) -> fork -> agend (Python)
    #    So we want the grandparent PID (the interactive shell)
    try:
        import subprocess
        ppid = os.getppid()
        # Get the parent of our parent (the interactive shell)
        result = subprocess.run(
            ["ps", "-p", str(ppid), "-o", "ppid="],
            capture_output=True,
            text=True,
            timeout=1
        )
        if result.returncode == 0:
            grandparent_pid = result.stdout.strip()
            if grandparent_pid and grandparent_pid.isdigit():
                return f"shell:{grandparent_pid}"
    except Exception:
        pass
    
    # 5. Fall back to ppid (may vary between commands, but better than nothing)
    return str(os.getppid())


def get_last_session_id(
    workspace: Optional[str] = None, shell_pid: Optional[str] = None
) -> Optional[str]:
    """
    Get the last session ID for a shell.

    Args:
        workspace: Workspace directory
        shell_pid: Shell process ID (default: current shell)

    Returns:
        The last session ID, or None if not found
    """
    if shell_pid is None:
        shell_pid = get_shell_pid()

    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT session_id FROM shell_sessions WHERE shell_pid = ?",
            (shell_pid,),
        )
        row = cursor.fetchone()
        if row:
            return row["session_id"]
        return None


def get_locked_session_id_for_shell(
    workspace: Optional[str] = None, shell_pid: Optional[str] = None
) -> Optional[str]:
    """
    Get the locked session ID for a specific shell.

    Args:
        workspace: Workspace directory
        shell_pid: Shell process ID (default: current shell)

    Returns:
        The locked session ID, or None if not locked
    """
    if shell_pid is None:
        shell_pid = get_shell_pid()

    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT locked_session_id FROM shell_sessions WHERE shell_pid = ?",
            (shell_pid,),
        )
        row = cursor.fetchone()
        if row and row["locked_session_id"]:
            return row["locked_session_id"]
        return None


def set_last_session_id(session_id: str, workspace: Optional[str] = None) -> None:
    """
    Set the last session ID for the current shell.

    Args:
        session_id: The session ID to remember
        workspace: Workspace directory
    """
    shell_pid = get_shell_pid()
    timestamp = datetime.now().isoformat()

    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        # Preserve locked_session_id if exists
        cursor.execute(
            "SELECT locked_session_id FROM shell_sessions WHERE shell_pid = ?",
            (shell_pid,),
        )
        row = cursor.fetchone()
        locked_session_id = row["locked_session_id"] if row else None

        cursor.execute(
            """
            INSERT OR REPLACE INTO shell_sessions 
            (shell_pid, session_id, updated_at, locked_session_id)
            VALUES (?, ?, ?, ?)
            """,
            (shell_pid, session_id, timestamp, locked_session_id),
        )


def get_locked_session_id(workspace: Optional[str] = None) -> Optional[str]:
    """
    Get the locked session ID for the current shell.

    Args:
        workspace: Workspace directory

    Returns:
        The locked session ID, or None if not locked
    """
    shell_pid = get_shell_pid()

    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT locked_session_id FROM shell_sessions WHERE shell_pid = ?",
            (shell_pid,),
        )
        row = cursor.fetchone()
        if row and row["locked_session_id"]:
            return row["locked_session_id"]
        return None


def set_session_lock(
    session_id: str, workspace: Optional[str] = None
) -> None:
    """
    Lock the current shell to a specific session ID.

    Args:
        session_id: The session ID to lock to
        workspace: Workspace directory
    """
    shell_pid = get_shell_pid()
    timestamp = datetime.now().isoformat()

    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        # Check if row exists
        cursor.execute(
            "SELECT session_id FROM shell_sessions WHERE shell_pid = ?",
            (shell_pid,),
        )
        row = cursor.fetchone()

        if row:
            cursor.execute(
                """
                UPDATE shell_sessions 
                SET locked_session_id = ?, updated_at = ?
                WHERE shell_pid = ?
                """,
                (session_id, timestamp, shell_pid),
            )
        else:
            cursor.execute(
                """
                INSERT INTO shell_sessions 
                (shell_pid, session_id, updated_at, locked_session_id)
                VALUES (?, ?, ?, ?)
                """,
                (shell_pid, session_id, timestamp, session_id),
            )


def clear_session_lock(workspace: Optional[str] = None) -> Optional[str]:
    """
    Clear the session lock for the current shell.

    Args:
        workspace: Workspace directory

    Returns:
        The previously locked session ID, or None if wasn't locked
    """
    shell_pid = get_shell_pid()
    timestamp = datetime.now().isoformat()

    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT locked_session_id FROM shell_sessions WHERE shell_pid = ?",
            (shell_pid,),
        )
        row = cursor.fetchone()
        old_locked = row["locked_session_id"] if row else None

        if row:
            cursor.execute(
                """
                UPDATE shell_sessions 
                SET locked_session_id = NULL, updated_at = ?
                WHERE shell_pid = ?
                """,
                (timestamp, shell_pid),
            )

        return old_locked


def cleanup_stale_sessions(workspace: Optional[str] = None) -> int:
    """
    Clean up shell sessions for processes that no longer exist.

    This helps prevent the database from growing indefinitely.

    Args:
        workspace: Workspace directory

    Returns:
        Number of stale sessions removed
    """
    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()

        # Get all shell PIDs
        cursor.execute("SELECT shell_pid FROM shell_sessions")
        rows = cursor.fetchall()

        stale_pids = []
        for row in rows:
            shell_pid = row["shell_pid"]
            try:
                pid = int(shell_pid)
                os.kill(pid, 0)  # Signal 0 just checks if process exists
            except (ValueError, ProcessLookupError, PermissionError):
                stale_pids.append(shell_pid)

        if stale_pids:
            placeholders = ",".join("?" * len(stale_pids))
            cursor.execute(
                f"DELETE FROM shell_sessions WHERE shell_pid IN ({placeholders})",
                stale_pids,
            )

        return len(stale_pids)


# ============================================================================
# Utility Functions
# ============================================================================


def get_session_stats(workspace: Optional[str] = None) -> dict:
    """
    Get statistics about stored sessions.

    Args:
        workspace: Workspace directory

    Returns:
        Dict with statistics
    """
    with get_db_connection(workspace) as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM sessions")
        session_count = cursor.fetchone()["count"]

        cursor.execute("SELECT SUM(iteration_count) as total FROM sessions")
        row = cursor.fetchone()
        iteration_count = row["total"] if row["total"] else 0

        cursor.execute("SELECT COUNT(*) as count FROM shell_sessions")
        shell_session_count = cursor.fetchone()["count"]

        return {
            "sessions": session_count,
            "iterations": iteration_count,
            "shell_sessions": shell_session_count,
        }


def session_exists(session_id: str, workspace: Optional[str] = None) -> bool:
    """
    Check if a session exists.

    Args:
        session_id: The session ID to check
        workspace: Workspace directory

    Returns:
        True if session exists, False otherwise
    """
    return get_session(session_id, workspace) is not None


# ============================================================================
# Continue Mode Support
# ============================================================================


def get_latest_iteration_result(
    session_id: str, workspace: Optional[str] = None
) -> Optional[dict]:
    """
    Get the latest iteration result from a session's results directory.

    Reads the highest-numbered iteration_XXX.json file.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        Dict with iteration result data, or None if no results found
    """
    import json

    results_dir = get_agend_dir(workspace) / session_id
    if not results_dir.exists():
        return None

    # Find all iteration files
    result_files = sorted(results_dir.glob("iteration_*.json"), reverse=True)
    if not result_files:
        return None

    # Read the latest one
    try:
        with open(result_files[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def get_continue_state(
    session_id: str, workspace: Optional[str] = None
) -> tuple[int, list[str]]:
    """
    Get the state needed to continue a session.

    Returns the next iteration number and pending items from the last run.

    Args:
        session_id: The session ID
        workspace: Workspace directory

    Returns:
        Tuple of (next_iteration, pending_items).
        Returns (1, []) if no previous state found.
    """
    result = get_latest_iteration_result(session_id, workspace)
    if not result:
        return 1, []

    last_iteration = result.get("iteration", 0)
    pending_items = result.get("pending_items", [])

    return last_iteration + 1, pending_items
