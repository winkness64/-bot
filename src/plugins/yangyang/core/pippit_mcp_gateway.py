from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import mimetypes
from pathlib import Path
import shlex
import subprocess
import threading
import time
from typing import Any, Iterable, Protocol
import urllib.error
import urllib.request


DEFAULT_DAILY_LIMIT_PER_KEY = 60
DEFAULT_STATE_FILENAME = 'pippit_mcp_state.json'


def _utc_today_key(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    return current.strftime('%Y-%m-%d')


def _clean_text(value: str | None) -> str:
    return str(value or '').strip()


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(parsed, 1)


def build_submit_message(
    *,
    prompt: str,
    mode: str = 'text_to_image',
    style: str | None = None,
    size: str | None = None,
    count: int | None = None,
    extra_instructions: str | None = None,
) -> str:
    cleaned_prompt = _clean_text(prompt)
    if not cleaned_prompt:
        raise ValueError('prompt is required')

    lines: list[str] = []
    if mode == 'image_edit':
        lines.append('请基于我上传的参考图执行图像编辑任务。')
    elif mode == 'text_to_video':
        lines.append('请根据以下描述生成视频。')
    elif mode == 'image_to_video':
        lines.append('请基于我上传的参考图生成视频。')
    else:
        lines.append('请根据以下描述生成图片。')
    lines.append(cleaned_prompt)

    meta_parts: list[str] = []
    if style and _clean_text(style):
        meta_parts.append(f'风格：{_clean_text(style)}')
    if size and _clean_text(size):
        meta_parts.append(f'尺寸：{_clean_text(size)}')
    if count is not None:
        meta_parts.append(f'张数：{max(int(count), 1)}')
    if extra_instructions and _clean_text(extra_instructions):
        meta_parts.append(f'补充要求：{_clean_text(extra_instructions)}')
    if meta_parts:
        lines.append('；'.join(meta_parts))
    return '\n'.join(lines)


@dataclass(frozen=True)
class PippitCredential:
    key_id: str
    api_key: str
    enabled: bool = True
    daily_limit: int | None = None


@dataclass
class PippitGatewayConfig:
    cli_command: str = 'pippit-tool-cli'
    cli_mode: str = 'scripts'
    python_executable: str = 'python3'
    submit_script: str = 'submit_run.py'
    get_thread_script: str = 'get_thread.py'
    upload_script: str = 'upload_file.py'
    download_script: str = 'download_results.py'
    working_directory: str | None = None
    state_path: str | None = None
    daily_limit_per_key: int = DEFAULT_DAILY_LIMIT_PER_KEY
    poll_interval_seconds: float = 3.0
    poll_timeout_seconds: int = 300
    credentials: list[PippitCredential] = field(default_factory=list)


@dataclass
class PippitGatewayState:
    selected_key_id: str | None = None
    daily_usage: dict[str, dict[str, int]] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'selected_key_id': self.selected_key_id,
            'daily_usage': self.daily_usage,
            'failures': self.failures,
            'updated_at': self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> 'PippitGatewayState':
        data = payload if isinstance(payload, dict) else {}
        return cls(
            selected_key_id=data.get('selected_key_id'),
            daily_usage=_normalize_nested_int_mapping(data.get('daily_usage')),
            failures=_normalize_int_mapping(data.get('failures')),
            updated_at=str(data.get('updated_at')) if data.get('updated_at') else None,
        )


@dataclass(frozen=True)
class CliCommandPlan:
    argv: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    def shell_preview(self) -> str:
        return ' '.join(shlex.quote(part) for part in self.argv)


@dataclass(frozen=True)
class SubmitRunRequest:
    message: str
    thread_id: str | None = None
    asset_ids: tuple[str, ...] = ()
    raw_submit_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class UploadResult:
    asset_id: str
    media_kind: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubmitResult:
    thread_id: str
    run_id: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class PollResult:
    thread_id: str
    run_id: str | None
    status: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class DownloadResult:
    thread_id: str
    output_dir: str
    files: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class GatewayExecutionResult:
    credential: PippitCredential
    request: SubmitRunRequest
    submit: SubmitResult
    poll: PollResult
    download: DownloadResult


class CommandRunner(Protocol):
    def run(self, plan: CliCommandPlan) -> dict[str, Any]:
        ...


class PippitGatewayError(RuntimeError):
    pass


class PippitExecutionPendingError(PippitGatewayError):
    pass


class PippitExecutionFailedError(PippitGatewayError):
    pass


class CredentialSelectionError(RuntimeError):
    pass


def _normalize_nested_int_mapping(value: Any) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    if not isinstance(value, dict):
        return result
    for day, entries in value.items():
        if not isinstance(entries, dict):
            continue
        result[str(day)] = _normalize_int_mapping(entries)
    return result


def _normalize_int_mapping(value: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(value, dict):
        return result
    for key, raw in value.items():
        try:
            result[str(key)] = int(raw)
        except Exception:
            continue
    return result


class PippitStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> PippitGatewayState:
        with self._lock:
            if not self.path.exists():
                return PippitGatewayState()
            try:
                payload = json.loads(self.path.read_text(encoding='utf-8'))
            except Exception:
                return PippitGatewayState()
            return PippitGatewayState.from_dict(payload)

    def save(self, state: PippitGatewayState) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(self.path.suffix + '.tmp')
            tmp_path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')
            tmp_path.replace(self.path)


class SubprocessCommandRunner:
    def __init__(self, *, timeout_seconds: int = 300, base_env: dict[str, str] | None = None):
        self.timeout_seconds = _coerce_positive_int(timeout_seconds, 300)
        self.base_env = dict(base_env or {})

    def run(self, plan: CliCommandPlan) -> dict[str, Any]:
        env = dict(self.base_env)
        env.update(plan.env)
        completed = subprocess.run(
            plan.argv,
            cwd=plan.cwd or None,
            env=env or None,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        stdout = completed.stdout or ''
        stderr = completed.stderr or ''
        if completed.returncode != 0:
            raise PippitGatewayError(
                f'command failed with exit code {completed.returncode}: {stderr.strip() or stdout.strip() or plan.shell_preview()}'
            )
        payload = _parse_json_output(stdout)
        if payload is None:
            payload = {
                'stdout': stdout.strip(),
                'stderr': stderr.strip(),
                'argv': list(plan.argv),
            }
        return payload


def _parse_json_output(text: str) -> dict[str, Any] | None:
    cleaned = str(text or '').strip()
    if not cleaned:
        return None
    try:
        payload = json.loads(cleaned)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else {'result': payload}


def _first_non_empty_string(*values: Any) -> str | None:
    for value in values:
        cleaned = _clean_text(value if isinstance(value, str) else (str(value) if value is not None else None))
        if cleaned:
            return cleaned
    return None


def _detect_media_kind_from_path(file_path: str) -> str | None:
    ext = Path(_clean_text(file_path)).suffix.lower()
    mime, _ = mimetypes.guess_type(file_path)
    if mime:
        if mime.startswith('image/'):
            return 'image'
        if mime.startswith('video/'):
            return 'video'
        if mime.startswith('audio/'):
            return 'audio'
    if ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}:
        return 'image'
    if ext in {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv', '.m4v'}:
        return 'video'
    if ext in {'.mp3', '.wav'}:
        return 'audio'
    return None


def build_video_submit_body(
    *,
    prompt: str,
    image_asset_ids: Iterable[str] = (),
    video_asset_ids: Iterable[str] = (),
    audio_asset_ids: Iterable[str] = (),
    duration_sec: int | None = None,
    ratio: str | None = None,
    model: str | None = None,
    resolution: str | None = None,
) -> dict[str, Any]:
    cleaned_prompt = _clean_text(prompt)
    if not cleaned_prompt:
        raise ValueError('prompt is required')

    def _asset_refs(values: Iterable[str]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for item in values:
            cleaned = _clean_text(item)
            if cleaned:
                refs.append({'pippit_asset_id': cleaned})
        return refs

    param: dict[str, Any] = {
        'prompt': cleaned_prompt,
    }
    images = _asset_refs(image_asset_ids)
    videos = _asset_refs(video_asset_ids)
    audios = _asset_refs(audio_asset_ids)
    if images:
        param['images'] = images
    if videos:
        param['videos'] = videos
    if audios:
        param['audios'] = audios
    if duration_sec is not None:
        param['duration_sec'] = max(int(duration_sec), 1)
    if _clean_text(ratio):
        param['ratio'] = _clean_text(ratio)
    if _clean_text(model):
        param['model'] = _clean_text(model)
    if _clean_text(resolution):
        param['resolution'] = _clean_text(resolution)

    return {
        'agent_name': 'pippit_video_part_agent',
        'message': cleaned_prompt,
        'video_part_tool_param': param,
    }


    candidates = [
        payload.get('thread_id'),
        payload.get('threadId'),
        payload.get('conversation_id'),
        payload.get('conversationId'),
    ]
    data = payload.get('data')
    if isinstance(data, dict):
        candidates.extend([data.get('thread_id'), data.get('threadId')])
        thread = data.get('thread')
        if isinstance(thread, dict):
            candidates.extend([thread.get('id'), thread.get('thread_id'), thread.get('threadId')])
        run = data.get('run')
        if isinstance(run, dict):
            candidates.extend([run.get('thread_id'), run.get('threadId')])
        thread_block = data.get('thread')
        if isinstance(thread_block, dict):
            run_list = thread_block.get('run_list')
            if isinstance(run_list, list):
                for item in run_list:
                    if isinstance(item, dict):
                        candidates.extend([item.get('thread_id'), item.get('threadId')])
    thread = payload.get('thread')
    if isinstance(thread, dict):
        candidates.extend([thread.get('id'), thread.get('thread_id'), thread.get('threadId')])
    return _first_non_empty_string(*candidates, fallback)


def _extract_thread_id(payload: dict[str, Any], fallback: str | None = None) -> str | None:
    candidates = [
        payload.get('thread_id'),
        payload.get('threadId'),
        payload.get('conversation_id'),
        payload.get('conversationId'),
    ]
    data = payload.get('data')
    if isinstance(data, dict):
        candidates.extend([data.get('thread_id'), data.get('threadId')])
        thread = data.get('thread')
        if isinstance(thread, dict):
            candidates.extend([thread.get('id'), thread.get('thread_id'), thread.get('threadId')])
            run_list = thread.get('run_list')
            if isinstance(run_list, list):
                for item in run_list:
                    if isinstance(item, dict):
                        candidates.extend([item.get('thread_id'), item.get('threadId')])
        run = data.get('run')
        if isinstance(run, dict):
            candidates.extend([run.get('thread_id'), run.get('threadId')])
    thread = payload.get('thread')
    if isinstance(thread, dict):
        candidates.extend([thread.get('id'), thread.get('thread_id'), thread.get('threadId')])
    return _first_non_empty_string(*candidates, fallback)


def _extract_run_id(payload: dict[str, Any]) -> str | None:
    candidates = [payload.get('run_id'), payload.get('runId'), payload.get('id')]
    data = payload.get('data')
    if isinstance(data, dict):
        candidates.extend([data.get('run_id'), data.get('runId')])
        run = data.get('run')
        if isinstance(run, dict):
            candidates.extend([run.get('id'), run.get('run_id'), run.get('runId')])
        thread = data.get('thread')
        if isinstance(thread, dict):
            run_list = thread.get('run_list')
            if isinstance(run_list, list):
                for item in run_list:
                    if isinstance(item, dict):
                        candidates.extend([item.get('id'), item.get('run_id'), item.get('runId')])
    run = payload.get('run')
    if isinstance(run, dict):
        candidates.extend([run.get('id'), run.get('run_id'), run.get('runId')])
    return _first_non_empty_string(*candidates)


def _normalize_status_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        mapping = {
            0: 'queued',
            1: 'queued',
            2: 'running',
            3: 'completed',
            4: 'failed',
            5: 'cancelled',
        }
        return mapping.get(value, str(value))
    cleaned = _clean_text(value)
    if cleaned.isdigit():
        return _normalize_status_value(int(cleaned))
    return cleaned.lower() if cleaned else None


def _extract_status(payload: dict[str, Any]) -> str:
    candidates: list[Any] = [
        payload.get('status'),
        payload.get('state'),
        payload.get('run_status'),
        payload.get('runStatus'),
    ]
    data = payload.get('data')
    if isinstance(data, dict):
        candidates.extend([
            data.get('status'),
            data.get('state'),
            data.get('run_status'),
            data.get('runStatus'),
        ])
        run = data.get('run')
        if isinstance(run, dict):
            candidates.extend([run.get('status'), run.get('state')])
        thread = data.get('thread')
        if isinstance(thread, dict):
            run_list = thread.get('run_list')
            if isinstance(run_list, list) and run_list:
                item = run_list[0]
                if isinstance(item, dict):
                    candidates.extend([item.get('status'), item.get('state')])
    run = payload.get('run')
    if isinstance(run, dict):
        candidates.extend([run.get('status'), run.get('state')])
    for candidate in candidates:
        normalized = _normalize_status_value(candidate)
        if normalized:
            return normalized
    return 'unknown'


def _extract_asset_id(payload: dict[str, Any]) -> str | None:
    candidates = [payload.get('asset_id'), payload.get('assetId'), payload.get('pippit_asset_id'), payload.get('file_id'), payload.get('fileId'), payload.get('id')]
    data = payload.get('data')
    if isinstance(data, dict):
        candidates.extend([
            data.get('asset_id'),
            data.get('assetId'),
            data.get('pippit_asset_id'),
            data.get('file_id'),
            data.get('fileId'),
            data.get('id'),
        ])
    asset = payload.get('asset')
    if isinstance(asset, dict):
        candidates.extend([asset.get('id'), asset.get('asset_id'), asset.get('assetId'), asset.get('pippit_asset_id')])
    return _first_non_empty_string(*candidates)


def _extract_files(payload: dict[str, Any]) -> tuple[str, ...]:
    result: list[str] = []

    def _push(value: Any) -> None:
        found = None
        if isinstance(value, str):
            found = _clean_text(value)
        elif isinstance(value, dict):
            found = _first_non_empty_string(
                value.get('path'),
                value.get('file'),
                value.get('url'),
                value.get('name'),
                value.get('download_url'),
                value.get('cover_url'),
            )
        if found:
            result.append(found)

    values = payload.get('files')
    if isinstance(values, list):
        for item in values:
            _push(item)
    data = payload.get('data')
    if isinstance(data, dict):
        files = data.get('files')
        if isinstance(files, list):
            for item in files:
                _push(item)
        thread = data.get('thread')
        if isinstance(thread, dict):
            run_list = thread.get('run_list')
            if isinstance(run_list, list):
                for run in run_list:
                    if not isinstance(run, dict):
                        continue
                    entry_list = run.get('entry_list')
                    if not isinstance(entry_list, list):
                        continue
                    for entry in entry_list:
                        if not isinstance(entry, dict):
                            continue
                        artifact = entry.get('artifact')
                        if isinstance(artifact, dict):
                            _push(artifact)
                        message = entry.get('message')
                        if isinstance(message, dict):
                            content = message.get('content')
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict):
                                        _push(block)
    single = _first_non_empty_string(payload.get('file'), payload.get('path'), payload.get('url'))
    if single:
        result.append(single)
    deduped: list[str] = []
    seen = set()
    for item in result:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return tuple(deduped)


class PippitMcpGateway:
    def __init__(
        self,
        config: PippitGatewayConfig,
        *,
        state_store: PippitStateStore | None = None,
        key_manager: PippitKeyManager | None = None,
        runner: CommandRunner | None = None,
    ):
        self.config = config
        resolved_state_path = config.state_path or DEFAULT_STATE_FILENAME
        self.state_store = state_store or PippitStateStore(resolved_state_path)
        self.key_manager = key_manager or PippitKeyManager(
            config.credentials,
            state_store=self.state_store,
            daily_limit_per_key=config.daily_limit_per_key,
        )
        self.runner = runner or SubprocessCommandRunner(timeout_seconds=config.poll_timeout_seconds)

    def _base_env(self, credential: PippitCredential) -> dict[str, str]:
        return {
            'PIPPIT_API_KEY': credential.api_key,
            'XYQ_ACCESS_KEY': credential.api_key,
        }

    def _use_official_cli(self) -> bool:
        return _clean_text(self.config.cli_mode).lower() in {'official', 'official_cli', 'cli'}

    def _submit_run_http(self, body: dict[str, Any], credential: PippitCredential) -> dict[str, Any]:
        endpoint = 'https://xyq.jianying.com/api/biz/v1/skill/submit_run'
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(
            endpoint,
            data=data,
            method='POST',
            headers={
                'Authorization': f'Bearer {credential.api_key}',
                'Content-Type': 'application/json',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=max(float(self.config.poll_timeout_seconds), 30.0)) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='replace') if exc.fp else ''
            raise PippitGatewayError(f'submit_run http error status={exc.code} body={detail[:500]}') from exc
        except urllib.error.URLError as exc:
            raise PippitGatewayError(f'submit_run network error: {exc.reason}') from exc
        except Exception as exc:
            raise PippitGatewayError(f'submit_run unexpected error: {exc}') from exc
        if not isinstance(payload, dict):
            raise PippitGatewayError('submit_run raw response is not a json object')
        ret = str(payload.get('ret', '')).strip()
        if ret and ret != '0':
            raise PippitGatewayError(f"submit_run request failed ret={ret} errmsg={payload.get('errmsg', '')}")
        return payload

    def plan_submit_run(self, request: SubmitRunRequest, credential: PippitCredential) -> CliCommandPlan:
        if self._use_official_cli():
            argv = [self.config.cli_command, 'short-drama', '+submit-run', '--message', request.message]
            if request.thread_id:
                argv.extend(['--thread-id', request.thread_id])
            for asset_id in request.asset_ids:
                if _clean_text(asset_id):
                    argv.extend(['--asset-ids', _clean_text(asset_id)])
            return CliCommandPlan(argv=tuple(argv), env=self._base_env(credential), cwd=self.config.working_directory)
        argv = [self.config.python_executable, self.config.submit_script, '--message', request.message]
        if request.thread_id:
            argv.extend(['--thread-id', request.thread_id])
        for asset_id in request.asset_ids:
            if _clean_text(asset_id):
                argv.extend(['--asset-ids', _clean_text(asset_id)])
        env = self._base_env(credential)
        return CliCommandPlan(argv=tuple(argv), env=env, cwd=self.config.working_directory)

    def plan_get_thread(self, *, thread_id: str, run_id: str | None = None, after_seq: int | None = None, credential: PippitCredential) -> CliCommandPlan:
        if self._use_official_cli():
            argv = [self.config.cli_command, 'get-thread', '--thread-id', thread_id]
            if run_id:
                argv.extend(['--run-id', run_id])
            if after_seq is not None:
                argv.extend(['--after-seq', str(int(after_seq))])
            return CliCommandPlan(argv=tuple(argv), env=self._base_env(credential), cwd=self.config.working_directory)
        argv = [self.config.python_executable, self.config.get_thread_script, '--thread-id', thread_id]
        if run_id:
            argv.extend(['--run-id', run_id])
        if after_seq is not None:
            argv.extend(['--after-seq', str(int(after_seq))])
        return CliCommandPlan(argv=tuple(argv), env=self._base_env(credential), cwd=self.config.working_directory)

    def plan_upload_file(self, *, file_path: str, credential: PippitCredential) -> CliCommandPlan:
        cleaned = _clean_text(file_path)
        if not cleaned:
            raise ValueError('file_path is required')
        if self._use_official_cli():
            argv = [self.config.cli_command, 'short-drama', '+upload-file', '--path', cleaned]
            return CliCommandPlan(argv=tuple(argv), env=self._base_env(credential), cwd=self.config.working_directory)
        argv = [self.config.python_executable, self.config.upload_script, '--file', cleaned]
        return CliCommandPlan(argv=tuple(argv), env=self._base_env(credential), cwd=self.config.working_directory)

    def plan_download_results(self, *, urls: Iterable[str], output_dir: str, credential: PippitCredential) -> CliCommandPlan:
        cleaned_output = _clean_text(output_dir)
        cleaned_urls = tuple(_clean_text(item) for item in urls if _clean_text(item))
        if not cleaned_urls:
            raise ValueError('urls is required')
        if not cleaned_output:
            raise ValueError('output_dir is required')
        argv = [self.config.python_executable, self.config.download_script, '--urls', *cleaned_urls, '--output-dir', cleaned_output]
        return CliCommandPlan(argv=tuple(argv), env=self._base_env(credential), cwd=self.config.working_directory)

    def prepare_text_to_image(self, *, prompt: str, style: str | None = None, size: str | None = None, count: int | None = None, thread_id: str | None = None) -> tuple[PippitCredential, SubmitRunRequest, CliCommandPlan]:
        credential = self.key_manager.choose_credential()
        message = build_submit_message(prompt=prompt, mode='text_to_image', style=style, size=size, count=count)
        request = SubmitRunRequest(message=message, thread_id=thread_id)
        plan = self.plan_submit_run(request, credential)
        return credential, request, plan

    def prepare_image_edit(self, *, prompt: str, asset_ids: Iterable[str], style: str | None = None, size: str | None = None, thread_id: str | None = None) -> tuple[PippitCredential, SubmitRunRequest, CliCommandPlan]:
        cleaned_assets = tuple(_clean_text(item) for item in asset_ids if _clean_text(item))
        if not cleaned_assets:
            raise ValueError('asset_ids is required for image_edit')
        credential = self.key_manager.choose_credential()
        message = build_submit_message(prompt=prompt, mode='image_edit', style=style, size=size)
        request = SubmitRunRequest(message=message, thread_id=thread_id, asset_ids=cleaned_assets)
        plan = self.plan_submit_run(request, credential)
        return credential, request, plan

    def upload_file(self, *, file_path: str, credential: PippitCredential) -> UploadResult:
        payload = self.runner.run(self.plan_upload_file(file_path=file_path, credential=credential))
        asset_id = _extract_asset_id(payload)
        if not asset_id:
            raise PippitGatewayError('upload_file did not return asset_id')
        return UploadResult(asset_id=asset_id, media_kind=_detect_media_kind_from_path(file_path), raw=payload)

    def submit_run(self, request: SubmitRunRequest, credential: PippitCredential) -> SubmitResult:
        if request.raw_submit_body:
            payload = self._submit_run_http(request.raw_submit_body, credential)
        else:
            payload = self.runner.run(self.plan_submit_run(request, credential))
        thread_id = _extract_thread_id(payload, request.thread_id)
        if not thread_id:
            raise PippitGatewayError('submit_run did not return thread_id')
        run_id = _extract_run_id(payload)
        return SubmitResult(thread_id=thread_id, run_id=run_id, raw=payload)

    def poll_run_until_terminal(
        self,
        *,
        thread_id: str,
        credential: PippitCredential,
        run_id: str | None = None,
        sleep_func: Any | None = None,
        time_func: Any | None = None,
    ) -> PollResult:
        sleeper = sleep_func or time.sleep
        timer = time_func or time.monotonic
        deadline = timer() + max(float(self.config.poll_timeout_seconds), 1.0)
        last_payload: dict[str, Any] | None = None
        while True:
            payload = self.runner.run(self.plan_get_thread(thread_id=thread_id, run_id=run_id, credential=credential))
            last_payload = payload
            status = _extract_status(payload)
            resolved_thread_id = _extract_thread_id(payload, thread_id) or thread_id
            resolved_run_id = _extract_run_id(payload) or run_id
            if status in {'completed', 'succeeded', 'success', 'done', 'finished'}:
                return PollResult(thread_id=resolved_thread_id, run_id=resolved_run_id, status=status, raw=payload)
            if status in {'failed', 'error', 'cancelled', 'canceled', 'timeout', 'expired'}:
                raise PippitExecutionFailedError(f'run ended with status={status}')
            if timer() >= deadline:
                raise PippitExecutionPendingError(f'poll timeout waiting for terminal status, last_status={status}')
            sleeper(max(float(self.config.poll_interval_seconds), 0.0))

    def download_results(self, *, thread_id: str, output_dir: str, credential: PippitCredential, poll_payload: dict[str, Any] | None = None) -> DownloadResult:
        source_payload = poll_payload if isinstance(poll_payload, dict) else {}
        files = _extract_files(source_payload)
        if not files:
            payload = self.runner.run(self.plan_get_thread(thread_id=thread_id, credential=credential))
            files = _extract_files(payload)
            source_payload = payload
        if not files:
            raise PippitGatewayError('download_results could not find downloadable urls from get_thread payload')
        payload = self.runner.run(self.plan_download_results(urls=files, output_dir=output_dir, credential=credential))
        downloaded = payload.get('downloaded') if isinstance(payload, dict) else None
        normalized_files = tuple(downloaded) if isinstance(downloaded, list) and downloaded else files
        return DownloadResult(thread_id=thread_id, output_dir=output_dir, files=normalized_files, raw=payload if isinstance(payload, dict) else {'files': list(normalized_files), 'source_payload': source_payload})

    def execute_text_to_image(self, *, prompt: str, output_dir: str, style: str | None = None, size: str | None = None, count: int | None = None, thread_id: str | None = None) -> GatewayExecutionResult:
        credential, request, _ = self.prepare_text_to_image(prompt=prompt, style=style, size=size, count=count, thread_id=thread_id)
        return self._execute_request(credential=credential, request=request, output_dir=output_dir)

    def execute_text_to_video(
        self,
        *,
        prompt: str,
        output_dir: str,
        image_asset_ids: Iterable[str] = (),
        video_asset_ids: Iterable[str] = (),
        audio_asset_ids: Iterable[str] = (),
        image_file_paths: Iterable[str] = (),
        video_file_paths: Iterable[str] = (),
        audio_file_paths: Iterable[str] = (),
        duration_sec: int | None = None,
        ratio: str | None = None,
        model: str | None = None,
        resolution: str | None = None,
    ) -> GatewayExecutionResult:
        credential = self.key_manager.choose_credential()
        image_ids = [_clean_text(item) for item in image_asset_ids if _clean_text(item)]
        video_ids = [_clean_text(item) for item in video_asset_ids if _clean_text(item)]
        audio_ids = [_clean_text(item) for item in audio_asset_ids if _clean_text(item)]
        for file_path in image_file_paths:
            upload = self.upload_file(file_path=file_path, credential=credential)
            image_ids.append(upload.asset_id)
        for file_path in video_file_paths:
            upload = self.upload_file(file_path=file_path, credential=credential)
            video_ids.append(upload.asset_id)
        for file_path in audio_file_paths:
            upload = self.upload_file(file_path=file_path, credential=credential)
            audio_ids.append(upload.asset_id)
        request = SubmitRunRequest(
            message=_clean_text(prompt),
            raw_submit_body=build_video_submit_body(
                prompt=prompt,
                image_asset_ids=image_ids,
                video_asset_ids=video_ids,
                audio_asset_ids=audio_ids,
                duration_sec=duration_sec,
                ratio=ratio,
                model=model,
                resolution=resolution,
            ),
        )
        return self._execute_request(credential=credential, request=request, output_dir=output_dir)

    def execute_image_edit(self, *, prompt: str, asset_ids: Iterable[str] = (), file_paths: Iterable[str] = (), output_dir: str, style: str | None = None, size: str | None = None, thread_id: str | None = None) -> GatewayExecutionResult:
        credential = self.key_manager.choose_credential()
        cleaned_assets = [_clean_text(item) for item in asset_ids if _clean_text(item)]
        for file_path in file_paths:
            upload = self.upload_file(file_path=file_path, credential=credential)
            cleaned_assets.append(upload.asset_id)
        if not cleaned_assets:
            raise ValueError('asset_ids is required for image_edit')
        message = build_submit_message(prompt=prompt, mode='image_edit', style=style, size=size)
        request = SubmitRunRequest(message=message, thread_id=thread_id, asset_ids=tuple(cleaned_assets))
        return self._execute_request(credential=credential, request=request, output_dir=output_dir)

    def _execute_request(self, *, credential: PippitCredential, request: SubmitRunRequest, output_dir: str) -> GatewayExecutionResult:
        try:
            submit = self.submit_run(request, credential)
            self.mark_submit_success(credential)
            poll = self.poll_run_until_terminal(thread_id=submit.thread_id, run_id=submit.run_id, credential=credential)
            download = self.download_results(thread_id=submit.thread_id, output_dir=output_dir, credential=credential, poll_payload=poll.raw)
            return GatewayExecutionResult(
                credential=credential,
                request=request,
                submit=submit,
                poll=poll,
                download=download,
            )
        except Exception:
            self.mark_submit_failure(credential)
            raise

    def mark_submit_success(self, credential: PippitCredential, now: datetime | None = None) -> PippitGatewayState:
        return self.key_manager.mark_success(credential, now=now)

    def mark_submit_failure(self, credential: PippitCredential, now: datetime | None = None) -> PippitGatewayState:
        return self.key_manager.mark_failure(credential, now=now)


class PippitKeyManager:
    def __init__(
        self,
        credentials: Iterable[PippitCredential],
        *,
        state_store: PippitStateStore,
        daily_limit_per_key: int = DEFAULT_DAILY_LIMIT_PER_KEY,
    ):
        self.credentials = [item for item in credentials if item.enabled and _clean_text(item.key_id) and _clean_text(item.api_key)]
        self.state_store = state_store
        self.daily_limit_per_key = _coerce_positive_int(daily_limit_per_key, DEFAULT_DAILY_LIMIT_PER_KEY)

    def choose_credential(self, now: datetime | None = None) -> PippitCredential:
        if not self.credentials:
            raise CredentialSelectionError('no enabled pippit credentials configured')
        today = _utc_today_key(now)
        state = self.state_store.load()
        usage = state.daily_usage.get(today, {})
        failures = state.failures

        preferred = None
        if state.selected_key_id:
            preferred = next((item for item in self.credentials if item.key_id == state.selected_key_id), None)
            if preferred and usage.get(preferred.key_id, 0) < self._limit_for(preferred):
                return preferred

        ordered = sorted(
            self.credentials,
            key=lambda item: (usage.get(item.key_id, 0), failures.get(item.key_id, 0), item.key_id),
        )
        for item in ordered:
            if usage.get(item.key_id, 0) < self._limit_for(item):
                return item
        raise CredentialSelectionError('all pippit credentials reached daily limit')

    def mark_success(self, credential: PippitCredential, now: datetime | None = None) -> PippitGatewayState:
        today = _utc_today_key(now)
        state = self.state_store.load()
        day_usage = state.daily_usage.setdefault(today, {})
        day_usage[credential.key_id] = int(day_usage.get(credential.key_id, 0)) + 1
        state.selected_key_id = credential.key_id
        state.failures[credential.key_id] = 0
        state.updated_at = (now or datetime.now(UTC)).isoformat()
        self._cleanup_old_days(state, keep_day=today)
        self.state_store.save(state)
        return state

    def mark_failure(self, credential: PippitCredential, now: datetime | None = None) -> PippitGatewayState:
        state = self.state_store.load()
        state.failures[credential.key_id] = int(state.failures.get(credential.key_id, 0)) + 1
        if state.selected_key_id == credential.key_id:
            state.selected_key_id = None
        state.updated_at = (now or datetime.now(UTC)).isoformat()
        self.state_store.save(state)
        return state

    def _cleanup_old_days(self, state: PippitGatewayState, *, keep_day: str) -> None:
        state.daily_usage = {day: value for day, value in state.daily_usage.items() if day == keep_day}

    def _limit_for(self, credential: PippitCredential) -> int:
        if credential.daily_limit is None:
            return self.daily_limit_per_key
        return _coerce_positive_int(credential.daily_limit, self.daily_limit_per_key)