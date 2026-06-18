# 秧秧 WebUI 工作指南

> 目的：以后优化 `/yy-web` 时，优先按截图和真实使用反馈迭代，黑奴只负责契约、安全和验尸，不再让黑奴隔着源码猜审美。

## 1. 当前定位

- `/yy-web` 是秧秧的只读巡检驾驶舱，不是运维写操作后台。
- 当前版本目标是 `0.2`：浅粉 Nekro Agent 风格 + 直观仪表盘总览。
- 前端保持单文件：`src/plugins/yangyang/webui/web_ui.html`。
- 后端 API 保持：`src/plugins/yangyang/webui/web_api.py`。

## 2. 视觉方向

以后 UI 参考优先级：

1. 阿漂截图反馈。
2. 当前生产页面截图。
3. Nekro Agent 浅粉后台风。
4. 黑奴扒源码结果。

核心风格：

- 奶油粉 / 浅绯红主色，不走黑色工厂风。
- 左侧浅色侧栏 + 顶部粉色状态栏。
- 主内容区用浅粉背景、白粉卡片、柔和边框、低阴影。
- 组件圆角约 `8px - 12px`，避免锐利工业感。
- 字号偏小但清晰，后台密度控制在截图风格附近。

## 3. 总览页结构

总览页优先做“直观看板”，不要默认堆 JSON。

推荐结构：

1. 时间筛选：`今天 / 本周 / 本月`，先做静态视觉占位，后续有数据源再接入。
2. 顶部 5 指标卡：
   - `任务总数`
   - `活跃节点`
   - `模型档案`
   - `工厂执行`
   - `执行成功率`
3. 中间图表：
   - `实时数据`：任务数 / 沙盒调用 / 成功调用 / 失败调用。
   - `概览`：模型数 / 工厂调用。
4. 下方图表：
   - `执行状态`：成功调用 / 失败调用。
   - `响应成功率`：成功率趋势。
5. 底部区域：
   - `分布统计`
   - `活跃排名`

如果没有真实时间序列数据，可以先用现有 API 聚合值生成静态趋势占位，但必须保持“这是巡检看板”的语义。

## 4. API 与数据边界

当前允许使用的只读 API：

- `GET /yy-web/api/ping`
- `GET /yy-web/api/dashboard`
- `GET /yy-web/api/models`
- `GET /yy-web/api/isaac/factory`
- `GET /yy-web/api/runtime-config/summary`

禁止事项：

- 禁止新增 `POST / PUT / DELETE / PATCH`，除非阿漂明确把 WebUI 从只读升级为操作台。
- 禁止直接在前端写 runtime config。
- 禁止在 UI 中展示真实 token、api_key、secret、password、base_url 明文。
- 禁止请求 `/root`、`/opt`、`/mnt/warehouse` 等宿主路径。

聊天统计暂时搁置。若以后要做类似“消息数量 / 活跃频道 / 用户”统计，需要先扒真实消息库、会话索引或 AstrBot 数据源，不能凭空造字段。

## 5. 安全硬约束

每次改 `web_ui.html` 后必须检查：

```bash
grep -n "innerHTML\|localStorage\|document.write\|eval(" src/plugins/yangyang/webui/web_ui.html || true
grep -nE "POST|PUT|DELETE|PATCH|https?://|cdn\.|cdnjs|unpkg|jsdelivr" src/plugins/yangyang/webui/web_ui.html || true
python3 -m py_compile src/plugins/yangyang/webui/web_api.py src/plugins/yangyang/webui/security.py src/plugins/yangyang/webui/setup.py
```

验收要求：

- 无 `innerHTML` 动态拼接。
- 无 `localStorage`，token 只允许 `sessionStorage` 或内存变量。
- 无外部 CDN / 字体 / 图片。
- 无写方法请求。
- API 路径必须仍是 `/yy-web/api/*`。
- 401 必须有明确提示。
- 远程 token 走 `Authorization: Bearer <token>`。

## 6. 前端实现规范

- 保持单文件 HTML，不引入 npm、Vite、Webpack、ECharts CDN。
- 图表优先用内联 SVG，占位也要像真实图表：网格、坐标、图例、折线。
- 动态 DOM 使用 `createElement` / `appendChild` / `textContent`。
- 可以保留 `el(tag, attrs, children)` helper，但不要提供不受控 `html` 注入能力。
- 数据展示优先卡片、表格、图表、排行；JSON 原文只能作为调试折叠/隐藏区域。
- 移动端至少保证单列可读，不要求完美适配。

## 7. 黑奴使用规则

黑奴适合做：

- API 契约扫描。
- 安全审查。
- 静态测试脚本。
- 多方案草案。
- 验尸和风险归纳。

黑奴不适合单独决定：

- 视觉审美。
- 配色方向。
- 卡片密度。
- “像不像截图”。

推荐流程：

1. 阿漂给截图或口头风格目标。
2. 主会话直接手工改一版。
3. 截图反馈后继续微调。
4. 黑奴只做安全验尸和 checklist。
5. 需要扒数据源时再派黑奴查代码。

## 8. 备份与留痕

每次大改前备份当前 HTML：

```bash
cp src/plugins/yangyang/webui/web_ui.html \
   src/plugins/yangyang/webui/web_ui.html.backup-$(date +%Y%m%d-%H%M)-说明
```

工作日记追加到：

```text
/AstrBot/data/workspaces/project_notes/秧秧_工作日记.md
```

建议记录：

- 改动目标。
- 参考截图或来源。
- 备份文件名。
- 静态检查结果。
- 仍需人工确认的点。

## 9. 下一步候选

优先级从高到低：

1. 根据阿漂截图继续调卡片高度、间距、图表比例。
2. 给 tab / 按钮补 `aria-selected`、键盘焦点样式。
3. 给图表加入更真实的横轴时间标签。
4. 如果扒到聊天统计数据源，再做消息数、活跃频道、用户统计。
5. 如果后端提供历史 run 时间序列，再把 SVG 占位图接真实数据。

## 10. 模块归位约定

当前主导航约定：

- `总览`：指标卡、图表看板、Bot 服务摘要、日志摘要。
- `模型配置`：模型档案只读展示。
- `I叔工厂`：工厂专属内容，内部再分 `总览 / 工厂 RUNS / 黑奴池 / 报告树`。
- `日志`：系统日志、沙盒日志、工厂日志、Bot 日志；当前只读壳子，后端日志 API 接入后再显示实时内容。
- `配置中心`：配置项壳子，先只读，写入能力另开票。
- `Runtime 摘要`：后端脱敏 runtime-config 原始摘要。

不要再把 `工厂 RUNS`、`黑奴池` 散放到主导航；它们属于 `I叔工厂`。
不要把 `Bot 服务` 独立成主导航；它先归入 `总览`。
