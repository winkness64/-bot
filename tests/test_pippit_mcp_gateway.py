from __future__ import annotations

from datetime import datetime
import importlib.util
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).resolve().parents[1] / 'src/plugins/yangyang/core/pippit_mcp_gateway.py'
SPEC = importlib.util.spec_from_file_location('pippit_mcp_gateway_test_module', MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

CliCommandPlan = MODULE.CliCommandPlan
CredentialSelectionError = MODULE.CredentialSelectionError
GatewayExecutionResult = MODULE.GatewayExecutionResult
PippitCredential = MODULE.PippitCredential
PippitGatewayConfig = MODULE.PippitGatewayConfig
PippitGatewayError = MODULE.PippitGatewayError
PippitKeyManager = MODULE.PippitKeyManager
PippitMcpGateway = MODULE.PippitMcpGateway
PippitStateStore = MODULE.PippitStateStore
PippitExecutionPendingError = MODULE.PippitExecutionPendingError
build_video_submit_body = MODULE.build_video_submit_body
build_submit_message = MODULE.build_submit_message


class FakeRunner:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[CliCommandPlan] = []

    def run(self, plan: CliCommandPlan) -> dict:
        self.calls.append(plan)
        if not self.responses:
            raise AssertionError('unexpected extra runner call')
        payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def _build_credentials() -> list[PippitCredential]:
    return [
        PippitCredential(key_id='k1', api_key='api-key-1', daily_limit=2),
        PippitCredential(key_id='k2', api_key='api-key-2', daily_limit=2),
    ]


def test_build_submit_message_for_text_to_image() -> None:
    message = build_submit_message(
        prompt='生成一张哲学硬汉头像',
        mode='text_to_image',
        style='赛博工业',
        size='1024x1024',
        count=2,
    )
    assert '生成图片' in message
    assert '生成一张哲学硬汉头像' in message
    assert '风格：赛博工业' in message
    assert '尺寸：1024x1024' in message
    assert '张数：2' in message


def test_key_manager_rotates_after_limit(tmp_path: Path) -> None:
    store = PippitStateStore(tmp_path / 'state.json')
    manager = PippitKeyManager(_build_credentials(), state_store=store, daily_limit_per_key=2)
    now = datetime(2026, 6, 17, 12, 0, 0)

    first = manager.choose_credential(now)
    assert first.key_id == 'k1'
    manager.mark_success(first, now)
    manager.mark_success(first, now)

    second = manager.choose_credential(now)
    assert second.key_id == 'k2'


def test_key_manager_raises_when_all_keys_exhausted_using_global_default(tmp_path: Path) -> None:
    store = PippitStateStore(tmp_path / 'state.json')
    credentials = [
        PippitCredential(key_id='k1', api_key='api-key-1', daily_limit=None),
        PippitCredential(key_id='k2', api_key='api-key-2', daily_limit=None),
    ]
    manager = PippitKeyManager(credentials, state_store=store, daily_limit_per_key=1)
    now = datetime(2026, 6, 17, 12, 0, 0)
    first = manager.choose_credential(now)
    manager.mark_success(first, now)
    second = manager.choose_credential(now)
    manager.mark_success(second, now)
    try:
        manager.choose_credential(now)
    except CredentialSelectionError as exc:
        assert 'daily limit' in str(exc)
    else:
        raise AssertionError('expected CredentialSelectionError')


def test_state_store_persists_selected_key_and_usage(tmp_path: Path) -> None:
    store = PippitStateStore(tmp_path / 'state.json')
    manager = PippitKeyManager(_build_credentials(), state_store=store, daily_limit_per_key=2)
    now = datetime(2026, 6, 17, 12, 0, 0)
    credential = manager.choose_credential(now)
    manager.mark_success(credential, now)

    payload = store.load()
    assert payload.selected_key_id == credential.key_id
    assert payload.daily_usage['2026-06-17'][credential.key_id] == 1


def test_gateway_prepare_text_to_image_builds_submit_plan(tmp_path: Path) -> None:
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            working_directory='/tmp/pippit-cli',
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
        )
    )
    credential, request, plan = gateway.prepare_text_to_image(
        prompt='生成一张蓝眼工程师头像',
        style='冷光工业风',
        size='1024x1024',
        count=1,
        thread_id='thread-1',
    )
    assert credential.key_id == 'k1'
    assert request.thread_id == 'thread-1'
    assert '--message' in plan.argv
    assert '--thread-id' in plan.argv
    assert plan.env['PIPPIT_API_KEY'] == 'api-key-1'
    assert plan.cwd == '/tmp/pippit-cli'
    assert isinstance(plan, CliCommandPlan)


def test_gateway_official_cli_submit_plan_uses_pippit_tool_cli(tmp_path: Path) -> None:
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            working_directory='/tmp/pippit-cli',
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
            cli_mode='official_cli',
        )
    )
    credential, request, plan = gateway.prepare_text_to_image(
        prompt='生成一张蓝眼工程师头像',
        style='冷光工业风',
        size='1024x1024',
        count=1,
        thread_id='thread-1',
    )
    assert credential.key_id == 'k1'
    assert request.thread_id == 'thread-1'
    assert plan.argv[:3] == ('pippit-tool-cli', 'short-drama', '+submit-run')
    assert '--message' in plan.argv
    assert plan.env['XYQ_ACCESS_KEY'] == 'api-key-1'
    assert plan.env['PIPPIT_API_KEY'] == 'api-key-1'


def test_gateway_official_cli_upload_plan_uses_path_flag(tmp_path: Path) -> None:
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
            cli_mode='official_cli',
        )
    )
    credential = gateway.key_manager.choose_credential()
    plan = gateway.plan_upload_file(file_path='/tmp/in.txt', credential=credential)
    assert plan.argv == ('pippit-tool-cli', 'short-drama', '+upload-file', '--path', '/tmp/in.txt')
    assert plan.env['XYQ_ACCESS_KEY'] == 'api-key-1'


def test_extractors_support_real_nestagent_payload() -> None:
    payload = {
        'ret': '0',
        'errmsg': '',
        'data': {
            'run': {
                'run_id': 'skill_run_1',
                'thread_id': 'skill_thread_1',
                'state': 1,
            },
            'thread': {
                'run_list': [
                    {
                        'run_id': 'skill_run_1',
                        'thread_id': 'skill_thread_1',
                        'state': 3,
                        'entry_list': [
                            {
                                'artifact': {
                                    'download_url': 'https://example.com/out.mp4',
                                }
                            }
                        ],
                    }
                ]
            },
            'files': [
                {'download_url': 'https://example.com/file1.png'},
                {'cover_url': 'https://example.com/file2.png'},
            ],
        },
    }
    assert MODULE._extract_thread_id(payload) == 'skill_thread_1'
    assert MODULE._extract_run_id(payload) == 'skill_run_1'
    assert MODULE._extract_status(payload) == 'queued'
    files = MODULE._extract_files(payload)
    assert 'https://example.com/file1.png' in files
    assert 'https://example.com/file2.png' in files
    assert 'https://example.com/out.mp4' in files


def test_download_plan_uses_urls_not_thread_id(tmp_path: Path) -> None:
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
            cli_mode='scripts',
        )
    )
    credential = gateway.key_manager.choose_credential()
    plan = gateway.plan_download_results(
        urls=['https://example.com/a.png', 'https://example.com/b.mp4'],
        output_dir='out',
        credential=credential,
    )
    assert plan.argv == (
        'python3',
        'download_results.py',
        '--urls',
        'https://example.com/a.png',
        'https://example.com/b.mp4',
        '--output-dir',
        'out',
    )


def test_gateway_legacy_script_mode_keeps_python_runner(tmp_path: Path) -> None:
    runner = FakeRunner([
        {'thread_id': 'thread-1', 'run_id': 'run-1'},
        {
            'data': {
                'thread': {
                    'run_list': [
                        {
                            'run_id': 'run-1',
                            'thread_id': 'thread-1',
                            'state': 3,
                            'entry_list': [
                                {'artifact': {'download_url': 'https://example.com/out/a.png'}},
                                {'artifact': {'download_url': 'https://example.com/out/b.png'}},
                            ],
                        }
                    ]
                }
            }
        },
        {'downloaded': ['out/a.png', 'out/b.png']},
    ])
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            working_directory='/tmp/pippit-cli',
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
            poll_interval_seconds=0,
            poll_timeout_seconds=5,
            cli_mode='scripts',
        ),
        runner=runner,
    )
    result = gateway.execute_text_to_image(
        prompt='生成一张蓝眼工程师头像',
        style='冷光工业风',
        size='1024x1024',
        count=1,
        output_dir='out',
    )
    assert isinstance(result, GatewayExecutionResult)
    assert result.submit.thread_id == 'thread-1'
    assert result.poll.status == 'completed'
    assert result.download.files == ('out/a.png', 'out/b.png')
    assert [Path(call.argv[1]).name for call in runner.calls] == ['submit_run.py', 'get_thread.py', 'download_results.py']


def test_download_results_extracts_urls_from_poll_payload_then_downloads(tmp_path: Path) -> None:
    runner = FakeRunner([
        {'downloaded': ['out/01.png', 'out/02.mp4']},
    ])
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
            cli_mode='scripts',
        ),
        runner=runner,
    )
    credential = gateway.key_manager.choose_credential()
    poll_payload = {
        'data': {
            'files': [
                {'download_url': 'https://example.com/a.png'},
                {'download_url': 'https://example.com/b.mp4'},
            ]
        }
    }
    result = gateway.download_results(
        thread_id='thread-1',
        output_dir='out',
        credential=credential,
        poll_payload=poll_payload,
    )
    assert result.files == ('out/01.png', 'out/02.mp4')
    assert runner.calls[0].argv == (
        'python3',
        'download_results.py',
        '--urls',
        'https://example.com/a.png',
        'https://example.com/b.mp4',
        '--output-dir',
        'out',
    )


def test_execute_image_edit_uploads_then_runs(tmp_path: Path) -> None:
    runner = FakeRunner([
        {'asset_id': 'asset-1'},
        {'thread_id': 'thread-2', 'run_id': 'run-2'},
        {
            'data': {
                'thread': {
                    'run_list': [
                        {
                            'run_id': 'run-2',
                            'thread_id': 'thread-2',
                            'state': 3,
                            'entry_list': [
                                {'artifact': {'download_url': 'https://example.com/out/edit.png'}},
                            ],
                        }
                    ]
                }
            }
        },
        {'downloaded': ['out/edit.png']},
    ])
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
            poll_interval_seconds=0,
            poll_timeout_seconds=5,
            cli_mode='scripts',
        ),
        runner=runner,
    )
    result = gateway.execute_image_edit(
        prompt='修一下这张图',
        file_paths=['/tmp/in.png'],
        output_dir='out',
    )
    assert result.request.asset_ids == ('asset-1',)
    assert result.download.files == ('out/edit.png',)
    assert [Path(call.argv[1]).name for call in runner.calls] == ['upload_file.py', 'submit_run.py', 'get_thread.py', 'download_results.py']


def test_poll_timeout_marks_failure_and_raises(tmp_path: Path) -> None:
    runner = FakeRunner([
        {'thread_id': 'thread-3', 'run_id': 'run-3'},
        {'thread_id': 'thread-3', 'run_id': 'run-3', 'status': 'queued'},
    ])
    gateway = PippitMcpGateway(
        PippitGatewayConfig(
            state_path=str(tmp_path / 'state.json'),
            credentials=_build_credentials(),
            poll_interval_seconds=0,
            poll_timeout_seconds=1,
        ),
        runner=runner,
    )
    timer = iter([0.0, 2.0])
    try:
        credential, request, _ = gateway.prepare_text_to_image(prompt='test')
        submit = gateway.submit_run(request, credential)
        gateway.mark_submit_success(credential)
        gateway.poll_run_until_terminal(
            thread_id=submit.thread_id,
            run_id=submit.run_id,
            credential=credential,
            sleep_func=lambda _: None,
            time_func=lambda: next(timer),
        )
    except PippitExecutionPendingError:
        gateway.mark_submit_failure(credential)
    else:
        raise AssertionError('expected timeout')
    state = gateway.state_store.load()
    assert state.failures[credential.key_id] == 1
