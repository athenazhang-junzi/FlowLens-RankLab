# FlowLens LiveLab

面向视频内容分发策略的本地实验诊断原型。它借鉴 Cornac-AB 的“模型分流—反馈回传—指标评估”骨架，并增加 FlowLens RankLab Gate C 的真实公开数据离线回放摘要。

## 证据边界

- 实验队列中的用户、事件和指标仍由固定随机种子在浏览器本地模拟。
- 页面顶部的 RankLab 结果来自 KuaiRand-Pure 公开数据 E3 离线回放，由 `data/ranklab_offline_run.js` 静态导入。
- 原型不会连接腾讯视频、真实业务数据或真实线上实验系统。
- 模拟与离线回放都不能表述为线上 A/B 结论或业务提升。Gate C 本轮实际决策为 `ITERATE_AND_RETEST`。
- LiveLab 已纳入 FlowLens 主仓库，通过 FlowLens 生成的静态摘要连接；前端不直接调用 Metarank 服务。

## 本地运行

```bash
cd apps/livelab
python3 -m http.server 4187
```

浏览器打开 `http://127.0.0.1:4187`。

项目没有 npm、Docker、Java 或数据库依赖。停止服务后，浏览器刷新会回到同一份固定种子的初始模拟数据。

## 核心演示路径

1. 在左侧实验队列切换实验，观察不同健康状态。
2. 在“策略对照”中检查控制组、实验组、流量比例和指标口径。
3. 点击“模拟下一批事件”，观察分阶段进度，并在批次回执中核对新增样本、触发率与健康结果。
4. 点击右侧任一健康卡，直接定位对应检查规则与建议排查动作。
5. 在“指标分析”中点击指标行，下钻查看 A/B 分子、分母、口径与方向判断。
6. 在“决策卡”中记录继续、暂停或迭代的理由，并确认未保存／已保存状态。

## 文件

- `00-PRD-v1.md`：产品范围、角色、事件合同和验收标准。
- `DESIGN_SYSTEM.md`：GrowthBook 风格的视觉令牌、组件状态和动效规范。
- `index.html`：语义化页面结构。
- `styles.css`：响应式布局与组件样式。
- `app.js`：固定种子模拟器、诊断计算和页面交互。
- `data/ranklab_offline_run.js`：由 FlowLens Gate C 生成的可追溯离线运行摘要。
- `tests/test_static.py`：零依赖静态质量检查。

## 验证

```bash
python3 -m unittest discover -s tests -v
node --check app.js
```

## 来源与改造关系

- 上游参考：[PreferredAI/cornac-ab](https://github.com/PreferredAI/cornac-ab)，Apache-2.0。
- 本项目没有复制 Cornac-AB 的页面代码；只借鉴其公开的实验流程与服务边界。
- 设计参考：GrowthBook 的紧凑实验工具信息架构，以及 PostHog 对实验状态、暴露量和指标结果的呈现方式。
