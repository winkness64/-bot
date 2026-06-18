# Yangyang Memory M1 + C3.1 Stable 整包（2026-06-04）

本包是基于 **C3.1 结构化回忆路由真机灰度通过** 后的 stable 整包，包含今天上午截至 First-person Query Disambiguation 小补丁后的完整稳定代码；不是只包含最后一层小补丁。

## 包含能力

- **C4 Closure Full**：长期记忆检索注入闭环与灰度控制。
- **M1 Provider on C4**：Provider/Model Router 相关接入代码。
- **C4 Subject Guard on M1**：长期记忆 prompt 主语约束，避免把用户记忆说成助手自己的经历。
- **C3.1 Structured Memory Query Router**：显式自我记忆问句路由到结构化 slot，例如 drink/game 等。
- **First-person Query Disambiguation**：第一人称问句歧义约束：`我喜欢喝什么`、`我晚上喜欢打什么游戏` 等默认解释为用户在询问自己的记忆，直接用用户主语回答；只有明确 `你喜欢/你喝/你玩` 才理解为询问助手偏好。

## 旧包层级关系

旧补丁层级为：

`C4 Full -> M1-on-C4 -> Subject Guard -> C3.1 -> Disambiguation`

本 stable 整包已合并上述层级的当前稳定成果，方便后续部署不再逐层打补丁。

## 覆盖方式

本 tar 包带顶层目录 `yangyang_memory_m1_c3_1_stable_20260604/`。在目标仓库根目录覆盖时可使用：

```bash
tar -xzf dist/patches/yangyang_memory_m1_c3_1_stable_20260604.tar.gz \
  -C /path/to/yangyang_nonebot_mvp \
  --strip-components=1
```

覆盖前建议先备份当前工作树或至少备份将被覆盖的文件。

## runtime_config 注意事项

包内带有：

`src/plugins/yangyang/data/runtime_config.json`

该文件用于记录本次稳定代码对应的参考配置状态。**宿主机部署时不要盲目覆盖整份 runtime_config。**

建议流程：

1. 先备份宿主机现有 `runtime_config.json`。
2. 以宿主机现有 runtime_config 为准。
3. 如确需同步 Provider 配置，只合并 `providers` 相关字段或手工比对合并。
4. 保持 C4 长期记忆灰度开关、owner/private-only 状态和群聊注入状态不被意外改变。
5. 不借此包扩大群聊注入，不开启群聊主动。

## 测试结果

在当前仓库执行：

```bash
python3 -m py_compile \
  src/plugins/yangyang/memory/retrieval.py \
  src/plugins/yangyang/memory/store.py \
  tests/test_memory_phase_c.py

python3 -m pytest -q tests/test_memory_phase_c.py tests/test_provider.py
```

结果：

```text
52 passed in 0.57s
```

其中新增覆盖：rendered memory prompt 在 `我喜欢喝什么` 这类第一人称记忆问句下包含第一人称歧义约束；既有 C1 问句防线、Subject Guard、C3.1 drink/game slot 映射保持通过。

## 包内主要文件范围

- `src/plugins/yangyang/memory/*.py`
- `src/plugins/yangyang/core/prompt_builder.py`
- `src/plugins/yangyang/core/model_router.py`
- `src/plugins/yangyang/core/model/*.py`
- `src/plugins/yangyang/admin/runtime_config.py`
- `src/plugins/yangyang/data/runtime_config.json`
- `src/plugins/yangyang/__init__.py`
- `tests/test_memory_phase_c.py`
- `tests/test_provider.py`
- `README_MEMORY_M1_C3_1_STABLE_20260604.md`

## 禁区未触碰

本包不包含以下变更：

- 不做 cron / 定时哨兵。
- 不碰群聊闸门、owner gate、loop guard、kill switch。
- 不扩大群聊注入，不开启群聊主动。
- 不改变 C1 写入语义，不新增写入类型。
- 不清洗/修改真实数据文件。
- 不改 runtime_config 语义。
- 不接 MiniMax 真实调用。
- 不做主动陪伴、不做 C1.1 open_loop、不做 Phase D。
- 不操作宿主机生产服务，不重启。
