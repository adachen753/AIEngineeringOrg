# GraphConnectors 共享上下文与边界

配置检查日期：2026-11-12（Asia/Shanghai）。实际仓库为 Q:\GraphConnectors（不是 Q:\graphconnector）。只读检查 HEAD：6c6999c2fe593950a3fc6b816e22dfe3c077be0d；不代表所有工作树文件均等于该提交，执行任务必须重新核验。

## 来源与时效
- 知识包：Q:/AIManager/docs/20261111 - GraphConnectors knowledge pack.md。
- 同目录：20261111 - high level design.md、20261111 - implementation prompt.md。高层设计是目标组织；implementation prompt 第一版约束为小 Python 项目、串行有限 workflow，不能将目标设计当已实现能力。
- 本次直接核对 Q:/GraphConnectors/AGENTS.md、ARCHITECTURE.md、global.json，以及 .github/instructions/coding-guidelines.instructions.md 的规则入口。任务必须继续加载目标路径匹配规则；本配置不是全仓审计。
- 规则优先级：当前用户授权/保护规则 > 适用 AGENTS.md > 匹配路径规则 > 当前工程/构建配置 > 历史说明。证据带路径、时间、commit、适用组件及 verified/documented/hypothesis；不把历史说明当运行证据。

## 代码导航
sources/dev/GCS/Services 是云服务；GCSApp 是 Model D SF 组合入口，Orchestration 是 Actor 编排；GCS/OnPremAgent 是 on-prem 组合；GCS/plugins、Management、LocalFilesAgent 按任务定位。sources/dev/SCD、SDS-S、ScdDataAgent、Analytics、Tools 分别为内容域、schema、data agent、监控分析及工具。sources/test 镜像生产组件。Core 常为抽象，Standard 常为实现；Autofac 注册与 host/manifest、dirs.proj 遍历一并核验。target/ 是生成输出，不编辑。

## 构建证据限制
global.json 声明 .NET SDK 10.0.403、rollForward=latestMajor、Traversal 4.1.82、NoTargets 3.7.134；ARCHITECTURE.md 的 10.0.302 已漂移。实际 SDK/MSBuild、Debug/Release/x64、warnings-as-errors 与项目属性须执行前核验。AGENTS.md 的 targeted msbuild Rebuild 与 Test/coverage 命令仅为候选，不证明目标 csproj 支持或测试已运行。未验证 dotnet、MSTest、SF、Docker、MCP 能力，不安装环境或认证。

## 永久保护与权限
Q:/GraphConnectors/cwzClaude/ 与 Q:/GraphConnectors/sources/dev/cwzClaude-SQL/ 永久禁止任何写入、生成、删除、移动、覆盖或清理；本配置无需读取其内容。不得 stash/clean/reset/移动任何 cwz* 草稿目录。不得读取密钥，不访问生产或外部资源，不执行 init.cmd、机器级 SF reset/cleanup、证书安装或部署；如任务需要，停止并请求单独授权及受控方案。Markdown 是角色指导，不是可强制执行的文件/网络边界。

## 当前能力，不得夸大
legacy 模式独立执行角色为 manager/dev/test/reviewer；delivery 模式为 manager/architect/dev/test，单个 Architect 内含后端与安全视角。其他 profiles 仍是支持视角，不是新增独立 thread、投票或审批门。delivery 新增固定构建与外部部署/Computer-use 桥协议，但具体 GraphConnectors C#/MSBuild/SF 配方和桌面驱动仍需配置及实机验证。真实 Codex 自动执行因沙箱能力验证未通过而 fail-closed；本配置不解除该拦截，不提升权限，不把规划当验收完成。若 repo 不是 GraphConnectors，仅通用原则适用，不向其他项目强加其 C# 规则。
