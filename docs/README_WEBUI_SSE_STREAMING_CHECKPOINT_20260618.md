# WEBUI SSE STREAMING CHECKPOINT - 2026-06-18

## 状态
- 已在 NoneBot 主插件侧新增内部 SSE 接口：`/yy/api/chat/send_stream`
- 接口定位：localhost-only / internal bridge only
- 事件骨架已对齐 WebUI 现有消费模式，当前最小事件集合：
  - `proxy_open`
  - `session_id`
  - `plain`
  - `agent_stats`
  - `end`
  - `error`
  - `proxy_closed`
- 调用形态：通过现有 `router.call(... allow_streaming=True, stream_callback=...)` 输出流式 chunk

## 当前判断
- `/yy/api` 虽然不是新的对外产品接口，但作为 8787 ⇄ NoneBot 内部桥接壳子非常合适
- 现有代码已经具备三段可焊接结构：
  1. 主插件可直接注册内部路由
  2. localhost-only 访问控制已存在
  3. model router 侧已有 streaming callback 能力

## 已知剩余工作
1. 把当前 SSE 端点相关测试夹具修平，拿到稳定自检结果
2. 去 8787 WebUI 本地 NoneBot 分支，把原来的 `probe_fallback` 包壳逻辑改成直连 `/yy/api/chat/send_stream`
3. 保证前端继续按既有 SSE 事件透传消费，不额外改前端协议

## 下一步施工方向
- 先定位 8787 代码里 instance 命中本地 NoneBot 的分支入口
- 找到当前 `probe_fallback` 调用和手工 SSE 包装位置
- 改造成：
  - 8787 -> POST NoneBot `/yy/api/chat/send_stream`
  - 请求头保留 `Accept: text/event-stream`
  - 上游 chunk 原样透传到前端

## 备注
- `webui_work_guide.md` 继续保留，不覆盖旧思路
- 当前文档仅作 2026-06-18 施工检查点，后续如打通 8787 再补第二份实施记录


## 补充备注（漂♂总口述）
- 8787 WebUI 的价值不只是单点聊天，而是已经打通：黑奴工厂、工厂日志、Nekro 日志、AstrBot 日志、NoneBot 日志，以及 AstrBot 透传。
- 可以把 8787 视为整套赛博战舰的总台 / 舰桥。
- 后续施工判断应以“总台统一接管与透传能力”作为设计前提，不把它误判成单一聊天壳子。
