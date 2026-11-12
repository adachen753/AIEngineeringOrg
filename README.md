# AIEngineeringOrg

## 需求与设计文档

- [需求说明](docs/20261111%20-%20requirement.md)
- [高层设计](docs/20261111%20-%20high%20level%20design.md)
- [实施提示词](docs/20261111%20-%20implementation%20prompt.md)
- [GraphConnectors 知识包](docs/20261111%20-%20GraphConnectors%20knowledge%20pack.md)

**当前未通过完整 MVP 验收。** 后台、UI/CLI、持久化和隔离验证执行器已实现；真实 SDK 新建/续聊/重启恢复实验已成功，但 Windows 命令 sandbox 在请求禁用网络时仍能连接 localhost。为避免角色间接调用后台绕过授权，生产角色调度保持 fail-closed，不使用 mock 或宽权限冒充完成。详见 docs/verification-status.md。

本地 Python Git 小项目的串行 Manager 计划 → feature 分支上的 Dev 实现 → Test 验收及固定提交测试 → 独立 Reviewer → Manager 接纳 → integration 分支及集成测试 → 报告入口。每次提交表示一个 feature；暂不支持一次提交多个 feature 或跨任务自动合并。FastAPI 后台拥有唯一工作流执行器和 Git 写入权限；Streamlit 和 CLI 只访问同一 API、SQLite 状态和产物。关闭 UI 不会停止后台。

## 新增配置与交付

- 默认角色配置：`ai_manager/roles/config.json`，关联四角色各自的 Soul/Goal Markdown。可通过 `AIM_ROLE_CONFIG` 指定自定义配置；新任务保存配置快照。详见 `docs/role-configuration.md`。
- 任务文件模板：`templates/submission.json` 与 `templates/submission.md`。UI 支持上传文件，CLI 支持文件提交；格式详见 `docs/submission-format.md`。文件内容不能代替显式执行授权。
- 后台拥有 feature 分支与 `codex/integration/<任务ID>`，Reviewer 只读审查；交付记录包含分支、commit、审查及集成测试证据。不自动合入 main，不自动推送或创建远程 PR。
- 新流程仍受适配层安全预检阻断。代码路径与本地测试不代表真实 SDK 全流程已验收；之前的 `docs/evidence` 是历史实验，不是新增流程的运行证据。

## 安装与配置（PowerShell，项目根目录）

日常操作见 [启动、停止与重启说明](docs/start-stop.md)，包含本机 Node 路径、数据目录、日志与常见问题。

需要 Python 3.12+、Node.js 24+、Git，以及适配层要求的有效 Codex 认证。不要在命令、提交文件或日志里放密钥。认证方式、SDK 接入与真实恢复证据以适配层的实际验证记录为准；本 README 不声称已经完成真实接入验收。
无密钥配置示例见 .env.example（参考用，不自动加载；PowerShell 设置环境变量或用启动脚本参数）。真实只读 SDK 接入和恢复已经验证，完整角色工作流仍然阻塞。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
```

适配层使用 Node.js 24 直接执行 TypeScript 服务入口；先安装其依赖。启动脚本默认查找 adapter/src/server.ts；入口不同时使用 -AdapterEntry 指定。服务文件缺失或 /health 不可用时脚本会失败，不会用模拟服务替代。

```powershell
Push-Location adapter
npm install
Pop-Location
```

```powershell
.\scripts\start.ps1 -UI
.\scripts\stop.ps1
```

默认 API http://127.0.0.1:8765、适配层 http://127.0.0.1:8766、UI http://127.0.0.1:8501。默认仅绑定本机。脚本支持 -Python、-Node、-AdapterEntry、-ApiPort、-AdapterPort、-UiPort、-DataDir。适配层必须读取 HOST / PORT；若接口不匹配，应调整适配层启动配置而非开放公网。

后台配置：AIM_DATA_DIR（默认 .aim-data）、AIM_ADAPTER_URL。客户端配置：AIM_API_URL；CLI 的 --api-url 必须放在子命令前。数据目录必须稳定、专用，不能放入受保护树。不要启动多个后台执行器、使用 uvicorn reload 或多 worker。

启动脚本将 AIM_ADAPTER_DATA 指向数据目录下的 adapter 子目录。适配层可使用 AIM_CODEX_EXE 指定已安装的 Codex 可执行文件。适配层崩溃或强制停止后可能留下独占锁；须人工核查原进程已退出后按适配层恢复说明处理，脚本不会自动删除锁或重放任务。

手动启动后台或 UI（适配层须另行启动）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn ai_manager.api:app --host 127.0.0.1 --port 8765 --workers 1
.\.venv\Scripts\python.exe -m streamlit run ai_manager/ui.py --server.address 127.0.0.1 --server.port 8501
```

## 提交与控制

UI 表单填写 repo、base commit、feature、允许修改范围、授权测试范围、验收条件、幂等键和超时。授权框默认未勾选：任务保存为 awaiting_approval；明确批准后才允许调度。超时为 10–3600 秒；当前后台仅允许固定 pytest 参数数组。授权范围用显式仓库相对路径，不是任意 shell 命令。

CLI 使用 UTF-8 JSON 提交文件。例如 submission.json（替换仓库和真实提交，不是已通过验收示例）：

```json
{
  "repo": "C:/temp/example-python-repo",
  "base_commit": "REPLACE_WITH_ACTUAL_COMMIT",
  "feature": "为已有函数增加明确的边界行为",
  "allowed_paths": ["example.py", "tests"],
  "test_paths": ["tests"],
  "acceptance": ["正常和边界行为有新增测试，相关回归通过"],
  "test_command": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
  "idempotency_key": "example-feature-001",
  "authorized": false,
  "timeout_seconds": 300
}
```

```powershell
.\.venv\Scripts\python.exe -m ai_manager.cli submit submission.json
.\.venv\Scripts\python.exe -m ai_manager.cli status
.\.venv\Scripts\python.exe -m ai_manager.cli status WORKFLOW_ID
.\.venv\Scripts\python.exe -m ai_manager.cli events WORKFLOW_ID
.\.venv\Scripts\python.exe -m ai_manager.cli artifacts WORKFLOW_ID
.\.venv\Scripts\python.exe -m ai_manager.cli input WORKFLOW_ID '补充需求'
.\.venv\Scripts\python.exe -m ai_manager.cli approve WORKFLOW_ID --approved
.\.venv\Scripts\python.exe -m ai_manager.cli retry WORKFLOW_ID
.\.venv\Scripts\python.exe -m ai_manager.cli cancel WORKFLOW_ID
```

网络失败后使用同一幂等键和相同提交内容查询/重试提交；新任务使用新键。客户端不自动重发写操作。批准发送 approved=true；补充需求发送 text。非法状态动作返回错误，不代表已经执行。取消只调用 Engine.cancel：确认停止与不确定结果的持久化由执行器负责。

UI 输入 Workflow ID 可恢复展示，详情包含实际保存的 threads、阶段、提交、原因；事件和产物提供对话、命令、diff、日志、报告等可审计信息。SDK thread 不保证出现在 Codex 桌面侧栏，不展示模型内部思考。产物下载仅接受已登记的单个文件名，拒绝目录穿越。

API：GET /health、/workflows、/workflows/{id}、/workflows/{id}/events、/workflows/{id}/artifacts、/workflows/{id}/artifacts/{name}；POST /workflows、/workflows/{id}/{input|approve|retry|cancel}。/health 仅检查后台 worker 存活，不证明 Codex 认证或功能验收成功。

## 停止、恢复与排错

先用 UI/CLI 取消活动任务并确认后台状态；再运行 stop.ps1。脚本核验自身记录的 PID、启动时间和可执行文件路径后，只终止这些进程及其派生子进程树，不按 Python/Node/Codex 名称批量终止。进程退出无法确认时保留记录。强制停止后台不等于工作流已经成功或安全完成；重启必须检查 interrupted 和恢复证据。

.aim-launch 保存启动进程记录和 stdout/stderr；.aim-data 保存业务状态和产物。停止不清理数据、日志、worktree 或用户仓库。重启使用原数据目录；执行中重启必须依据后台恢复策略检查 interrupted/不确定状态，禁止盲目重试。
.aim-launch 的停止脚本仅在核验已记录的 adapter PID 死亡且 .exclusive.lock 所有者一致后移除该自有进程锁，以允许后续安全重启；不会删除工作流证据或清理用户文件。直接强杀 standalone adapter 后，按 docs/codex-integration.md 先核验锁的 PID，再只处理其自有锁。

端口占用时脚本直接拒绝启动；启动失败查看 .aim-launch/*.err.log。连接失败先检查 /health 和环境变量。HTTP 409 常表示状态、授权、幂等键或范围冲突；422 表示提交 schema 不合法。已有进程记录时先运行 stop.ps1，不覆盖所有权记录。不向公网暴露这些无身份认证的本地管理接口；同机客户端和适配层均视为可信。

## 验证与限制

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

自动化测试、语法检查和脚本解析不等于真实 Codex/UI 功能验收。真实验收必须另外记录 workflow/thread ID、真实修改和新增测试、固定验证提交、命令与退出码、日志、报告及未验证项；此处没有伪造这些证据。

客户端实现的临时 smoke 检查已通过：10 项 CLI 路由/提交/故障检查（mock API）；FastAPI TestClient 验证未授权等待审批、幂等、Origin 拒绝、产物类型、取消与 worker 健康状态（idle worker，无 Codex 执行）；Streamlit AppTest 验证初始渲染、默认未授权、API 提交/详情，以及 input/approve/retry/cancel 路由（mock API）；PowerShell 两个脚本通过语法解析。未据此宣称真实服务启动、真实 Codex 工作流或完整 MVP 验收通过。

MVP 只面向小型 Python Git 项目、单活动任务和有限修复/重试。未实现完整产品的独立 Reviewer、多 architect、并行 scenario、跨任务去重、自动合并/部署、Service Fabric E2E 或分布式调度。取消和恢复能力受实际适配层与执行器实现约束，不能声称 exactly-once。禁止对受保护 cwzClaude / cwzClaude-SQL 树写入或对 cwz* 用户目录执行清理、stash、reset、移动。

Base commit 必须填写 40–64 位不可变十六进制 SHA，不接受 HEAD 或分支。现有测试文件的顶层 AST 节点必须保留：允许追加测试，不允许删改已接受断言；已有测试需要修正时保守阻塞，须人工检查，而不是自动放宽。

架构和真实验收状态参见 docs/architecture.md、docs/codex-integration.md、docs/verification-status.md。真实 UI/API 提交驱动（独立无敏感 Git 测试仓库，使用 Streamlit AppTest 而非手动浏览器）：启动后台及适配层后运行 .\.venv\Scripts\python.exe acceptance/run.py。此驱动不模拟 Codex，状态为 blocked 就是实际阻塞，不是通过验收。
# 四角色自动交付

新增 Manager → 单 Architect → Dev → Build/Fix → Tester 部署/E2E → Manager 交付模式，默认最多修复 5 轮，可配置；不编写或运行 UT，不启用独立 Reviewer。
配置与安全边界见 [四角色交付说明](docs/four-role-delivery.md)。真实 Agent 沙箱阻塞仍保留；真实 SF/Computer-use 驱动须先配置验证，不能视为已完成本机 E2E。
