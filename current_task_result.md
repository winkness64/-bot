PASS
Task: Model Profile Switcher v2 Phase 1A

Changed files:
- src/plugins/yangyang/core/model_profile_switcher.py
  - list_model_profiles/selection index now follows runtime_config.providers dict order first, then builtin/models fallback append.
  - descriptor now exposes index/profile_id/provider/model/timeout/enabled/source without secrets.
  - providers.<id>.enabled now wins over models.<id>.enabled for switcher enabled checks.
  - set_active_model_profile supports selection_index; invalid/disabled does not write config.
- src/plugins/yangyang/core/model_router.py
  - _tier_enabled aligned so providers.<id>.enabled wins over models.<id>.enabled.
- src/plugins/yangyang/core/owner_toolbox_light.py
  - small schema/dispatch support for selection_index only; did not read full file.
  - list reply shows [index].
- tests/test_model_profile_switcher.py
  - added/updated Phase1A regression tests.

Final active defaults from runtime DEFAULTS:
- model_profile_switcher.active_profile_private = v4_flash
- model_profile_switcher.active_profile_group = v4_flash

Runtime DEFAULTS statuses:
- v4_flash: index=1 enabled=true source=providers
- v4_pro: index=0 enabled=true source=providers
- m2_7: index=2 enabled=false source=providers
- gpt_5_5: index=3 enabled=false source=builtin_catalog; not switchable

Tests:
- python3 ast parse: PASS
- ./.venv/bin/pytest -q tests/test_model_profile_switcher.py: PASS, 22 passed
- ./.venv/bin/pytest -q tests/test_owner_toolbox_light_llm_loop.py: PASS, 18 passed
- static natural-language entrance grep for gpt/几个模型/第 patterns: PASS, no matches

Constraints:
- Did not scan/read owner_toolbox_light.py full 1700+ lines.
- Only read small located owner_toolbox_light.py snippets for schema/dispatch/format.
- Did not add regex/keyword natural-language switch entrance.
- Did not modify .env, providers schema, remote /models, MiniMax/GPT enablement, BP, or architecture migration.
- Service not restarted.
