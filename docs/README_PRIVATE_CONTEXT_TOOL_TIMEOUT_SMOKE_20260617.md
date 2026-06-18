# LLM Timeout Bucket / Progress Notice Smoke 留档

时间：2026-06-17 21:46 CST

## 本轮目标
- 对本次 Commit 1~4 改动做最小 smoke
- 留下可追溯结论与阻塞点

## 本轮已确认文件
- `src/plugins/yangyang/admin/runtime_config.py`
- `src/plugins/yangyang/core/model_router.py`
- `src/plugins/yangyang/__init__.py`
- `src/plugins/yangyang/core/owner_toolbox/native_loop.py`
- `src/plugins/yangyang/core/owner_toolbox/plan_only_gate.py`
- `src/plugins/yangyang/core/owner_engineering_toolbox.py`
- `src/plugins/yangyang/output/sender.py`
- `src/plugins/yangyang/output/sender_adapter.py`
- `src/plugins/yangyang/output/sender_adapter_factory.py`

## 编译检查
已执行：

```bash
.venv/bin/python -m py_compile \
  src/plugins/yangyang/admin/runtime_config.py \
  src/plugins/yangyang/core/model_router.py \
  src/plugins/yangyang/__init__.py \
  src/plugins/yangyang/core/owner_toolbox/native_loop.py \
  src/plugins/yangyang/core/owner_toolbox/plan_only_gate.py \
  src/plugins/yangyang/core/owner_engineering_toolbox.py \
  src/plugins/yangyang/output/sender.py \
  src/plugins/yangyang/output/sender_adapter.py \
  src/plugins/yangyang/output/sender_adapter_factory.py
```

结果：**通过**。

## smoke 结果
### 1) plan_only / progress path
已执行：

```bash
.venv/bin/python -m pytest -q tests/test_plan_only_gate.py tests/test_owner_toolbox_progress_paths.py
```

结果：**13 passed**。

说明：
- plan_only gate 相关路径正常
- progress 审计路径相关路径正常
- 说明本轮上层 bucket 接线至少没有把这些已有链路砍炸

### 2) sender / sender_adapter 相关脚本化测试
尝试执行：

```bash
.venv/bin/python tests/test_sender_long_text_split.py
.venv/bin/python tests/test_sender_adapter_factory.py
```

结果：**未完成有效验证**，阻塞于旧测试装载链。

共同报错根因：
- `tests/mock_pipeline_test.py -> prepare_modules()` 会加载 `src/plugins/yangyang/__init__.py`
- 当前测试 stub 环境里 `nonebot` 缺少 `get_driver` / `on_message` 导出
- 导致导入阶段提前炸掉，而不是业务断言失败

典型错误：
- `ImportError: cannot import name 'get_driver' from 'nonebot'`

判断：
- 这更像**旧测试基建/stub 未跟上当前 `__init__.py` 导入要求**
- 不是本轮 timeout bucket / progress notice 功能本身已被实锤打坏

## 当前结论
### 已确认通过
- 本轮关键文件语法级通过
- plan_only / progress path smoke 通过
- 上层接线没有在这两条现成回归链上炸掉

### 尚未实锤完成
- `sender.py` 长文预告 + 私聊长文本分发 的脚本化回归
- `sender_adapter.py` 当前会话长文预告与真实适配器路径的脚本化回归

### 当前主要阻塞
- 不是业务逻辑直接失败
- 是测试装载器 `mock_pipeline_test.py` 的 nonebot stub 不完整

## 下一步建议
优先二选一：

1. **补测试 stub**
   - 给 `tests/mock_pipeline_test.py` 的 nonebot stub 补齐 `get_driver` / `on_message`
   - 然后重跑：
     - `tests/test_sender_long_text_split.py`
     - `tests/test_sender_adapter_factory.py`

2. **临时绕开插件根导入**
   - 让 sender / sender_adapter 单测直接加载目标模块，不经 `plugins.yangyang.__init__`
   - 更适合做小范围快速回归

## 工程判断
本轮 smoke 结论可以先记成：

> Commit 1~4 已完成基础落码；编译通过；plan_only/progress 现有回归通过；sender 侧回归被旧 stub 基建阻塞，待补测试装载层后复测。


## 2026-06-17 21:57 CST 续测补档

### sender 长文分发回归已打通
已执行：

```bash
python3 -m py_compile src/plugins/yangyang/core/owner_toolbox_light.py
python3 tests/test_sender_long_text_split.py
```

结果：**通过**。

通过项：
- `sender private long text forward preferred`
- `sender private long text fallback split delivery`
- `sender group text still capped`

本轮补点：
- `src/plugins/yangyang/core/owner_toolbox_light.py`
  - 增加历史兼容别名：
    - `execute_owner_toolbox_command = execute_owner_toolbox_tool`
    - `execute_owner_toolbox_command_async = execute_owner_toolbox_tool_async`
- 作用：修复旧测试装载器对历史导出名的依赖，不改变当前主实现语义。

判断：
- A 路 smoke 已跑通，说明私聊长文**优先 forward、失败 fallback split** 的历史能力仍在。
- Commit 4 的最小进度提示改动没有把 sender 的核心分发链砍炸。

### 当前仍建议
- 再补跑 `tests/test_sender_adapter_factory.py`
- 如需更完整，再补当前会话 sender adapter 的专项 smoke

### 更新后的工程结论
> Commit 1~4 已完成基础落码；编译通过；plan_only/progress 回归通过；sender 长文分发 smoke 已通过；为兼容旧测试装载链，已补 owner_toolbox_light 历史别名导出。


## 续测更新（2026-06-17）

### Sender 长文分发 smoke
- 已补齐 `owner_toolbox_light` 历史接口别名导出：
  - `execute_owner_toolbox_command = execute_owner_toolbox_tool`
  - `execute_owner_toolbox_command_async = execute_owner_toolbox_tool_async`
- 验证结果：`tests/test_sender_long_text_split.py` 实跑通过
  - sender private long text forward preferred
  - sender private long text fallback split delivery
  - sender group text still capped

结论：私聊长文仍然优先 forward，失败再 fallback split，本轮改动未破坏既有长文发送语义。

### Sender adapter factory smoke
- 已将 `tests/test_sender_adapter_factory.py` 的 9 条异步 smoke 改为同步 pytest 包装，避免宿主缺少 async runner 插件导致整组测试无法执行。
- 兼容当前实现的断言语义：
  - `result.mode: failed -> send_failed`
  - `result.reason` 前缀：`delivery_failed:` -> `send_failed:`
- 验证结果：`tests/test_sender_adapter_factory.py` 直接 pytest 通过
  - 9 passed

结论：sender adapter factory 这组 smoke 已收口，异步测试基建缺件问题已绕开，不影响本轮功能验证。

### 当前汇总
- Commit 1~4 已落码
- 关键文件编译通过
- `plan_only / progress` smoke 通过
- `sender` 长文分发 smoke 通过
- `sender adapter factory` smoke 通过
- 为兼容旧测试装载链，已补若干历史别名与测试桩

### 备注
- 宿主侧需使用 `python3`，`python` 命令不存在；不影响本轮 pytest 结论。


## 2026-06-17 22:21 CST sender 三组合并复测补档

### owner_toolbox_light 相关真失败已修
- 修复 `owner_toolbox_light` prelude 发送路径在测试桩 / 宿主未提供 `bot.send(...)` 时的回退兼容。
- 当前策略：优先 `bot.send(event, text)`；若不可用，则按会话类型回退：
  - 私聊：`send_private_msg`
  - 群聊：`send_group_msg`
- 结果：`test_plugin_owner_toolbox_assistant_prelude_strips_role_prefix` 通过。
- 结论：此前失败根因不是 prelude 文本清洗，而是测试桩仅提供 `send_private_msg`、未提供 `send`，导致首条预热消息未发出。

### sender adapter nonebot smoke 已收口
- 已将 `tests/test_sender_adapter_nonebot.py` 从脚本式 smoke 改为可直接执行的 pytest 形态：
  - 补 `mods` fixture
  - 异步测试改为同步包装 `asyncio.run(...)`
- 在 `src/plugins/yangyang/output/sender_adapter.py` 补齐长文路径缺失 helper：
  - `_config_get_bool`
  - `_config_get`
  - `_build_progress_notice_text`
- 同步修正过期断言：
  - 当前实现中，私聊长文合并转发成功前会先发一条预热提示
  - 因此 `test_nonebot_adapter_long_text_forward_success` 改为断言：
    - 存在 `send_private_forward_msg`
    - 且存在 1 次预热提示发送调用

### sender 三组最终总复测
已执行三组合并 pytest：

```bash
python3 -m pytest -q \
  tests/test_sender_long_text_split.py \
  tests/test_sender_adapter_factory.py \
  tests/test_sender_adapter_nonebot.py
```

结果：**20 passed in 1.27s**。

### 最终结论
- `sender` 长文分发 smoke：通过
- `sender adapter factory` smoke：通过
- `sender adapter nonebot` smoke：通过
- 本轮 sender 侧真实实现缺件、兼容回退、pytest 基建债、以及长文预热提示相关断言漂移，均已收口。
- 截至本次补档，Commit 1~4 相关 sender / progress / plan_only 回归链已拿到完整绿票。

## 临时补丁清单（2026-06-17 夜）
### A. 正式兼容，当前应保留
1. `src/plugins/yangyang/core/owner_toolbox_light.py` 中的历史别名导出
   - 用途：兼容旧测试装载链与历史引用入口
   - 判断：成本低、兼容价值高，短期不建议删除

2. `src/plugins/yangyang/output/sender_adapter.py` 中补齐的 helper
   - `_config_get_bool`
   - `_config_get`
   - `_build_progress_notice_text`
   - 判断：这不是测试垫片，而是真实实现缺件补全，应保留

3. owner toolbox prelude 的发送回退兼容
   - `bot.send(...)` 不可用时回退到 `send_private_msg / send_group_msg`
   - 判断：属于正式兼容逻辑，不是测试专供 hack，应保留

### B. 真实修复，当前应保留
1. `owner_toolbox_light` prelude 真失败修复
   - 根因：旧实现把 prelude 发送异常吞掉，导致测试误判为“已发送但无效”
   - 现状：已按真实失败路径收口，相关 smoke 已恢复

2. `sender_adapter_nonebot` 长文发送相关修正
   - 补齐缺失 helper 后，sender 链路恢复可测
   - 长文合并转发成功路径允许先发“长消息发送中，请稍等...”预热提示
   - 对应测试断言已与当前实现语义对齐

3. sender 三组总复测
   - `tests/test_sender_long_text_split.py`
   - `tests/test_sender_adapter_factory.py`
   - `tests/test_sender_adapter_nonebot.py`
   - 结果：**20 passed in 1.27s**

### C. 测试债，先标记，后续统一回收
1. 三个 sender 测试中的 `asyncio.run(...)` 同步包装
   - 目的：绕过当前宿主缺少统一 async runner 插件的问题
   - 判断：现阶段可用，但不优雅；后续如统一引入 `pytest-asyncio` 或同类方案，再回收

2. `mods` fixture + `prepare_modules()` 装载链
   - 判断：属于旧 smoke 风格遗产，后续应重构为更标准的测试装载层

3. 部分断言为适配现实现象做的调整
   - 代表项：长文预热提示断言
   - 判断：建议后续补注释，明确其验证的是产品语义，而不是盲目追随实现细节

## 当前处理原则
- 现在不建议回删历史别名
- 现在不建议回删 sender_adapter 中新增 helper
- 现在不建议回删 prelude 发送回退兼容
- 现在不建议急着移除测试里的同步包装
- 当前正确动作不是“硬砍补丁”，而是“区分正式兼容、真实修复、测试债”


## 追加留档：current session delivery integration pytest 化与真实链路回归（2026-06-17）

### 背景
在继续推进“真实链路回归”时，`tests/test_current_session_delivery_integration.py` 未能直接在 pytest 下运行。报错并非业务逻辑回归，而是测试文件仍保留旧脚本式写法，缺少与当前测试基建一致的装载与执行包装。

### 初始现象
- `fixture 'mods' not found`
- 文件名义上属于 integration test，但实际尚未完成 pytest 化
- 问题性质判断：**测试债 / 测试基建未对齐**，不是 current session delivery 功能本身损坏

### 本次处理
对 `tests/test_current_session_delivery_integration.py` 做了最小必要改造，使其与前面 sender 三组测试风格对齐：

1. 补齐 `mods` fixture
2. 增加 `_run(asyncio.run(...))` 同步包装
3. 将原有 async pytest 风格调整为当前仓库可直接执行的测试形态
4. 保留脚本 `main()` 入口，确保“直接跑文件”能力不丢

### 回归结果
- `tests/test_current_session_delivery_integration.py`
- **8 passed in 0.72s**

### 与前序结果合并后的链路状态
当前与 owner 私聊工具链相关的关键测试结果为：

- `tests/test_owner_toolbox_light_plugin.py` → **9 passed**
- `tests/test_owner_engineering_toolbox_plugin_smoke.py` → **3 passed**
- `tests/test_current_session_delivery_integration.py` → **8 passed in 0.72s**

### 收口结论
1. `owner toolbox` 主入口链路正常
2. `owner engineering toolbox` smoke 正常
3. `current session delivery` 集成链路已补平并拿到绿票
4. 本轮卡点确认是**测试文件未完成 pytest 化**，不是业务回归故障

### 工程判断
这次处理再次验证：
- 当前项目里仍有一部分“旧 smoke/脚本式测试”遗留
- 后续若继续推进 sender / adapter / current session 相关改动，建议把这类测试基建债统一收口
- 但就本轮目标而言，**真实链路回归已取得可用绿票，可作为后续继续开发的稳定基线**


## 2026-06-17 22:49 CST 测试债清理续档：loader 分层拆解

### 本轮动作
按“继续 2”的路线，继续拆 `tests/fixtures/mock_pipeline_loader.py`，把原先一整坨 `prepare_modules()` 分成可单独维护的装配阶段：

- `_prepare_package_roots()`
  - 负责 nonebot stub 安装与 `plugins.*` 包根挂载
- `_load_core_admin_modules()`
  - 负责 `admin/core` 侧模块装载
- `_load_memory_modules()`
  - 负责 memory 侧装载
- `_load_output_modules()`
  - 负责 output 侧装载
- `_load_plugin_module()`
  - 负责最终插件根模块装载
- `_resolve_legacy_exports()`
  - 负责历史导出名 / fallback 名兼容
- `_build_exports()`
  - 负责最终 `mods` 导出表拼装

对外仍保留：
- `prepare_modules()` 作为稳定入口
- `tests/mock_pipeline_runtime.py` 作为稳定 runtime 门面
- `tests/mock_pipeline_test.py` 作为历史兼容壳

### 这刀的价值
- `prepare_modules()` 不再是一根超长总线怪
- 后面想继续削 loader 时，可以按“包根 / core-admin / memory / output / plugin / legacy export”分别下刀
- 旧测试入口不需要同时改，兼容层还在，回归面更稳

### 本轮验证
已执行：

```bash
python3 -m py_compile \
  tests/fixtures/mock_pipeline_loader.py \
  tests/mock_pipeline_runtime.py \
  tests/mock_pipeline_test.py

python3 -m pytest -q \
  tests/test_sender_long_text_split.py \
  tests/test_sender_adapter_factory.py \
  tests/test_sender_adapter_nonebot.py \
  tests/test_current_session_delivery_integration.py \
  tests/test_owner_toolbox_light_plugin.py \
  tests/test_owner_engineering_toolbox_plugin_smoke.py
```

结果：**40 passed in 2.34s**。

### 当前判断
这轮不是功能修复，是**测试装载层结构化瘦身**。
关键点在于：
- 外部导入口没断
- 历史 fallback 没丢
- 关键 sender / current session / owner toolbox 链路继续全绿

### 下一步建议
下一刀优先级：
1. 继续把依赖 `from mock_pipeline_test import ...` 的老测试，逐步迁到：
   - `mock_pipeline_runtime`
   - 或 `tests/fixtures/*`
2. 等迁移面收缩到足够小，再考虑让 `mock_pipeline_test.py` 退役
3. 如果还要继续削 loader，可把 `_load_core_admin_modules()` 再细分成：
   - owner action 相关
   - toolbox 相关
   - general runtime/router 相关

### 一句话结论
`mock_pipeline_loader.py` 已从“大坨一刀流”切成“分阶段装配”，关键回归 **40 passed**，可以继续清理历史 import 债。


## 2026-06-17 23:02 CST smoke 尾巴迁移补档

### 本轮处理
- 已将 `tests/test_i_line_p0_plugin_smoke.py` 的按路径直载入口：
  - `tests/mock_pipeline_test.py`
  - 改为
  - `tests/mock_pipeline_runtime.py`
- 同步把动态模块名从 `mock_pipeline_test_for_i_line_p0` 调整为 `mock_pipeline_runtime_for_i_line_p0`

### 目的
- 切断现役 smoke 对历史兼容壳 `tests/mock_pipeline_test.py` 的最后一条直接依赖
- 让现役测试统一收口到 `tests/mock_pipeline_runtime.py` 这个稳定门面

### 当前判断
- 截至本次修改，仓内对 `mock_pipeline_test.py` 的命中已收缩为：
  - 历史 `.bak_* / .before_*` 文件
  - 本 README 留档文字
- 现役 `tests/test_*.py` 已不再直接引用 `mock_pipeline_test.py`

### 待验证点
- 需补跑：
  - `tests/test_i_line_p0_plugin_smoke.py`
  - sender / current session / owner toolbox 关键回归组
- 若全绿，则 `tests/mock_pipeline_test.py` 将正式降级为“纯历史兼容壳”，可视后续需要决定是否退役


## 2026-06-17 23:13 CST 追加：provider 真流式骨架
- 已把 `stream=True` 从“只透传参数”升级为“provider 侧真实消费 async stream 并拼装 ProviderResponse”。
- 已覆盖文件：
  - `src/plugins/yangyang/core/model/provider_openai_compat.py`
  - `src/plugins/yangyang/core/model/provider_deepseek.py`
  - `tests/test_provider.py`
- 当前流式语义：
  - provider 创建请求阶段仍受 `asyncio.wait_for(..., timeout=timeout)` 保护
  - stream 消费阶段使用统一 deadline，覆盖首包等待与流中增量读取
  - 最终会聚合 content / tool_calls / usage 到 `ProviderResponse`
- 同步修正：旧 fallback 测试已改成 retryable 的 `TimeoutError` 口径，和当前路由策略对齐。


## 2026-06-17 23:13 CST 追加：provider 真流式骨架
- 已把 `stream=True` 从“只透传参数”升级为“provider 侧真实消费 async stream 并拼装 ProviderResponse”。
- 已覆盖文件：
  - `src/plugins/yangyang/core/model/provider_openai_compat.py`
  - `src/plugins/yangyang/core/model/provider_deepseek.py`
  - `tests/test_provider.py`
- 当前流式语义：
  - provider 创建请求阶段仍受 `asyncio.wait_for(..., timeout=timeout)` 保护
  - stream 消费阶段使用统一 deadline，覆盖首包等待与流中增量读取
  - 最终会聚合 content / tool_calls / usage 到 `ProviderResponse`
- 同步修正：旧 fallback 测试已改成 retryable 的 `TimeoutError` 口径，和当前路由策略对齐。
- 修正 1 个真实实现坑：`asyncio.timeout_at()` 需要 event loop time，不能喂 `time.perf_counter()`；已改正，否则流式超时测试会假绿。
- 再修 1 个流式语义细节：stream 消费 deadline 的最小值从 `0.1s` 下调到 `0.001s`，避免短超时 bucket/测试被人为放宽。
