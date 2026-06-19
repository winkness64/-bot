from __future__ import annotations

from fixtures.mock_pipeline_stubs import (
    PLUGIN_ROOT,
    SRC_ROOT,
    ensure_package,
    install_nonebot_stubs,
    load_module,
)


def _prepare_package_roots() -> None:
    install_nonebot_stubs()
    ensure_package("plugins", SRC_ROOT / "plugins")
    ensure_package("plugins.yangyang", PLUGIN_ROOT)
    ensure_package("plugins.yangyang.admin", PLUGIN_ROOT / "admin")
    ensure_package("plugins.yangyang.core", PLUGIN_ROOT / "core")
    ensure_package("plugins.yangyang.memory", PLUGIN_ROOT / "memory")
    ensure_package("plugins.yangyang.output", PLUGIN_ROOT / "output")
    ensure_package("plugins.yangyang.tasks", PLUGIN_ROOT / "tasks")


def _load_core_admin_modules() -> dict:
    return {
        "runtime": load_module("plugins.yangyang.admin.runtime_config", PLUGIN_ROOT / "admin" / "runtime_config.py"),
        "event_adapter": load_module("plugins.yangyang.core.event_adapter", PLUGIN_ROOT / "core" / "event_adapter.py"),
        "decision": load_module("plugins.yangyang.core.decision_engine", PLUGIN_ROOT / "core" / "decision_engine.py"),
        "owner_action_router": load_module("plugins.yangyang.core.owner_action_router", PLUGIN_ROOT / "core" / "owner_action_router.py"),
        "owner_action_gate": load_module("plugins.yangyang.core.owner_action_gate", PLUGIN_ROOT / "core" / "owner_action_gate.py"),
        "owner_action_executor": load_module("plugins.yangyang.core.owner_action_executor", PLUGIN_ROOT / "core" / "owner_action_executor.py"),
        "owner_action_context": load_module("plugins.yangyang.core.owner_action_context_resolver", PLUGIN_ROOT / "core" / "owner_action_context_resolver.py"),
        "owner_action_reply_draft": load_module("plugins.yangyang.core.owner_action_reply_draft", PLUGIN_ROOT / "core" / "owner_action_reply_draft.py"),
        "owner_action_delivery": load_module("plugins.yangyang.core.owner_action_delivery", PLUGIN_ROOT / "core" / "owner_action_delivery.py"),
        "owner_action_delivery_safety": load_module("plugins.yangyang.core.owner_action_delivery_safety", PLUGIN_ROOT / "core" / "owner_action_delivery_safety.py"),
        "owner_engineering_toolbox": load_module("plugins.yangyang.core.owner_engineering_toolbox", PLUGIN_ROOT / "core" / "owner_engineering_toolbox.py"),
        "owner_toolbox_light": load_module("plugins.yangyang.core.owner_toolbox_light", PLUGIN_ROOT / "core" / "owner_toolbox_light.py"),
        "runtime_compat": load_module("plugins.yangyang.core.runtime_compat", PLUGIN_ROOT / "core" / "runtime_compat.py"),
        "cooldown": load_module("plugins.yangyang.core.cooldown_manager", PLUGIN_ROOT / "core" / "cooldown_manager.py"),
        "prompt": load_module("plugins.yangyang.core.prompt_builder", PLUGIN_ROOT / "core" / "prompt_builder.py"),
        "router": load_module("plugins.yangyang.core.model_router", PLUGIN_ROOT / "core" / "model_router.py"),
    }


def _load_memory_modules() -> dict:
    return {
        "store": load_module("plugins.yangyang.memory.store", PLUGIN_ROOT / "memory" / "store.py"),
    }


def _load_output_modules() -> dict:
    return {
        "sender_adapter": load_module("plugins.yangyang.output.sender_adapter", PLUGIN_ROOT / "output" / "sender_adapter.py"),
        "sender_adapter_factory": load_module("plugins.yangyang.output.sender_adapter_factory", PLUGIN_ROOT / "output" / "sender_adapter_factory.py"),
        "current_session_delivery_integration": load_module(
            "plugins.yangyang.output.current_session_delivery_integration",
            PLUGIN_ROOT / "output" / "current_session_delivery_integration.py",
        ),
        "current_session_manual_smoke": load_module(
            "plugins.yangyang.output.current_session_manual_smoke",
            PLUGIN_ROOT / "output" / "current_session_manual_smoke.py",
        ),
        "current_session_smoke_trigger": load_module(
            "plugins.yangyang.output.current_session_smoke_trigger",
            PLUGIN_ROOT / "output" / "current_session_smoke_trigger.py",
        ),
        "sender": load_module("plugins.yangyang.output.sender", PLUGIN_ROOT / "output" / "sender.py"),
        "factory_completion_current_session_bridge": load_module(
            "plugins.yangyang.output.factory_completion_current_session_bridge",
            PLUGIN_ROOT / "output" / "factory_completion_current_session_bridge.py",
        ),
    }


def _load_tasks_modules() -> dict:
    return {
        "factory_completion_notifier": load_module(
            "plugins.yangyang.tasks.factory_completion_notifier",
            PLUGIN_ROOT / "tasks" / "factory_completion_notifier.py",
        ),
        "tasks": load_module("plugins.yangyang.tasks", PLUGIN_ROOT / "tasks" / "__init__.py"),
    }


def _load_plugin_module() -> object:
    return load_module("plugins.yangyang", PLUGIN_ROOT / "__init__.py")


def _resolve_legacy_exports(core: dict) -> dict:
    owner_action_delivery_safety_mod = core["owner_action_delivery_safety"]
    owner_engineering_toolbox_mod = core["owner_engineering_toolbox"]
    owner_action_executor_mod = core["owner_action_executor"]
    owner_action_context_mod = core["owner_action_context"]
    owner_action_reply_draft_mod = core["owner_action_reply_draft"]
    owner_action_delivery_mod = core["owner_action_delivery"]
    return {
        "is_owner_action_delivery_allowed": getattr(
            owner_action_delivery_safety_mod,
            "is_owner_action_delivery_allowed",
            getattr(owner_action_delivery_safety_mod, "check_owner_action_delivery_safety", None),
        ),
        "summarize_owner_action_delivery_guard": getattr(
            owner_action_delivery_safety_mod,
            "summarize_owner_action_delivery_guard",
            getattr(owner_action_delivery_safety_mod, "build_owner_action_delivery_audit_record", None),
        ),
        "parse_owner_engineering_toolbox_command": getattr(
            owner_engineering_toolbox_mod,
            "parse_owner_engineering_toolbox_command",
            getattr(owner_engineering_toolbox_mod, "handle_owner_engineering_toolbox_message", None),
        ),
        "execute_owner_action": getattr(
            owner_action_executor_mod,
            "execute_owner_action",
            getattr(owner_action_executor_mod, "run_owner_action", None),
        ),
        "resolve_owner_action_context": getattr(
            owner_action_context_mod,
            "resolve_owner_action_context",
            getattr(owner_action_context_mod, "build_owner_action_context", None),
        ),
        "build_owner_action_reply_draft": getattr(
            owner_action_reply_draft_mod,
            "build_owner_action_reply_draft",
            getattr(owner_action_reply_draft_mod, "draft_owner_action_reply", None),
        ),
        "deliver_owner_action_reply": getattr(
            owner_action_delivery_mod,
            "deliver_owner_action_reply",
            getattr(owner_action_delivery_mod, "deliver_owner_action_reply_draft", None),
        ),
    }


def _build_exports(core: dict, memory: dict, output: dict, tasks: dict, plugin_mod: object, legacy: dict) -> dict:
    runtime_mod = core["runtime"]
    event_adapter_mod = core["event_adapter"]
    decision_mod = core["decision"]
    owner_action_router_mod = core["owner_action_router"]
    owner_action_gate_mod = core["owner_action_gate"]
    owner_action_executor_mod = core["owner_action_executor"]
    owner_action_context_mod = core["owner_action_context"]
    owner_action_reply_draft_mod = core["owner_action_reply_draft"]
    owner_action_delivery_mod = core["owner_action_delivery"]
    owner_engineering_toolbox_mod = core["owner_engineering_toolbox"]
    owner_toolbox_light_mod = core["owner_toolbox_light"]
    runtime_compat_mod = core["runtime_compat"]
    cooldown_mod = core["cooldown"]
    prompt_mod = core["prompt"]
    router_mod = core["router"]
    store_mod = memory["store"]
    sender_adapter_mod = output["sender_adapter"]
    sender_adapter_factory_mod = output["sender_adapter_factory"]
    current_session_delivery_integration_mod = output["current_session_delivery_integration"]
    current_session_manual_smoke_mod = output["current_session_manual_smoke"]
    current_session_smoke_trigger_mod = output["current_session_smoke_trigger"]
    sender_mod = output["sender"]
    factory_completion_bridge_mod = output["factory_completion_current_session_bridge"]
    factory_completion_notifier_mod = tasks["factory_completion_notifier"]
    tasks_mod = tasks["tasks"]

    return {
        "RuntimeConfig": runtime_mod.RuntimeConfig,
        "DEFAULTS": runtime_mod.DEFAULTS,
        "EventAdapter": event_adapter_mod.EventAdapter,
        "DecisionEngine": decision_mod.DecisionEngine,
        "CooldownManager": cooldown_mod.CooldownManager,
        "MemoryStore": store_mod.MemoryStore,
        "PromptBuilder": prompt_mod.PromptBuilder,
        "ModelRouter": router_mod.ModelRouter,
        "SenderAdapter": sender_adapter_mod.SenderAdapter,
        "SendResult": sender_adapter_mod.SendResult,
        "NullSenderAdapter": sender_adapter_mod.NullSenderAdapter,
        "FakeSenderAdapter": sender_adapter_mod.FakeSenderAdapter,
        "NoneBotCurrentSessionSenderAdapter": sender_adapter_mod.NoneBotCurrentSessionSenderAdapter,
        "build_owner_action_sender_adapter": sender_adapter_factory_mod.build_owner_action_sender_adapter,
        "CurrentSessionDeliveryIntegrationResult": current_session_delivery_integration_mod.CurrentSessionDeliveryIntegrationResult,
        "deliver_owner_action_current_session_if_enabled": current_session_delivery_integration_mod.deliver_owner_action_current_session_if_enabled,
        "CurrentSessionManualSmokeResult": current_session_manual_smoke_mod.CurrentSessionManualSmokeResult,
        "run_current_session_manual_smoke_if_enabled": current_session_manual_smoke_mod.run_current_session_manual_smoke_if_enabled,
        "CurrentSessionSmokeTriggerResult": current_session_smoke_trigger_mod.CurrentSessionSmokeTriggerResult,
        "handle_current_session_smoke_trigger_if_matched": current_session_smoke_trigger_mod.handle_current_session_smoke_trigger_if_matched,
        "parse_current_session_smoke_trigger_command": current_session_smoke_trigger_mod.parse_current_session_smoke_trigger_command,
        "Sender": sender_mod.Sender,
        "Decision": decision_mod.Decision,
        "runtime_compat": runtime_compat_mod,
        "parse_owner_action": owner_action_router_mod.parse_owner_action,
        "OwnerAction": owner_action_router_mod.OwnerAction,
        "evaluate_owner_action_gate": owner_action_gate_mod.evaluate_owner_action_gate,
        "OwnerActionGateResult": owner_action_gate_mod.OwnerActionGateResult,
        "execute_owner_action": legacy["execute_owner_action"],
        "OwnerActionExecutionResult": getattr(owner_action_executor_mod, "OwnerActionExecutionResult", None),
        "resolve_owner_action_context": legacy["resolve_owner_action_context"],
        "OwnerActionContext": getattr(owner_action_context_mod, "OwnerActionContext", None),
        "build_owner_action_reply_draft": legacy["build_owner_action_reply_draft"],
        "OwnerActionReplyDraft": getattr(owner_action_reply_draft_mod, "OwnerActionReplyDraft", None),
        "deliver_owner_action_reply": legacy["deliver_owner_action_reply"],
        "deliver_owner_action_reply_draft": legacy["deliver_owner_action_reply"],
        "OwnerActionDeliveryResult": owner_action_delivery_mod.OwnerActionDeliveryResult,
        "is_owner_action_delivery_allowed": legacy["is_owner_action_delivery_allowed"],
        "summarize_owner_action_delivery_guard": legacy["summarize_owner_action_delivery_guard"],
        "parse_owner_engineering_toolbox_command": legacy["parse_owner_engineering_toolbox_command"],
        "handle_owner_engineering_toolbox_message": owner_engineering_toolbox_mod.handle_owner_engineering_toolbox_message,
        "FactoryCompletionBridgeResult": factory_completion_bridge_mod.FactoryCompletionBridgeResult,
        "notify_owner_current_session_on_factory_completion": factory_completion_bridge_mod.notify_owner_current_session_on_factory_completion,
        "run_factory_completion_notifier": factory_completion_notifier_mod.run_factory_completion_notifier,
        "factory_completion_notifier_module": factory_completion_notifier_mod,
        "tasks_module": tasks_mod,
        "plugin": plugin_mod,
        "owner_toolbox_light": owner_toolbox_light_mod,
    }


def prepare_modules():
    _prepare_package_roots()
    core = _load_core_admin_modules()
    memory = _load_memory_modules()
    output = _load_output_modules()
    tasks = _load_tasks_modules()
    plugin_mod = _load_plugin_module()
    legacy = _resolve_legacy_exports(core)
    return _build_exports(core, memory, output, tasks, plugin_mod, legacy)
