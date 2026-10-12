# The bundled typefaces

Every face here is under the **SIL Open Font License 1.1** (`OFL.txt`), which a
GPLv3 program may ship. They are bundled rather than borrowed from the system
because the typography used to resolve to twenty-five absolute macOS font
paths: on Windows or Linux every stack fell through to Pillow's default bitmap
face, and since the layout code measures text to fit it, titles, thumbnails,
slates and end screens did not merely look wrong — they mis-wrapped and
overflowed. One of the old paths pointed at a font bought and installed by
hand, so even another Mac was not safe.

The macOS faces are still listed behind these in every stack (see
`app/titles.py` and `app/diagram.py`), because where they exist they are what
every video made before this looked like.

| File | Family | Used for | Replaces (macOS) |
| --- | --- | --- | --- |
| `Inter-SemiBold.ttf` | Inter | slide titles, most UI type | Avenir Next Demi Bold |
| `Inter-Medium.ttf` | Inter | kickers, small caps lines | Avenir Next Medium |
| `Inter-Bold.ttf` | Inter | spare weight | — |
| `ArchivoBlack-Regular.ttf` | Archivo Black | display slates, thumbnails | SF Compact Black |
| `ArchivoNarrow-Bold.ttf` | Archivo Narrow | condensed layouts | Avenir Next Condensed |
| `EBGaramond-Regular.ttf` | EB Garamond | the printed-title-page slate | Baskerville |
| `EBGaramond-Italic.ttf` | EB Garamond | its italic | Baskerville Italic |
| `CormorantSC-SemiBold.ttf` | Cormorant SC | small-caps lines | Bodoni 72 Smallcaps |
| `JetBrainsMono-Bold.ttf` | JetBrains Mono | code boards, terminal slates | iA Writer Mono Bold |
| `JetBrainsMono-Regular.ttf` | JetBrains Mono | the lighter mono | iA Writer Mono |
| `ShantellSans-SemiBold.ttf` | Shantell Sans | the board's **marker** hand | Marker Felt Wide |
| `Caveat-Bold.ttf` | Caveat | the **ballpoint** hand | Bradley Hand Bold |
| `RockSalt-Regular.ttf` | Rock Salt | the **chalk** hand | Chalkduster |
| `PatrickHand-Regular.ttf` | Patrick Hand | the **casual** hand | Skia |
| `PermanentMarker-Regular.ttf` | Permanent Marker | the **poster** hand | — |

Copyright, as recorded in each file:

- Inter — Copyright 2016 The Inter Project Authors, <https://github.com/rsms/inter>
- Archivo Black — Copyright 2017 The Archivo Black Project Authors
- Archivo Narrow — Copyright 2019 The Archivo Narrow Project Authors
- EB Garamond — Copyright 2017 The EB Garamond Project Authors
- Cormorant SC — Copyright 2015 The Cormorant Project Authors
- JetBrains Mono — Copyright 2020 The JetBrains Mono Project Authors
- Shantell Sans — Copyright 2022 The Shantell Sans Project Authors
- Caveat — Copyright 2014 The Caveat Project Authors
- Patrick Hand — Copyright (c) 2012 Patrick Wagesreiter
- Permanent Marker, Rock Salt — Copyright (c) 2010 Font Diner, Inc.

All fetched from Google Fonts. `OFL.txt` is the licence they share.
