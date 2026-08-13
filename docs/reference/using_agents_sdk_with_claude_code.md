### Using with the agents sdk in python and claude code

---

### Assistant Response
Using the **Claude Agent SDK in Python** alongside **Claude Code** and a long-lived `setup-token` is a highly effective way to run programmatic agent workflows. Because the Python SDK acts as a direct wrapper over your locally bundled or system-level Claude Code CLI binary, it natively understands subscription-based OAuth tokens. 

#### How the Token Interacts with the Python SDK

When you generate a token using `claude setup-token`, you create a **long-lived OAuth token** tailored for headless execution and CI/CD pipelines. 

* **The Python SDK Advantage**: The Python library (`claude-agent-sdk`) automatically searches for and communicates with your Claude Code execution engine. 
* **Quotas and Billing**: Instead of billing via pay-as-you-go API keys (`sk-ant-api...`), the SDK draws down directly from your Claude subscription limits (Pro, Max, Team, or Enterprise) via your OAuth token.

---

#### Step-by-Step Implementation

Follow this structure to deploy your Python agent with the long-lived token.

##### 1. Environment Setup
Install the official Agent SDK. It is highly recommended to use [uv](https://github.com) or a standard Python virtual environment (Python 3.10+).

```bash
# Initialize and install using uv
uv init && uv add claude-agent-sdk

# Or using standard pip
python3 -m venv .venv
source .venv/bin/activate
pip install claude-agent-sdk
```

##### 2. Authenticate using the Setup-Token
Export your long-lived OAuth token to your environment variables. The underlying `claude` engine will prioritize this credential over standard API keys.

```bash
# Provide the token generated via 'claude setup-token'
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..." 

# (Optional) If managing multiple profiles or using the ant CLI framework
export ANTHROPIC_PROFILE="production-agent"
```

##### 3. Write your Python Agent Logic
The core programmatic interface relies on `query()` and `ClaudeAgentOptions`. This scripts the agent loop to read files, run tests, or execute terminal tools locally.

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def run_autonomous_agent():
    print("Initializing Agent Loop via Claude Code engine...")
    
    # Configure your agent's system instructions and tool permissions
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Bash", "Glob"], # Native filesystem capabilities
    )
    
    # Prompt the agent to complete a task locally
    prompt = "Review the files in this directory and optimize the error handling in main.py."
    
    async for message in query(prompt=prompt, options=options):
        # The SDK streams events as Claude reasons, runs bash commands, and edits files
        if hasattr(message, 'content'):
            print(message.content)

if __name__ == "__main__":
    asyncio.run(run_autonomous_agent())
```

---

#### Critical Guardrails to Keep in Mind

* **No Multi-User Apps**: The `setup-token` path binds the execution to your individual or team subscription. Anthropic explicitly blocks and detects multi-user wrapper apps attempting to tunnel subscription access to multiple unauthenticated end-users.
* **Avoid `--bare` Invocations**: If you or your scripts accidentally force a bare-mode execution bypass (`--bare`), the engine will intentionally ignore the OAuth token and demand a traditional commercial API key.
* **Local Filesystem Isolation**: Because the Agent SDK executes standard `Claude Code` tools (like `Bash` and `Edit`) directly on the host machine via `stdio`, **always** run this setup inside a sandboxed environment, Docker container, or isolated CI runner to prevent accidental local file destruction.

To fine-tune this for your environment, let me know:
* Are you running this agent **locally, in a Docker container, or on a CI provider** (like GitHub Actions)?
* Do you need to register **custom Python functions as tools** (`@tool` decorators) for the agent to call?

---

### User Message
I was planning on running locally in the same env that i was running claude code just too get the TTHW ‘magic moment’ where the sdk wrapper handles keeping track of agent message sessions, messages etc and my python app (bridge layer 3) connects my UI (layer 4) to claude code execution (layer 2) where layer 1 is the agent + agent-skill definitions (AGENT.md and SKILL.md plus pure pyton scripts, references, hooks, etc. per claude agent-skills model). Then moving to Docker Containers locally makes sense for doing real work, The (this) app also will have a session manager and will use git worktrees and a claim system for running 2-3 agents/workflows.

---

### Assistant Response
This four-layer architecture is an exceptionally solid layout for an enterprise-grade agent orchestration platform. 

The approach precisely targets the true value of the `claude-agent-sdk`. Developers often mistake it for a basic stateless API wrapper, but its real power lies in **supervising a long-lived stateful sub-process** that handles bash loops, diff editing, tool execution, and context tracking automatically over standard input/output (stdio).

A blueprint maps your current local testing approach directly to your planned multi-agent, git-worktree production system.

---

#### Layer-by-Layer Architectural Alignment

```
┌────────────────────────────────────────────────────────┐
│ Layer 4: UI (Frontend / Dashboard)                     │
└───────────────────────────┬────────────────────────────┘
                            │ (WebSockets / SSE)
┌───────────────────────────▼────────────────────────────┐
│ Layer 3: Bridge Layer & Session Manager (Python App)   │
│   ├── Claim & Queue System  ├── Git Worktree Manager   │
└───────────────────────────┬────────────────────────────┘
                            │ (ClaudeSDKClient Session)
┌───────────────────────────▼────────────────────────────┐
│ Layer 2: Execution Layer (Claude Code Runtime Engine)  │
└───────────────────────────┬────────────────────────────┘
                            │ (Progressive Disclosure)
┌───────────────────────────▼────────────────────────────┐
│ Layer 1: Configuration Layer (AGENT.md + SKILL.md)     │
└────────────────────────────────────────────────────────┘
```

##### Layer 1: Configuration (`AGENT.md` & `SKILL.md`)
This layer implements Anthropic’s **Progressive Disclosure** paradigm. Instead of flooding the context window with dozens of Python helper functions simultaneously, the `claude-agent-sdk` reads `AGENT.md` for global guardrails and registers a local directory path containing your skills.
* **`SKILL.md` Protocol**: Claude only reads the high-level capability definition file initially. When it encounters a problem requiring that skill, it dynamically injects the underlying execution scripts or hooks into its immediate execution context.

##### Layer 2: Execution Layer (`Claude Code`)
The SDK spawns a system subprocess mapping directly to the underlying `claude` engine. Because you are providing a long-lived `setup-token`, Layer 2 handles authentication seamlessly behind the scenes while maintaining permission validation (`acceptEdits` vs `ask`) and filesystem tooling out of the box.

##### Layer 3: Bridge Layer & Session Manager (Your Core Engine)
This is where you implement your state logic. To capture that "magic moment" where the SDK handles session persistence natively, **do not use `query()`** (which acts as a one-shot query). Instead, instantiate the stateful `ClaudeSDKClient`.

```python
import os
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

class AgentSessionManager:
    def __init__(self, worktree_root: str):
        self.worktree_root = worktree_root
        
    async def initialize_agent_session(self, session_id: str, agent_path: str):
        # Configure local execution properties for this specific agent's sandbox
        options = ClaudeAgentOptions(
            # Direct the engine to look at your Layer 1 Agent and Skill configs
            skills_dir=os.path.join(agent_path, ".claude/skills"), 
            # Execute tools directly inside this agent's allocated Git Worktree
            cwd=self.worktree_root,
            permission_mode="acceptEdits", # Bypasses human terminal approvals
            # The SDK natively preserves execution states into local JSONL tracking files
            session_id=session_id 
        )
        
        # Connect to the Layer 2 runtime process
        client = ClaudeSDKClient(options=options)
        await client.connect()
        return client
```

##### Layer 4: UI (Streaming State)
Because agent loops can run for minutes and make dozens of consecutive tool calls, your Layer 3 bridge needs to map the async iterator streams originating from Layer 2 up to Layer 4 via WebSockets or Server-Sent Events (SSE).

---

#### Moving From Local Testing to Docker Production

Your path forward is clean because the transition from a local machine to a Docker architecture primarily shifts **where the workspace directories point**.

##### Local Testing Phase
* **Setup**: You run your Layer 3 Python script directly on your host machine. 
* **Behavior**: The SDK spins up local `claude` subprocesses. Tools like `Bash` or `Edit` will interact directly with your local project directories.

##### Docker Production Phase
* **Subprocess Architecture Consideration**: Because each running agent acts as a stateful, long-lived process tied directly to disk states, running everything inside a single monolithic Python container breaks container isolation.
* **The Scale Strategy**: Your Python Bridge Layer (Layer 3) should run in a core orchestration container. When a job is claimed, Layer 3 issues a call to your infrastructure provider (or local Docker daemon) to provision a isolated worker container.




### User Messageusing with the agents sdk in python and claude code
---### Assistant ResponseUsing the **Claude Agent SDK in Python** alongside **Claude Code** and a long-lived `setup-token` is a highly effective way to run programmatic agent workflows. Because the Python SDK acts as a direct wrapper over your locally bundled or system-level Claude Code CLI binary, it natively understands subscription-based OAuth tokens. 
#### How the Token Interacts with the Python SDK
When you generate a token using `claude setup-token`, you create a **long-lived OAuth token** tailored for headless execution and CI/CD pipelines. 

* **The Python SDK Advantage**: The Python library (`claude-agent-sdk`) automatically searches for and communicates with your Claude Code execution engine. 
* **Quotas and Billing**: Instead of billing via pay-as-you-go API keys (`sk-ant-api...`), the SDK draws down directly from your Claude subscription limits (Pro, Max, Team, or Enterprise) via your OAuth token.
---#### Step-by-Step Implementation
Follow this structure to deploy your Python agent with the long-lived token.
##### 1. Environment SetupInstall the official Agent SDK. It is highly recommended to use [uv](https://github.com) or a standard Python virtual environment (Python 3.10+).
```bash
# Initialize and install using uv
uv init && uv add claude-agent-sdk

# Or using standard pip
python3 -m venv .venv
source .venv/bin/activate
pip install claude-agent-sdk
```
##### 2. Authenticate using the Setup-TokenExport your long-lived OAuth token to your environment variables. The underlying `claude` engine will prioritize this credential over standard API keys.
```bash
# Provide the token generated via 'claude setup-token'
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..." 

# (Optional) If managing multiple profiles or using the ant CLI framework
export ANTHROPIC_PROFILE="production-agent"
```
##### 3. Write your Python Agent LogicThe core programmatic interface relies on `query()` and `ClaudeAgentOptions`. This scripts the agent loop to read files, run tests, or execute terminal tools locally.
```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def run_autonomous_agent():
    print("Initializing Agent Loop via Claude Code engine...")
    
    # Configure your agent's system instructions and tool permissions
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Bash", "Glob"], # Native filesystem capabilities
    )
    
    # Prompt the agent to complete a task locally
    prompt = "Review the files in this directory and optimize the error handling in main.py."
    
    async for message in query(prompt=prompt, options=options):
        # The SDK streams events as Claude reasons, runs bash commands, and edits files
        if hasattr(message, 'content'):
            print(message.content)

if __name__ == "__main__":
    asyncio.run(run_autonomous_agent())
```
---#### Critical Guardrails to Keep in Mind
* **No Multi-User Apps**: The `setup-token` path binds the execution to your individual or team subscription. Anthropic explicitly blocks and detects multi-user wrapper apps attempting to tunnel subscription access to multiple unauthenticated end-users.
* **Avoid `--bare` Invocations**: If you or your scripts accidentally force a bare-mode execution bypass (`--bare`), the engine will intentionally ignore the OAuth token and demand a traditional commercial API key.
* **Local Filesystem Isolation**: Because the Agent SDK executes standard `Claude Code` tools (like `Bash` and `Edit`) directly on the host machine via `stdio`, **always** run this setup inside a sandboxed environment, Docker container, or isolated CI runner to prevent accidental local file destruction.

To fine-tune this for your environment, let me know:* Are you running this agent **locally, in a Docker container, or on a CI provider** (like GitHub Actions)?
* Do you need to register **custom Python functions as tools** (`@tool` decorators) for the agent to call?
---### User MessageI was planning on running locally in the same env that i was running claude code just too get the TTHW ‘magic moment’ where the sdk wrapper handles keeping track of agent message sessions, messages etc and my python app (bridge layer 3) connects my UI (layer 4) to claude code execution (layer 2) where layer 1 is the agent + agent-skill definitions (AGENT.md and SKILL.md plus pure pyton scripts, references, hooks, etc. per claude agent-skills model). Then moving to Docker Containers locally makes sense for doing real work, The (this) app also will have a session manager and will use git worktrees and a claim system for running 2-3 agents/workflows.
---### Assistant ResponseThis four-layer architecture is an exceptionally solid layout for an enterprise-grade agent orchestration platform. 

The approach precisely targets the true value of the `claude-agent-sdk`. Developers often mistake it for a basic stateless API wrapper, but its real power lies in **supervising a long-lived stateful sub-process** that handles bash loops, diff editing, tool execution, and context tracking automatically over standard input/output (stdio).

A blueprint maps your current local testing approach directly to your planned multi-agent, git-worktree production system.
---#### Layer-by-Layer Architectural Alignment```
┌────────────────────────────────────────────────────────┐
│ Layer 4: UI (Frontend / Dashboard)                     │
└───────────────────────────┬────────────────────────────┘
                            │ (WebSockets / SSE)
┌───────────────────────────▼────────────────────────────┐
│ Layer 3: Bridge Layer & Session Manager (Python App)   │
│   ├── Claim & Queue System  ├── Git Worktree Manager   │
└───────────────────────────┬────────────────────────────┘
                            │ (ClaudeSDKClient Session)
┌───────────────────────────▼────────────────────────────┐
│ Layer 2: Execution Layer (Claude Code Runtime Engine)  │
└───────────────────────────┬────────────────────────────┘
                            │ (Progressive Disclosure)
┌───────────────────────────▼────────────────────────────┐
│ Layer 1: Configuration Layer (AGENT.md + SKILL.md)     │
└────────────────────────────────────────────────────────┘
```

##### Layer 1: Configuration (`AGENT.md` & `SKILL.md`)
This layer implements Anthropic’s **Progressive Disclosure** paradigm. Instead of flooding the context window with dozens of Python helper functions simultaneously, the `claude-agent-sdk` reads `AGENT.md` for global guardrails and registers a local directory path containing your skills.
* **`SKILL.md` Protocol**: Claude only reads the high-level capability definition file initially. When it encounters a problem requiring that skill, it dynamically injects the underlying execution scripts or hooks into its immediate execution context.

##### Layer 2: Execution Layer (`Claude Code`)
The SDK spawns a system subprocess mapping directly to the underlying `claude` engine. Because you are providing a long-lived `setup-token`, Layer 2 handles authentication seamlessly behind the scenes while maintaining permission validation (`acceptEdits` vs `ask`) and filesystem tooling out of the box.
##### Layer 3: Bridge Layer & Session Manager (Your Core Engine)This is where you implement your state logic. To capture that "magic moment" where the SDK handles session persistence natively, **do not use `query()`** (which acts as a one-shot query). Instead, instantiate the stateful `ClaudeSDKClient`.
```python
import os
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

class AgentSessionManager:
    def __init__(self, worktree_root: str):
        self.worktree_root = worktree_root
        
    async def initialize_agent_session(self, session_id: str, agent_path: str):
        # Configure local execution properties for this specific agent's sandbox
        options = ClaudeAgentOptions(
            # Direct the engine to look at your Layer 1 Agent and Skill configs
            skills_dir=os.path.join(agent_path, ".claude/skills"), 
            # Execute tools directly inside this agent's allocated Git Worktree
            cwd=self.worktree_root,
            permission_mode="acceptEdits", # Bypasses human terminal approvals
            # The SDK natively preserves execution states into local JSONL tracking files
            session_id=session_id 
        )
        
        # Connect to the Layer 2 runtime process
        client = ClaudeSDKClient(options=options)
        await client.connect()
        return client
```
##### Layer 4: UI (Streaming State)Because agent loops can run for minutes and make dozens of consecutive tool calls, your Layer 3 bridge needs to map the async iterator streams originating from Layer 2 up to Layer 4 via WebSockets or Server-Sent Events (SSE).
---#### Moving From Local Testing to Docker Production
Your path forward is clean because the transition from a local machine to a Docker architecture primarily shifts **where the workspace directories point**.
##### Local Testing Phase* **Setup**: You run your Layer 3 Python script directly on your host machine. 
* **Behavior**: The SDK spins up local `claude` subprocesses. Tools like `Bash` or `Edit` will interact directly with your local project directories.
##### Docker Production Phase* **Subprocess Architecture Consideration**: Because each running agent acts as a stateful, long-lived process tied directly to disk states, running everything inside a single monolithic Python container breaks container isolation.* **The Scale Strategy**: Your Python Bridge Layer (Layer 3) should run in a core orchestration container. When a job is claimed, Layer 3 issues a call to your infrastructure provider (or local Docker daemon) to provision a isolated worker container.

* Volume Pinning: Mount the specific assigned Git Worktree directory and the .claude/sessions/ directory directly into that localized worker container. This strategy guarantees full process and filesystem isolation so that an agent executing a rogue Bash command cannot corrupt neighboring agent worktrees. [1] 

## Git Worktrees and the Claim System
Integrating a Git Worktree pipeline fits perfectly with this model. When your Layer 3 queue picks up an incoming engineering task:

   1. Provision Git Worktree: Run a local git command to branch out: git worktree add ../worktrees/task-101 feature-branch.
   2. Claim Token: Lock the target worktree and attach a dedicated session_id to it.
   3. Boot Engine: Initialize the ClaudeSDKClient passing the workspace parameter cwd="../worktrees/task-101".
   4. Collect Work & Teardown: Once the stream signals a completion state, your Python bridge can run git validation checks, run safety testing hooks, commit the modifications, and run git worktree remove ../worktrees/task-101.

If you are ready to begin mapping out the streaming state connection between Layer 3 and Layer 4, let me know:

* What Python web framework (e.g., FastAPI, Quart) you are using for the backend bridge?
* How you intend to push real-time agent tool-execution logs up to your frontend UI?


[1] [https://www.augmentcode.com](https://www.augmentcode.com/guides/claude-agent-sdk-skills-reusable-agent-capabilities)


