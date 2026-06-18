# SSE send_stream Disconnect/Teardown Patch\n\n## 结论\n\n本补丁针对 `src/plugins/yangyang/__init__.py` 里的 `/yy/api/chat/send_stream` 做最小修复，目标是降低 `8787/QQ 内嵌工作台 -> 8080` 真 SSE 桥把 Web 面拖进半死僵局的风险。\n\n## 病灶\n\n原实现存在三处高危点：\n\n1. 没有 `request.is_disconnected()` 断连感知。\n2. `queue.get()` 轮询在客户端已断时仍可能盲等。\n3. `finally` 中继续 `yield proxy_closed`，会把收尾发送和异常关闭路径缠在一起。\n\n## 本次修复\n\n- 在 `_event_stream()` 主循环中增加 `await request.is_disconnected()` 检查。\n- 客户端断开后记录日志并立即跳出流循环。\n- 在清理阶段先 `finished.set()`，再 cancel 后台模型任务。\n- 为 `_run_model_call()` 增加 `asyncio.CancelledError` 分支，取消时不再误记为普通失败。\n- 在 `_on_stream_delta()` 和模型调用成功回填前增加 `finished.is_set()` 守卫，避免断流后继续往队列堆事件。\n- 不再在 `finally` 中发送 `proxy_closed`；仅在正常收尾且客户端未断开时发送。\n\n## 预期效果\n\n- WebView/SSE 客户端半途断开时，后台任务能更快收口。\n- 降低残留流式连接长期占住 HTTP/ASGI 处理链的概率。\n- 避免收尾阶段再次 `yield` 放大关闭路径异常。\n\n## 回归覆盖\n\n新增 `tests/test_send_stream_sse_guardrails.py`，约束：\n\n- 源码必须含 `request.is_disconnected()`。\n- 源码必须显式处理 `asyncio.CancelledError`。\n- `proxy_closed` 不允许再出现在 `finally:` 清理块内。\n\n## 应用说明\n\n代码补丁生效仍需要重启 NoneBot 进程加载新代码。\n
## 操作流程（给秧秧执行）

### 一、重启前检查

1. 确认补丁文件已在位：
   - `src/plugins/yangyang/__init__.py`
   - `tests/test_send_stream_sse_guardrails.py`
2. 如需本地静态自检，执行：
   - `python3 -m py_compile src/plugins/yangyang/__init__.py tests/test_send_stream_sse_guardrails.py`
   - `./.venv/bin/python -m pytest -q tests/test_send_stream_sse_guardrails.py`
3. 若上述两项通过，再执行 NoneBot 进程重启。

### 二、重启后验收顺序

1. 先看服务状态与最近日志：
   - 确认进程已正常拉起。
   - 确认没有新的 `traceback`、`import error`、`syntax error`。
   - 重点关注是否有 `CancelledError`、ASGI/StreamingResponse 异常上浮。

2. 先测普通 HTTP 面是否恢复：
   - `/openapi.json`
   - `/`
   - `/yy/api/model/status`

   预期：
   - 能快速返回。
   - 即使业务失败，也应返回正常状态码/JSON；不应再出现“TCP 已连上但长时间 0 字节无响应”。

3. 再测 SSE 主桥：
   - `POST /yy/api/chat/send_stream`

   验收点：
   - 请求发起后能开始回流。
   - 客户端中途断开后，服务端不会长期卡死。
   - 断开一次后再次请求，8080 不应被前一条残留连接拖进僵局。

4. 最后复现原始工作台链路：
   - 使用 QQ 内嵌页 / 8787 / 本地工作台发起一次正常请求。
   - 中途关闭页面、切换页面或主动断开一次。
   - 随后立即再次测试 `/openapi.json`。

   预期：
   - `/openapi.json` 仍能快速返回。
   - 说明 SSE 断连不会再把整个 8080 Web 面拖进半死状态。

### 三、回报时最少需要带回的结果

1. `/openapi.json` 是否秒回。
2. `send_stream` 正常跑完一轮时是否报错。
3. 中途断开 SSE 后，8080 是否还会出现“能连上但不吐字节”。
4. 最新日志里是否仍有以下异常关键词：
   - `streaming response error`
   - `ASGI send exception`
   - `task destroyed but pending`
   - `CancelledError` 上浮

### 四、若仍复现，下一步排查方向

1. 检查 8787 前端/桥接脚本是否存在重复建流、断开不 clean、页面切换后旧连接残留。
2. 继续排查 Uvicorn/FastAPI 层的 keep-alive、连接池或长连接关闭路径异常。
