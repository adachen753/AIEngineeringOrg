# 角色配置与 GraphConnectors 项目配置

新增四角色 delivery 模式会独立调度 Manager、Architect、Dev、Test；无 UT/Reviewer 阶段。原 legacy 模式的角色路由仍按下表运行。详见 docs/four-role-delivery.md，不能把新增编排代码等同于真实 SDK/SF/Computer-use 已验收。

入口：Q:/AIManager/ai_manager/roles/config.json。每个角色分别关联同名目录内 soul.md（原则）与 goal.md（职责）。context 指向 graphconnectors.md，共享来源、代码地图、安全边界及能力限制。内容根据用户知识包、高层设计、implementation prompt 和仓库只读证据配置，借鉴 yeaft 思考方法，不冒充人物。

## 角色与实际路由

|配置角色|职责|当前使用方式|
|---|---|---|
|manager|需求、调度、风险、交付|独立 Manager 阶段|
|feature_designer|feature spec、验收、非目标|Manager 支持视角|
|architect|系统边界、服务交互、可靠性|Manager/Dev 支持视角（System Architect）|
|backend_architect|API、模型、一致性、兼容|Manager/Dev 支持视角|
|dev|最小实现、工程规范|独立 Dev 阶段|
|bugfix|失败归因、根因与回归|Dev 支持视角|
|test|验收矩阵、边界、测试证据|独立 Test 阶段|
|scenario_tester|场景与状态转换测试|Test 支持视角|
|integration|固定集成 commit、资源隔离|Test 支持视角|
|reviewer|独立只读审查|独立 Reviewer 阶段|
|security|威胁模型、ACL、凭据与边界|Manager/Reviewer 支持视角（Security Architect）|
|release|交付清单、PR 草稿、回滚|Manager 支持视角|
|knowledge_curator|带来源、时效和等级的知识|Manager 支持视角|

**支持视角会实际拼入对应角色提示，但不是独立 agent/thread、交叉评审或新增审批门。** 高层设计中的独立 Architect Council、DAG、多 feature 并行和专用 Bug Fix 循环尚未实现；不能用配置伪装成已有能力。输出仍必须匹配后台阶段 schema，不因额外角色生成不兼容字段。

## 定制与生效

JSON version=1；manager/dev/test/reviewer 必须存在，另外九个角色可选，不接受未知角色或字段。context 可省略以兼容旧四角色配置。路径只能是配置目录内的相对 Markdown，包含路径逃逸与大小校验。全部文本与 SHA-256 在首次任务保存时快照化，支持角色与共享上下文同样入快照；重试和原幂等键恢复原快照。修改文件仅影响新任务，无需重启服务；历史任务不能自动升级。

本次包含加载器代码更新，正在运行的后端须重启一次才能识别扩展配置；之后仅修改角色文本无需重启，只影响新任务。旧任务仍使用原快照。

可复制整个 roles 目录，然后启动前设置：

```powershell
$env:AIM_ROLE_CONFIG = 'C:/my-config/roles/config.json'
Q:/AIManager/scripts/start.ps1 -UI
```

默认配置已启用 GraphConnectors 上下文；用于其他仓库时应替换 context 或省略，并定制角色。项目规则不能替代任务中的 repo、base_commit、allowed_paths、test_paths、acceptance 与显式授权；这些仍在任务 JSON/Markdown 中填写。

## 明确边界

本次未修改 GraphConnectors 或用户知识包/设计文档，未运行该仓库构建、认证或部署。实际 Q:/GraphConnectors HEAD 为 6c6999c2fe593950a3fc6b816e22dfe3c077be0d（2026-11-12 只读检查）；每次任务重新核验。保护目录始终不可写。

当前测试执行器仍为小 Python pytest，尚未接入 C#/MSBuild/SF。真实 Codex 自动执行仍因沙箱验证不满足而 fail-closed；Soul/Goal 不解除拦截或授予权限。角色配置是指导，不是新增强制执行的安全控制。
