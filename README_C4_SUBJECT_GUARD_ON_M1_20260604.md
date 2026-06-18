# C4 Subject Guard on M1 Patch — 2026-06-04

## 基线

- 基于 M1 Provider on C4 Closure 灰度补丁：`dist/patches/yangyang_m1_provider_on_c4_closure_20260604.tar.gz`
- 基线 SHA256：`533d6fa9b08c51f4065909c74862dce04f3c7a810fd7d7737f2c866ce7a6bbfc`
- 基线定向测试：`tests/test_memory_phase_c.py tests/test_provider.py` -> `45 passed`

## 修复内容

本补丁修复 M1-on-C4 灰度中长期记忆命中后的主语漂移问题：

- 长期记忆条目如 `用户说：打绝区零（preference/game/private）` 描述的是当前用户/对话对象。
- 模型回答用户关于自己偏好、习惯、个人信息的问题时，应使用“你 / 用户 / 对方 / 阿漂”等用户主语。
- 不应把用户记忆改写成助手自己的经历，例如“我最近都在打绝区零”。
- 不确定时可使用“记忆里显示 / 你之前说过”。

## 实现方式

- 仅在长期记忆检索结果的 rendered prompt section 中增加主语约束说明。
- 保持原有 C4 检索、召回、打分、scope 过滤与注入开关语义不变。
- 不改长期记忆数据格式；原有 `- <summary>（<tags>）` 行格式保持。
- 对低字符预算增加精简约束文案，避免预算较小时完全丢失主语提示。

## 改动文件

- `src/plugins/yangyang/memory/retrieval.py`
- `tests/test_memory_phase_c.py`

## 测试结果

已执行：

```bash
python3 -m py_compile \
  src/plugins/yangyang/memory/retrieval.py \
  src/plugins/yangyang/memory/store.py \
  src/plugins/yangyang/core/prompt_builder.py \
  tests/test_memory_phase_c.py \
  tests/test_provider.py

python3 -m pytest -q tests/test_memory_phase_c.py tests/test_provider.py
```

结果：

```text
46 passed
```

测试数由基线 45 增至 46，新增覆盖 rendered memory prompt 包含“当前用户 / 不是助手经历 / 不要改成我 / 你之前说过”类主语约束。

## 覆盖方式

补丁包带顶层目录 `yangyang_c4_subject_guard_on_m1_20260604/`。

在仓库根目录执行：

```bash
tar -xzf dist/patches/yangyang_c4_subject_guard_on_m1_20260604.tar.gz --strip-components=1
```

或从任意路径指定目标仓库：

```bash
tar -xzf /path/to/yangyang_c4_subject_guard_on_m1_20260604.tar.gz \
  -C /AstrBot/data/workspaces/default_FriendMessage_335059272/yangyang_nonebot_mvp \
  --strip-components=1
```

## 禁区确认

本补丁未修改：

- 群聊闸门
- owner gate
- loop guard
- kill switch
- runtime_config
- C4 检索 / 召回 / 打分语义
- MiniMax 真实调用
- Memory Query Router
- Phase D
- 宿主机生产服务
