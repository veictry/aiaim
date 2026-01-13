# AIAIM - AI Agent Iterative Manager

一个基于 Supervisor/Worker 模式的 AI Agent 迭代任务管理器。

## 概述

AIAIM 实现了一个简单但强大的模式：

1. **创建会话** - 启动时创建共享的 chat session，全程使用同一个 chat_id
2. **Worker Agent** 执行用户指定的任务（实时输出到屏幕）
3. **Supervisor Agent** 检查任务是否完成，并列出未完成的项目
4. 如果任务未完成，Worker 继续处理未完成项目
5. 循环直到任务完成或达到最大迭代次数

```
┌─────────────────────────────────────────────────────────┐
│                      TaskRunner                          │
│                                                          │
│   ┌──────────┐     执行任务      ┌──────────────────┐   │
│   │  Worker  │ ───────────────→ │   实际工作环境    │   │
│   │  Agent   │ ←─────────────── │  (cursor-cli等)  │   │
│   └──────────┘     执行结果      └──────────────────┘   │
│        │                                                 │
│        │ 完成后                                          │
│        ▼                                                 │
│   ┌──────────┐     检查状态      ┌──────────────────┐   │
│   │Supervisor│ ───────────────→ │   实际工作环境    │   │
│   │  Agent   │ ←─────────────── │  (cursor-cli等)  │   │
│   └──────────┘   完成/未完成清单  └──────────────────┘   │
│        │                                                 │
│        │ 如果未完成                                      │
│        └──────────→ 返回 Worker 继续处理                 │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## 安装

```bash
pip install aiaim
```

或从源码安装：

```bash
git clone https://github.com/aiaim/aiaim.git
cd aiaim
pip install -e .
```

## 前置条件

- Python 3.9+
- `cursor-cli` 命令行工具（或其他配置的 agent CLI）

## 快速开始

### 命令行使用

```bash
# 运行一个任务
aiaim run "创建一个计算斐波那契数列的 Python 函数"

# 仅检查任务状态（不执行）
aiaim check "创建一个计算斐波那契数列的 Python 函数"

# 运行单步迭代
aiaim step "创建一个 Python 函数" -p "添加错误处理" -p "添加文档字符串"

# 带选项运行
aiaim run "完成任务描述" \
    --agent-type cursor-cli \
    --model claude-4.5-opus-high-thinking \
    --max-iterations 5 \
    --delay 2.0 \
    --output result.json
```

### Python API 使用

```python
from aiaim import TaskRunner, AgentType

# 创建任务运行器
runner = TaskRunner(
    agent_type=AgentType.CURSOR_CLI,
    model="claude-4.5-opus-high-thinking",
    max_iterations=10,
)

# 运行任务
result = runner.run("创建一个计算斐波那契数列的 Python 函数")

# 检查结果
if result.completed:
    print("任务完成!")
    print(f"迭代次数: {result.iterations}")
    print(f"总耗时: {result.total_time:.2f}秒")
else:
    print("任务未完成")
    print(f"错误: {result.error}")
```

### 自定义 Agent

```python
from aiaim import AgentCLI, AgentResponse, SupervisorAgent, WorkerAgent

# 使用自定义配置创建 agent
class MyCustomCLI(AgentCLI):
    def create_chat(self) -> str:
        # 创建会话并返回 chat_id
        ...
    
    def execute(self, prompt: str, on_output=None) -> AgentResponse:
        # 自定义执行逻辑
        # on_output 回调用于实时输出
        ...

# 使用自定义 agent
supervisor = SupervisorAgent(agent_cli=MyCustomCLI())
worker = WorkerAgent(agent_cli=MyCustomCLI())

runner = TaskRunner(
    supervisor_agent=supervisor,
    worker_agent=worker,
)
```

### 实时输出回调

```python
def my_output_handler(line: str):
    print(f"[AGENT] {line}", end="")

runner = TaskRunner(
    on_agent_output=my_output_handler,  # 实时输出回调
)
```

## CLI 命令

### `aiaim run`

运行完整的任务循环。

```
aiaim run [OPTIONS] TASK

Options:
  -a, --agent-type [cursor-cli]  Agent 类型
  -m, --model TEXT               模型名称
  -n, --max-iterations INTEGER   最大迭代次数
  -d, --delay FLOAT              迭代间隔（秒）
  -o, --output PATH              输出文件路径（JSON）
  -q, --quiet                    静默模式
```

### `aiaim check`

仅检查任务状态，不执行任何操作。

```
aiaim check [OPTIONS] TASK

Options:
  -a, --agent-type [cursor-cli]  Agent 类型
  -m, --model TEXT               模型名称
```

### `aiaim step`

运行单步迭代（一次 Worker + Supervisor）。

```
aiaim step [OPTIONS] TASK

Options:
  -a, --agent-type [cursor-cli]  Agent 类型
  -m, --model TEXT               模型名称
  -p, --pending TEXT             待完成项目（可多次指定）
```

## 配置

### 默认值

- Agent 类型: `cursor-cli`
- 模型: `claude-4.5-opus-high-thinking`
- 最大迭代次数: `10`
- 迭代间隔: `1.0` 秒

### 支持的 Agent 类型

| 类型 | 说明 |
|------|------|
| `cursor-cli` | Cursor CLI 命令行工具 |

## API 参考

### `TaskRunner`

主任务运行器，协调 Supervisor 和 Worker 的工作循环。

```python
TaskRunner(
    agent_type: AgentType = AgentType.CURSOR_CLI,
    model: str = "claude-4.5-opus-high-thinking",
    max_iterations: int = 10,
    delay_between_iterations: float = 1.0,
    supervisor_agent: Optional[SupervisorAgent] = None,
    worker_agent: Optional[WorkerAgent] = None,
    on_iteration_complete: Optional[Callable] = None,
    on_status_update: Optional[Callable] = None,
)
```

### `SupervisorAgent`

负责检查任务完成状态的 Agent。

```python
SupervisorAgent(
    agent_cli: Optional[AgentCLI] = None,
    agent_type: AgentType = AgentType.CURSOR_CLI,
    model: str = "claude-4.5-opus-high-thinking",
    check_prompt_template: Optional[str] = None,
)
```

### `WorkerAgent`

负责执行具体任务的 Agent。

```python
WorkerAgent(
    agent_cli: Optional[AgentCLI] = None,
    agent_type: AgentType = AgentType.CURSOR_CLI,
    model: str = "claude-4.5-opus-high-thinking",
    execute_prompt_template: Optional[str] = None,
)
```

### `AgentCLI`

Agent CLI 的抽象基类。

```python
AgentCLI.create(
    agent_type: AgentType = AgentType.CURSOR_CLI,
    model: str = "claude-4.5-opus-high-thinking",
    chat_id: Optional[str] = None,  # 可选的 chat ID
    **kwargs,
) -> AgentCLI
```

主要方法：
- `create_chat() -> str`: 创建会话并返回 chat_id
- `execute(prompt, on_output=None) -> AgentResponse`: 执行 prompt，支持实时输出回调

对于 `CursorCLI`：
- `create_chat()` 调用 `cursor-cli create-chat`
- `execute()` 在有 chat_id 时会使用 `cursor-cli --resume <chat_id> "<prompt>"`

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 代码格式化
black aiaim/
ruff check aiaim/
```

## 许可证

MIT License
