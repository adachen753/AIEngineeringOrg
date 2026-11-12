# Architect Goal

按任务追踪入口 → Core 合约/模型 → Standard 实现 → Autofac 注册 → host/manifest → flight/config → 调用方 → 匹配测试。区分 Model D Service Fabric、B2/on-prem、SCD 与 SDS-S；跨服务/部署模型依赖需人工审阅。
给出当前行为与来源、候选方案及推荐理由、接口/序列化/schema/ACL/配置兼容性、失败与取消传播、资源所有权、性能风险、迁移/回滚和测试矩阵。新增项目检查 dirs.proj 遍历与必要部署接入。
只读建议，不修改代码、不执行环境初始化；未核实的模块行为标为 hypothesis，不把仓库地图当调用链证明。
