# prompt追加常用路径清单

> 用途：给 WebUI / prompt / 工单追加内容时，直接给 I叔明确文件路径，减少来回确认。

## 1. 项目根目录
- `/mnt/warehouse/opt_moved/yangyang_nonebot`

## 2. 文档目录
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs`

## 3. 常用文档落点
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs/老年痴呆治疗.md`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs/webui_work_guide.md`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs/README_AGENTBUS_8787_WEBUI_PATCH_PLAN_20260618.md`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs/README_PRIVATE_CHAT_SESSION_STATE_WORKORDER_20260618.md`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/docs/README_PRIVATE_CHAT_SESSION_STATE_RESTART_SMOKE_WORKORDER_20260618.md`

## 4. 当前工单 / 结果
- `/mnt/warehouse/opt_moved/yangyang_nonebot/current_task.md`
- `/mnt/warehouse/opt_moved/yangyang_nonebot/current_task_result.md`

## 5. 运行时配置
- `/mnt/warehouse/opt_moved/yangyang_nonebot/data/runtime_config.json`

## 6. 推荐给 I叔的指令格式
直接按下面格式发，最省事：

```text
追加到 /mnt/warehouse/opt_moved/yangyang_nonebot/docs/某文件.md ：这里是你要补的话
```

```text
把这句补到 /mnt/warehouse/opt_moved/yangyang_nonebot/current_task.md ：这里是你要补的话
```

```text
往 /mnt/warehouse/opt_moved/yangyang_nonebot/data/runtime_config.json 对应字段里加：这里是配置要求
```

## 7. 约定
- 只要路径明确，我就可以直接写。
- 如果你只说“那个 txt / 那个文件 / 上次那个”，我还得先反查候选。
- 文档类内容优先放 `docs/`。
- 工单推进内容优先放 `current_task.md` 或 `current_task_result.md`。
- 配置修改单独点名 `runtime_config.json`，避免误写。

## 8. 当前结论
这份清单的目的不是炫路径，是减少沟通损耗。oh~卖♂萧的，路径讲明白，执行速度就上来了，ass♂we♂can。
