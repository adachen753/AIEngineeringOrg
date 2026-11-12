# Integration Goal

为 codex/integration/<任务ID> 规划目标回归及适用跨组件检查，记录与 feature candidate 的关系。不自行 merge/push 或修改产品代码。
针对 GraphConnectors 先确认 SDK/MSBuild/runner 与目标 csproj；SF、证书、端口、数据库、队列、tenant/connection、mock 与输出目录需各自所有权和锁。SF E2E 首次串行，stock publish/cleanup 可能 reset SF 或停止共享 mock，未单独授权禁止执行。
IFS/Cosmic E2E 以 docs/how-to/run-ifs-cosmic-e2e-locally.md 与 OneBoxTests.xml 为待核查入口，不推广为全部 E2E。环境不具备时报 blocked，不伪造通过；当前后端不提供 C#/SF runner。
