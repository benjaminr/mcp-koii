# KOII Pattern Notation

A small text format for writing beats, basslines and songs for the EP-133 K.O. II.
It is designed to be easy to read, easy to write (by people and by Claude), and
strict: anything ambiguous is an error with a line and column, never a silent guess.

```
# Boom-bap verse
@bpm 92
@swing 58

kick:  x... ..x. x... ....
snare: .... x... .... x..o
hat:   x.x. x.x. x.x. x.xX
```

## The one rule

**Every track is a grid. One character = one step.** With the default grid each
step is a 16th note, so 16 characters is one bar of 4/4. Spaces and `|` are
ignored, so group steps however helps you count:

```
kick: x...x...x...x...
kick: x... x... x... x...
kick: x...|x...|x...|x...
```

## Step characters

| Char  | Meaning                                          | Velocity |
|-------|--------------------------------------------------|----------|
| `x`   | hit                                              | 100      |
| `X`   | accent                                           | 127      |
| `o`   | ghost note                                       | 50       |
| `1`–`9` | hit at a level (1 = softest, 9 = hardest)      | 14, 28, 42, 56, 71, 85, 99, 113, 127 |
| `.`   | rest                                             | –        |
| `-`   | hold: the previous note keeps sounding this step | –        |

Anything else is an error. `-` must follow a hit or another `-`.

Holds only change what you hear when the pad is in a gated play mode
(KEY / LEGATO in Sound Edit); in ONESHOT mode the sample always plays to its end.

## Tracks

```
<name>: <steps>
```

`<name>` says which sound to play. It is resolved in this order:

1. a `@map` in the pattern (see below)
2. a kit alias: built in (`kick`, `snare`, `hat`, …) or one you've set with `set_alias`
3. a pad label: `A.` `A0` `AEnter` `A1` … `A9`, the same for groups B, C, D
   (`AE` and `AFX` are accepted for `AEnter`)
4. a MIDI note number (`0`–`127`) or a MIDI channel (`ch1`–`ch16`, for pitched tracks)

Names have no spaces (use `openhat` or `oh`, not `open hat`) and are case-insensitive.

Writing the same track name again **continues** that track, which is the easy way
to write multi-bar parts:

```
kick: x...x...x...x...
kick: x...x...x..xx...      # bar 2: kick is now 32 steps long
```

## Pattern length

The pattern is as long as its longest track. A shorter track must divide that
length evenly, and it repeats to fill it:

```
kick: x...x...x...x...x...x...x..x.x..   # 32 steps
hat:  x.x.                               # 4 steps, repeats 8 times
```

Any other length is an error that names the longest track, which catches the most
common counting mistake.

## Pitched tracks: basslines, chords and melodies

Pads play a fixed sample. To play *pitches*, send notes on a MIDI channel that a
pad listens to, and give the track a `notes` line:

```
@map bass = ch2

bass:       x..x..x.x-..x...
bass notes: C1 C1 Eb1 G0 C1
```

- The grid gives the rhythm; the `notes` line gives the pitches.
- Each hit takes the next note. If the list runs out it starts again from the
  first note, so `bass notes: C1` plays every hit on C1.
- Chords join notes with `+`: `C3+Eb3+G3`.
- Note names: `C4` = MIDI 60 (middle C), sharps `#`, flats `b`, octaves −1 to 9.
  Plain MIDI numbers (`48`) work too.

A pitched track **must** play on a channel (`chN`), and a pad track can't have a
`notes` line. On the device, set the pad that should play the line to that MIDI
channel (Sound Edit → MIDI page, OS 2.0+). See [DEVICE.md](DEVICE.md).

Pitched notes from C2 (36) to B5 (83) share note numbers with pads, and by default
the EP-133's other pads hear every channel, so they would play along. The pattern
summary shows a warning when that can happen; keep basslines below C2 or change the
device's receive channel as DEVICE.md describes.

## Directives

Directives start with `@` and apply to the whole pattern. All are optional.

| Directive | Values | Default | Meaning |
|-----------|--------|---------|---------|
| `@bpm 92` | 20–300 | 120 | Tempo |
| `@swing 58` | 50–75 | 50 | Swing percent. 50 = straight, ~66 = triplet feel |
| `@grid 1/16` | `1/4` `1/8` `1/16` `1/32` `1/8t` `1/16t` | `1/16` | Length of one step (`t` = triplet) |
| `@map name = target` | pad label, MIDI note, or `ch1`–`ch16` | – | Name a sound for this pattern only |

Swing, precisely: steps come in pairs; the second step of each pair starts at
`swing%` of the pair's duration instead of 50%.

## Comments

`#` starts a comment when it begins a line or follows a space. A `#` inside a
note name (`C#2`) is part of the note.

## Songs

A song is an arrangement of saved patterns:

```
intro x2, verse x4, verse+bassline x4, chorus x8, outro
```

- `name xN` plays a pattern N times (default 1).
- `a+b` plays patterns together. As with tracks, the shorter one must divide the
  longer one and repeats.
- Sections are separated by commas or new lines.
- A song name can appear inside another song.
- Each section uses the tempo of its first pattern unless the song sets a tempo.

The same syntax works anywhere you can play something, so
`play("verse x2, chorus x2")` works without saving a song first.

## Full example

```
# Two-bar groove with a bassline
@bpm 98
@swing 56
@map bass = ch2

kick:  x...|..x.|x...|....
kick:  x...|..x.|x..x|..x.
snare: ....|x...|....|x...
hat:   x.x.|x.x.|x.x.|x.xX
oh:    ....|....|....|..x.

bass:       x..x|..x-|x...|.x..
bass:       x..x|..x-|x.x.|x...
bass notes: C1 C1 G0 C1 Eb1 C1 C1 G0 Bb0 C1
```
