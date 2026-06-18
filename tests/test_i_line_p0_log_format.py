from pathlib import Path


def test_isaac_p0_handled_log_uses_preformatted_message() -> None:
    text = Path("src/plugins/yangyang/__init__.py").read_text(encoding="utf-8")
    assert "yangyang plugin: isaac_p0 handled allowed=%s reason=%s task_type=%s" not in text
    assert "yangyang plugin: isaac_p0 handled allowed={isaac_p0_result.allowed}" in text
    assert "reason={isaac_p0_result.reason} task_type={isaac_p0_result.task_type}" in text
    assert "normal_prompt_bypassed=True memory_builder_skipped=True" in text
