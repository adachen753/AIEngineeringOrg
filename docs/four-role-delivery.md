# 四角色 Feature 交付

## 实现范围与当前阻塞

新增独立 delivery 模式：Manager → 单个 Architect → Dev → Build → Tester 规划 → 本地部署 → Computer-use E2E → Tester 归因 → Manager 报告。编译/分析器错误与有证据的 E2E 产品 bug 可返回 Dev；SDK、证书、权限、依赖、未知错误及部署失败停止，不盲目修复。无 Reviewer 阶段，也不实现 Reviewer→Dev 通信。

默认 max_fix_rounds=5，可配置 0–20；表示首次实现之外，整个 workflow 共用的最多五次源码修复机会，Build 和 E2E 共用预算。total_timeout_seconds 默认 7200，可配置 60–86400；从首次调度开始计入用户澄清等待，重试不重置。到时取消已知 Agent/构建/桌面任务，无法确认终止则保留 interrupted，不自动重放。旧 legacy pytest 流程保留兼容；新模式不写、不运行 UT，后端也拒绝常见 UT 路径和文件名的改动。

**代码链路已具备不等于本机真实 GraphConnectors 验收通过。** 现有 Codex adapter 仍因 NETWORK_SANDBOX_NOT_ENFORCED 拒绝真实派发；没有移除或绕过此保护。实际 SDK 沙箱、MSBuild 目标、SF 配方、专用资源、Computer-use 场景驱动与 SQL 预期仍须验证。缺少任何项时不能报告成功。

## 一次配置，后续只交 Feature

1. 将 templates/projects.example.json 复制到目标仓库之外的运营者配置目录，例如 C:/AIManagerOperator/projects.json。填写并验证 repo、源码范围、固定 MSBuild 绝对路径与参数、部署包目录、资源/配方/场景 ID、验收基线及检查 ID；模板默认 disabled。
2. 将 templates/desktop-bridge.example.json 同样复制并填写。artifact_root 必须对应后台数据目录的 worktrees；data_dir 和配置须在其外部。配置固定 deploy_command 与 e2e_command，脚本必须由运营者维护，不能从 Feature 或 Agent 输出生成任意命令。
3. 两个进程使用同一个至少 32 字符随机 AIM_DESKTOP_BRIDGE_TOKEN。不要写入任务、仓库、Markdown、截图或源码。Agent SDK、构建和桌面驱动子进程会剔除此环境变量；这不替代 OS 隔离。
4. 先验证权限与真实场景，再将配置 enabled 改为 true。仅存在声明或标志不是安全验证证据。

启动前设置 AIM_PROJECT_CONFIG、AIM_BRIDGE_CONFIG、AIM_DESKTOP_BRIDGE_TOKEN，然后运行 scripts/start.ps1 -UI -DesktopBridge（Node 不在 PATH 时仍需传 -Node）。本次包含 Python/Node 代码变更，正在运行的旧服务不会自动升级。不要覆盖现有启动记录，按 scripts/stop.ps1 正常停机后再启动。

前端新增“四角色自动交付”表单。项目 ID 固定后，只需填写 Feature，并明确批准源码/构建和专用本地部署/E2E 两种授权。JSON/Markdown 可使用 templates/feature-delivery.json；Markdown 仍要求唯一 json 代码块。文件中的 authorized/deploy_authorized 不会自动生效。

CLI：aim submit FEATURE.json --approved --deploy-approved。后台入口 POST /features，字段为 project、feature、idempotency_key、authorized、deploy_authorized、max_fix_rounds、total_timeout_seconds。相同幂等键恢复原提交和项目快照，即使目标 HEAD 后来变化；不同输入不能复用同一键。来源路径、base commit 和固定命令不能由 Agent 自行扩权。

## 版本与反馈闭环

- 每任务 codex/feature/<workflow-id>，后台提交 Dev 变更。单个 Architect 独立只读执行，综合安全、兼容、后端、部署、失败恢复和回滚，不声称有第二位独立设计评审。
- 构建在候选固定提交的独立 worktree 上执行。禁止 tracked source 被构建修改，未忽略的生成文件只能在配置输出范围；生成包按文件 SHA-256 建 manifest。worktree 本身不是机器级安全沙箱，构建项目可执行代码，必须在被批准且隔离的构建环境中运行。
- 本模式的 integration 分支指向同一已构建候选提交，不做额外跨 feature 合并。部署桥重新核验文件大小/哈希，防止包被替换。每次修复重新 build、部署和 E2E；旧证据不得复用为新版本的成功。
- Build/Test→Dev 的 issue 含来源、候选 commit、错误/复现、实际执行证据、轮次与时间；完整分析传给 Dev，任务消息与产物持久化。达到上限仍保存最后问题。
- 最终 report.json 包含分支、commit、构建/部署/E2E、逐项验收映射、修复次数，以及 UT=NOT_WRITTEN_NOT_RUN、independent_review=NOT_PERFORMED。禁止自动 push、merge main、生产部署或集群清理。

## Desktop bridge 与驱动协议

桥服务位于 ai_manager/desktop_bridge.py，可独立通过 uvicorn ai_manager.desktop_bridge:app --host 127.0.0.1 --port 8767 --workers 1 启动。HTTP 需要 Bearer token，拒绝浏览器 Origin；单桌面单任务，配置中只允许已登记 resource/recipe/scenario/checks。持久化资源所有权，失败或不确定时保留，不自动清理共享环境。重启后 running 标为 interrupted，禁止自动重放；需人工检查实际部署/子进程并对账。

桥只负责认证、调度、资源串行、进程停止、版本/包校验及证据检查，**不内置可直接用于当前 GraphConnectors 的 SF 发布脚本或 SSMS 场景**。必须配置已审核的实际驱动；不能把当前 Codex 桌面的 computer-use skill 当成 AIManager 天然可调用的服务。

固定驱动以 argv 启动，不使用 shell 字符串插值。输入路径在 AIM_BRIDGE_REQUEST_FILE，输出路径在 AIM_BRIDGE_RESULT_FILE，证据目录在 AIM_BRIDGE_EVIDENCE_DIR。请求含 stage、resource、recipe、scenario、feature、Architect design、Tester plan、Manager acceptance、固定 commit、构建 cwd 与 artifact manifest。驱动不得将 feature/设计文字解释为 shell/SQL 权限；只操作预先批准的资源。

deploy 驱动需执行经过批准的专用 application 部署，并输出 healthy=true 与真实 evidence；非零退出、缺少证据或不健康均不通过。不得直接使用可能 reset SF/停止共享 mock 的 stock cleanup。

e2e 驱动需真实使用 Computer-use，输出 driver=computer-use，以及每个批准 check ID 的 passed 布尔值和 screenshot/query evidence；acceptance_mapping 对每条 Manager 验收给 criterion 与非空 check_ids。允许观察失败，但不能省略检查或用“表存在”代替业务断言；实际表名、schema、预期字段/行数/更新时间先核实。驱动结果是受信执行器提供的证据，不是由返回 driver 字符串就证明真的操作了桌面，必须审核驱动和留存原始证据。

## 验证

acceptance/four_role_delivery_smoke.py 是明确标记 SYNTHETIC 的集成脚本：真实临时 Git/worktree、后台持久化、构建子进程、认证 HTTP 桥与驱动子进程；Agent、编译错误及 UI/SQL 观察为受控替身。验证 Build→Dev、Tester→Dev、默认五轮与零轮上限，不属于新增 UT，也不代表真实 SDK/MSBuild/SF/Computer-use/SQL 已通过。
