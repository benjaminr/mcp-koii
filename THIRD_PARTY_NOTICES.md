# Third-party notices

koii studio's own code is under the MIT licence in [LICENSE](LICENSE). It also relies on
the work below.

## ep-series-sysex

`koii_studio/files.py` talks to the EP-133's file system (the sample library, projects and
pads) following the protocol reverse-engineered in
[kmorrill/ep-series-sysex](https://github.com/kmorrill/ep-series-sysex), including its
safety rules and its verified write sequence. That project is under the MIT licence:

```
MIT License

Copyright (c) 2026 Kevin Morrill

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Libraries

Installed separately (see `requirements.txt`), each under its own licence:
[mido](https://github.com/mido/mido) (MIT),
[python-rtmidi](https://github.com/SpotlightKid/python-rtmidi) (MIT),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT),
[NumPy](https://numpy.org/) (BSD) and [SciPy](https://scipy.org/) (BSD).

## Teenage Engineering

EP-133 and K.O. II are trademarks of teenage engineering, which doesn't make or endorse
koii studio. The factory sound names in `koii_studio/device.py` were read off the device's
display so patterns can name pads; the on-screen device in the visualiser is drawn by
koii studio, in CSS, to match the hardware's layout.
