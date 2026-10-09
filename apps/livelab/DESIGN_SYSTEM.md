# FlowLens LiveLab Design System

## 1. 设计原则

- **先健康、后结果**：右侧检查器持续显示 SRM、触发率、污染和事件完整性。
- **上下文不丢失**：实验队列、当前实验和诊断结论同时可见。
- **颜色不独立传意**：状态同时使用图标、文字和形状。
- **模拟数据诚实标记**：标题区和每个结果页都出现“模拟流量”标识。
- **紧凑不拥挤**：桌面三栏，8px 网格，正文至少 14px，交互目标至少 44px。

### 风格强度依据

- Energy：安静到中等。实验决策工具需要持续阅读，不使用高饱和大色块或循环动效。
- Finish：精确、完整。面向策略产品和数据协作，采用严格对齐、1px 边框和一致状态反馈。
- Density：标准偏密。实验队列、当前方案和健康检查需要在同一视野中比较。
- Weight：中等。关键数字使用 600–700 字重，常规正文保持 400–500。
- Seriousness：高。所有结果明确标记证据等级，不使用卡通、游戏化或庆祝式表现。

## 2. 色彩令牌

| 令牌 | 值 | 用途 |
|---|---:|---|
| `--bg` | `#F3F6F4` | 页面冷白底色 |
| `--surface` | `#FFFFFF` | 主表面 |
| `--surface-subtle` | `#F7FAF8` | 次级表面 |
| `--ink` | `#17201D` | 标题和正文 |
| `--muted` | `#5B6863` | 辅助说明 |
| `--border` | `#D7E0DC` | 分隔线 |
| `--primary` | `#167A63` | 主操作、当前状态 |
| `--primary-strong` | `#0F5F4D` | hover / active |
| `--primary-soft` | `#DDF1EA` | 选中背景 |
| `--warning` | `#A65D11` | 待关注 |
| `--warning-soft` | `#FFF0DA` | 待关注背景 |
| `--danger` | `#B43A3A` | 失败与破坏性操作 |
| `--danger-soft` | `#FCE7E5` | 失败背景 |
| `--info` | `#365E87` | 模拟/信息状态 |

主色覆盖控制在约 10%，红色只用于异常或破坏性动作。

## 3. 字体

- CJK：`LXGWNeoXiHei`（emfont），回退到 `PingFang SC`、`Microsoft YaHei`。
- Latin / 数字：`IBM Plex Sans`（Google Fonts），数值使用 `tabular-nums`。
- 页面标题：26px / 700 / 1.2。
- 分区标题：18px / 650 / 1.3。
- 正文：15px / 450 / 1.55。
- 标签：12px / 600 / 1.4，字距 0.02em。

## 4. 间距与深度

- 基础单位：4px；主节奏：8 / 12 / 16 / 24 / 32px。
- 卡片圆角：10px；按钮和输入框：8px；状态徽标：999px。
- 常规表面无阴影；浮层使用 `0 12px 32px rgba(23,32,29,.12)`。
- 表格、列表和检查项优先使用 1px 边框建立层次。

## 5. 组件配方

以下类字符串是 Tailwind 语义规范；当前无依赖版本在 `styles.css` 中实现等价状态。

```text
CONTAINER/CARD
Default: bg-[#FFFFFF] border border-[#D7E0DC] rounded-[10px] p-4 shadow-none
Hover: hover:border-[#B8C9C2] hover:-translate-y-px
Focus: focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#167A63] focus-visible:ring-offset-2
Active: active:scale-[0.995]
Disabled: opacity-55 pointer-events-none
Loading: aria-busy:opacity-70 aria-busy:cursor-wait
Error: data-[state=error]:border-[#B43A3A] data-[state=error]:bg-[#FCE7E5]
Success: data-[state=success]:border-[#167A63] data-[state=success]:bg-[#DDF1EA]

PRIMARY_BUTTON
Default: min-h-[44px] bg-[#167A63] text-white px-4 py-2 rounded-lg font-semibold transition duration-150 ease-out
Hover: hover:bg-[#0F5F4D] hover:-translate-y-px
Focus: focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#167A63] focus-visible:ring-offset-2
Active: active:scale-[0.98]
Disabled: disabled:opacity-50 disabled:cursor-not-allowed disabled:translate-y-0
Loading: aria-busy:opacity-70 aria-busy:pointer-events-none aria-busy:cursor-wait
Error: data-[state=error]:bg-[#B43A3A]
Success: data-[state=success]:bg-[#0F5F4D]

SECONDARY_BUTTON
Default: min-h-[44px] bg-white border border-[#B8C9C2] text-[#17201D] px-4 py-2 rounded-lg font-semibold transition duration-150 ease-out
Hover: hover:bg-[#F7FAF8] hover:border-[#7D9189] hover:-translate-y-px
Focus: focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#167A63] focus-visible:ring-offset-2
Active: active:scale-[0.98]
Disabled: disabled:opacity-50 disabled:cursor-not-allowed
Loading: aria-busy:opacity-70 aria-busy:pointer-events-none
Error: data-[state=error]:border-[#B43A3A] data-[state=error]:text-[#B43A3A]
Success: data-[state=success]:border-[#167A63] data-[state=success]:text-[#0F5F4D]

INPUT_FIELD
Default: min-h-[44px] w-full bg-white border border-[#B8C9C2] text-[#17201D] px-3 py-2 rounded-lg transition-colors duration-150
Hover: hover:border-[#7D9189]
Focus: focus:outline-none focus:ring-2 focus:ring-[#167A63] focus:border-[#167A63]
Active: active:border-[#167A63]
Disabled: disabled:opacity-50 disabled:cursor-not-allowed disabled:bg-[#EEF3F0]
Loading: aria-busy:opacity-70 aria-busy:cursor-wait
Error: aria-invalid:border-[#B43A3A] aria-invalid:ring-2 aria-invalid:ring-[#FCE7E5]
Success: data-[valid=true]:border-[#167A63] data-[valid=true]:ring-1 data-[valid=true]:ring-[#DDF1EA]

NAVIGATION_ITEM
Default: min-h-[44px] flex items-center gap-2 px-3 py-2 rounded-lg text-[#5B6863] transition-colors duration-150
Hover: hover:bg-[#F7FAF8] hover:text-[#17201D]
Focus: focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#167A63]
Active: aria-current:bg-[#DDF1EA] aria-current:text-[#0F5F4D] aria-current:font-semibold
Disabled: disabled:opacity-50 disabled:cursor-not-allowed
Loading: aria-busy:opacity-70
Error: data-[state=error]:text-[#B43A3A]
Success: data-[state=success]:text-[#0F5F4D]

BADGE/TAG
Default: inline-flex items-center gap-1 px-2 py-1 rounded-full bg-[#EEF3F0] text-[#46544F] text-xs font-semibold border border-[#D7E0DC]
Hover: hover:bg-[#E4ECE8]
Focus: focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#167A63]
Active: active:scale-[0.98]
Disabled: opacity-50
Loading: aria-busy:opacity-70
Error: data-[state=error]:bg-[#FCE7E5] data-[state=error]:text-[#8D2E2E] data-[state=error]:border-[#E5B6B1]
Success: data-[state=success]:bg-[#DDF1EA] data-[state=success]:text-[#0F5F4D] data-[state=success]:border-[#A8D5C5]
```

## 6. 动效

- 按钮反馈：150ms ease-out；按下缩放至 0.98。
- 导航切换：内容透明度 0→1、Y 轴 4px→0，180ms ease-out；用于连续性。
- 诊断更新：状态背景交叉淡化 220ms；用于反馈。
- 不使用滚动淡入、视差、循环装饰动画。
- `prefers-reduced-motion: reduce` 下关闭位移与过渡。

## 7. 图标与素材

- 图标来自 Lucide 的 24×24 outline 路径，统一 1.8px stroke。
- 本工具不需要人物、内容封面或装饰图片；删除图像槽位比伪造内容缩略图更诚实。
- 图表使用语义化 HTML/CSS 绘制；颜色之外同时显示数值、标签和方向符号。
