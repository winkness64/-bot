# WEBUI SSE STREAMING FIX RECORD - 2026-06-18

日期：2026-06-18  
状态：已修复 / 已验证  
定位：记录 8787 切换 NoneBot 真 SSE 透传后，NoneBot 内部 SSE 路由启动炸裂的根因、修法与后续工程约定。

---

## 1. 本次问题所在阶段

本轮主线施工已完成两步：

1. NoneBot 主插件侧新增内部 SSE 接口：`/yy/api/chat/send_stream`
2. 8787 在役脚本已从 `probe_fallback` 假流切换到该 SSE 接口真透传

8787 侧补丁本身方向正确，但在联通自检时出现异常：

- 8787 服务侧代码语法通过
- WebUI 服务可启动
- 但本地打 `/yy/api/chat/send_stream` 时出现超时/不可用表现
- 继续排查后确认：**真正炸点不在 8787，而在 NoneBot 新 SSE 路由本身的声明方式**

---

## 2. 根因

问题函数存在类似声明：

```python
async def _yy_internal_chat_send_stream(...) -> StreamingResponse | JSONResponse:
```

这在 Python 语法层面没问题，但在当前 FastAPI + Pydantic v1 组合下会触发错误推断：

- FastAPI 会尝试从函数返回类型推断 `response_model`
- `StreamingResponse | JSONResponse` 属于 PEP 604 联合类型
- 该联合类型不是一个可被 Pydantic v1 正常接收的字段模型
- 结果是：**应用启动期/路由注册期就可能炸掉**，导致 SSE 端点不可正常提供服务

一句话：

**不是业务逻辑炸了，是框架把“返回类型注解”误当成了响应模型定义。**

---

## 3. 修复方式

修法很小，但很关键：

在该 FastAPI 路由装饰器上显式加：

```python
response_model=None
```

核心意义：

- 明确告诉 FastAPI：**不要从函数签名推断响应模型**
- 该路由按实际返回对象工作
- `StreamingResponse` / `JSONResponse` 这种运行时响应对象不再被错误送去做 Pydantic 模型推断

这次修复的本质不是改业务，而是**关闭框架的错误自动推断**。

---

## 4. 修复后验证结果

本轮回报确认通过项：

- `py_compile`：通过
- NoneBot 服务启动：通过
- 启动后无 error / exception / traceback
- NapCat Bot `3940223711 connected`：正常
- SSE 端点 `/yy/api/chat/send_stream`：HTTP 200
- 因此 8787 -> NoneBot 的真 SSE 透传主链路恢复成立

结论：

**8787 主桥已通，NoneBot 本地 SSE 口已复活。**

---

## 5. 责任边界复盘

这次需要明确区分两层：

### 5.1 8787 侧

8787 的改造方向正确：

- 从 `probe_fallback` 假流切换到 `/yy/api/chat/send_stream`
- 由本地手搓事件改为上游 SSE 原样透传
- 这一步是对的，也是未来 Agent Bus 总控形态的正确方向

### 5.2 NoneBot 侧

真正导致“改完看起来又挂了”的直接炸点，是 NoneBot 新路由定义里：

- 使用了 `StreamingResponse | JSONResponse` 联合类型注解
- 但没有显式禁止 FastAPI 推断 `response_model`

所以这次事故不应误判成：

- SSE 设计方向错误
- 8787 真透传方案错误
- WebUI 流式主线不可行

实际只是：

**新 SSE 路由落地时踩中了 FastAPI/Pydantic v1 的类型推断坑。**

---

## 6. 后续工程约定

以后在本项目内，凡是 FastAPI 路由满足以下任一条件：

- 返回 `StreamingResponse`
- 返回 `JSONResponse`
- 返回 `Response` / `FileResponse` / `RedirectResponse` 等响应对象
- 返回类型写成联合类型，如 `A | B` / `Union[A, B]`
- 返回值本身不是准备交给 Pydantic 生成 schema 的普通数据模型

统一按以下规则处理：

### 规则 1：优先显式加 `response_model=None`

避免 FastAPI 从签名乱猜响应模型。

### 规则 2：流式接口不要把复杂响应对象联合类型喂给 Pydantic v1

如果只是表达“运行时可能返回两类 Response 对象”，那是工程注解，不该让框架拿去生成模型。

### 规则 3：对内部桥接 / SSE / 文件 / 重定向类接口，优先把“实际响应行为”放在实现里，不依赖自动 schema 推断

这些接口更偏基础设施，不是纯 CRUD 数据口。

### 规则 4：新增流式路由后，必须补最小启动验证

至少检查：

- `py_compile`
- 服务能启动
- 路由返回 200 / 合法 content-type
- 无启动期 traceback

---

## 7. 对当前主线的最终定性

这次修复完成后，可以把当前链路定性为：

- **8787 总控 SSE**：继续作为未来 Agent Bus 的统一前台事件壳
- **NoneBot `/yy/api/chat/send_stream`**：作为本地人格/执行入口的正式 SSE 事件口
- **`probe_fallback`**：退居诊断与探针层，不再充当正式聊天主链路

因此，本轮不是推翻前案，而是把施工中踩到的框架坑补平。

---

## 8. 一句话归档

**这次炸点不是 SSE 方案错，也不是 8787 方向错，而是 FastAPI/Pydantic v1 对 `StreamingResponse | JSONResponse` 返回类型推断误伤；补上 `response_model=None` 后，NoneBot SSE 口恢复，8787 真流主桥成立。**


---

## 9. 最小联调说明（留给后续排障）

以下只保留最小必要验证口径，用于确认 SSE 路由与 8787 主桥是否仍存活。

### 9.1 直接验证 NoneBot SSE 入口

建议验证要点：

- 请求方法：`POST`
- Header 至少带：`Accept: text/event-stream`
- 预期：HTTP `200`
- 预期响应头：`content-type: text/event-stream`
- 预期首批事件中应尽快出现：
  - `proxy_open`
  - `session_id`

如果连接已建立但长时间 0 字节：

- 先看服务是否为旧版本未重载
- 再看客户端是否缓冲输出
- 再看上游调用链是否根本未进入流式回调

### 9.2 验证 8787 主桥

建议验证要点：

- 8787 不再手搓假流事件
- `yy_test_host` 分支应直连 `/yy/api/chat/send_stream`
- 页面侧应能收到上游 SSE 原样事件，而非旧 `probe_fallback` 拼装事件

### 9.3 最小通过标准

满足以下条件即可判定主链路恢复：

1. NoneBot 服务启动正常
2. 无启动期 `error/exception/traceback`
3. SSE 入口返回 `200`
4. 能看到首个 SSE 事件输出
5. 8787 页面或调用侧能收到透传流

---

## 10. 同类风险巡检结果

本轮对项目源码与测试目录做了联合返回类型快速巡检，关键命中如下：

- 命中位置：`src/plugins/yangyang/__init__.py`
- 命中函数：`_yy_internal_chat_send_stream`
- 命中声明：`-> StreamingResponse | JSONResponse`

当前结论：

- **这轮只发现这一处同类显式雷点**
- 且该路由装饰器已补上 `response_model=None`
- 因此当前已知启动级炸点已被封口

后续如果继续新增 FastAPI 路由，尤其是：

- SSE
- 文件下载
- 重定向
- 多类 `Response` 对象条件返回

统一默认先检查两件事：

1. 是否误用了 `A | B` / `Union[A, B]` 作为可被框架推断的返回类型
2. 是否已显式加上 `response_model=None`

---

## 11. 本次补充归档结论

这次主线已经形成可复用工程约定：

- **流式桥接方案成立**
- **8787 真 SSE 透传方向成立**
- **FastAPI/Pydantic v1 的返回类型推断坑已确认并留档**
- **后续新增同类路由时，默认显式禁用 response_model 自动推断**

一句话：

**以后谁再在流式路由上喂 `StreamingResponse | JSONResponse` 却不关自动推断，谁就会把同一颗雷重新踩响。**
