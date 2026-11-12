---
Created: 2026-11-11
Tags:
---



# AI Engineering Organization

## Multi-Agent Software Engineering System — Project Plan

**Document Type:** Technical Project Plan / Initial Implementation Specification  
**Status:** Proposed  
**Primary Goal:** Build an AI-powered software engineering organization that can independently analyze requirements, design solutions, implement features, execute tests, fix bugs, and deliver verified engineering artifacts.

---

# 1. Project Vision

## 1.1 What I Want to Build

I want to build a Multi-Agent Engineering Organization.

Instead of interacting with multiple AI coding sessions manually, I will communicate with one central agent:

**Engineering Manager Agent**

The Manager will understand my requirements, create an execution plan, delegate tasks to specialized agents, coordinate their work, monitor progress, resolve conflicts, and aggregate the final results.

The goal is to make the system behave like a small software engineering team.

I should be able to give it a high-level requirement and receive:

- Architecture and design decisions
    
- Implementation code and Git diff
    
- Test plans and execution results
    
- Bug analysis and fixes
    
- Code review results
    
- Final engineering report
    
- Known risks and unresolved issues
    

The system should support two primary scenarios.

## 1.2 Scenario A: Scenario-Based Testing

Input:

I provide a collection of test scenarios, potentially covering different modules or business flows.

Example:

```
Scenario 1: Verify the normal order creation flow.
Scenario 2: Verify order creation with invalid customer information.
Scenario 3: Verify concurrent order updates.
Scenario 4: Verify timezone-related pricing behavior.
```

Expected workflow:

1. Engineering Manager analyzes the scenarios.
    
2. Manager groups scenarios by module, dependency, and execution requirements.
    
3. Manager creates independent testing tasks.
    
4. Multiple Test Worker Agents execute tasks in parallel.
    
5. Each worker investigates failures and identifies potential bugs.
    
6. Bug Fix Agents implement fixes when authorized.
    
7. Test Workers rerun relevant tests.
    
8. Manager aggregates all results and generates a final report.
    

Expected output:

- Scenario execution status
    
- Test logs and evidence
    
- Identified bugs
    
- Root cause analysis
    
- Code changes, if applicable
    
- Regression test results
    
- Overall test report
    

Important: The system must distinguish between a test failure and an actual product bug. Environment problems, test-data issues, flaky tests, and infrastructure failures should not automatically trigger code modifications.

## 1.3 Scenario B: Feature Development

Input:

I provide a feature requirement.

Example:

```
Implement a new pricing capability.

Requirements:
- Support configurable pricing attributes.
- Support different pricing rules for different customer groups.
- Ensure backward compatibility.
- Add unit tests and E2E tests.
```

Expected workflow:

1. Manager analyzes the requirement.
    
2. Multiple Architect Agents independently analyze the problem.
    
3. Architects review each other's proposals.
    
4. Manager coordinates discussions and resolves disagreements.
    
5. A Design Decision is finalized.
    
6. Dev Agent implements the feature.
    
7. Reviewer Agent reviews the implementation.
    
8. Test Agent executes unit tests, integration tests, and E2E tests.
    
9. If tests fail, Manager routes the issue back to the appropriate agent.
    
10. Bug Fix Agent fixes implementation issues.
    
11. Tests are rerun.
    
12. Manager produces the final engineering report.
    

Expected output:

- Requirement analysis
    
- Architecture proposals
    
- Final design decision
    
- API and data model changes
    
- Implementation code
    
- Git diff
    
- Test reports
    
- Code review findings
    
- Known limitations and risks
    

---

# 2. Core Architectural Principles

The system should follow these principles.

## 2.1 Separate Orchestration from Execution

This is the most important architectural decision.

The outer layer manages the engineering workflow.

The inner layer executes actual engineering tasks.

|Layer|Responsibility|Recommended Technology|
|---|---|---|
|Workflow Orchestration|Task planning, delegation, parallel execution, retries, routing, approvals|LangGraph|
|Agent Collaboration|Role definitions and structured team collaboration|CrewAI, optional|
|Coding Execution|Code exploration, implementation, debugging, terminal commands|Codex SDK|
|Test Execution|Build, unit tests, integration tests, E2E tests|Existing test frameworks / Playwright|
|Workspace Isolation|Separate working directories and branches|Git Worktree|
|Execution Isolation|Isolated test environments|Docker|
|Persistence|Workflow state, task state, checkpoints|SQLite initially|
|Artifact Storage|Designs, reports, logs, test results, code references|Local filesystem initially|
|User Interface|Chat, dashboard, approvals, progress tracking|Streamlit initially|

LangGraph, CrewAI, and Codex are not competing products.

They solve different problems:

- **LangGraph:** Controls the lifecycle of the engineering workflow.
    
- **CrewAI:** Provides a higher-level way to define and coordinate role-based agents.
    
- **Codex:** Performs actual coding work.
    

For the first version, LangGraph + Codex should be the primary combination.

CrewAI should remain optional. I want to learn it, but I should not introduce it into the critical execution path until there is a concrete benefit.

## 2.2 Do Not Bind Every Agent to a Codex Chat Session

An Agent Role is not the same thing as a Chat Session.

These concepts must be separated:

|Concept|Meaning|Example|
|---|---|---|
|Role|Defines responsibilities|Backend Architect|
|Agent Definition|Prompt, model, tools, permissions, configuration|Backend Architect configuration|
|Agent Instance|One concrete execution of an agent|Backend Architect analyzing Feature A|
|Task|Work assigned to an agent|Review the proposed database schema|
|Thread / Session|Execution context for an agent|One Codex thread|
|Subagent|A delegated worker inside another agent's execution|Explore existing database implementation|
|Runtime|Engine used to execute the agent|Codex SDK or LLM API|

The relationship is:

```
Agent Definition
       |
       v
     Task
       |
       v
 Agent Execution
       |
       v
    Result
```

A Role can have multiple execution instances.

An execution instance may use a separate thread, but it does not have to.

Examples:

- Architect Agent: Usually a normal LLM call. No independent Codex session required.
    
- Dev Agent: Uses Codex SDK and a dedicated coding session.
    
- Test Agent: Can use a test runner or Codex SDK.
    
- Bug Fix Agent: Uses Codex SDK with an isolated workspace.
    
- Reviewer Agent: Can use a normal LLM call or a coding agent depending on complexity.
    

**Important:** Agent count and Codex session count should never be treated as the same thing.

### 2.2.1 Thread 与顶层任务：当前实施选择

Thread 可以理解为 Codex 的一个独立对话上下文，包含多轮请求、回复和执行记录。通过 thread ID 可以继续或恢复同一任务；追加一轮请求不等于创建新 thread。Role 是职责配置，thread 是执行上下文，workflow 是后台管理的工程流程，三者不同。后台创建的 thread 不应假定会自动显示在 Codex 桌面侧栏；系统应提供自己的查看入口。

本节是当前实施选择，优先于上面关于普通 LLM 调用的可选示例。对本项目的目标，顶层角色使用独立 thread 更合适，但“看见做了什么”还需要执行记录和 UI。

推荐“每个顶层任务一个 thread”，而不是“每个角色永久一个 thread”：

- **Manager**：持续 thread，负责与用户交流、提出计划和汇总；后台校验结构化动作并实际执行调度。
- **Architect**：每个独立设计任务一个 thread，默认只读；交叉评审通过后台投递方案和问题。
- **Dev / Reviewer**：每个任务独立 thread；同一开发任务的修复恢复原 Dev thread，保留上下文。Reviewer 独立评审指定代码版本，默认只读。
- **Test**：规划、失败分析用 thread；实际测试由执行器运行，记录命令、退出码、提交版本、环境和日志。
- **临时探索**：宿主支持时可用 subagent，不必全部建立长期 thread；第一版不依赖内部 subagent 才能完成核心工作流。

用户只与一个 Manager 交流，但后台有多个执行上下文。独立 thread 不自动隔离文件；代码修改任务仍需独立 Git worktree。这种安排便于追踪 Dev/Test，避免不同任务的上下文混在一起；代价是更多调度、上下文和生命周期管理成本。

### 2.2.2 执行记录、UI 与角色通信

UI 按任务展示各角色的输入、可获取的执行事件与操作记录、代码 diff、测试证据和结果，并提供 thread 查看入口。这里指可审计的操作与产物，不要求展示模型内部思考过程。

后台持久化 workflow ID、task ID、attempt ID、角色、thread ID、执行状态、时间、代码版本和产物引用。聊天不能代替工作流状态或实际测试证据。

独立 threads 不会自动互聊。Dev 返回提交和产物引用，后台向 Test 投递验证任务；Test 返回失败分类和证据，Manager 判断后由后台向原 Dev thread 追加修复请求。消息保存发送方、接收方、任务、代码版本及投递状态，恢复时避免重复投递。

后台与 Codex 使用官方 SDK 或 App-server；Dev/Test 间采用本系统定义的结构化业务消息，由后台转发，不默认采用 ACP。SDK 适合程序化任务执行；App-server 适合需要历史、审批和流式执行事件的自建客户端。具体能力在技术验证阶段确认。

官方参考：[Codex SDK](https://developers.openai.com/codex/sdk)、[Codex App-server](https://developers.openai.com/codex/app-server)。

## 2.3 Two-Level Agent Hierarchy

Use two levels of delegation.

```
Level 1: Engineering Organization
---------------------------------

Engineering Manager (LangGraph)
       |
       |---- System Architect
       |---- Backend Architect
       |---- Security Architect
       |---- Dev Agent
       |---- Test Agent
       |---- Bug Fix Agent
       |---- Reviewer


Level 2: Coding Agent Internal Delegation
-----------------------------------------

Dev Agent (Codex)
       |
       |---- Explorer Subagent
       |---- Test Analysis Subagent
       |---- Implementation Subagent
```

LangGraph manages the overall software engineering lifecycle.

Codex Subagents help a coding agent decompose its own coding task.

Do not let LangGraph create a separate Codex session for every small code exploration task. That would introduce unnecessary complexity.

---

# 3. Overall System Architecture

## 3.1 High-Level Architecture

```
flowchart TD
    U[User] --> UI[Chat / Dashboard]
    UI --> M[Engineering Manager]

    M --> O[LangGraph Orchestrator]
    O --> P[Task Planner]
    P --> A[Agent Registry]

    A --> AR[Architect Agents]
    A --> D[Dev Agent]
    A --> T[Test Agent]
    A --> B[Bug Fix Agent]
    A --> R[Reviewer Agent]

    AR --> L[LLM Runtime]
    D --> C[Codex Runtime]
    T --> TR[Test Runner]
    B --> C
    R --> L

    C --> W[Git Worktree]
    TR --> W
    W --> G[Git Repository]

    O --> S[Workflow State Store]
    AR --> AS[Artifact Store]
    D --> AS
    T --> AS
    B --> AS
    R --> AS

    AS --> AG[Result Aggregator]
    S --> AG
    AG --> M
    M --> UI
    UI --> U
```

## 3.2 Main Components

### A. Engineering Manager

The central coordinator.

Responsibilities:

- Understand user requirements.
    
- Identify the workflow type.
    
- Break down work into tasks.
    
- Select appropriate agents.
    
- Define task dependencies.
    
- Dispatch independent tasks in parallel.
    
- Monitor task status.
    
- Handle retries and failures.
    
- Resolve conflicting agent outputs.
    
- Request human approval when necessary.
    
- Aggregate results.
    
- Produce final deliverables.
    

The Manager should not implement every task itself.

### B. Agent Registry

Maintain a registry of available agent definitions.

Each agent should have:

- Agent ID
    
- Role
    
- Description
    
- System prompt
    
- Model configuration
    
- Runtime type
    
- Available tools
    
- Permission policy
    
- Input schema
    
- Output schema
    

The registry allows the Manager to choose agents dynamically.

### C. Workflow Engine

LangGraph controls the workflow state and transitions.

Responsibilities:

- State management
    
- Conditional routing
    
- Parallel execution
    
- Task dependencies
    
- Retry policies
    
- Checkpointing
    
- Human-in-the-loop approvals
    
- Failure recovery
    

### D. Runtime Layer

Provides a unified interface for executing different agent types.

For example:

```
class AgentRuntime:
    async def execute(self, task, context):
        raise NotImplementedError
```

Possible implementations:

```
LLMRuntime
CodexRuntime
TestRunnerRuntime
CrewRuntime (optional)
```

The workflow should not need to know the internal details of each runtime.

### E. Workspace Manager

Manages isolated development environments.

Responsibilities:

- Create Git Worktrees.
    
- Assign branches to tasks.
    
- Prevent concurrent agents from modifying the same working directory.
    
- Collect Git diffs.
    
- Run builds and tests.
    
- Clean up temporary workspaces.
    

### F. Artifact Store

Stores all outputs from agents.

Artifacts should be structured and persistent.

Do not rely on agents sharing long chat histories with one another.

### G. Result Aggregator

Collects and consolidates:

- Agent results
    
- Design decisions
    
- Code changes
    
- Test reports
    
- Review findings
    
- Risks
    
- Unresolved questions
    

The final report should be generated from verified artifacts rather than informal chat messages.

---

# 4. Agent Organization

## 4.1 Initial Agent Roles

The first version should include the following roles.

|Agent|Main Responsibilities|Runtime|
|---|---|---|
|Engineering Manager|Planning, delegation, monitoring, aggregation|LangGraph + LLM|
|System Architect|High-level system architecture|LLM|
|Backend Architect|API, data model, service design|LLM|
|Security Architect|Security analysis and threat modeling|LLM|
|Dev Agent|Code implementation|Codex SDK|
|Test Agent|Test planning and execution|Test Runner / Codex SDK|
|Bug Fix Agent|Bug investigation and fixes|Codex SDK|
|Reviewer Agent|Code and design review|LLM / Codex|

## 4.2 Agent Responsibilities

### Engineering Manager

Must:

- Analyze requirements.
    
- Select the correct workflow.
    
- Create a task DAG.
    
- Assign agents based on skills.
    
- Track execution status.
    
- Detect blocked tasks.
    
- Handle failed tasks.
    
- Enforce retry limits.
    
- Ensure all required artifacts exist.
    
- Produce a final report.
    

Must NOT:

- Blindly trust agent conclusions.
    
- Allow unlimited retries.
    
- Allow agents to modify production branches directly.
    
- Hide unresolved disagreements.
    

### Architect Agents

Each architect should independently analyze the requirement.

Example:

**System Architect**

- System boundaries
    
- Component design
    
- Service interactions
    
- Scalability
    
- Reliability
    

**Backend Architect**

- API design
    
- Database schema
    
- Business logic
    
- Data consistency
    
- Backward compatibility
    

**Security Architect**

- Authentication and authorization
    
- Input validation
    
- Data protection
    
- Security risks
    
- Threat modeling
    

Architects should produce structured proposals rather than long informal discussions.

### Dev Agent

Responsibilities:

- Understand approved design.
    
- Explore the existing codebase.
    
- Identify relevant files and dependencies.
    
- Implement the feature.
    
- Add or update unit tests.
    
- Run builds and relevant tests.
    
- Report code changes and unresolved issues.
    

Dev Agent should use Codex SDK.

### Test Agent

Responsibilities:

- Convert requirements into test cases.
    
- Identify test coverage gaps.
    
- Execute tests.
    
- Collect logs and evidence.
    
- Classify failures.
    
- Report reproducible bugs.
    

Failure categories:

```
PRODUCT_BUG
TEST_BUG
TEST_DATA_ISSUE
ENVIRONMENT_ISSUE
FLAKY_TEST
UNKNOWN
```

### Bug Fix Agent

Responsibilities:

- Investigate confirmed product bugs.
    
- Identify root cause.
    
- Implement a minimal fix.
    
- Add regression tests.
    
- Run relevant tests.
    
- Report the fix and remaining risks.
    

### Reviewer Agent

Responsibilities:

- Review code changes.
    
- Check consistency with approved design.
    
- Identify security and reliability problems.
    
- Check test coverage.
    
- Report blocking and non-blocking findings.
    

The reviewer should ideally be independent from the original implementation agent.

---

# 5. Workflow Design

## 5.1 Workflow A: Scenario Testing

### Workflow Diagram

```
flowchart TD
    A[User submits scenarios] --> B[Manager analyzes scenarios]
    B --> C[Create test tasks]
    C --> D[Dependency analysis]
    D --> E[Parallel Test Workers]

    E --> F[Collect test results]
    F --> G{All tests passed?}

    G -->|Yes| H[Generate Test Report]
    G -->|No| I[Classify failures]

    I --> J{Failure type}
    J -->|Product bug| K[Create Bug Fix Task]
    J -->|Test issue| L[Fix Test]
    J -->|Environment issue| M[Environment Investigation]
    J -->|Unknown| N[Human Review]

    K --> O[Bug Fix Agent]
    O --> P[Regression Test]
    P --> Q{Fix verified?}

    Q -->|Yes| H
    Q -->|No| N

    L --> E
    M --> E
    N --> H
    H --> R[Manager Final Report]
```

### Execution Details

**Step 1: Requirement Intake**

Input:

```
{
  "workflow_type": "scenario_testing",
  "repository": "path/to/repository",
  "scenarios": [
    {
      "id": "S001",
      "description": "Verify normal order creation"
    },
    {
      "id": "S002",
      "description": "Verify invalid customer handling"
    }
  ]
}
```

**Step 2: Scenario Analysis**

Manager should:

- Understand each scenario.
    
- Identify related modules.
    
- Identify dependencies.
    
- Group related scenarios.
    
- Identify which scenarios can run independently.
    
- Create execution tasks.
    

**Step 3: Parallel Execution**

Independent tasks can execute concurrently.

Each worker should have its own task context and, if code modifications are needed, its own isolated workspace.

**Step 4: Failure Classification**

Do not automatically interpret every failed test as a product bug.

Require evidence such as:

- Failure logs
    
- Stack traces
    
- Reproduction steps
    
- Relevant code locations
    
- Environment information
    

**Step 5: Bug Fix and Regression**

Only confirmed and authorized product bugs should enter the code modification workflow.

**Step 6: Final Report**

The report should contain:

- Total scenarios
    
- Passed / failed / blocked counts
    
- Failure classification
    
- Identified bugs
    
- Fix status
    
- Regression results
    
- Remaining risks
    

## 5.2 Workflow B: Feature Development

### Workflow Diagram

```
flowchart TD
    A[User submits feature requirement] --> B[Manager analyzes requirement]
    B --> C[Create architecture tasks]

    C --> D1[System Architect]
    C --> D2[Backend Architect]
    C --> D3[Security Architect]

    D1 --> E[Cross Review]
    D2 --> E
    D3 --> E

    E --> F[Manager resolves disagreements]
    F --> G[Design Decision]
    G --> H{Human approval required?}

    H -->|Yes| I[User Approval]
    H -->|No| J[Implementation Tasks]
    I --> J

    J --> K[Dev Agent]
    K --> L[Code Review]
    L --> M{Review passed?}

    M -->|No| K
    M -->|Yes| N[Test Agent]

    N --> O{Tests passed?}
    O -->|Yes| P[Final Verification]
    O -->|No| Q[Failure Classification]

    Q --> R[Bug Fix Agent]
    R --> N

    P --> S[Final Engineering Report]
```

### Architecture Discussion Strategy

Do not let Architect Agents engage in unlimited group conversations.

Use a structured process:

1. Independent Analysis
    
2. Cross Review
    
3. Targeted Discussion
    
4. Manager Arbitration
    
5. Design Freeze
    

Each architect should produce:

```
Architecture Proposal
- Problem understanding
- Proposed solution
- Component changes
- API changes
- Data model changes
- Dependencies
- Trade-offs
- Risks
- Alternatives
```

Cross Review should focus on specific disagreements.

For example:

```
Question:
Should pricing rules be stored in a relational table
or represented as a configurable JSON document?

System Architect:
Proposal A...

Backend Architect:
Proposal B...

Security Architect:
Security implications...

Manager:
Final decision and rationale...
```

The Manager must preserve the disagreement and decision rationale.

### Design Freeze

Before implementation, create:

```
design-decision.md
```

It should contain:

- Final architecture
    
- Selected approach
    
- Rejected alternatives
    
- Trade-offs
    
- API contracts
    
- Data model
    
- Security considerations
    
- Acceptance criteria
    

If implementation discovers that the approved design is invalid, the workflow should explicitly reopen design review instead of silently changing the architecture.

---

# 6. Workflow State and Data Models

## 6.1 Central Workflow State

LangGraph should maintain a shared state object.

Initial conceptual model:

```
class EngineeringWorkflowState(TypedDict):
    workflow_id: str
    workflow_type: str

    user_requirement: str

    tasks: list
    task_results: list

    design_decisions: list
    artifacts: list

    execution_status: str
    current_stage: str

    errors: list
    risks: list

    approval_required: bool
    approval_status: str

    final_report: dict
```

The exact schema can evolve.

Avoid placing large code files, full logs, or entire conversations directly in LangGraph state. Store references to artifacts instead.

## 6.2 Task Schema

Each task should contain:

```
{
  "task_id": "TASK-001",
  "workflow_id": "WF-001",
  "title": "Implement pricing API",
  "description": "Implement the approved pricing API design.",
  "agent_role": "dev_agent",
  "runtime": "codex",
  "status": "pending",
  "dependencies": [],
  "input_artifacts": [
    "design-decision.md"
  ],
  "output_artifacts": [],
  "workspace_id": null,
  "retry_count": 0,
  "max_retries": 2
}
```

Possible task statuses:

```
PENDING
READY
RUNNING
BLOCKED
WAITING_FOR_APPROVAL
SUCCEEDED
FAILED
CANCELLED
```

## 6.3 Agent Result Schema

Every agent must return a structured result.

```
{
  "task_id": "TASK-001",
  "agent_id": "dev-agent-01",
  "status": "succeeded",
  "summary": "Implemented the pricing API.",
  "artifacts": [
    "implementation-summary.md",
    "git-diff.patch"
  ],
  "findings": [],
  "risks": [],
  "requires_human_review": false
}
```

Do not rely on free-form messages as the only way to communicate between agents.

---

# 7. Artifact Management

All important outputs should be persisted.

Suggested artifact structure:

```
artifacts/
  workflows/
    WF-001/
      requirement.md

      planning/
        task-plan.json

      architecture/
        system-architecture.md
        backend-proposal.md
        security-review.md
        cross-review.md
        design-decision.md

      implementation/
        implementation-summary.md
        git-diff.patch

      testing/
        test-plan.md
        unit-test-report.md
        e2e-test-report.md
        test-logs/

      review/
        code-review.md

      final/
        final-engineering-report.md
```

Artifact rules:

1. Every task should declare its input artifacts.
    
2. Every task should declare its expected output artifacts.
    
3. Artifacts should have clear ownership.
    
4. Important decisions should be versioned.
    
5. Agents should reference artifact IDs instead of copying large amounts of content.
    
6. The Manager should verify that required artifacts exist before marking a workflow complete.
    

---

# 8. Recommended Technology Stack

## 8.1 MVP Stack

|Area|Technology|Why|
|---|---|---|
|Main Language|Python 3.12+|LangGraph ecosystem and rapid prototyping|
|Workflow Orchestration|LangGraph|State, parallel execution, routing, retries|
|Agent Collaboration|CrewAI, optional|Learn and experiment with role-based collaboration|
|Coding Runtime|Codex SDK / App-server via Node/TypeScript adapter|Task threads; evaluate history, approvals and streamed events|
|LLM Integration|LangChain model integrations or direct model APIs|Architecture and planning agents|
|Backend API|FastAPI|Expose workflow execution and status|
|UI|Streamlit|Fast MVP for chat and dashboard|
|CLI Entry|Python CLI using the same backend API|Submit, inspect, cancel and retry the same workflows as UI|
|Workflow Persistence|SQLite initially|Simple local persistence|
|Artifact Storage|Local filesystem|Easy to inspect and debug|
|Code Isolation|Git Worktree|Independent branches and working directories|
|Test Isolation|Docker|Reproducible execution environments|
|E2E Testing|Playwright|Browser automation|
|Unit Testing|pytest / existing project test framework|Automated verification|
|Logging|Python logging / structlog|Execution observability|
|Version Control|Git|Code and artifact traceability|

Important implementation note:

Use the currently supported Codex SDK and its official documentation to select the package, language, authentication mechanism, and API surface. Do not assume that the SDK interface or package name is identical across Python and TypeScript.

当前技术组合：Python + LangGraph 编排，FastAPI 后台，Node/TypeScript Codex 接入层，Streamlit UI 与 CLI 双入口，SQLite 状态与消息存储，本地文件产物，Git worktree 代码隔离，以及项目已有的构建和测试执行器。CrewAI 不进入第一版关键路径；Playwright 仅适用于浏览器 E2E。

UI 和 CLI 共用独立运行的后台、workflow ID、执行记录及产物。关闭客户端不应中断任务。计划提供启动入口，启动后台并按需打开 UI；这是待实现设计，不是已存在的启动命令。

与最新 requirement.md 对齐：Docker 不是第一版默认前提；GraphConnectors Service Fabric E2E 先使用一个环境串行验证。本文其他章节中的 Docker 推荐视为后续可选方案。

## 8.2 Later Production Stack

Only introduce these when the MVP demonstrates a real need.

|Area|Future Option|
|---|---|
|Database|PostgreSQL|
|Workflow Persistence|LangGraph checkpointer backed by PostgreSQL|
|Queue|Redis / Celery|
|Object Storage|Azure Blob Storage / S3|
|Container Execution|Docker / Kubernetes|
|Backend|FastAPI|
|Frontend|React / Next.js|
|Observability|OpenTelemetry|
|Agent Evaluation|LangSmith or custom evaluation framework|
|CI/CD|GitHub Actions / Azure DevOps|

Do not start with Kubernetes, Redis, distributed workers, or a complicated microservice architecture.

The first objective is to prove that the multi-agent workflow works reliably.

---

# 9. User Interface

A dedicated UI is not mandatory for the first version.

Start with Streamlit.

## 9.1 Main Screens

### A. Engineering Chat

The only place where the user needs to interact with the organization.

Example:

```
User:
Implement a new pricing capability.

Manager:
I understand the requirement.

I will:
1. Analyze the requirement.
2. Ask three architects to independently review the design.
3. Consolidate the design.
4. Implement the feature.
5. Run automated tests.
6. Generate the final report.

Would you like to approve the proposed design before implementation?
```

### B. Workflow Dashboard

Display:

- Workflow ID
    
- Workflow type
    
- Current stage
    
- Overall status
    
- Agent task status
    
- Progress
    
- Failed tasks
    
- Waiting approvals
    

### C. Agent Execution View

Show:

- Agent role
    
- Task description
    
- Runtime
    
- Current status
    
- Start / end time
    
- Output artifacts
    
- Error messages
    

### D. Artifact Viewer

Allow the user to inspect:

- Architecture proposals
    
- Design decisions
    
- Code diffs
    
- Test reports
    
- Logs
    
- Final reports
    

### E. Human Approval

The user should be able to approve or reject:

- Final architecture
    
- Potentially destructive operations
    
- Code changes
    
- Deployment actions
    
- High-risk bug fixes
    

---

# 10. Security and Execution Safety

This is a core engineering requirement, not an optional enhancement.

## 10.1 Workspace Isolation

Every coding task should have an isolated Git Worktree.

Example:

```
repository/
  main branch

worktrees/
  WF-001-TASK-001/
  WF-001-TASK-002/
  WF-001-TASK-003/
```

Do not let parallel coding agents modify the same working directory.

If multiple tasks need to modify the same files, serialize them or explicitly coordinate the merge.

## 10.2 Permission Model

Define permissions by role and task.

Example:

|Action|Architect|Dev|Test|Bug Fix|Manager|
|---|---|---|---|---|---|
|Read source code|Yes|Yes|Yes|Yes|Yes|
|Modify source code|No|Yes|No by default|Yes|No|
|Run unit tests|No|Yes|Yes|Yes|No|
|Run E2E tests|No|Optional|Yes|Optional|No|
|Modify Git history|No|Restricted|No|Restricted|No|
|Merge to main|No|No|No|No|Approval only|
|Deploy|No|No|No|No|Human approval|

Permissions must be enforced by the runtime, filesystem, Git, and execution environment.

Do not rely only on system prompts to prevent dangerous operations.

## 10.3 Human Approval Points

The system should support configurable approval policies.

Recommended initial defaults:

- Architecture approval: Required before significant implementation.
    
- Code modification: Allowed only in isolated worktrees.
    
- Destructive operations: Require approval.
    
- Main branch merge: Require approval.
    
- Deployment: Require explicit approval.
    
- Repeated failures: Stop and ask for human intervention.
    

---

# 11. Development Roadmap

Build this project incrementally.

Do not implement the complete organization in one step.

## Phase 0: Environment and Technology Exploration

Goal: Understand the key technologies before building the complete system.

Tasks:

1. Set up Python development environment.
    
2. Learn basic LangGraph concepts.
    
3. Build a simple LangGraph workflow.
    
4. Explore Codex SDK.
    
5. Understand Codex threads and sessions.
    
6. Explore Codex Subagents.
    
7. Create a simple Git Worktree.
    
8. Run an automated test through Python.
    

Deliverable:

A small proof of concept that can execute a task using a coding agent and collect its result.

## Phase 1: Basic Engineering Manager

Goal: Build the central orchestration engine.

Implement:

- Engineering Manager
    
- Agent Registry
    
- Task model
    
- Agent Runtime interface
    
- LangGraph workflow
    
- SQLite persistence
    
- Local artifact storage
    

Initial workflow:

```
User Requirement
       |
       v
Engineering Manager
       |
       v
Task Planner
       |
       v
Agent Registry
       |
       v
Agent Execution
       |
       v
Result Aggregator
       |
       v
Final Report
```

Initially, use mock agents or simple LLM agents.

Do not integrate complex coding execution yet.

Acceptance criteria:

- Accept a user requirement.
    
- Generate a task plan.
    
- Assign tasks to agents.
    
- Execute independent tasks.
    
- Collect structured results.
    
- Generate a final report.
    
- Persist workflow state.
    

## Phase 2: Multi-Agent Architecture Workflow

Goal: Prove that multiple agents can independently analyze and review a feature.

Implement:

- System Architect
    
- Backend Architect
    
- Security Architect
    
- Cross Review
    
- Discussion and arbitration
    
- Design Decision generation
    

Acceptance criteria:

- Three architects independently analyze the same requirement.
    
- Their proposals are stored separately.
    
- Cross reviews identify disagreements.
    
- Manager produces a final design decision.
    
- All decisions are traceable.
    

No code modification is needed in this phase.

## Phase 3: Codex Integration

Goal: Let the organization perform actual coding work.

Implement:

- Codex Runtime
    
- Task-to-Codex execution mapping
    
- Thread/session management
    
- Git Worktree Manager
    
- Code execution
    
- Build and test execution
    
- Git diff collection
    

Acceptance criteria:

- Manager creates a development task.
    
- Dev Agent receives the task and approved design.
    
- Codex executes the task in an isolated worktree.
    
- Build and tests can be executed.
    
- Git diff is collected.
    
- Results are returned to LangGraph.
    

## Phase 4: Feature Development Workflow

Goal: Complete an end-to-end feature development cycle.

Implement:

- Requirement analysis
    
- Architecture workflow
    
- Design approval
    
- Development
    
- Code review
    
- Test execution
    
- Bug fixing
    
- Regression testing
    
- Final report
    

Acceptance criteria:

A single feature requirement can go through the entire workflow with minimal manual intervention.

## Phase 5: Scenario Testing Workflow

Goal: Support multiple test scenarios in parallel.

Implement:

- Scenario parser
    
- Scenario grouping
    
- Dependency analysis
    
- Parallel test workers
    
- Failure classification
    
- Bug investigation
    
- Bug fix routing
    
- Regression testing
    
- Test report generation
    

Acceptance criteria:

- Multiple independent scenarios execute concurrently.
    
- Test results are persisted.
    
- Failures are classified.
    
- Confirmed bugs can be routed to Bug Fix Agents.
    
- Regression results are included in the final report.
    

## Phase 6: UI and Observability

Goal: Make the system easy to operate and debug.

Implement:

- Streamlit chat interface
    
- Workflow dashboard
    
- Agent status view
    
- Artifact viewer
    
- Approval interface
    
- Execution logs
    
- Cost and token tracking
    

Later, consider replacing Streamlit with React if the UI becomes more complex.

## Phase 7: Reliability and Production Readiness

Implement:

- Retry policies
    
- Checkpoint recovery
    
- Timeout handling
    
- Cancellation
    
- Idempotency
    
- Concurrency limits
    
- Artifact versioning
    
- Agent evaluation
    
- Security hardening
    
- Cost control
    
- Monitoring
    

---

# 12. Learning Roadmap

I want to learn the underlying technologies while building the system.

The learning process should be project-driven rather than purely theoretical.

## 12.1 LangGraph

Priority: Very High

Learn:

1. StateGraph
    
2. Nodes and Edges
    
3. Conditional Edges
    
4. Parallel Execution
    
5. State Management
    
6. Checkpointing
    
7. Persistence
    
8. Human-in-the-loop
    
9. Subgraphs
    
10. Multi-agent orchestration
    

Questions I should be able to answer:

- How does LangGraph maintain workflow state?
    
- How do I execute multiple workers in parallel?
    
- How do I route a task based on its result?
    
- How do I retry a failed task?
    
- How do I resume a workflow after interruption?
    
- How do I wait for human approval?
    
- How do I build a supervisor/worker architecture?
    

Practical exercise:

Build a workflow with three parallel agents and a result aggregation node.

## 12.2 Codex SDK and Codex Subagents

Priority: Very High

Learn:

1. Codex SDK architecture
    
2. Thread/session lifecycle
    
3. Starting and continuing tasks
    
4. Streaming execution events
    
5. Approval handling
    
6. Tool permissions
    
7. Working directory configuration
    
8. Subagent delegation
    
9. Execution interruption and recovery
    

Questions:

- How does a Codex thread differ from an Agent?
    
- How do I create and manage multiple coding sessions?
    
- How can LangGraph call Codex?
    
- How do I collect code changes and execution results?
    
- How do Codex Subagents work?
    
- How are sandbox and approval policies enforced?
    

Practical exercise:

Create a Python or TypeScript wrapper that starts a Codex coding task, waits for completion, and returns a structured result.

Use the official current Codex SDK documentation when implementing this integration.

## 12.3 Multi-Agent Design Patterns

Priority: High

Learn:

- Supervisor / Worker
    
- Hierarchical Agents
    
- Parallel Agents
    
- Sequential Pipelines
    
- Reflection and Review
    
- Debate and Arbitration
    
- Human-in-the-loop
    
- Dynamic Task Routing
    

Practical exercise:

Build an Architect Council with three independent architects, cross-review, and final arbitration.

## 12.4 CrewAI

Priority: Medium

Learn:

1. Agent
    
2. Task
    
3. Crew
    
4. Process
    
5. Hierarchical Process
    
6. Delegation
    
7. Tool integration
    
8. Structured outputs
    

Practical exercise:

Build the same Architect Council with CrewAI.

Compare it with LangGraph in terms of:

- Control flow
    
- State management
    
- Parallel execution
    
- Debugging
    
- Retry handling
    
- Extensibility
    

The objective is to understand the trade-offs, not necessarily to use both frameworks in production.

## 12.5 Engineering Infrastructure

Priority: High

Learn:

- Git branching
    
- Git Worktree
    
- Docker
    
- Python async programming
    
- FastAPI
    
- pytest
    
- Playwright
    
- Structured logging
    
- SQLite / PostgreSQL
    

These technologies make the system reliable and reproducible.

---

# 13. Repository Structure

Start with a modular monolith.

Suggested structure:

```
ai-engineering-organization/
│
├── app/
│   ├── main.py
│   └── dashboard.py
│
├── agents/
│   ├── manager.py
│   ├── registry.py
│   │
│   ├── architects/
│   │   ├── system_architect.py
│   │   ├── backend_architect.py
│   │   └── security_architect.py
│   │
│   ├── developers/
│   │   ├── dev_agent.py
│   │   └── reviewer.py
│   │
│   └── testers/
│       ├── test_planner.py
│       ├── test_agent.py
│       └── bug_fix_agent.py
│
├── workflows/
│   ├── feature_workflow.py
│   ├── scenario_workflow.py
│   ├── architecture_workflow.py
│   └── common.py
│
├── runtimes/
│   ├── base.py
│   ├── llm_runtime.py
│   ├── codex_runtime.py
│   └── test_runner.py
│
├── infrastructure/
│   ├── workspace_manager.py
│   ├── artifact_store.py
│   ├── state_store.py
│   └── logging.py
│
├── schemas/
│   ├── task.py
│   ├── agent.py
│   ├── agent_result.py
│   ├── workflow_state.py
│   └── design.py
│
├── prompts/
│   ├── manager.md
│   ├── system_architect.md
│   ├── backend_architect.md
│   ├── security_architect.md
│   ├── dev_agent.md
│   ├── test_agent.md
│   ├── bug_fix_agent.md
│   └── reviewer.md
│
├── artifacts/
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── examples/
│   ├── feature_requirement.md
│   └── test_scenarios.md
│
├── pyproject.toml
└── README.md
```

The structure can be adjusted during implementation. Avoid creating unnecessary abstractions before they are needed.

---

# 14. MVP Scope: What to Build First

The initial MVP should be deliberately small.

## 14.1 MVP Agent Organization

Start with:

|Role|Implementation|
|---|---|
|Engineering Manager|LangGraph + LLM|
|System Architect|LLM Agent|
|Backend Architect|LLM Agent|
|Security Architect|LLM Agent|
|Dev Agent|Codex SDK|
|Test Agent|Test Runner / Codex SDK|
|Reviewer|LLM Agent|

Bug Fix Agent can initially reuse the Dev Agent runtime with a different role prompt and task configuration.

Do not build a separate infrastructure for every role.

## 14.2 MVP Workflow

The first complete demonstration should be:

```
User submits a small feature requirement
                 |
                 v
       Engineering Manager
                 |
                 v
        Three Architect Agents
                 |
                 v
          Cross Review
                 |
                 v
         Design Decision
                 |
                 v
        Human Approval
                 |
                 v
             Dev Agent
                 |
                 v
          Code Review
                 |
                 v
            Test Agent
                 |
                 v
        Bug Fix if Necessary
                 |
                 v
          Final Report
```

## 14.3 What NOT to Build Initially

Avoid these in the first version:

- Dynamic agent creation
    
- Complex agent-to-agent free-form conversations
    
- Kubernetes
    
- Distributed execution infrastructure
    
- Multiple databases
    
- Complex frontend
    
- Automatic production deployment
    
- Unlimited recursive task delegation
    
- Multiple competing orchestration frameworks
    
- Autonomous modifications to the main branch
    

First prove the core workflow.

---

# 15. Important Engineering Design Decisions

These decisions should guide implementation.

## 15.1 Workflow State Is the Source of Truth

Do not use chat history as the primary state store.

The workflow state should track:

- Current stage
    
- Task dependencies
    
- Execution status
    
- Approval status
    
- Retry count
    
- Artifact references
    
- Failure reasons
    

Chat history is useful context, but not a substitute for workflow state.

## 15.2 Use Structured Outputs

All agents should return structured outputs.

For example:

```
TaskResult:
  status
  summary
  findings
  artifacts
  risks
  next_actions
  requires_approval
```

Use Pydantic models to validate outputs.

## 15.3 Make Every Execution Traceable

For each workflow, record:

- Workflow ID
    
- Task ID
    
- Agent ID
    
- Runtime
    
- Model
    
- Start time
    
- End time
    
- Execution status
    
- Input artifacts
    
- Output artifacts
    
- Error details
    
- Token usage and cost, when available
    

## 15.4 Bounded Retry

Every retry loop must have a maximum.

Example:

```
Maximum implementation retries: 2
Maximum regression retries: 2
Maximum architecture discussion rounds: 2
```

If the system cannot converge, stop and request human intervention.

## 15.5 Independent Verification

An agent should not be the sole judge of its own success.

Examples:

- Dev Agent reports implementation completed.
    
- Build and tests independently verify the result.
    
- Reviewer checks the code.
    
- Manager checks required artifacts and acceptance criteria.
    

The system should distinguish between an agent claiming success and objectively verified success.

---

# 16. Definition of Done

The project should be considered successful when the following capabilities work reliably.

## Functional Requirements

- User can submit a feature requirement.
    
- User can submit multiple test scenarios.
    
- Manager can classify workflow types.
    
- Manager can create task dependencies.
    
- Independent agents can execute in parallel.
    
- Architects can independently analyze and cross-review.
    
- Manager can produce a final design decision.
    
- Codex can execute implementation tasks.
    
- Coding tasks use isolated workspaces.
    
- Automated tests can be executed.
    
- Test failures can be classified.
    
- Confirmed bugs can be routed to Bug Fix Agents.
    
- Regression tests can be executed.
    
- Results and artifacts are persisted.
    
- Manager can generate a final engineering report.
    

## Reliability Requirements

- Workflow state survives process restart.
    
- Failed tasks can be retried within configured limits.
    
- Parallel tasks do not accidentally overwrite each other's files.
    
- Failed agents do not silently disappear.
    
- All execution steps are traceable.
    
- Human approval is enforced for sensitive operations.
    
- The workflow can stop safely when it cannot make progress.
    

## User Experience Requirements

- User communicates primarily with Engineering Manager.
    
- User does not need to manually manage individual coding sessions.
    
- User can inspect agent progress.
    
- User can inspect design decisions and code changes.
    
- User can approve or reject important decisions.
    
- User receives a consolidated final report.
    

---

# 17. Final Recommendation

The recommended implementation strategy is:

**LangGraph + Codex SDK + Git Worktree + Docker + Streamlit.**

The responsibilities are:

```
LangGraph
    Controls the engineering organization.

LLM Agents
    Analyze requirements, design systems, review proposals.

Codex SDK
    Performs actual coding and debugging.

Git Worktree
    Isolates concurrent development tasks.

Docker / Test Runner
    Provides reproducible test execution.

Artifact Store
    Preserves engineering knowledge and deliverables.

Streamlit
    Provides a simple user interface.
```

The most important thing is to build a reliable workflow before building a sophisticated agent organization.

Start with a small Architect Council, one Dev Agent, and one Test Agent.

Once that works, add parallel scenario testing, bug-fix loops, richer observability, and more specialized roles.

The long-term goal is not simply to create many agents.

It is to create a controlled, traceable, and verifiable engineering system where multiple specialized agents can collaborate to deliver real software changes with minimal human coordination.
