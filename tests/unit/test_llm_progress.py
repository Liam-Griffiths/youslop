"""Synthetic streaming only; never contacts a model server."""
import io
import json
import re

import httpx
import pytest

from app import cli, llm, script_gen


class Stream:
    status_code = 200

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_lines(self):
        yield from self.lines


@pytest.mark.parametrize('backend', ['lmstudio', 'ollama'])
def test_stream_reply_usage_and_rising_counts(monkeypatch, backend):
    monkeypatch.setattr(llm, '_lmstudio_model', lambda *a, **k: 'fake')
    monkeypatch.setattr(llm, 'local_context_tokens', lambda: 32768)
    ticks = iter(range(100))
    monkeypatch.setattr(llm.time, 'monotonic', lambda: next(ticks))
    if backend == 'lmstudio':
        chunks = [{'choices': [{'delta': delta}]} for delta in [
            {'reasoning_content': 'hmm'}, {'reasoning_content': 'yes'},
            {'content': '<think>draft</think>'}, {'content': 'hello'}, {'content': ' world'}]]
        chunks += [{'choices': [{'delta': {}, 'finish_reason': 'stop'}]},
                   {'choices': [], 'model': 'fake', 'usage': {'prompt_tokens': 9, 'completion_tokens': 8}}]
        lines = [': comment', ''] + ['data: ' + json.dumps(c) for c in chunks] + ['data: [DONE]']
    else:
        chunks = [{'message': delta} for delta in [
            {'thinking': 'hmm'}, {'thinking': 'yes'},
            {'content': '<think>draft</think>'}, {'content': 'hello'}, {'content': ' world'}]]
        chunks += [{'done': True, 'model': 'fake', 'prompt_eval_count': 9, 'eval_count': 8}]
        lines = [''] + [json.dumps(c) for c in chunks]

    def stream(method, url, json, timeout):
        assert method == 'POST' and json['stream'] is True
        if backend == 'lmstudio':
            assert json['stream_options'] == {'include_usage': True}
        return Stream(lines)

    monkeypatch.setattr(httpx, 'stream', stream)
    updates = []
    sink = llm.status_sink.set(updates.append)
    label = llm.status_label.set(lambda: 'Writing section')
    try:
        with llm.capture_usage() as usage:
            fn = getattr(llm, '_complete_' + backend)
            assert fn('prompt', '', 'fake', 10, False) == 'hello world'
    finally:
        llm.status_sink.reset(sink)
        llm.status_label.reset(label)
    assert usage[0]['usage']['input_tokens'] == 9
    assert usage[0]['usage']['output_tokens'] == 8
    counts = [int(re.search(r'· (\d+) tokens', u)[1]) for u in updates if ' tokens' in u]
    assert counts == sorted(counts) and counts[0] < counts[-1] == 8
    assert any('(thinking)' in u for u in updates)
    assert updates[0].startswith('Writing section · waiting for ')
    assert updates[-1] == ''


@pytest.mark.parametrize('backend', ['lmstudio', 'ollama'])
def test_timeout_clears_status(monkeypatch, backend):
    monkeypatch.setattr(llm, '_lmstudio_model', lambda *a, **k: 'fake')
    monkeypatch.setattr(llm, 'local_context_tokens', lambda: None)

    def fail(*a, **k):
        raise httpx.ReadTimeout('synthetic timeout')

    monkeypatch.setattr(httpx, 'stream', fail)
    updates = []
    token = llm.status_sink.set(updates.append)
    try:
        with pytest.raises(llm.LLMError, match='timed out'):
            getattr(llm, '_complete_' + backend)('x', '', 'fake', 10, False)
    finally:
        llm.status_sink.reset(token)
    assert updates[-1] == ''


def test_hosted_waiting_status_cleared(monkeypatch):
    monkeypatch.setattr(llm, 'resolve_backend', lambda: 'api')
    monkeypatch.setattr(llm, '_complete_api', lambda *a: 'reply')
    updates = []
    token = llm.status_sink.set(updates.append)
    try:
        assert llm.complete('x') == 'reply'
    finally:
        llm.status_sink.reset(token)
    assert updates == ['Model call · waiting for Anthropic API', '']


@pytest.mark.parametrize('tty', [True, False])
def test_cli_status_only_on_tty(monkeypatch, tty):
    stderr = io.StringIO()
    monkeypatch.setattr(stderr, 'isatty', lambda: tty)
    monkeypatch.setattr(cli.sys, 'stderr', stderr)
    output = cli._StatusLine()
    output.status('12 tokens')
    output.progress('Next step')
    assert ('\r12 tokens' in stderr.getvalue()) is tty
    assert stderr.getvalue().endswith('Next step\n')


def test_script_pools_inherit_sink_and_usage(monkeypatch, project):
    updates = []

    def section(*args):
        llm.status_sink.get()('writing')
        llm._record_usage('fake', {'output_tokens': 1})
        return [{'kind': 'body', 'beat': 'Beat', 'text': 'Words.', 'visual': 'Picture'}]

    def visual(*args, **kwargs):
        llm.status_sink.get()('planning')
        llm._record_usage('fake', {'output_tokens': 2})
        return [{'n': 1, 'queries': ['picture']}]

    monkeypatch.setattr(script_gen, '_write_section', section)
    monkeypatch.setattr(script_gen, 'complete_json', visual)
    token = llm.status_sink.set(updates.append)
    try:
        with llm.capture_usage() as usage:
            slides = script_gen.write_script(project, {'sections': [{'heading': 'First'}, {'heading': 'Second'}]})
            script_gen.plan_visuals(project, slides)
    finally:
        llm.status_sink.reset(token)
    assert updates.count('writing') == 2 and 'planning' in updates
    assert sum(row['usage']['output_tokens'] for row in usage) >= 4


def test_updates_throttled_and_label_tracks_latest_log(monkeypatch):
    ticks = iter([0, .1, .2, .5, .7, 1.0])
    monkeypatch.setattr(llm.time, 'monotonic', lambda: next(ticks))
    updates, label = [], ['First step']
    sink = llm.status_sink.set(updates.append)
    label_token = llm.status_label.set(lambda: label[0])
    try:
        counter = llm._StreamProgress()
        for _ in range(4):
            counter.update(content='token')
        label[0] = 'Next step'
        counter.update(content='token')
    finally:
        llm.status_sink.reset(sink)
        llm.status_label.reset(label_token)
    assert len(updates) == 2
    assert updates[0].startswith('First step · 3 tokens')
    assert updates[1].startswith('Next step · 5 tokens')
