from pathlib import Path


def _read_block() -> str:
    path = Path('src/plugins/yangyang/__init__.py')
    text = path.read_text(encoding='utf-8')
    marker = 'async def _event_stream():'
    start = text.index(marker)
    end = text.index('return StreamingResponse(', start)
    return text[start:end]


def test_send_stream_has_disconnect_guard():
    block = _read_block()
    assert 'await request.is_disconnected()' in block


def test_send_stream_handles_cancelled_error():
    block = _read_block()
    assert 'except asyncio.CancelledError:' in block


def test_proxy_closed_not_yielded_inside_finally_cleanup():
    block = _read_block()
    finally_start = block.index('finally:')
    finally_end = block.index('if not client_disconnected:', finally_start)
    finally_block = block[finally_start:finally_end]
    assert "yield _yy_sse_encode('proxy_closed'" not in finally_block
    assert "if not client_disconnected:" in block
    assert "yield _yy_sse_encode('proxy_closed', {'session_id': session_id})" in block
