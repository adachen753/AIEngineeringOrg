# Dev Goal

仅实现批准 feature 与授权路径，配合目标测试；在后台分配的 feature worktree 工作，不自行 commit、切分支、push 或合并。遵守阶段可写边界和命令限制。
GraphConnectors C#：4 空格，PascalCase 公共成员，camelCase 局部变量，_camelCase 字段，Async 后缀，实例 this.、静态类型限定；遵守 StyleCop 顺序，移除未用 using，非框架事件入口禁止 async void，按路径规则补齐 XML 文档。不得顺便重排无关代码。
检查取消/超时/重试幂等、并发与释放、日志脱敏、DI 注册、Core/Standard 边界及兼容性。提交变更摘要、匹配测试建议、剩余风险与文件证据；不得宣称未执行的构建测试通过。
