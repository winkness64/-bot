PASS
Task: Factory auto-report notifier removal / scheduler noise cleanup
Status: CLOSED by owner decision and code removal

Goal:
- 彻底移除已废弃的黑奴工厂自动汇报定时通知链路。
- 停止 `FactoryNotifier: skip — already notified run ...` 这类每分钟轮询噪声日志。
- 保留工厂作为人工探路/草稿用途，不再承担自动回传主链职责。

Delivered:
- 已从调度器启动流程中移除 `factory_completion_notifier` job 注册。
- 已保留 notifier 模块与桥接测试资产，但默认运行链路不再触发该定时任务。
- 已更新调度测试，确认当前 scheduler 仅保留 memory pipeline 与 token usage hourly push。

Evidence:
- 代码落点：src/plugins/yangyang/tasks/__init__.py
- 测试覆盖：tests/test_factory_completion_notifier.py
- 复验结果：54 passed

Close summary:
- 漂♂总已明确判定自动工厂路线本轮不再继续推进。
- 本次采取“双杀版”：既不再注册 notifier job，也一并消除其周期性 skip 日志来源。
- 后续如需恢复自动汇报，应以新需求/新工单重开，不走当前残留逻辑复活。
