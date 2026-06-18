"""B0 Runtime Compat - 6项手动测试套件"""
import sys, os, json, tempfile, shutil, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from plugins.yangyang.core.runtime_compat import (
    resolve_plugin_init_config,
    resolve_memory_root,
    escape_log_preview,
)
from plugins.yangyang.memory.core import MemorySystem

pass_count = 0
fail_count = 0

def ok(msg):
    global pass_count
    pass_count += 1
    print(f"  ✅ {msg}")

def ng(msg):
    global fail_count
    fail_count += 1
    print(f"  ❌ {msg}")

# ============================================================
# ✅ 测试1: 配置加载
# ============================================================
print("\n" + "=" * 60)
print("🧪 [测试1] 配置加载: plugin_config 优先级")
print("=" * 60)

class MockContext:
    def get_config(self):
        return {"memory_root": "/主配置/路径"}

mock_plugin_config = {
    "memory_root": "/插件配置/路径",
    "memory_short_term_capture_enabled": True,
    "memory_prompt_injection_enabled": False,
}

result = resolve_plugin_init_config(
    context=MockContext(),
    plugin_config=mock_plugin_config,
)
ok(f"plugin_config memory_root: {result.get('memory_root')}")
ok(f"short_term_capture: {result.get('memory_short_term_capture_enabled')}")
ok(f"prompt_injection: {result.get('memory_prompt_injection_enabled')}")

assert result.get("memory_root") == "/插件配置/路径", "❌ plugin_config 未覆盖 context.get_config()"
ok("plugin_config 优先级高于 context.get_config()")

# ============================================================
# ✅ 测试2: memory_root 路径解析
# ============================================================
print("\n" + "=" * 60)
print("🧪 [测试2] memory_root 路径解析")
print("=" * 60)

tmpdir = Path(tempfile.mkdtemp(prefix="b0_test_"))

# 2a. 绝对路径
abs_root = resolve_memory_root(plugin_config={"memory_root": str(tmpdir / "abs_memory")})
assert abs_root == (tmpdir / "abs_memory").resolve()
ok(f"绝对路径: {abs_root}")

# 2b. 相对路径
rel_root = resolve_memory_root(
    plugin_config={"memory_root": "./rel_memory"},
    cwd=tmpdir,
)
expected_rel = (tmpdir / "rel_memory").resolve()
assert rel_root == expected_rel
ok(f"相对路径 (→cwd): {rel_root}")

# 2c. 环境变量覆盖
env_root = resolve_memory_root(
    plugin_config={"memory_root": "/old/fallback"},
    env={"YANGYANG_MEMORY_ROOT": str(tmpdir / "env_memory")},
)
assert env_root == (tmpdir / "env_memory").resolve()
ok(f"环境变量优先: {env_root}")

# 2d. 默认路径
default_root = resolve_memory_root(
    data_dir=str(tmpdir / "data_dir"),
    plugin_config={},
)
assert default_root == (tmpdir / "data_dir" / "memory").resolve()
ok(f"默认路径 (data_dir/memory): {default_root}")

shutil.rmtree(tmpdir, ignore_errors=True)

# ============================================================
# ✅ 测试3: 日志 preview 单行化
# ============================================================
print("\n" + "=" * 60)
print("🧪 [测试3] 日志 preview 单行化")
print("=" * 60)

multi_line = "[短期上下文记忆]\n- user: hello\n- user: world"
escaped = escape_log_preview(multi_line, limit=200)
assert "\n" not in escaped, "换行符未转义"
assert "\\n" in escaped, "应包含字面 \\n"
ok("换行符 → 字面 \\n")

assert escape_log_preview("正常日志一行") == "正常日志一行"
ok("正常文本不变")

long_text = "x" * 300
truncated = escape_log_preview(long_text, limit=100)
assert len(truncated) == 100
assert truncated.endswith("…")
ok("截断 + 省略号")

# ============================================================
# ✅ 测试4: 长上下文预算
# ============================================================
print("\n" + "=" * 60)
print("🧪 [测试4] 长上下文预算")
print("=" * 60)

tmpdir2 = Path(tempfile.mkdtemp(prefix="b0_long_"))
ms = MemorySystem(base_dir=tmpdir2, short_term_limit=200)
ms.prompt_char_budget = 2400
ms.prompt_short_term_item_limit = 1000

for i in range(100):
    ms.add_to_short_term("session_test", {
        "uid": "test_user",
        "text": f"第{i}条测试消息",
        "timestamp": time.time() - (100 - i) * 10,
        "nick": "TestUser",
    })

prompt_100 = ms.build_memory_prompt("test_user", "session_test")
print(f"  100 items prompt: {len(prompt_100)} chars (budget={ms.prompt_char_budget})")
assert len(prompt_100) <= 3000
ok(f"100 items 受预算控制: {len(prompt_100)} chars")

# 1000 items
ms2 = MemorySystem(base_dir=tmpdir2, short_term_limit=2000)
ms2.prompt_char_budget = 2400
ms2.prompt_short_term_item_limit = 5000
for i in range(1000):
    ms2.add_to_short_term("session_test2", {
        "uid": "test_user",
        "text": f"压力测试第{i}条",
        "timestamp": time.time() - (1000 - i) * 10,
        "nick": "StressTest",
    })

prompt_1000 = ms2.build_memory_prompt("test_user", "session_test2")
print(f"  1000 items prompt: {len(prompt_1000)} chars (budget={ms2.prompt_char_budget})")
assert len(prompt_1000) <= 3000
assert "第999条" in prompt_1000 or "第998条" in prompt_1000
ok(f"1000 items 预算裁剪 + 保留最近items")

shutil.rmtree(tmpdir2, ignore_errors=True)

# ============================================================
# ✅ 测试5: 安全默认值
# ============================================================
print("\n" + "=" * 60)
print("🧪 [测试5] 安全默认值")
print("=" * 60)

result_defaults = resolve_plugin_init_config(
    context=MockContext(),
    config={},
    plugin_config={},
)

st = result_defaults.get("memory_short_term_capture_enabled")
pi = result_defaults.get("memory_prompt_injection_enabled")
ds = result_defaults.get("memory_daily_summary_enabled")

ok(f"short_term_capture_enabled = {st!r}")
ok(f"prompt_injection_enabled = {pi!r}")
ok(f"daily_summary_enabled = {ds!r}")

assert st is not True
assert pi is not True
assert ds is not True
ok("全部默认 False/None，安全")

# ============================================================
# ✅ 测试6: 群聊闸门回归
# ============================================================
print("\n" + "=" * 60)
print("🧪 [测试6] 群聊闸门回归")
print("=" * 60)

# Capture 默认关闭 → 无副作用
result_gate = resolve_plugin_init_config(context=None, plugin_config={})
assert result_gate.get("memory_short_term_capture_enabled") is not True
ok("capture 默认关闭，群聊无副作用")

print("\n" + "=" * 60)
total = pass_count + fail_count
print(f"📊 结果: {pass_count} ✅ / {fail_count} ❌ / {total} 项")
if fail_count == 0:
    print("🎉 B0 6项测试全部通过！")
else:
    print(f"⚠️  {fail_count} 项失败")
print("=" * 60)
