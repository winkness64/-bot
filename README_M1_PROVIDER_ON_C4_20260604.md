# yangyang M1 Provider on C4 Closure 20260604

本补丁包用于在 **C4 Closure Full** 基线上应用 M1 Provider 可插拔架构与两处日志 `%s` 小修。

## 基线

- C4 Closure Full 包：`dist/patches/yangyang_c4_closure_fix_20260604_full.tar.gz`
- C4 Closure Full SHA256：`369702c2f5e1bb8bb94c091e18e45bf02e0e6f57c2875dbf9fa1ae6353356c17`
- 旧包 `yangyang_c4_closure_fix_20260604.tar.gz` 漏 `candidate_extractor.py`，不可作为本补丁基线。

## 覆盖方式

本包带顶层目录。进入仓库根目录后执行：

```bash
tar -xzf dist/patches/yangyang_m1_provider_on_c4_closure_20260604.tar.gz --strip-components=1
```

生产灰度前建议先备份 `src/plugins/yangyang/data/runtime_config.json`。若宿主机已有本地运行时开关，请保持本地语义，仅合并/确认 `providers` 配置块，不要误覆盖生产私有配置。

## 日志 `%s` 修复

只修日志格式，不改变 C4 检索注入语义。

1. `src/plugins/yangyang/memory/core.py`
   - 原日志：`MemorySystem: build_memory_prompt user_id=%s session_id=%s preview=%s`
   - 修复：提前生成 `preview = escape_log_preview(...)`，用 f-string 输出。
2. `src/plugins/yangyang/core/prompt_builder.py`
   - 原日志：`PromptBuilder: memory_prompt_preview target_uid=%s session_id=%s preview=%s`
   - 修复：提前生成 `resolved_session_id` / `preview`，用 f-string 输出。

## M1 Provider 架构说明

- `ModelProvider` / `ProviderResponse` 定义统一 provider 协议与返回结构。
- `DeepSeekV4Provider` 封装 DeepSeek/OpenAI-compatible 调用，保持懒加载 openai client。
- `MockProvider` 用于本地单测和 provider 注入验证。
- `MiniMaxM2Provider` 仅是 M1 占位：默认 `available=False`，`complete()` 直接抛 `NotImplementedError`，不接真实 MiniMax 调用。
- `ModelRouter` 保留 tier fallback、敏感错误脱敏 fallback、本地安全模板，并通过 `providers.<tier>` 读取 provider/model/timeout/cooldown 配置。
- `RuntimeConfig.DEFAULTS` 与 `runtime_config.json` 保留 providers 配置，`m2_7` 默认 disabled。

## 测试结果

在开发仓库执行：

```bash
python3 -m py_compile \
  src/plugins/yangyang/memory/core.py \
  src/plugins/yangyang/core/prompt_builder.py \
  src/plugins/yangyang/core/model/__init__.py \
  src/plugins/yangyang/core/model/provider_base.py \
  src/plugins/yangyang/core/model/provider_deepseek.py \
  src/plugins/yangyang/core/model/provider_minimax.py \
  src/plugins/yangyang/core/model/provider_mock.py \
  src/plugins/yangyang/core/model_router.py \
  src/plugins/yangyang/admin/runtime_config.py \
  src/plugins/yangyang/memory/candidate_extractor.py \
  tests/test_provider.py \
  tests/test_memory_phase_c.py
```

结果：`py_compile/json OK`

```bash
python3 -m pytest -q tests/test_memory_phase_c.py
```

结果：`40 passed in 0.52s`

```bash
python3 -m pytest -q tests/test_provider.py
```

结果：`5 passed in 0.17s`

```bash
python3 -m pytest -q tests/test_memory_phase_c.py tests/test_provider.py
```

结果：`45 passed in 0.45s`

额外全量 pytest 非本次准入项：当前仓库仍有历史失败，`6 failed, 134 passed, 119 errors in 17.15s`。主要为旧测试缺 `mods` fixture 以及既有 current-session/memory_phase_a 历史失败；本次未越界修复。

## 禁区确认

本次未触碰：

- 群聊闸门、owner gate、loop guard、kill switch
- C4 检索注入语义
- risk/sensitive 拦截恢复
- MiniMax / M2.7 / M2-her 真实调用
- Memory Query Router / Phase D
- 生产服务、宿主机重启
