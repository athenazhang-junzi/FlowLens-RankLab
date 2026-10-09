# FlowLens LiveLab

LiveLab 是 FlowLens RankLab 的本地实验诊断界面。

它包含两类信息：

- 页面顶部的 RankLab 卡片读取 KuaiRand-Pure 离线回放摘要；
- 实验队列、批次进度和决策卡使用固定随机种子在浏览器本地模拟。

两者都不能表述为真实线上 A/B 或业务收益。

## 运行

```bash
cd apps/livelab
python3 -m http.server 4187
```

浏览器打开 `http://127.0.0.1:4187`。项目没有 npm、Docker、Java 或数据库依赖。

## 演示路径

1. 查看顶部 RankLab 离线结论和 `ITERATE_AND_RETEST` 决策。
2. 切换左侧实验，观察不同健康状态。
3. 点击“模拟下一批事件”，检查批次回执与健康规则。
4. 点击指标行查看分子、分母、口径和方向判断。
5. 在决策卡中记录继续、暂停或迭代的理由。

## 文件

- `index.html`：页面结构。
- `styles.css`：响应式布局与组件样式。
- `app.js`：固定种子模拟器与交互逻辑。
- `data/ranklab_offline_run.js`：Gate C 生成的离线摘要。
- `tests/test_static.py`：零依赖静态检查。

## 验证

```bash
python3 -m unittest discover -s tests -v
node --check app.js
```

流程设计参考 [PreferredAI/cornac-ab](https://github.com/PreferredAI/cornac-ab) 的模型分流、反馈回传和指标评估思路；本项目没有复制其页面代码。
