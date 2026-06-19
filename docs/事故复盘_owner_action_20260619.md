# 事故复盘：owner_action 私聊自动回传异常

- 日期：2026-06-19
- 影响范围：owner 私聊中的 `reply_current -> current_session` 自动回传链路
- 结论级别：已定位并完成关键修复，待重启后做最终链路验证

## 一、事故现象

漂♂总在 owner 私聊中发送工程指令后，系统能够识别 `owner_action`，但消息未能正常自动回传到当前私聊会话。

排障过程中先后出现两类表象：

1. **前期表象：一直停留在 dry_run / planned**
   - `gate_mode=dry_run`
   - `gate_reason=reply_current_pending:execution_disabled`
   - `exec_status=planned`
   - `exec_real_send=False`

2. **后期表象：已进入真发链路，但 OneBot 网络请求报错**
   - `sender.send(...)`
   - `_send_private_long_text(...)`
   - `bot.send_private_msg(...)`
   - 报错：`httpx.UnsupportedProtocol`
   - 报错：`Request URL is missing an 'http://' or 'https://' protocol`
   - 包装后异常：`nonebot.adapters.onebot.v11.exception.NetworkError: HTTP request failed`

## 二、影响

- owner 私聊自动回传不可用
- 表面上像是权限/开关未放开，实际上是多层问题串联
- 导致排障路径被“灰测门禁 + 适配器配置”双重误导

## 三、根因分析

本次不是单点故障，而是**三层问题叠加**。

### 1. owner_action 灰测门禁残留
早期链路中，`reply_current` 在 gate 阶段被固定压到 `dry_run` / `planned`，即使相关开关已经打开，仍然可能被旧分支或保守判定继续拦截。

这导致前期日志持续表现为：

- `execution_disabled`
- `dry_run_only`
- `permission_denied`

其中最主要的误导，是让人以为始终只是配置没开。

### 2. sender / delivery 相关开关需成套放开
排障中确认，以下能力位需要同时满足，链路才可能进入真实发送：

- `owner_action_execution_enabled=True`
- `owner_action_allow_reply_current=True`
- `owner_action_current_session_delivery_enabled=True`
- `owner_action_auto_reply_current_production_enabled=True`
- `owner_action_nonebot_sender_enabled=True`
- `dry_run=False`

前期这些保险丝未全部贯通时，系统只会停留在计划态，不会真发。

### 3. OneBot v11 配置字段名使用了旧变量名
这是后期真故障。

项目 `.env` 中原先使用的是旧字段：

- `ONEBOT_ACCESS_TOKEN`
- `ONEBOT_SECRET`
- `ONEBOT_WS_URL`
- `ONEBOT_API_ROOT`

但当前 NoneBot OneBot v11 适配器实际吃的是：

- `onebot_v11_access_token`
- `onebot_v11_secret`
- `onebot_v11_ws_urls`
- `onebot_v11_api_roots`

现场验配置对象时可见：

- `api_roots = {}`
- `access_token = None`
- `ws_urls = set()`

也就是说：

> `.env` 虽然“看起来配了”，但适配器实际没有正确吃到主动发消息配置。

## 四、为何会出现“能连上，但发不出去”

这是本次事故最容易误判的点。

- NapCat 反向 WebSocket 连到 NoneBot，这条链路可以成立
- 所以日志中会出现：
  - `WebSocket /onebot/v11/ws [accepted]`
  - `Bot 3940223711 connected`

但这只能说明：**反向连接进来了**。

它**不等于**主动 API 发消息配置正确。

当发送链路拿不到可用 websocket 上下文，或回退路径被触发时，就会依赖 `onebot_v11_api_roots`。而旧字段名导致该配置未正确生效，最终引发：

- URL 缺协议头
- API root 为空/脏值
- HTTP fallback 失败

于是爆出：

- `UnsupportedProtocol`
- `HTTP request failed`

## 五、已执行修复

已将 `.env` 中旧字段改为当前 v11 适配器实际使用字段：

- `ONEBOT_ACCESS_TOKEN` → `onebot_v11_access_token`
- `ONEBOT_SECRET` → `onebot_v11_secret`
- `ONEBOT_WS_URL` → `onebot_v11_ws_urls=["ws://127.0.0.1:3001/"]`
- `ONEBOT_API_ROOT` → `onebot_v11_api_roots={"default":"http://127.0.0.1:3001"}`

说明：

- `ONEBOT_WS_REVERSE_URL` 暂未删除
- 原因是该变量可能仍被项目内文档、检查脚本或兼容逻辑使用
- 为避免牵连旁路，先保守保留

## 六、修复结果

已完成配置修正，当前状态为：

- owner_action 前期门禁问题已被基本切穿
- 发送链路已能推进到 `sender.send(...)`
- 真故障已定位到 OneBot v11 配置命名不兼容
- 配置文件已完成修复
- 待服务重启后验证最终自动回传是否完全恢复

## 七、后续验证项

重启后重点观察以下日志与现象：

1. owner 私聊触发后，是否仍出现：
   - `gate_mode=dry_run`
   - `execution_disabled`
   - `exec_status=planned`

2. 是否成功进入真实发送：
   - `exec_real_send=True`
   - 或出现明确发送成功迹象

3. OneBot v11 是否仍报以下网络错误：
   - `UnsupportedProtocol`
   - `HTTP request failed`

4. owner 私聊中是否能真实收到自动回传消息

## 八、建议

### 短期建议
- 重启后立刻做一次 owner 私聊冒烟测试
- 用最短指令验证 `reply_current -> current_session` 真发链路
- 若仍异常，继续顺着实际发送上下文定位 websocket / HTTP fallback 选择分支

### 中期建议
- 在项目文档中统一 OneBot v11 环境变量命名
- 清理旧字段兼容债，避免下一次再被“看起来配了、其实没生效”坑死
- 给 owner_action 链路补充更直观的状态日志，明确区分：
  - gate 拦截
  - delivery 未放行
  - sender 未启用
  - adapter 网络配置错误

## 九、一句话结案

本次事故不是单一配置错误，而是：

> **灰测门禁残留 + sender 放行链路 + OneBot v11 旧字段名配置失效** 三层问题叠加。

最终真凶落在：

> **`.env` 仍使用旧 OneBot 字段名，导致 v11 适配器未正确吃到主动发消息配置。**

—— 事故文档完。

## 十、后续现场补充（NapCat live 配置误判）

在完成 `.env` 与 OneBot v11 字段名修复后，owner 私聊自动回传链路已恢复，`测试4`、`测试厕所` 等冒烟消息均可正常收发。

但后续复验中又出现新的误导性现象：

- 日志一度仍持续出现 `403 Forbidden`
- 重启瞬间出现过 `Duplicate bot connection with id 3940223711`
- 现场一开始误以为：此前已修改的 NapCat 配置已经被当前运行实例实际加载

复盘后确认，这一段的真问题不是 NoneBot 主链，而是 **NapCat live 配置判断错位**。

### 1. 误判点

前面排障时，先改到了一份并非当前 systemd 实例实际吃到的配置文件，因此虽然“看起来改过了”，但运行中的 3940223711 仍会继续拉起旧的反向 WebSocket 配置。

也就是说：

- 改动落到了旁路文件
- 当前活实例吃的是另一份 live 配置
- 所以重启后 `403` 仍会继续刷，造成“像是改动没生效”的假象

### 2. 真正病灶

最终确认，需要处理的不是顶层同名字段残留，而是 live 配置中的：

- `network.websocketClients`

该字段内仍保留反向 WebSocket 目标，导致 NapCat 启动后继续主动向 NoneBot 的 `/onebot/v11/ws` 发起连接。

这会带来两个典型表象：

1. 若主链已存在，会在重启切换时短暂打出：
   - `Duplicate bot connection with id 3940223711`
2. 若反向链路状态异常或被拒，会周期性打出：
   - `403 Forbidden`

### 3. 最终修复动作

对当前 live 配置做了正刀修复：

- 将 `network.websocketClients` 清空为 `[]`

修复后重启 NapCat，再做 owner 私聊冒烟验证。

### 4. 修复后结果

复验结果：

- `测试4` 可正常收发
- `测试厕所` 可正常收发
- `403 Forbidden` 停止连发
- 未再持续出现 `Duplicate bot connection`
- 主连接保持正常，`Bot 3940223711 connected` 仍可见

说明：

> **这次尾巴问题的根因，不是主发送链路再次损坏，而是 NapCat live 配置里残留的反向 WebSocket 客户端未清干净。**

### 5. 本次事故最终完整结论

本次链路异常实际由两段问题前后串联组成：

1. **前段真故障**：`.env` 仍使用旧 OneBot v11 字段名，导致主动发送配置未被适配器正确加载
2. **后段尾巴故障**：NapCat 当前 live 配置中的 `network.websocketClients` 残留，导致 403 / duplicate 假象持续干扰判断

最终收口结论：

> **前段修 `.env`，后段清 live 配置；两刀都砍中后，owner 私聊链路恢复，403 停止，NapCat/NoneBot 主链稳定。**
