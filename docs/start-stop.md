# 本地启动、停止与重启

以下命令在 PowerShell 中执行，项目目录为 `Q:\AIManager`。首次安装请先完成 README 中的 Python 虚拟环境与 Node 依赖安装。启动前确认没有另一套服务占用端口；重启前确认没有正在执行的任务。

## 启动（包含前端）

```powershell
Set-Location -LiteralPath 'Q:\AIManager'
.\scripts\start.ps1 -UI -DataDir '.aim-data\launch-smoke'
```

如果提示找不到 `node`，可显式指定 Node 可执行文件。本机示例：

```powershell
Set-Location -LiteralPath 'Q:\AIManager'
.\scripts\start.ps1 -UI `
  -DataDir '.aim-data\launch-smoke' `
  -Node 'C:\Users\adachen\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
```

其他电脑应填写本机实际 Node 路径，不要照搬缓存路径。默认 Python 为项目下的 `.venv\Scripts\python.exe`。示例沿用已有数据目录；省略 `-DataDir` 会使用 `.aim-data`，可能看不到原先任务。

- 前端：[http://127.0.0.1:8501/](http://127.0.0.1:8501/)
- 后台健康检查：[http://127.0.0.1:8765/health](http://127.0.0.1:8765/health)
- Adapter 健康检查：[http://127.0.0.1:8766/health](http://127.0.0.1:8766/health)

## 停止

```powershell
Set-Location -LiteralPath 'Q:\AIManager'
.\scripts\stop.ps1
```

停止脚本会校验启动记录中的进程身份，停止记录归属的进程树；不只是前端，也包含后台和 Adapter，以及通过同一脚本启动的桌面桥。数据和日志保留。关闭浏览器页面不会停止后台。停止可能中断任务，重启后应检查中断状态，不要直接重复部署。

## 重启

先执行上述停止命令，确认成功后再执行启动命令。若停止报错，先排查，不要继续启动；不要删除或覆盖启动记录来强行启动。重启后刷新浏览器。

## 日志与常见问题

日志与进程归属记录位于 `Q:\AIManager\.aim-launch`：

```powershell
Get-Content -LiteralPath 'Q:\AIManager\.aim-launch\ui.err.log' -Tail 50
Get-Content -LiteralPath 'Q:\AIManager\.aim-launch\backend.err.log' -Tail 50
Get-Content -LiteralPath 'Q:\AIManager\.aim-launch\adapter.err.log' -Tail 50
```

- **找不到 Node**：安装项目要求版本的 Node，或通过 `-Node` 指定已有可执行文件。
- **启动记录已存在**：先运行 `stop.ps1`；若无法确认归属，保留记录并人工检查。
- **端口已占用**：确认占用者，不要杀死不明进程；可通过 `-ApiPort`、`-AdapterPort`、`-UiPort` 调整端口。
- **工具提示 blocked by policy**：此前自动重启被工具安全策略拦截，不等于 PowerShell ExecutionPolicy 错误。可由用户在自己的 PowerShell 中执行上述命令，无需为此设置 Bypass 或关闭安全策略。
- **页面可打开但任务阻塞**：服务健康不代表真实 Agent 运行已验收；当前 Adapter 的隔离保护仍可能拒绝派发，不应绕过。

## 可选：桌面部署与 E2E 桥

默认启动不包含桌面桥。需先配置 `AIM_PROJECT_CONFIG`、`AIM_BRIDGE_CONFIG` 和至少 32 字符的 `AIM_DESKTOP_BRIDGE_TOKEN`，审核实际部署/Computer-use 驱动与专用资源，再在启动参数中增加 `-DesktopBridge`。不要把令牌写入仓库或日志。配置及能力边界见 [四角色交付说明](four-role-delivery.md)。
