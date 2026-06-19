# 模型fallback优化和排查

- 时间：2026-06-18 20:54 CST
- 类型：存档点 / checkpoint
- 主题：模型 fallback 优化、8787 模型页同步、8080 状态口排查

## 本轮已完成

1. 调整模型路由逻辑：fallback 仅作用于当前单轮请求。
2. 下一轮请求恢复主模型优先，不会因为上一轮 fallback 命中而长期切走。
3. 扩展候选选择：不再只切第一个 fallback，显式 fallback 链走完后继续尝试其他启用 profile。
4. 冷却键细化为 provider + profile_id + model，避免不同 profile 因同名 model 相互污染。
5. cooldown 按故障类型分级缩短：超时 / 上游错误 / 429 改为短冷却，不再默认长时间躺死。
6. 增加本轮 attempt trace：记录本轮依次尝试了谁、谁被 cooldown 跳过、谁报错、谁最终接住。
7. 已同步到 8787 webui 模型页，用于展示本轮尝试轨迹。
8. 为 8080 状态口补充了观测字段：
   - `sampled_at`
   - `status_latency_ms`
9. 为 8787 webui 增加了状态观测展示：
   - 状态口采样时间
   - 状态口耗时
   - 8787 本次拉取时间
   - 8787 拉取耗时
   - 最近一次拉取失败时间 / 原因
10. 在 `src/plugins/yangyang/__init__.py` 内为 `/yy/api/model/status` 增加了路由入口/出口日志。
11. 首轮 event loop probe 挂载位置过早，启动时报 `RuntimeError: no running event loop`，已修正为在 startup 阶段挂载。
12. 又增加了 `/yy/api/*` 的轻量 HTTP middleware 观测：
    - `http enter`
    - `http exit`
    - `http error`
13. `model/status` 路由内的 `request_id` 已与 middleware 贯通，便于单次请求全链路对点。

## 当前结论

1. fallback 主线优化已落地。
2. 8787 页面侧已补显示能力，且已确认能展示本轮尝试轨迹。
3. 已观察到一轮明确成功样本：
   - `#1 gpt_5_4`
   - `OK`
   - `openai_compat / gpt-5.4`
   - `success / 20:41:35`
   - 说明模型状态在成功窗口内可被 8787 正常拉到。
4. 当前主卡点不在 8787，而在 NoneBot 8080 状态口，且表现为间歇性卡死：
   - 8080 端口在监听。
   - TCP 可连接。
   - 部分时刻 `/yy/api/model/status` 可返回 `200`。
   - 另一些时刻 HTTP 请求能连上但持续 0 字节超时返回。
5. 已确认“并非路由恒定失效”：
   - 重启后曾出现 `20:51:03`、`20:51:24` 两次 `200` 返回。
   - 说明服务不是始终坏死，而是会在运行过程中进入卡住窗口。
6. 已确认“至少有一次请求根本没进路由函数”：
   - 超时前后未出现 `model status enter`。
   - 因此该次卡死点不在路由内部，更像死在路由分发前或更前层。
7. 当前最可疑范围：
   - ASGI / uvicorn 层请求处理链被闷住；
   - 主事件循环存在间歇性冻结；
   - 某个 middleware / lifespan / 共享锁 / 同步阻塞逻辑拖死了 HTTP 请求链。

## 本轮排障轨迹摘要

1. 初始现象：8080 监听正常，但状态口多次出现“连得上、0 字节、超时”。
2. 复打过程中曾观察到：
   - `/` 返回 `404`，说明 HTTP 链路在某些时刻是通的；
   - `/yy/api/model/status` 返回 `200`，说明状态路由并非未注册。
3. 首轮埋点结论：
   - 路由内日志不足以解释所有超时；
   - event loop probe 初版因挂载时机错误未成功工作。
4. 二轮埋点后结论：
   - 已把 probe 挂到 startup；
   - 已加 middleware 级别观测；
   - 下一次复现时可以直接判断请求是否进入 ASGI/middleware/路由哪一层。

## 待继续排查

1. 重启 NoneBot 后立刻复打 8080 状态口。
2. 重点观察以下日志是否出现以及出现顺序：
   - `http enter`
   - `http exit`
   - `http error`
   - `model status enter`
   - `model status exit`
   - `event loop lag detected`
3. 依据下一次复现结果直接分流：
   - 连 `http enter` 都没有：更前层就闷死。
   - 有 `http enter`，没有 `model status enter`：卡在路由分发前。
   - 有 `model status enter`，没有 `model status exit`：卡在路由内部或下游调用。
   - 出现 `event loop lag detected`：主事件循环被同步阻塞狠狠干住。

## 相关代码改动范围

- `src/plugins/yangyang/core/model_router.py`
- `src/plugins/yangyang/__init__.py`
- `scripts/agentbus_factory_webui.py`

## 备注

这份文档是当前阶段存档点，供后续继续砍 8080 状态口问题时接刀。后续若再次复现，应优先结合 middleware、route、event loop 三层埋点日志做定性，不再只凭 curl 现象猜测。

## 收口结论（2026-06-18 20:58 CST）

1. 当前 8080 状态口问题定性为**低优先级、间歇性管理面异常**。
2. 现阶段它表现为：
   - 偶发超时；
   - 但并非持续性坏死；
   - 暂未证明已影响主业务主链。
3. 因此本轮先**收口处理**：
   - 保留现有 middleware / route / event loop 埋点；
   - 维持带病观察；
   - 暂不为该问题单独中断主流程或扩大施工面。
4. 后续若再次复现，优先依据现有埋点直接分层定性；若开始影响实际功能，再升级优先级继续深剖。


## WebUI 真流式改造收口（2026-06-18 21:50 CST）

1. 8787 WebUI 已完成从“5 秒轮询/摘要跳变观感”向“真流式页面”的切换。
2. 页面已补齐流式双面板：
   - `thinking`
   - `reply`
3. 发送后前端状态会即时进入 `connecting / streaming`，不再依赖 5 秒一刷的伪流式观感。
4. 顶部时间显示已修正为前端本地秒表逐秒递增；后端 SSE 仅负责提供校准基准，不再表现为 5 秒一跳。
5. 8787 → NoneBot 聊天主链已接入正式流接口：
   - WebUI 入口统一走 `POST /api/astrbot/chat/send`
   - `yy_test_host` 分流到 NoneBot 本地正式流
   - 后端对接 `/yy/api/chat/send_stream`
   - SSE chunk 透传，不再使用 probe 假流冒充主链
6. 已补事件归一化兼容层，前端可兼容识别多种流事件命名与文本字段来源，降低 AstrBot / NoneBot 两侧事件形态差异带来的显示毛刺。
7. 已补停止流/断流状态收口：
   - 用户主动停止时前端状态收为 `aborted`
   - 自然收尾区分 `done / closed / error`
   - `closed` 不再一律误判为 fallback 失败
8. 在役 WebUI 已完成重启并通过实测，当前结论：
   - WebUI 真流式改造已落地
   - 页面体验与状态语义已达到可用标准
   - 本项先收口，后续不再按“未做真流式”重复开题
9. 后续若继续打磨，优先考虑链路观测增强：
   - `request_id`
   - 首包耗时
   - 总流时长
   但这些属于增强项，不影响本轮收口结论。
