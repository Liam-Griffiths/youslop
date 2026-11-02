"""Offline Script interaction checks and one 40-paragraph paint measurement.

CORKBORED_DATA=$(mktemp -d) .venv/bin/python scripts/verify_script_stage.py
Uses the UI harness's isolated synthetic data and model-call guards.
"""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ui_snapshots import seed, server


def main():
    with tempfile.TemporaryDirectory(prefix='corkbored-script-') as data:
        os.environ.update(CORKBORED_DATA=data, YOUSLOP_DATA=data, CORKBORED_TOKEN='off')
        from app.stage import _evaluate, _run_cdp
        seed()
        with server() as base:
            def visit(cdp, session, run):
                cdp.send('Page.navigate', {'url': base + '#/p/psnapessay/script'}, session)
                cdp.wait_event('Page.loadEventFired')
                result = _evaluate(cdp, session, r'''(async () => {
                  const wait = async predicate => {
                    for (let i=0; i<200; i++) {
                      if (predicate()) return;
                      await new Promise(r => setTimeout(r,25));
                    }
                    throw Error('Timed out waiting for Script');
                  };
                  const assert = (ok, msg) => { if (!ok) throw Error(msg); };
                  await wait(() => document.querySelector('.script-counts'));
                  const seed = state.project.slides[0];
                  state.project.slides = Array.from({length:40}, (_,i) => ({...seed,
                    id:'paragraph'+i, chapter:i===0?'Opening':'', narration:'Paragraph '+i,
                    title:'', visual_note:'Fixture picture', word_count:2}));
                  const start = performance.now();
                  paintScript();
                  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
                  const paint_ms = performance.now() - start;
                  const cards = [...document.querySelectorAll('.script-card')];
                  assert(cards.length===40, '40 paragraph cards');
                  cards[0].focus();
                  cards[0].dispatchEvent(new KeyboardEvent('keydown',{key:'j',bubbles:true}));
                  assert(document.activeElement===cards[1], 'J moves');
                  cards[1].dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
                  assert(document.activeElement===cards[1].querySelector('textarea'), 'Enter edits');
                  document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
                  assert(document.activeElement===cards[1], 'Escape leaves editing');
                  scriptFind('Paragraph 39');
                  assert(document.querySelectorAll('.script-unit:not([hidden])').length===1, 'Find');
                  scriptFind('');
                  assert(document.querySelectorAll('.script-unit:not([hidden])').length===40, 'Clear find');
                  assert(document.documentElement.scrollWidth<=innerWidth, 'No horizontal overflow');
                  return {passed:6, paint_ms:Math.round(paint_ms*100)/100, paragraphs:40};
                })()''')
                print(result)
            _run_cdp({'items': []}, print, size=(1600, 1000), session_action=visit)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
