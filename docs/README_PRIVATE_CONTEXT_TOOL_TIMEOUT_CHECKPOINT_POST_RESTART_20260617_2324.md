# LLM Timeout / Streaming Checkpoint 补档（重启后补记）

时间：2026-06-17 23:24 CST

## 背景
- 本轮原计划：先留档做 checkpoint，再重启观察运行态。
- 实际情况：服务已先行重启，随后补做正式留档。
- 因此本文件用于把“本次阶段存档点”补齐，作为后续继续推进真流式消费前的可回退锚点。

## 本次 checkpoint 定位
- 阶段：LLM timeout / streaming 主线第一阶段
- 状态：可进入下一主线开发
- 用途：为后续 provider 真流式消费、首包/总时长/流中断超时语义落地提供回退基线

## 已确认事实
1. 测试地基已清理到可安全推进主线：
   - 现役 smoke 已切到 `tests/mock_pipeline_runtime.py`
   - `tests/mock_pipeline_test.py` 保留为历史兼容壳，不再被现役 `test_*.py` 直接依赖
2. timeout / stream 第一阶段骨架已进主线：
   - provider 契约增加 `stream: bool = False`
   - router 将 `stream` 真正透传到 provider
   - timeout bucket override 回归已补
3. 关键回归已通过：
   - 已有记录为 `40 passed`
   - owner toolbox / sender / 私聊长文链路均已通过
4. 目前已知 warning 主要为既有兜底：
   - 模型不可用时回落 local safe template
   - 私聊 forward 不支持时降级 chunked text
   - 测试环境缺少 openai 依赖时走告警路径
   以上均未构成当前 checkpoint 阻塞

## 重启前后语义说明
- 原计划中的“重启验证”已经发生，但先于本补档。
- 因此本 checkpoint 的语义是：
  - **以当前已重启后的代码状态为阶段存档点**
  - 不是“重启前快照”
- 若后续真流式消费开发需要回退，可回到本轮留档文件与归档包对应状态。

## 工程结论
- 当前节点可作为正式 checkpoint。
- 可以继续进入下一刀：
  1. provider 真流式消费
  2. 首包超时
  3. 总超时
  4. 流中断超时
  5. 配套 fallback 语义回归

## 备注
- 当前工程目录不是 git 仓库，无法用 commit hash 锚定。
- 本次采用“留档文件 + 归档包”作为阶段存档方式。
