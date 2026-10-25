# Sound design

koii studio has a small synthesiser and sampler built for the EP-133. Designs are JSON. The
same engine renders them for Claude (over MCP), for the visualiser's designer (module 06)
and for upload, so what you hear in the browser is what goes on the device.

Every sound renders at the device's own rate (46,875 Hz, 16-bit) and is normalised.
Uploading sets the sample's root note, loop and play mode for you.

## A design

```json
{
  "name": "dusty keys",
  "length": 2.0,
  "stereo": false,
  "layers": [
    {"engine": "fm", "pitch": 261.63, "level": 0.8,
     "params": {"ratio": 1, "mod_ratio": 1, "index": 2.2, "index_decay": 600},
     "amp": {"attack": 2, "decay": 1500, "sustain": 0.3, "release": 300},
     "filter": {"type": "lowpass", "cutoff": 6000, "end": 2500, "time": 800},
     "lfos": [{"target": "pitch", "shape": "sine", "rate": 5, "depth": 0.01, "fade": 400}]}
  ],
  "effects": [{"type": "chorus", "mix": 0.3}, {"type": "lofi", "bits": 12, "mix": 0.5}],
  "instrument": {"playmode": "key", "root": "auto", "loop": "auto", "release": 160}
}
```

Leave anything out and it takes its default. `design_sound` returns the full design
with every default filled in, and `sound_design_schema` lists every setting with its
range and unit. A mistake names its exact place, e.g. `layers[0].amp.decay must be
1–10000 ms`.

## Layers: up to 6, mixed together

Each layer is a sound source with its own pitch, envelopes, filter and LFOs:

| Engine | What it's for | Key settings |
|--------|---------------|--------------|
| `analog` | basses, leads, pads, kick bodies | `wave` (sine, triangle, saw, square, pulse), `voices` + `detune` for unison, `sub` |
| `fm` | electric pianos, bells, metallic basses | `ratio`, `mod_ratio`, `index` (brightness), `index_decay`, a second modulator |
| `pluck` | plucked strings, harps, kalimba-like tones | `brightness`, `sustain`, `pick` |
| `modal` | struck objects: marimba, glass, bells, wood, membranes (toms, congas) | `material`, `decay`, `hardness`, `inharmonic` |
| `metal` | cymbals, hats, cowbells (808-style square clusters) | `cluster`, `tune` |
| `additive` | organs, choirs, drawbar tones | harmonic levels `h1`–`h16`, `decay_tilt` |
| `noise` | snares, claps, hats, shakers, risers, vinyl | `colour` (white, pink, brown, blue, crackle), `bursts` + `spacing` for claps |
| `sample` | a recording, a loaded file, a slice, or a device sound | `source`, `start`/`end`, `mode` (play or granular), `reverse`, grain settings |

Every layer also has:

- `level`, `pan` (stereo designs), `pitch` (Hz), and `delay` (ms, for flams and layered attacks)
- `amp`: `attack`, `hold`, `decay`, `sustain`, `release` (ms) and `curve` (0 linear … 1 snappy)
- `pitch_env`: `amount` (semitones above the pitch to start at) and `time`; this is the kick drop and the zap
- `filter`: `type` (lowpass, highpass, bandpass, notch), sweeping from `cutoff` to `end` over `time`, plus `resonance`
- `lfos` (up to 3): `target` (pitch, cutoff, amp, pan), `shape`, `rate`, `depth` and `fade` (ms before it reaches full depth)

A `sample` layer's `source` is a source id (see `list_designs`), or `slot:N` to use device
sound N as saved by the latest backup. Its `pitch` is relative to C4 (261.63 Hz): 261.63
plays the sample as it is, and 523.25 plays it an octave up.

## Effects: in order, up to 10

`eq` (low, mid and high bands) · `drive` (`tanh`, `fold`, `clip`, `tube`) · `lofi` (bits,
rate, noise) · `compressor` · `transient` (attack and sustain shaping) · `chorus` ·
`delay` · `reverb` (size, decay, damping, predelay) · `width` (stereo amount and Haas
delay). Most have a `mix`.

## On the device: `instrument`

| Setting | |
|---------|-|
| `playmode` | `oneshot` plays the whole sample. `key` and `legato` stop when the pad is released, and can sustain on a loop |
| `root` | `auto` detects the pitch and sets the root note plus fine tune, so the pad plays in tune; `none` leaves C4; or a MIDI note |
| `loop` | `auto` finds a seamless loop in the sustained part and crossfades it. A one-shot becomes `key`, since only key and legato sustain |
| `attack`, `release` | the device's own envelope, 0–255 (factory loops use a release of about 64–128) |
| `amplitude` | the device's level, 0–100 |
| `tempo` | `bpm` makes the device stretch the sample to the project tempo; set `bpm` (60–180) and `bars` (0.25–4) |

## Exploring

- `vary_sound(design, amount, locks)`: variations. 0.1 is subtle, 0.3 is related, 0.7 is
  wild. Locks are dotted paths with `*`: `layers.*.amp` keeps every envelope, `effects`
  keeps the chain, `layers.0` keeps the first layer whole. Pitch and level move less than
  other settings, so variations stay in tune and in balance. Length only changes with
  `!length`.
- `morph_sounds(a, b, t)`: part way between two designs. Matching layers (same place,
  same engine) blend setting by setting; others crossfade.
- The analysis after each render gives pitch, LUFS, peak, brightness (spectral centroid),
  attack, decay and the three closest sounds on the device. Use it to steer, e.g.
  "brightness 6 kHz is harsh for a kick; bring the click down".

## Recipes

- **Kick:** an analog sine at 45–55 Hz with a pitch drop of 12–30 semitones over 30–60 ms,
  decay 200–1100 ms (long for 808s), plus a short highpassed noise click and a little drive.
- **Snare:** a triangle body at 180–220 Hz with a small drop, plus bandpassed white noise
  at 2–4 kHz. `transient` adds snap.
- **Clap:** noise with `bursts` 3–4 and `spacing` 8–12 ms through a bandpass at about 1.2 kHz,
  plus a short reverb.
- **Hats:** highpassed noise above 7 kHz with a `metal` cymbal layer; decay 30–60 ms closed,
  250–400 ms open.
- **Bass that plays in tune on pads:** any pitched source with `root: auto` and
  `loop: auto`. The detected root makes the device transpose it correctly.
- **Pads and strings:** detuned saws (`voices` 4–5), a slow attack, a lowpass, chorus and
  reverb, and `loop: auto`.
- **Texture from a recording:** a `sample` layer in `granular` mode with a long grain
  (150–300 ms), some `spray` and `grain_pitch`, then reverb. Try it on a device sound
  (`slot:N`).
- **Lofi anything:** `lofi` with 10–12 bits at 16–22 kHz, `eq` with the highs down, and a
  `vinyl crackle` layer at a low level.

## Sampling

In the visualiser's sample tab:

- **Record** the EP-133's USB audio.
- **Bounce** a pattern: koii studio plays it on the device once while the page records, and the
  result is trimmed to exactly its bars and starts on the first hit. It uploads with tempo
  sync on.
- **Load** a file.

Edits (trim, fades, reverse, normalise, pitch, stretch, mono) are a list of steps, so the
original never changes. **Chop** cuts at detected hits or into equal slices, and the first
12 slices can go to 12 slots in a row. Claude can do the same with `chop_source`.

## Kits

`make_kit(style)` builds twelve sounds in group A pad order (`.` `0` ENTER `1`–`9`). The
styles are 808, 909, lofi, acoustic, industrial and glitch. `upload=True` puts them in 12
empty slots in a row, in the background. Each pad then needs assigning on the device:
press SOUND, hold the pad, and use − / + to reach the slot.
