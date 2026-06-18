# M2.2-B2-B3 · Owner Private Real Topic Boundary Gray Runbook

日期：2026-06-05  
目标：为 **owner 私聊真实 LLM topic boundary 小灰度**提供操作手册。  
范围：只做灰度方案、测试用例、观察点与回滚方案。  
硬限制：本文档不修改代码、不修改 `runtime_config`、不启用真实模型、不操作宿主机、不重启服务。

---

## 0. 当前基线

已知前置状态：

- `M2.2 Stable Candidate` 宿主机灰度通过。
- `B2-B async topic boundary integrated bundle` 宿主机部署与最小真机回归通过。
- B2-B integrated 包：

```text
dist/patches/yangyang_m2_2_b2b_async_topic_boundary_integrated_20260604.tar.gz
SHA256=11d4a9946ff55876a5356c4e0675409023ddfc62102d44065f337be036e6791a
```

- 主流程已切到：

```text
handle_explicit_memory_message_async
```

- 当前 runtime gate 默认关闭：

```text
memory_topic_boundary_enabled=None
topic_boundary_keys={}
```

- 默认关闭下行为等价 A3.1 规则版，真实 topic boundary 未触发。

---

## 1. 灰度前置条件

开始真实 LLM topic boundary 灰度前，必须逐项确认：

### 1.1 代码与测试基线

- B2-B integrated bundle 已部署。
- 定向测试通过：

```bash
python3 -m pytest -q \
  tests/test_memory_phase_c.py \
  tests/test_provider.py \
  tests/test_explicit_memory.py \
  tests/test_recent_message_records.py \
  tests/test_context_resolver.py \
  tests/test_topic_boundary_resolver.py \
  tests/test_topic_boundary_provider.py \
  tests/test_topic_boundary_gate.py \
  tests/test_async_explicit_handler.py
```

期望：

```text
146 passed
```

- `py_compile all yangyang` 无失败。
- 最小真机回归已通过：
  - direct write 正常；
  - contextual write 默认关闭下走 `recent_context_resolver_v1_rules`；
  - query 不写；
  - C3.1 绝区零命中；
  - 群聊 `记一下xxx` 不写主脑；
  - 无真实 topic boundary 调用。

### 1.2 备份

灰度前必须备份：

```bash
cd /opt/yangyang_nonebot
mkdir -p backups
cp src/plugins/yangyang/data/runtime_config.json \
  backups/runtime_config.json.bak_before_topic_boundary_gray_$(date +%Y%m%d-%H%M%S)
cp src/plugins/yangyang/data/memory/long_term/memories.jsonl \
  backups/memories.jsonl.bak_before_topic_boundary_gray_$(date +%Y%m%d-%H%M%S)
```

建议同时备份代码：

```bash
tar -czf backups/yangyang_before_topic_boundary_gray_$(date +%Y%m%d-%H%M%S).tar.gz \
  src/plugins/yangyang tests 2>/dev/null || true
```

### 1.3 服务与路径

灰度前确认：

- 服务名：

```text
yangyang-nonebot.service
```

- 重启方式：

```bash
systemctl restart yangyang-nonebot.service
```

- 状态检查：

```bash
systemctl status yangyang-nonebot.service --no-pager
```

- 日志查看方式按宿主机实际环境选择，例如：

```bash
journalctl -u yangyang-nonebot.service -f
```

或项目侧日志路径。

### 1.4 灰度范围

本次只允许：

```text
owner 私聊 only
```

禁止：

```text
群聊 topic boundary
非 owner topic boundary
群聊主动
群聊显式记忆
```

---

## 2. 建议开启配置（手动、临时、小流量）

> 注意：本 Runbook 只给出建议配置，不实际修改 `runtime_config`。

建议临时加入或更新以下 keys：

```json
{
  "memory_topic_boundary_enabled": true,
  "memory_topic_boundary_private_enabled": true,
  "memory_topic_boundary_model_tier": "v4_flash",
  "memory_topic_boundary_max_records": 8,
  "memory_topic_boundary_max_payload_chars": 600,
  "memory_topic_boundary_min_confidence": 0.65,
  "memory_topic_boundary_timeout_seconds": 15,
  "memory_topic_boundary_fallback_on_invalid": true,
  "memory_topic_boundary_fallback_on_error": true,
  "memory_topic_boundary_fallback_on_ambiguous": false
}
```

说明：

- 如果担心成本，可先用更便宜但可靠的 tier。
- 但 topic boundary 模型必须能稳定输出 JSON。
- 不建议一开始使用太弱模型，否则 `invalid_model_output` 会很多。
- `fallback_on_ambiguous=false` 是安全关键：模型判断多主题混杂时，不应回退 A3.1 规则版误写。
- `fallback_on_invalid=true` / `fallback_on_error=true`：模型坏输出或异常时回退 A3.1，保证基本功能不炸。

---

## 2.1 轻量 smoke 参数原则（2026-06-05 修订）

第一次真实灰度不要直接使用大窗口。实测发现：

```text
max_records=40
timeout_seconds=8
```

容易导致真实 topic boundary 模型超时。轻量 smoke 已验证以下参数可跑通 3 轮短窗口：

```json
{
  "memory_topic_boundary_max_records": 8,
  "memory_topic_boundary_timeout_seconds": 15,
  "memory_topic_boundary_max_payload_chars": 600
}
```

推荐爬坡顺序：

```text
阶段 1：max_records=8，timeout=15，3轮短窗口
阶段 2：max_records=12，timeout=15，3-6轮窗口
阶段 3：max_records=16，timeout=15~20，6轮窗口
阶段 4：max_records=24，timeout=20，长窗口
阶段 5：max_records=40，仅在前面稳定后再试
```

不要一上来 40 条 + 8 秒，这会让模型半夜跑马拉松。

## 3. 灰度测试用例

测试顺序必须从短窗口到长窗口，从简单到复杂。每个用例完成后检查日志和 `memories.jsonl`。

### A. 3 轮单主题 resolved

步骤：

1. owner 私聊连续聊 3 条同一话题，例如：

```text
今天 topic boundary 先测 3 轮短窗口。
这轮主要验证真实模型能找准同一话题。
如果成功，payload 应该只包含 3 轮短窗口验收内容。
```

2. 发送：

```text
把刚才我们的讨论内容记一下
```

期望：

- 日志出现真实 topic boundary 标识，例如：

```text
topic_boundary_resolver_v1_mockable
pending_topic_boundary_confirmation
```

或后续真实实现中的等价 resolver 标识。

- pending payload 只包含该话题。
- 不混入旧主题、query 句、bot 回复、确认词。
- 确认后写入：

```text
source=explicit_context_resolved
```

- evidence 包含 topic boundary resolver 标识、used_msg_ids、context_range。

### B. 6 轮单主题 resolved

目的：覆盖 A3.1 规则版做不到的长窗口。

步骤：

1. owner 私聊连续聊 6 条同一话题。
2. 中间可穿插 bot 回复。
3. 发送：

```text
把刚才我们的讨论内容记一下
```

期望：

- LLM 能选中完整 6 轮主题边界。
- payload 明显优于 A3.1 的 1-3 条规则版。
- pending 后再确认写入。

### C. 15 轮单主题 resolved

目的：验证 LLM topic boundary 是否真正优于固定条数规则。

步骤：

1. 围绕同一话题连续聊约 15 轮。
2. 发送：

```text
把刚才我们的讨论内容记一下
```

期望：

- LLM 不必复述所有 15 轮，但应抓住核心主题和结论。
- used_msg_ids 或 context_range 覆盖主要讨论段。
- payload 不超过 `memory_topic_boundary_max_payload_chars`。
- 没有明显遗漏关键结论。

### D. 多主题混杂 ambiguous

步骤：

1. 先聊主题 1。
2. 再聊主题 2。
3. 再聊主题 3。
4. 发送：

```text
把刚才那个记一下
```

期望：

- resolver 返回 ambiguous 或等价状态。
- bot 追问澄清。
- 不 pending 可确认写入。
- 不回退 A3.1 规则版。
- `memories.jsonl` 不新增该 ambiguous 测试记忆。

### E. 插入 query 句

复现之前观察点：规则版会把 query 句合入 payload。

步骤：

1. 聊一个主题。
2. 中间插入：

```text
你记得我昨天说了什么吗
```

3. 继续聊原主题。
4. 发送：

```text
把刚才我们的讨论内容记一下
```

期望：

- LLM 不把 query 句合入 payload。
- query 句仅作为插曲，不作为被记录主题。
- pipeline 仍然：

```text
raw_candidates=0
promoted=0
```

### F. invalid / model_error fallback

真实模型难稳定制造 invalid/model_error，不强测。

可选方式：

- 临时配置错误 tier；
- 或未来使用 mock 灰度；
- 或观察单测已覆盖。

期望：

- invalid/model_error 不导致 Traceback。
- 按配置回退 A3.1 规则版。
- 日志明确记录失败原因。

### G. direct / query / C3.1 / group boundary 回归

必须测：

1. direct write：

```text
记一下：topic boundary 灰度 direct 回归
```

期望：direct write，`source=owner_command`。

2. query 不写：

```text
你记得我昨天说了什么吗
```

期望：不触发 explicit write，走 C4/LLM。

3. C3.1 回归：

```text
我晚上喜欢打什么游戏
```

期望：命中绝区零，问句不写入。

4. 群聊边界：

```text
记一下topic boundary 群聊边界测试
```

期望：群聊不触发 topic boundary，不写 private_user。

---

## 4. 观察日志关键词

### 应该出现

开启 topic boundary 后，在 owner 私聊 contextual write 中应看到：

```text
topic boundary enabled decision
router.call tier
memory_topic_boundary_model_tier
topic boundary resolver status
pending_topic_boundary_confirmation
evidence resolver 标识
topic_boundary_resolver_v1_mockable
```

实际字段以代码日志为准。若当前代码日志不足，先补日志再真灰度。

### 不应该出现

```text
群聊 topic boundary 调用
非 owner topic boundary 调用
provider error 未被捕获
Traceback
ImportError
%s
%d
直接写入 without pending
model_call 在 direct write/query/audit 场景触发
```

### 若日志不足

如果无法判断是否真实走了 topic boundary，不要继续扩大测试。应先补日志，至少要能看到：

- gate decision；
- 是否调用 router；
- resolver status；
- fallback reason；
- used_msg_ids；
- pending action。

---

## 5. 失败处理

### 5.1 Traceback / provider error / 回复卡死

立即关闭：

```json
{
  "memory_topic_boundary_enabled": false
}
```

或删除全部 `memory_topic_boundary_*` keys。

然后重启：

```bash
systemctl restart yangyang-nonebot.service
```

确认：

```text
topic_boundary_keys={}
memory_topic_boundary_enabled=False/None
```

### 5.2 payload 明显错误

如果 pending payload 明显错误：

```text
不要确认
```

发送：

```text
取消
```

必要时等待 pending TTL 过期，或重启清空内存 pending。

### 5.3 错误写入

如果误确认或错误写入：

1. 备份当前 `memories.jsonl`。
2. 定位 entry id。
3. 删除该 explicit entry，或恢复备份。
4. grep 确认污染词消失。

### 5.4 服务无法启动

使用部署前代码备份回滚：

```bash
cd /opt/yangyang_nonebot
# 具体备份路径按实际填写，例如：
# backups/yangyang_before_topic_boundary_gray_YYYYMMDD-HHMMSS.tar.gz
```

恢复后重启服务。

---

## 6. 回滚步骤

### 6.1 配置回滚

将：

```json
"memory_topic_boundary_enabled": false
```

或删除所有：

```text
memory_topic_boundary_*
```

然后重启：

```bash
systemctl restart yangyang-nonebot.service
```

### 6.2 代码回滚

用部署前备份包恢复：

```text
/opt/yangyang_nonebot/backups/yangyang_before_topic_boundary_gray_YYYYMMDD-HHMMSS.tar.gz
```

若是回到 B2-B integrated 基线，可重新覆盖：

```text
yangyang_m2_2_b2b_async_topic_boundary_integrated_20260604.tar.gz
SHA256=11d4a9946ff55876a5356c4e0675409023ddfc62102d44065f337be036e6791a
```

### 6.3 数据回滚

方式一：删除测试 explicit entries。  
方式二：恢复灰度前备份：

```text
backups/memories.jsonl.bak_before_topic_boundary_gray_YYYYMMDD-HHMMSS
```

恢复前务必再次备份当前文件。

---

## 7. 成功判定

只有同时满足以下条件，才算 B2-B3 小灰度通过：

- owner 私聊真实 topic boundary 能处理 6 轮长窗口。
- owner 私聊真实 topic boundary 能处理 15 轮长窗口，并明显优于 A3.1 规则版。
- 多主题混杂 ambiguous 不错写。
- 插入 query 句不污染 payload。
- direct write 回归正常。
- query/audit 不写。
- C3.1 结构化回忆仍命中。
- 群聊边界不触发 topic boundary，不写主脑。
- 无 Traceback / ImportError / provider error。
- 无 `%s/%d` 日志残留。
- 成本可接受。

---

## 8. 是否进入下一阶段

通过 B2-B3 后，才考虑：

```text
继续优化 topic boundary prompt / JSON schema
memory grounding
alias/entity resolver
```

不建议立刻做：

```text
群聊 topic boundary
群友黑料库真实写入
亲密互动双层日志
主动陪伴
```

原因：真实 topic boundary 在 owner 私聊稳定前，不应扩大到群聊。

---

## 9. 最小灰度建议

第一次真实启用时，建议只做：

```text
3轮单主题
6轮单主题
多主题 ambiguous
插入 query 句
C3.1 回归
```

15 轮长窗口可以放第二轮，以免第一次点火同时验证太多变量。

## 9. 轻量 smoke 结果记录（2026-06-05 01:08）

真实 topic boundary async 链路轻量 smoke 已通过：

- 日志出现 `pending_topic_boundary_async`；
- resolver=`topic_boundary_resolver_v1_mockable`；
- action=`pending_topic_boundary_confirmation`；
- 无 TimeoutError/model_error/fallback/invalid_model_output/provider error；
- payload 只包含 3 轮短窗口验收内容，未混入 bot 回复、旧 B2-B 测试、绝区零、确认词或命令本身；
- 未确认写入，long_term matched=0；
- 测试后已恢复 runtime_config 备份并重启，当前 topic boundary 默认关闭。

本次结论：代码主链路可用；此前超时主要由初始参数过重导致。后续继续按轻量参数爬坡。
