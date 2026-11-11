# 角色配置

默认配置位于 `ai_manager/roles/config.json`，角色为 manager、dev、test、reviewer。每个角色分别关联 Soul 与 Goal Markdown 文件。默认内容参考本机 yeaft 的产品、务实开发、测试与架构审查框架，采用重新编写的工作原则，不冒充人物或持久记忆。

复制整个 roles 目录可以定制；JSON 必须包含 version=1 和完整的四个角色，禁止未知字段。每个角色仅包含 soul、goal 两个相对 Markdown 路径，路径不得逃逸配置目录。角色提示不能覆盖阶段要求、输出 schema、验收条件或后台权限。

启动前在 PowerShell 设置：

```powershell
$env:AIM_ROLE_CONFIG = "C:/my-config/roles/config.json"
.\scripts\start.ps1 -UI
```

后台首次保存任务时读取全部配置并保存文本及 SHA-256 快照。修改文件只影响新任务；相同幂等键恢复原任务及原快照。旧任务缺少快照时不能派发角色，须提交新任务。角色配置不包含凭据，请勿写入密钥。

任务输入模板与角色配置是两类文件：任务输入描述仓库、功能、授权路径、验收条件；角色配置描述工作原则和长期职责。角色权限、分支和审查流程由后台固定实现，不通过 Markdown 授权。
