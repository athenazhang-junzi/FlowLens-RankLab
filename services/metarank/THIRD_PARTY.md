# Metarank 第三方依赖说明

| 项目 | 当前基线 | 用途 | 许可证 | 来源 |
|---|---|---|---|---|
| Metarank | `metarank/metarank:0.8.0` | 事件导入、LambdaMART 训练和显式候选重排 | Apache-2.0 | <https://github.com/metarank/metarank> |

## 集成方式

FlowLens 不复制或修改 Metarank 的 Scala 源码。`compose.yml` 通过官方 Docker 镜像启动外部运行时，FlowLens 只维护自己的事件适配、配置和评估代码。

## 当前验证状态

- 配置字段依据 Metarank 0.8.0 上游源码与文档整理，并已由真实 Metarank 进程完成配置解析和事件校验。
- 当前镜像为原生 `linux/arm64`，digest：`sha256:495f8f72cef67bbbccd1bc29b9f3d1ddfa322eb2f79eb151a48d9a6b4ed74e63`。
- standalone 导入、LambdaMART 训练与 50 个排序 API 请求已通过；候选守恒为 253/253。
- `click: 3`、`long_view: 7` 是与现有 FlowLens 30%／70% 多任务权重等比例对齐的整数标签基线，不是调优后结论；只能在验证集上调整。XGBoost 排序标签要求非负整数，因此不能直接使用 `0.3`／`0.7`。
- `negative_feedback: 0` 只用于显式声明完整事件流中的交互类型；它不代表已调优的负向奖励函数。
