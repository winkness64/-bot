# LLM Timeout / Streaming Checkpoint 2026-06-17 23:21:56 CST

## 结论
- 当前阶段适合做存档点并重启验证。
- 测试地基清理完成，现役测试不再直接依赖 `tests/mock_pipeline_test.py` 兼容壳。
- LLM timeout / streaming 第一阶段骨架已进主线：provider 契约补 `stream` 透传、timeout bucket 回归已补。

## 本阶段已确认事项
1. 现役 smoke 已切到 `tests/mock_pipeline_runtime.py`，`tests/mock_pipeline_test.py` 仅保留为历史兼容壳。
2. 关键回归已通过：此前记录为 `40 passed`，且 owner toolbox / sender / 私聊长文链路均通过。
3. 日志中的 warning 主要表现为：
   - 模型不可用时回落本地 safe template
   - 私聊 forward 不支持时降级 chunked text
   目前判断为既有兜底路径，不构成当前 checkpoint 阻塞。
4. 测试环境中仍存在 `openai package is required for OpenAICompatibleProvider` 告警路径，但未导致关键测试失败。

## 工程判断
- 这是一枚合格 checkpoint：
  - 地基已清
  - timeout / stream 骨架已落
  - 外围关键链路未被打穿
- 下一主线应继续推进：
  - provider 真流式消费
  - 首包超时 / 总超时 / 流中断超时语义
  - 结合 fallback 语义补回归

## 本次存档目的
- 为后续“真流式消费”开发提供可回退节点。
- 重启验证运行态装配是否正常，包括：
  - 服务启动
  - 配置加载
  - provider 初始化
  - 私聊基础链路

## 建议的重启后观察点
1. `yangyang-nonebot.service` 启动状态是否为 active(running)
2. 最近 journal 中是否出现新的 traceback / exception / import error
3. 私聊最小验证时是否出现异常 fallback 或启动期副作用

## 备注
- 当前工程目录不是 git 仓库，无法使用 commit hash 作为锚点。
- 本 checkpoint 采用留档文件 + 归档包的方式做阶段存档。
