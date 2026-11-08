"""Render-sized Commons renditions never request an unscaled original."""
from app.media import providers


def test_narrow_original_gets_a_standard_thumbnail(monkeypatch):
    asked = []
    def fake_get(url, name, params):
        asked.append(int(params['iiurlwidth']))
        w = int(params['iiurlwidth'])
        if w >= 1585:  # Commons returns the original when asked for more than it has.
            info = dict(url='https://upload.example/orig.jpg', width=1585, height=1293,
                        thumburl='https://upload.example/orig.jpg?thumbnail_unscaled', thumbwidth=1585, thumbheight=1293)
        else:
            info = dict(url='https://upload.example/orig.jpg', width=1585, height=1293,
                        thumburl=f'https://upload.example/thumb/{w}px.jpg', thumbwidth=w, thumbheight=round(1293 * w / 1585))
        return {'query': {'pages': [{'imageinfo': [info]}]}}
    monkeypatch.setattr(providers, '_get', fake_get)
    wm = next(p for p in (getattr(providers, n) for n in dir(providers))
              if isinstance(p, type) and hasattr(p, 'THUMB_STEPS'))()
    url, w, h = wm.full_url('File:Card.jpg')
    assert asked == [1920, 1280]
    assert url.endswith('/1280px.jpg') and (w, h) == (1280, 1044)


def test_wide_original_keeps_one_request(monkeypatch):
    asked = []
    def fake_get(url, name, params):
        asked.append(int(params['iiurlwidth']))
        return {'query': {'pages': [{'imageinfo': [dict(url='o', width=4000, height=3000,
                 thumburl='https://upload.example/thumb/1920px.jpg', thumbwidth=1920, thumbheight=1440)]}]}}
    monkeypatch.setattr(providers, '_get', fake_get)
    wm = next(p for p in (getattr(providers, n) for n in dir(providers))
              if isinstance(p, type) and hasattr(p, 'THUMB_STEPS'))()
    assert wm.full_url('File:Map.jpg')[1:] == (1920, 1440) and asked == [1920]
