"""Deterministic speed-test streams; no server, model or benchmark runs."""
import json

import httpx
import pytest

from app import llm


@pytest.fixture
def speed_stream(monkeypatch):
    clock = [10.0]
    sent, updates = [], []
    monkeypatch.setattr(llm.time, 'monotonic', lambda: clock[0])
    probe = dict(reachable=True, model='anonymous', context=32768, warning='')
    monkeypatch.setattr(llm, 'local_probe', lambda: probe)
    token = llm.status_sink.set(updates.append)

    def run(total=100, reasoning=80, content='["cup"]', thinking='hmm', finish='stop', usage=True):
        class Stream:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def iter_lines(self):
                # Role/keepalive chunks must not count as the first token.
                yield ': keepalive'
                yield 'data: ' + json.dumps({'choices': [{'delta': {'role': 'assistant'}}]})
                clock[0] = 12.0
                yield 'data: ' + json.dumps({'choices': [{'delta': {'reasoning_content': thinking}}]})
                clock[0] = 16.0
                yield 'data: ' + json.dumps({'choices': [{'delta': {'content': content}}]})
                clock[0] = 22.0
                details = {} if reasoning is None else {'reasoning_tokens': reasoning}
                yield 'data: ' + json.dumps({'model': 'served-model', 'choices': [
                    {'delta': {}, 'finish_reason': finish}], 'usage': {
                        'completion_tokens': total, 'completion_tokens_details': details} if usage else {}})
                yield 'data: [DONE]'

        def stream(method, url, json, timeout):
            sent.append(json)
            assert method == 'POST' and url.endswith('/chat/completions')
            return Stream()

        monkeypatch.setattr(httpx, 'stream', stream)
        return llm.local_speed_test()

    yield run, sent, updates, probe
    llm.status_sink.reset(token)


def test_timing_split_request_and_status(speed_stream, monkeypatch):
    run, sent, updates, _ = speed_stream
    monkeypatch.setattr(llm, 'LMSTUDIO_THINKING', 'off')
    monkeypatch.setitem(llm._json_mode, 'on', True)
    result = run()
    assert result['first_token_seconds'] == 2
    assert result['generation_seconds'] == 10
    assert result['tokens_per_second'] == 10
    assert result['reasoning_tokens'] == 80
    assert result['answer_tokens'] == 20
    assert result['model'] == 'served-model'
    assert not result['estimated']
    assert len(sent) == 1
    assert sent[0]['max_tokens'] == 1024
    assert sent[0]['stream_options'] == {'include_usage': True}
    assert 'reasoning_effort' not in sent[0] and 'response_format' not in sent[0]
    assert any('thinking' in line for line in updates)
    assert updates[-1] == ''
    assert 'Never' in ' '.join(result['advice'])
    # 10 tok/s, 2 s first token x 12 calls; 4,000 tokens never, 30,000 auto.
    assert result['estimates']['never_minutes'] == pytest.approx((24 + 400) / 60)
    assert result['estimates']['auto_minutes'] == pytest.approx((24 + 3000) / 60)


@pytest.mark.parametrize('total,reasoning,thinking_advice,slow_advice', [
    (40, 20, True, True), (50, 20, True, False),
    (299, 20, True, False), (300, 20, False, False),
    (100, 0, False, False), (40, 0, False, True),
])
def test_advice_thresholds(speed_stream, total, reasoning, thinking_advice, slow_advice):
    run, _, _, _ = speed_stream
    result = run(total=total, reasoning=reasoning)
    advice = ' '.join(result['advice'])
    assert ('Local model thinking: Never' in advice) is thinking_advice
    assert ('smaller model or GPU offload' in advice) is slow_advice
    assert (result['estimates'] is not None) is thinking_advice


def test_context_warning_and_truncated_thinking(speed_stream):
    run, sent, _, probe = speed_stream
    probe.update(context=4096, warning='Reload with 16k or more (32k is better).')
    result = run(total=1024, reasoning=1024, content='', finish='length')
    assert result['truncated'] and result['answer_tokens'] == 0
    assert probe['warning'] in result['advice']
    assert '1,024-token limit' in ' '.join(result['advice'])
    assert len(sent) == 1


@pytest.mark.parametrize('content,thinking,reasoning', [
    ('["cup"]', 'hmm', True),
    ('<think>still thinking', '', True),
    ('<think>done</think>["cup"]', '', True),
    ('draft</think>["cup"]', '', True),
    ('["cup"]', '', False),
])
def test_missing_usage_is_explicitly_estimated(speed_stream, content, thinking, reasoning):
    run, _, _, _ = speed_stream
    result = run(content=content, thinking=thinking, usage=False)
    assert result['estimated']
    assert (result['reasoning_tokens'] > 0) is reasoning
    assert result['answer_tokens'] + result['reasoning_tokens'] == result['completion_tokens']
    assert 'estimated' in ' '.join(result['advice'])


def test_missing_split_preserves_reported_total(speed_stream):
    run, _, _, _ = speed_stream
    result = run(total=100, reasoning=None)
    assert result['estimated'] and result['completion_tokens'] == 100
    assert result['reasoning_tokens'] == 30  # 3 reasoning / 10 total characters
    assert result['answer_tokens'] == 70


def test_no_tokens_fails_and_clears_status(speed_stream):
    run, _, updates, _ = speed_stream
    with pytest.raises(llm.LLMError, match='no tokens'):
        run(content='', thinking='', usage=False)
    assert updates[-1] == ''


def test_unavailable_probe_sends_no_prompt(speed_stream, monkeypatch):
    run, _, updates, probe = speed_stream
    probe.update(reachable=False, warning='Server unavailable')
    monkeypatch.setattr(httpx, 'stream', lambda *a, **k: pytest.fail('must not send'))
    with pytest.raises(llm.LLMUnavailable, match='Server unavailable'):
        run()
    assert updates[-1] == ''


def test_speed_endpoint_queues_app_job(monkeypatch):
    from app import main

    def start(kind, pid, worker):
        assert kind == 'local speed test' and pid == ''
        assert worker(lambda message: None) == {'synthetic': True}
        return 'jsynthetic'

    monkeypatch.setattr(main.jobs, 'start', start)
    monkeypatch.setattr(llm, 'local_speed_test', lambda: {'synthetic': True})
    assert main.llm_local_speed() == {'job': 'jsynthetic'}
    assert any(route.path == '/api/llm/local/speed' and 'POST' in route.methods
               for route in main.app.routes)
