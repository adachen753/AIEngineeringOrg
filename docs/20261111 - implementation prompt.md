---
Created: 2026-11-11
Tags:
  - AI
  - AgentManager
Status: Ready
---

# AI Engineering Manager — MVP Implementation Prompt

以下正文可直接作为 Codex 的实现提示词。请在专用应用项目目录启动 Codex 后发送，不要在笔记目录或演示材料仓库开发应用。

---

你是本项目的实现 agent。请实现一个可运行、可追溯、经过真实验证的 AI Engineering Manager MVP，而不是仅输出设计或生成模拟演示。

## 1. 输入文档与优先级

先阅读：

- Q:/AIManager/docs/20261111 - requirement.md
- Q:/AIManager/docs/20261111 - high level design.md

本提示规定 MVP 范围，最新 requirement.md 规定产品约束，high level design.md 提供架构参考。冲突优先级：本提示的明确 MVP 范围 > 最新 requirement.md > high level design.md。明确标注被推迟的完整产品需求，不声称 MVP 已满足完整产品验收。

先检查当前仓库、工作树状态及适用的 AGENTS.md。在当前专用应用工作目录实现；不要修改输入文档。若当前目录只有笔记、演示材料或并非合适的应用目录，先询问项目位置，不擅自选址。

## 2. MVP 目标与非目标

用户通过一个 Manager 入口提交小 feature，系统完成：

需求提交与澄清 → Manager 形成验收条件和计划 → Dev 实现功能及单元测试 → Test 独立设计验证、按需新增测试 → 后台形成固定验证提交并执行测试 → 有限修复复测 → Manager 汇总证据。

UI 可以看到 Dev/Test 的实际操作和结果。CLI 与 UI 访问同一个后台和同一份持久化记录。

第一版只支持一个小型 Python Git 项目、单个活动 workflow、串行执行的 Manager/Dev/Test。模块接口需允许后续增加角色、项目测试执行器及并行度，但不要预先实现复杂框架。

暂不实现：多 architect、独立 Reviewer、并行 scenario、跨任务 bug 去重、自动合并主分支、自动部署、GraphConnectors/Service Fabric E2E、Docker、CrewAI、ACP/A2A、分布式队列和无限递归委派。独立 Reviewer 是后续能力；MVP 报告必须明确说明缺少独立代码评审。

## 3. 技术选择与 Codex 接入验证

- Python 后台，FastAPI 提供 API，LangGraph 管理阶段与路由。
- SQLite 保存状态、消息、执行记录；本地文件保存长日志和产物。
- Streamlit UI；Python CLI 调用同一 API。
- Node/TypeScript Codex 适配层，优先验证官方 Codex SDK。
- 若 SDK 的事件或控制能力无法满足最低需求，评估官方 App-server，记录选择理由；不强制同时实现两套接入。
- Git worktree 隔离代码写入，项目测试执行器运行实际命令。
- Pydantic 校验 agent 结果和调度动作。

实现前查看当前官方文档，验证可用包、版本、Windows 兼容性、认证、thread 创建/继续/恢复、事件流、权限、超时与取消能力。不要假设存在未验证的 Python SDK 接口。

官方参考：
- https://developers.openai.com/codex/sdk
- https://developers.openai.com/codex/app-server

首先完成一个最小真实接入实验：创建 thread、执行请求、保存 ID、继续原 thread、重新加载适配层后恢复 thread、取得真实结果与可获取的执行事件。认证缺失或 Codex 不可用时明确报告阻塞，保留证据；不得以 mock 替代真实验收。Mock 仅用于隔离单元测试。

## 4. Thread 策略与通信

Thread 是独立的多轮执行对话上下文，不是角色、workflow 或测试结果。追加请求不是新建 thread。

- 每个 workflow 的 Manager 使用一个持续 thread，支持多轮需求补充。
- Dev 每个任务使用独立 thread，同一功能修复继续原 Dev thread。
- Test 每个任务使用独立 thread，用于验证规划、测试补充和失败分析。
- 实际测试由后台执行器运行，不以 Test 的口头报告代替命令证据。
- 预留 Architect/Reviewer 角色配置，不实现其完整流程。
- 不依赖内部 subagent；允许你在实现本项目时分派文件写集互不重叠的实现 subagent。

后台集中转发结构化消息，不假设 threads 自动互通。消息包含 message ID、workflow/task/attempt ID、发送方、接收方、类型、代码版本、内容或产物引用、投递状态。投递可能出现不确定结果，不能声称严格 exactly-once；保存幂等键和执行证据，对不确定投递停止自动重发并标记需处理。

Manager 提出结构化计划和动作，后台做 schema、依赖、权限与状态校验后执行。Agent 文本不得绕过授权或直接控制任意调度。

## 5. Feature 与新增测试闭环

1. 输入目标仓库、base commit、feature 描述、允许修改范围、验收条件、已授权命令、超时及测试配置。
2. Manager 补充明确、可验证的验收条件；存在实施关键歧义时持久化等待用户回答，而不是猜测后修改。
3. Dev 在独立 worktree 实现功能及相关单元测试，保存代码 diff、实现提交和结果。
4. Test 独立检查验收覆盖、规划验证；允许在自己的 worktree 新增或修正测试，只修改授权的测试范围，不修改产品代码或正在被测的目录。
5. Test worktree 从明确的 Dev 提交创建。若新增测试，形成包含功能和测试的后续验证提交；没有测试修改时使用 Dev 提交。不需合并用户主分支。
6. 后台在独立固定提交的验证 worktree 运行新增测试与相关回归，执行期间禁止写入被测目录；记录开始及结束时的 HEAD 与工作树状态以检查污染。
7. 失败分类：产品 bug、测试问题、数据问题、环境问题、偶发失败、未知。产品修改必须基于证据和授权，不能仅因测试失败触发。
8. 产品 bug 回原 Dev thread；测试问题回 Test；环境或未知原因明确阻塞。修复轮次最多一次，所有重试均有上限和新 attempt ID。
9. 修复时将已接受测试提交纳入新的明确候选版本，保留测试，不盲目恢复旧 Dev HEAD。出现冲突则标记阻塞，保留双方提交和日志，不自动删除或覆盖文件。
10. 对新版本重新验证。报告提供“验收条件 → 测试/证据 → 实际结果”的对应关系。

不得用减少测试、跳过失败测试、放宽断言或未经批准缩小验收范围制造成功。新增 feature 测试必须能证明行为；适用时在 base commit 上验证新测试失败、实现后通过，并区分功能性失败与收集/环境错误。

## 6. 状态、恢复与控制

至少保存 workflow、task、attempt、thread 映射、依赖、阶段、状态、重试次数、base/实现/测试/验证提交、worktree 路径、消息、产物、审批和时间。

使用明确状态，例如 queued、running、awaiting_input、awaiting_approval、succeeded、failed、blocked、cancelled、interrupted；规定合法状态转换。LangGraph 检查点与 SQLite 业务状态需要有清晰的一致性策略和恢复测试。

- 后台独立于 UI/CLI 运行，关闭客户端不停止任务。
- 重启恢复已完成阶段及产物，不重复创建 worktree、提交、投递或运行已完成测试。
- 对仍在运行或结果未知的执行先检查 thread、进程、提交及日志；无法确认安全恢复则标记 interrupted，不盲目重跑，也不自动标为成功。
- 支持取消、显式重试和有限超时。取消应阻止后续调度，并按已验证能力终止本系统启动的相关执行；不能确认停止时标记不确定状态，禁止并发重试。
- 不杀死用户无关的 Codex、Python、Node 或测试进程。
- 客户端重复提交、刷新与网络重试不得创建重复 workflow，使用提交幂等键。

## 7. UI、CLI 与可观测性

Streamlit 提供：
- Manager 对话和任务提交/需求补充。
- workflow 列表、当前阶段、角色任务状态、失败及阻塞原因。
- 按任务查看 thread ID、可获取的对话与执行事件、命令、diff、提交、日志、测试证据和报告。
- 取消、显式重试、授权事项处理。
- 按 workflow ID 恢复展示，状态来自后台持久化记录，不来自聊天推测。

Thread 查看入口可在本应用展示保存的内容，不假设 SDK thread 自动出现在 Codex 桌面侧栏。只展示公开结果、实际操作和可审计事件，不要求模型内部思考过程。日志隐藏凭据，并限制产物访问路径。

CLI 支持 submit、status、events、artifacts、cancel、retry，以及补充需求/处理审批的必要入口；准确命令形式由实现确定并写入 README。UI 与 CLI 操作同一 workflow。

提供 Windows PowerShell 下可运行的启动入口与停止说明：先启动后台和适配层，再按需打开 UI。客户端不得自行运行工作流；后台默认仅绑定 localhost。不要在完成前虚构启动命令。

## 8. 授权与文件保护

绝不修改、删除、移动、覆盖或用作临时目录：
- Q:\GraphConnectors\cwzClaude\
- Q:\GraphConnectors\sources\dev\cwzClaude-SQL\

不要对任何 cwz* 用户工作目录执行清理、stash、reset 或移动。不要 stash/clean 用户的未提交内容。项目实现不修改输入笔记。

本提示授权在独立验收测试仓库与本系统拥有的 worktree 创建任务分支和功能/测试提交，以形成真实验证版本；不授权提交本应用仓库改动、push、合并用户主分支或自动部署。真实目标仓库的分支/提交操作需遵守该 workflow 的明确授权。

采用显式仓库及命令授权范围。执行器使用参数数组而非拼接 shell 字符串；角色权限落实到已验证的 Codex 配置与后台校验，不仅依赖提示词。凭据不写入仓库、日志或产物。清理仅限系统拥有且路径核验通过的资源，默认保留失败证据。

## 9. 实施步骤

先给出简短计划和目录结构，然后按阶段直接实现，不停留在建议：
1. 仓库检查、依赖与真实 Codex 接入实验。
2. 数据模型、SQLite 持久化、适配层和 LangGraph 工作流。
3. worktree 与固定版本测试执行器，打通 feature/新增测试/修复闭环。
4. FastAPI、CLI、Streamlit 与执行记录查看。
5. 单元测试、恢复控制测试、真实验收和文档。

合理小决定自行推进；涉及凭据、项目位置、实际外部环境授权或不可逆操作时明确询问。不要实现无关功能、引入不必要的依赖或修复无关问题。

## 10. 验收与交付

使用独立、无敏感内容的小型 Python Git 测试仓库，包含已有测试。通过真实 Codex 工作流实现一个带正常及边界行为的小 feature，新增对应测试，并取得实际通过结果。

验收至少覆盖：
- UI 提交一个真实任务，Manager/Dev/Test thread 可追溯，代码修改和新增测试真实存在。
- 固定验证提交上的新增测试与相关回归实际执行并通过，报告包含证据映射及未验证项。
- 失败分类与一次修复路由有针对性的测试；不能可靠制造真实失败时区分自动化测试证据与真实运行证据，不伪造。
- UI 刷新/关闭、CLI 查询同一 workflow，不影响后台任务。
- 后台在阶段间重启可恢复；执行中重启在无法确认安全时正确 interrupted，不产生重复副作用。
- 取消、超时、显式重试、重复提交和无效 agent 输出有自动化测试。
- 权限、受保护路径、日志脱敏和验证目录污染检查有测试。

交付：
- 可运行代码、锁定或可复现依赖、无密钥配置示例。
- README：安装、认证、配置、后台/UI/CLI 准确命令、停止、恢复、限制和排错。
- 简短架构说明及真实接入验证记录。
- 真实验收的 workflow ID、thread ID、提交、diff、测试命令/退出码、日志和最终报告。
- 最终列出已实现、已验证、未验证、未实现和外部阻塞项。

只有实际证据满足本 MVP 验收条件才报告完成；测试通过不等于完整产品已完成，也不等于具备独立 Reviewer 或 Service Fabric E2E 能力。
