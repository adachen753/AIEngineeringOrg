---
Created: 2026-11-11
Tags:
  - AI
  - AgentManager
  - GraphConnectors
Status: Initial repository-backed knowledge
---

# GraphConnectors — Manager Knowledge Pack

## 1. 用途与证据边界

供 AI Engineering Manager 及后续 Architect、Dev、Reviewer、Test 加载的初始项目知识包。来源为本机 Q:\GraphConnectors 的只读检查；本次未修改仓库，未执行构建、测试、部署、初始化或认证，未读取 Secrets 或凭据配置内容。

检查时 HEAD：6c6999c2fe593950a3fc6b816e22dfe3c077be0d。工作树可能另有未提交修改；本文描述检查到的工作树文件，不声称全部内容等同该提交。每次任务需重新记录 HEAD 和相关文件状态。

本文是知识与配置建议，不是已经部署的 Manager 配置。禁止把候选命令、历史说明或角色声明当作已验证环境或权限。

## 2. 加载策略与权威来源

Manager 启动时加载本包的代码地图、授权和验收规则。任务开始时按需读取目标路径适用的 AGENTS.md、路径规则、实现与匹配测试，不把全仓库复制进每个 thread。

来源优先级：当前用户授权和保护规则 > 适用 AGENTS.md > 匹配的路径规则 > 当前项目/构建/管线配置 > 架构说明和历史文档。规则冲突需报告，不自行用宽松版本覆盖严格规则。

主要来源：
- Q:\GraphConnectors\AGENTS.md：工程、代码、测试与 PR 规则。
- Q:\GraphConnectors\ARCHITECTURE.md：部署模型、模块边界、DI 和导航。
- Q:\GraphConnectors\README.md：开发入口。
- Q:\GraphConnectors\sources\README.md：本地开发说明，明确提示最新环境说明迁到内部 wiki；部分版本信息陈旧。
- Q:\GraphConnectors\global.json：SDK 与 MSBuild SDK 版本。
- Q:\GraphConnectors\Directory.Build.props：默认配置、输出目录、语言版本、警告策略。
- Q:\GraphConnectors\.github\copilot-instructions.md：开发与管理工具说明，不能将其宿主专用命令直接移植为 Manager API。
- Q:\GraphConnectors\.github\instructions\：coding-guidelines.instructions.md、connector-development.instructions.md、unitTests.instructions.md、content-parsing-service-design.instructions.md 等；按文件中的适用范围加载全文。本次只枚举文件名，未审计全部规则。

每条后续知识应带来源路径、检查时间、相关提交、适用组件及 verified/documented/hypothesis 状态。当前代码和实际测试证据优先于历史经验。

## 3. 代码地图

GraphConnectors 包括 Microsoft Graph Connectors 云服务、配置、分析、schema、工具和 on-prem agent。架构文档描述 Model D：Service Fabric 云服务；Model B2：Substrate/on-prem 相关架构。

| 路径 | 用途及任务入口 |
|---|---|
| sources/dev/GCS/Services/ | 云服务、编排和服务实现 |
| sources/dev/GCS/Services/GCSApp/ | Model D SF 应用组合入口 |
| sources/dev/GCS/Services/Orchestration/ | Actor 编排入口 |
| sources/dev/GCS/OnPremAgent/ | On-prem agent 和相关插件组合 |
| sources/dev/GCS/plugins/ | 插件目录；具体 connector 位置需按任务检索 |
| sources/dev/GCS/Management/ | Management 模块；按具体功能追踪实现 |
| sources/dev/GCS/LocalFilesAgent/ | LocalFilesAgent 实现 |
| sources/dev/SCD/ | Substrate Content Domain；组件文档入口 README.md |
| sources/dev/SDS-S/ | Schema 合约、业务逻辑与打包 |
| sources/dev/ScdDataAgent/ | SCD data-agent 服务及客户端 |
| sources/dev/Analytics/ | 分析和监控相关实现 |
| sources/dev/Tools/ | 配置、schema、ingestion、QoS 等工具 |
| sources/test/ | 通常镜像生产模块的测试树 |
| sources/test/GCS/Services/ | 服务测试，包括 OneBoxFunctionalTests |
| sources/test/GCS/UIAutomationTests/ | UI 自动化测试，需环境前置条件 |
| sources/test/GCS/LocalFilesAgent/ | LocalFilesAgent 单元测试及测试工具 |
| docs/ | 设计、spec、how-to 和 investigation；按目标组件加载 |
| build/、Directory.Build.* | 共享 MSBuild、分析、签名和输出逻辑 |
| dirs.proj、sources/dirs.proj | 项目遍历与构建接入 |
| target/、target/distrib/ | 生成输出；不作为源码编辑目标 |

架构说明：GCS namespace 常见 Microsoft.Graph.Connectors.*，SCD/基础设施常见 Microsoft.Substrate.*；Core 为合约/抽象，Standard 为实现。Autofac 和组件注册模块负责 DI。跨服务或部署模型依赖需要明确人工评审。

这些是导航线索，不是完整业务调用链。接具体任务后必须定位入口、配置/flight、合约、实现、注册、调用方和匹配测试。

## 4. 构建与测试知识

已检查配置：global.json 声明 .NET SDK 10.0.403，rollForward=latestMajor；Traversal 4.1.82、NoTargets 3.7.134。Directory.Build.props 默认 Debug/x64，TreatWarningsAsErrors=True，LangVersion=12，输出由 DistribRoot 等属性计算。

发现版本漂移：ARCHITECTURE.md 写 SDK 10.0.302，sources/README.md 写 7.0.306。不要照旧文安装；启动前检查实际 dotnet SDK 解析、MSBuild 来源和目标项目配置。rollForward 意味着实际 SDK 不一定与声明值相同。

仓库 AGENTS.md 记录的候选命令如下，本次未执行验证：


default build: msbuild dirs.proj /m /p:Configuration=Debug /p:Platform=x64
validation configuration: Release/x64
targeted build: msbuild <project.csproj> /t:Rebuild
test assets build: msbuild sources/test/dirs.proj /t:Build
coverage candidate: msbuild <Tests.csproj> /t:Test /p:QCodeCoverageBuild=true


最后一项是仓库规则给出的候选，不证明任意 csproj 都支持 Test target。实际测试 runner、filter、TRX、覆盖率参数和构建产物位置必须针对所选项目验证。构建测试资产成功不等于测试已执行。

样例已检查：sources/test/GCS/LocalFilesAgent/Microsoft.LocalFilesAgent.UsnJournal.Tests/Microsoft.LocalFilesAgent.UsnJournal.Tests.csproj。该项目 net10.0-windows、x64、IsTestProject=true，引用 MSTest、Microsoft.NET.Test.Sdk、FluentAssertions、NSubstitute，并通过 ProjectReference 指向对应生产实现。不得将这个项目的包版本和运行方式推广为全仓库统一标准。

仓库规则要求新/改代码 100% 单元覆盖及分支/边界检查，新类型匹配测试文件，确定性和无共享可变状态。需记录实际覆盖结果；无法获得覆盖证据时明确未验证。

## 5. 代码与交付约束

按 AGENTS.md：4 空格、PascalCase 公共成员、camelCase 局部变量/参数、_camelCase 私有字段、Async 后缀；实例成员 this.，静态成员类型限定；StyleCop 成员排序；避免未使用 using；禁止非框架事件入口 async void。所有类型和成员 XML 文档要求以仓库和匹配路径规则为准。

只处理当前任务相关代码，避免顺便重排或修复无关历史问题。新增项目必须接入遍历、必要 DI 注册和部署 manifest。评审针对固定提交；测试不得因失败被随意删除或弱化。

未来创建 PR 才加载提交与 PR 规则：描述必须包含 Scenario、Changes、Tests ran、Functional tests、Developer document updates；未运行测试明确原因。Windows az.cmd 多行描述有已记录风险，按仓库文件方式提交并回读验证。当前知识包不授权创建 PR、提交、push 或部署。

## 6. 环境与 E2E 安全

Model D 需要本地 Service Fabric、相关证书及服务权限；B2 前置条件不同。init.cmd 会改变开发环境和 hooks，不能作为只读 preflight 自动执行。证书安装、管理员权限、初始化和外部资源操作必须单独授权。

IFS Cosmic E2E 来源：Q:\GraphConnectors\docs\how-to\run-ifs-cosmic-e2e-locally.md。其权威 recipe 是 sources/test/GCS/Services/OneBoxFunctionalTests/SmokeFunctionalTests/CloudTest/OneBoxTests.xml。文档仅覆盖 Precheckin_OpenApi，不是全部 OneBox suite；该具体路径涉及 Windows SF 与 Linux 容器。Docker 不作为整个 Manager 第一版通用前提。

文档明确 stock publish/cleanup 可能 reset SF 和停止机器级 mock 进程。在共享工作站禁止原样运行；需专用测试机或单独授权、所有权核验的部署/清理。还存在 target-integrated checkout、隔离 queue helpers 和完整匹配 payload 的前置要求。当前尚未检查 recipe/helper 内容或证明本机满足条件。

调度配置需要独立锁定：SF 集群、部署 application、端口、数据库、队列、tenant/connection、mock 服务、证书及输出目录。worktree 只隔离文件，不隔离上述资源。首次接入串行执行 SF E2E。

Copilot 文档描述 gcs-admin MCP、认证和本地 AdminService；这些仅为该宿主的文档记录，本次没有验证本 Manager 能访问工具。接入后通过已授权 MCP 操作，不复制 token 或绕过文档规定直接调用 AdminService REST。文档中的认证脚本路径与当前仓库根不同，/mcp 是宿主相关指令，必须另做适配验证。

## 7. 角色知识与 Soul / Goal

Soul 表示稳定工程原则，Goal 表示职责；任务目标由 Manager 每次生成，权限必须后台落实。Yeaft Persona 可作为思考方式参考，不能替代状态机、独立验证或工具权限。以下为建议模板，不代表已安装角色配置。

### Manager
- Soul：证据优先、范围控制、有限循环；未验证不报完成，不把失败直接等同产品 bug。
- Goal：形成验收条件、计划与依赖，调度 Dev/Test，处理用户决策，汇总固定提交证据。
- Knowledge：本包、任务需求、权限、项目地图、环境能力及当前 workflow 状态。
- Outputs：结构化计划/动作、验收映射、路由决定、最终报告、未解决项。
- Permissions：提议调度；后台验证后执行。默认不直接写产品代码或操作外部环境。

### Architect（后续）
- Soul：Fowler 式边界与依赖分析，兼容性和可测试性优先。
- Goal：定位合约与调用链，给方案、影响范围、风险、迁移及测试策略。
- Knowledge：目标模块、Core/Standard 边界、DI、部署模型、相关设计和配置。
- Outputs：来源明确的方案及取舍；不假设 flight、schema 或 API 可以直接变更。
- Permissions：只读；跨模型依赖或重大合约变更返回 Manager 决策。

### Dev
- Soul：Torvalds 式具体代码与最小改动，根因修复，不绕过测试。
- Goal：按验收实现，在独立 worktree 补匹配单测，交付可追踪提交。
- Knowledge：目标路径规则、实现/合约/调用方、匹配测试、确认过的构建 profile。
- Outputs：修改路径、diff、提交、实际命令证据、风险；设计失效返回 Manager。
- Permissions：仅授权产品/测试路径；不写用户原始 checkout、受保护目录或外部环境。

### Reviewer（后续）
- Soul：独立判断、依据代码、按严重度排序，不重复 Dev 自我声明。
- Goal：检查固定提交的正确性、兼容性、异常/取消、并发及数据处理风险。
- Knowledge：需求、差异、相关调用链、测试及部署边界。
- Outputs：带路径和位置的发现、严重度、证据、评审结论和未检查项。
- Permissions：只读，不自行修改被审版本。

### Test
- Soul：Beck 式边界与确定性，独立验证，严格区分测试与产品问题。
- Goal：验收条件映射到测试，补缺失测试，交执行器运行并分析真实结果。
- Knowledge：测试规则/框架、相关实现、测试数据、环境 preflight、已授权 profile。
- Outputs：验证计划、测试提交、命令/退出码/TRX/日志、代码版本、失败分类及未验证项。
- Permissions：独立 worktree 的授权测试目录；产品代码问题交 Dev；不自动重置 SF 或清理共享服务。

每个角色配置还需：输入输出 schema、工具范围、超时、重试上限、thread 恢复策略、版本引用与 escalation 规则。顶层任务独立 thread，临时探索无需长期 thread；Test 命令由执行器运行，聊天不是测试证据。

## 8. 建议项目配置（非可直接执行配置）

project_id：graphconnectors
repository：Q:\GraphConnectors
base_commit：每次提交任务时显式记录
selected_component / connector：待用户选定
manager_storage：Manager 自己的目录，禁止写进保护目录
worktree_root / artifacts_root：待配置并验证所有权，避免共享输出冲突
coding_profile：C#、按目标项目解析 SDK/MSBuild，匹配 AGENTS/path rules
build_profile / test_profile：待验证目标 csproj、runner、参数、环境及输出
concurrency：首次接入单任务；SF 环境锁=1
repair_rounds：最多一次作为初始配置
permissions：显式 allowed repositories / write paths / command profiles / external resources
secrets：安全引用，不是知识包中的明文
approvals：初始化、证书、部署、资源变更、提交/集成/push 等按已给授权判断
retention：失败证据默认保留；只清理已核验系统拥有的资源

绝对禁止任何写入、移动、stash、reset、clean 或覆盖：
- Q:\GraphConnectors\cwzClaude\
- Q:\GraphConnectors\sources\dev\cwzClaude-SQL\

其他 cwz* 用户目录同样不参与 git 清理、移动或 stash。排除 Secrets、凭据文件、.git、target、packages 等作为常规全文知识索引；依赖/构建诊断确需读取非敏感内容时限定范围。检索和产物访问必须限制合法路径，不能因 agent 指令扩张权限。

## 9. 仍需补全，不能由仓库静态文档猜测

1. 第一批目标 connector/模块、feature、验收条件和允许修改路径。
2. 本机实际 SDK/MSBuild、私有包 feed 可用性、目标项目可运行命令和覆盖率输出。
3. 当前最新内部开发 wiki 与组件规格；现有仓库文档有陈旧内容。
4. 测试租户、连接、数据、账号、证书安全引用和资源所有者；不索取明文凭据。
5. 当前 SF/服务状态、共享机器限制、可授权的部署/清理流程。
6. Manager 宿主的 Codex/MCP 认证、事件和取消能力；现有 Copilot 配置不能直接视为可复用。
7. PR/owner 历史、已知 bug 与生产监控：按选定模块做单独证据调查，不采纳未经核验的历史结论。

首次实际验证建议：先选一个无外部依赖的小 C# 单测项目，完成 feature + 新测试 + 固定提交回归。小型 Python demo 的成功不能证明 GraphConnectors 构建、单测、SF E2E 已接通。

## 10. 下一轮模块知识采集清单

选定组件后补充：入口 → 合约/模型 → 具体实现 → DI/manifest → 配置/flight → 下游依赖 → 错误/重试/取消 → 匹配测试 → 日志/指标。每项给真实文件位置和读取证据。

Connector 业务验收可考虑 full/incremental crawl、分页/checkpoint、身份/ACL、schema 映射、删除检测、凭据、限流重试；仅为候选维度，不声称所有 connector 都具有相同实现。由实际需求和代码确认适用项。

