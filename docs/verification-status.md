# 交付与验证状态 — 2026-11-11

本轮新增 feature/integration 分支、独立只读 Reviewer、角色配置快照和 JSON/Markdown 输入。以下既有运行记录属于扩展前历史证据，不证明新流程已真实运行；生产执行仍保持 fail-closed。

本轮测试：全量执行 269 通过、1 个过期 retry 夹具失败；夹具更新后稳定版 Engine/分支回归 58 通过，适配层 7 通过，角色配置的 9 个资源已验证包含在 wheel 中。这不等于一次全量 270 通过。详细结果见 `docs/evidence/feature-role-extension-tests.json`。本地工作流测试使用受控 Agent 输出和真实临时 Git/pytest；没有真实 SDK 自动交付成功记录。

**未完成完整 MVP 真实验收。生产角色执行有意保持 fail-closed。没有用 mock、降低断言或宽权限冒充真实成功。**

## 已实现

- 独立 src Git 仓库（按提示不提交本应用）；Python FastAPI 后台、LangGraph 单阶段串行路由、SQLite WAL 业务检查点、结构化任务/attempt/thread/消息/审批/产物。
- TypeScript 官方 Codex SDK 适配服务：幂等投递、线程绑定、事件过滤、持久化、取消、超时与未知结果阻断。
- Manager 持续 thread、Dev/Test 独立 thread 与修复续聊接口；需求澄清、批准、一次显式重试和一次证据分类修复路由。
- 隔离 worktree、固定候选提交、真实可信 pytest bootstrap；采集 node IDs 和每个测试结果，验收映射必须指向实际通过的测试，拒绝跳过、污染及收集配置修改。
- CLI 与 Streamlit 只调用同一后台；Windows 隐藏进程启动脚本和经过身份核验的自有进程树停止/锁协调。
- Python 直接依赖和完整 requirements.lock、SDK npm 完整性锁、无密钥配置示例、架构与接入记录。

## 已验证

- Python 广泛测试：192 passed，exit 0，370.01 秒；最后六项新增测试之后，最新核心 Engine/Git/审查回归：72 passed，exit 0，228.12 秒。当前总收集 198 项；这是广泛测试加最新变更复验，不声称单次全量 198 执行。另一次强化 skip 绕过检查：5 passed，exit 0。
- SDK/适配层：7 passed，exit 0。模拟 engine 只用于明确标注的单元控制测试；实际 localhost HTTP 测试不模拟传输。
- 实际只读 SDK 新建、同实例续聊、新 Node 进程恢复同一 thread：01a1c97f-5798-7bf2-b471-d2f391d0e084。真实 no-tool AbortController 取消也有记录；不等于任意命令子进程取消已验证。
- 实际 Test 窄目录和 Dev 两目录权限实验：授权目录可写，产品/仓库根/.git/其他兄弟目录写入被 EPERM 拒绝。
- 实际启动 adapter 8876、backend 8875、UI 8851，健康检查通过；停止后所有端口消失；修复自有遗留锁处理后，同一数据再次启动通过。
- Streamlit AppTest 的真实表单调用真实 HTTP 后台，CLI 查询同一 workflow，重启后记录一致，重复同幂等键 HTTP 提交不新增事件。不是手动浏览器验收；工作流实际阻塞于权限 preflight。
- 自动化覆盖：分类与一次修复、重试/取消/超时、schema、审批、幂等、执行中恢复/未知状态、污染、保护路径及 Git 元数据路径、凭据脱敏、测试删减/跳过绕过、可信 runner 防本地 pytest.py 替换。

## 真实验收尝试与阻塞

Workflow：d88f143b-ad52-491a-8075-8de4f8db4a81。
独立无敏感 Git fixture base：5ccd8376b011c4d64c658271ef07c3f39cd8c864。
Feature：clamp(value, lower, upper)，正常、边界和非法区间行为。
实际状态 blocked，plan 阶段在任何角色投递/worktree 副作用前停止；Manager/Dev/Test thread、实现/验证提交、feature diff、绿色回归报告均不存在，不能声称功能交付。

**具体运行时阻塞：**在 networkAccessEnabled:false 和 network_access:false 的真实 Windows SDK command sandbox 内，Node 原始 TCP 仍成功连接自有 localhost listener。角色因此可能间接调用无身份认证的本地后台，绕过本意的文件授权。窄目录成功不能弥补这个观察到的授权缺口。没有访问真实后台进行绕过，也没有扩大权限继续实现 feature。

后续必须先验证能隔离本地管理端点及工具表面的执行环境/权限策略，或引入经过验证且不向角色泄露的授权边界，再启用生产调度并重新跑真实 MVP 验收。App-server permission profile 仅评估了 schema，不是已验证解决方案。

## 未验证 / 尚未实现

- 真实三角色 feature、新测试、固定提交绿色回归和最终 Manager 报告；真实 feature 修复失败闭环；真实活动工作流跨阶段与执行中重启。相应控制路径有自动化证据，不能冒充真实 agent 验收。
- base commit 上新增测试的功能性红色验证尚未执行；报告显式列为限制。
- 自动纠正已接受测试暂时保守拒绝 AST/断言修改，人工处理机制需补充； arbitrary file allowlists、Windows junction/hard-link 和所有外部工具面的隔离未完成验证。
- 完整产品推迟：独立 Reviewer、多 architect、并行 scenario、跨任务 bug 去重、主分支合并/部署、GraphConnectors/Service Fabric E2E、Docker、CrewAI、ACP/A2A、分布式队列。

## 证据和复查

docs/evidence/ 保存 SDK 原始公开证据、实际 UI workflow、启动健康和重启/幂等结果；docs/codex-integration.md 记录版本、认证、真实操作、取消和网络实验。
应用测试中的真实 temp Git/pytest/SQLite/API 与 mock agent 测试在名称和说明中区分。
要恢复展示本次实际阻塞记录，用 scripts/start.ps1 -UI -DataDir '.aim-data/launch-smoke'，然后在 UI 输入上述 workflow ID（默认端口可用时）；状态来自同一 SQLite。
最终已停止本次启动的服务，数据、worktree 和证据保留。未修改输入笔记或受保护目录，未提交、push、stash、clean、reset 或移动用户文件。
# 本轮扩展状态

新增 feature/integration 分支、独立只读 Reviewer、角色配置快照以及 JSON/Markdown 输入。下文和 docs/evidence 中已有 SDK 实验及任务运行记录属于扩展前的历史证据；不证明新增分支审查交付流程已真实执行。生产适配层仍 fail-closed，不能宣称自动开发交付已完成。新单元/本地 Git 回归结果应单独记录。
