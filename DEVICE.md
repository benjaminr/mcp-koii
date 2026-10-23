# EP-133 K.O. II: capabilities, limits and MIDI reference

What this project relies on, where each fact comes from, and how sure we are.

- **Hardware** = checked on a real EP-133 (OS 2.5) over USB on macOS, October 2026.
- **Official** = Teenage Engineering's [EP-133 guide](https://teenage.engineering/guides/ep-133)
  or [product page](https://teenage.engineering/products/ep-133).
- **Community** = reverse engineering or forum reports; not published by TE.
- **Unknown** = sources conflict or nobody has said.

## Capabilities at a glance

| Area | Fact | Source | What koii does |
|------|------|--------|----------------|
| Connection | USB-C port named `EP-133`, MIDI in and out | hardware | finds it automatically |
| Connection | Also a class-compliant USB audio device: 2 in / 2 out, 48 kHz on macOS | hardware | the visualiser's sound module listens to it |
| Connection | Identity request answers with manufacturer `00 20 76`, device `33`; version bytes are zero | hardware | can't read the OS version this way |
| Notes | 4 groups × 12 pads = notes 36–83, groups 12 notes apart, pad order `.` `0` ENTER `1`–`9` | hardware | pad labels and kit names map to these |
| Notes | Receives on all channels, sends on channel 1 | official; sending checked | plays pads on channel 1 by default |
| Notes | Incoming velocity is respected even with pad velocity off | hardware | `x X o 1–9` dynamics need no setup |
| Notes | Pad presses go out at a fixed velocity 100 while pad velocity is off | hardware | shown live in the visualiser |
| Pitch | A pad can have its own MIDI channel (Sound Edit → MIDI, knob X) and root note (knob Y) | official; channel checked | pitched tracks play on `chN` |
| Pitch | That pad still plays from its own pad note on channel 1 too | hardware | the same pad works as drum and bassline |
| Pitch | Pads without their own channel hear every channel, so pitched notes 36–83 also fire them | hardware | warns about clashing notes |
| Voices | 16 mono / 12 stereo voices; fewer with time-stretched, stereo or high-pitched samples | official | warns when a step starts more than 12 notes |
| Voices | ONESHOT pads play the whole sample and ignore note-off; KEY and LEGATO stop on note-off | official | holds (`-`) only matter in KEY/LEGATO |
| Control | Program change no longer switches sounds (since OS 2.0.2) | official | not used |
| Control | Bank select (CC 0/32) reaches sounds 1–999 | official | not used |
| Control | OS 2.5: CC 64 sustain for KEY/LEGATO pads; CC 12/13 drive FX X/Y | official | FX control planned |
| Sync | MIDI clock in/out, sync 1/8, 1/16 or 24 PPQN, MIDI thru | official | koii plays notes itself and sends no clock |
| Samples | 999 slots, 128 MB (64 MB on early units) | official | |
| Samples | Library read over the private file protocol (SysEx): list, metadata, download, audition | hardware (community protocol) | `list_device_sounds`, the samples module, backups |
| Samples | Stored as 16-bit **little-endian** PCM at 46,875 Hz (mono on this unit's factory sounds) | hardware | downloads convert to WAV |
| Samples | Each sample's `crc` metadata is a standard CRC-32 of its audio bytes | hardware | every download and backup is checked against it |
| Samples | Reading runs at about 26 KB/s (about 20 minutes for 33 MB) | hardware | backups copy unchanged samples from the previous one |
| Samples | Each sample has its own root note (e.g. slot 401 "s95x round" is F1, most are C4) | hardware | explains basslines sounding transposed |
| Samples | The file system handles one session at a time; overlapping sessions freeze it until power-cycled | community | every session holds `/tmp/ep-device.lock` |
| Samples | Uploading works: 433-byte pages, about 5 KB/s; the device computes the CRC-32 itself, so reading it back proves the sound arrived intact | hardware | uploads only to empty slots or koii's own, after a backup |
| Samples | Sample names are at most 20 ASCII characters | community | names are trimmed |
| Samples | Each sample's settings are JSON metadata: `sound.rootnote`, `sound.pitch` (fine tune, semitones), `sound.playmode` (`oneshot`, `key`, `legato`), `sound.loopstart`/`loopend` (frames; −1 for none), `envelope.attack`/`release` (0–255), `sound.amplitude` (0–100), `time.mode` (`off` or `bpm`), `sound.bpm`, `sound.bars` | hardware | designed sounds upload with these set |
| Samples | Settings can be changed without touching the audio; the CRC stays the same | hardware | `change_sound_settings` |
| Samples | Enums must be written as strings, and `sound.playmode` only together with `envelope.release` | hardware (community rule, confirmed) | enforced before sending |
| Samples | Tempo sync accepts 60–180 BPM and 0.25–4 bars; anything else is refused with "range error", including the `sound.bpm` 0.0 that factory sounds carry | hardware | bounces fold into the range (50 BPM × 1 bar is sent as 100 BPM × 2 bars) |
| Samples | Factory loops use `key` or `legato` mode with a loop over the sustained part and a shorter release (64–128) | hardware (backup) | auto loops switch a one-shot to `key` |
| Samples | To put a sample on a pad: SOUND, choose the pad, then − / + until the screen shows its number | official (quick start) | shown after each upload |
| Sequencer | Patterns per group, bars per pattern, projects: sources conflict | unknown | doesn't apply: koii sequences live over MIDI |

**Live MIDI versus the device's sequencer.** koii plays patterns from the computer, note by
note. The EP-133's own sequencer limits (patterns, bars, song positions) don't apply, but its
sound engine's do: voices, play modes and which pads listen on which channel.

**koii's own limits:** 4/4 only; steps of 1/4, 1/8, 1/16, 1/32 or 8th/16th triplets; up to
1,024 steps per pattern; 20–300 BPM; swing 50–75 %; MIDI notes 0–127 on channels 1–16.
Timing comes from the computer; scheduling is drift-free (tested within 10 ms), but USB MIDI
latency to the device hasn't been measured.

## Pads and MIDI notes (official, hardware-checked)

Each group has 12 pads laid out like a calculator keypad, and each pad is one MIDI note:

```
        group A          MIDI notes
   +-----+-----+-----+   +----+----+----+
   |  7  |  8  |  9  |   | 45 | 46 | 47 |
   +-----+-----+-----+   +----+----+----+
   |  4  |  5  |  6  |   | 42 | 43 | 44 |
   +-----+-----+-----+   +----+----+----+
   |  1  |  2  |  3  |   | 39 | 40 | 41 |
   +-----+-----+-----+   +----+----+----+
   |  .  |  0  |ENTER|   | 36 | 37 | 38 |
   +-----+-----+-----+   +----+----+----+
```

| Group | Notes | Pad labels in this project |
|-------|-------|----------------------------|
| A | 36–47 | `A.` `A0` `AEnter` `A1` … `A9` |
| B | 48–59 | `B.` `B0` `BEnter` `B1` … `B9` |
| C | 60–71 | `C.` `C0` `CEnter` `C1` … `C9` |
| D | 72–83 | `D.` `D0` `DEnter` `D1` … `D9` |

Pressing pads on the device and capturing its MIDI output confirmed `0` → 37, ENTER → 38,
`1`–`9` → 39–47 on group A, and `.` → 48 and `0` → 49 on group B, so `.` is the first
note of each group and groups are 12 notes apart.

The third pad of the bottom row is the ENTER key. FX is a separate button for the punch-in
effects. Older versions of this project mislabelled the pad as "FX", so `AFX` is still
accepted. Note names use C4 = 60, so group A starts at C2.

## What the device sends (hardware)

- The USB MIDI port is named **`EP-133`** (both input and output).
- Pad presses go out on **channel 1** as note-on, with note-off sent as note-on velocity 0.
- With pad velocity off (the default), presses are sent at a fixed **velocity 100**.
- Notes sent *to* the device are not echoed back unless MIDI thru is on.

## Channels (official)

- By default the EP-133 **receives on all channels** and **sends on channel 1**.
- **Per-pad channel (OS 2.0+):** in Sound Edit (SHIFT + SOUND) → MIDI page, **knob X** sets
  the channel the pad sends and receives on, and **knob Y** sets the pad's MIDI root note.
- **OS 2.0.1** added a system setting (MIDI → CHN → OFF, code 127) where pads only
  send/receive if they have a channel assigned in Sound Edit.

## Playing pitches (basslines, chords, melodies)

A pad hit (note 36–83) always plays the pad's sample at its recorded pitch. To play a
sample at different pitches from this project:

1. Pick the pad that holds the sound, e.g. a bass on `B.`.
2. Sound Edit → MIDI page → knob X: set that pad to a free channel, e.g. **2**.
3. Use the same channel in your pattern: `@map bass = ch2` (or once for every pattern:
   `set_alias("bass", "ch2")`).
4. Write the line: `bass: x..x..x.` and `bass notes: C2 C2 G1`.

Knob Y (root note) sets which MIDI note plays the sample at its original pitch. If the
line sounds transposed, adjust it there.

**Tested on hardware:** with `B.` on channel 2, notes C1–G1 played the bass at those
pitches, and a bassline on channel 2 played cleanly under drums on channel 1. The pad
also still played from its normal note (48) on channel 1, so giving a pad its own
channel doesn't stop it working as a drum pad.

**Pad clashes (hardware):** pads without their own channel listen on *all* channels by
default, so a pitched note that shares a number with a pad (36–83) also plays that pad.
On hardware, a C3–G3 run on channel 2 played the bass *and* the group B pads at notes
48–55. Two ways around it:

- Keep pitched notes below **C2** (note 36). Most basslines fit, and `check_pattern`
  warns about any note that clashes.
- Set the system MIDI channel to **1** instead of "all": with the EP-133 already on,
  SHIFT + ERASE opens system settings; type **111** and ENTER (**110** puts the default
  back). ⚠ Never hold SHIFT + ERASE while switching the EP-133 on: that formats it.
  Pads without their own channel then only hear channel 1, so drums still work and
  pitched channels can use any note. **Tested on hardware (OS 2.5):** with 111 set and a
  keys pad on channel 3, four-note chords from D3 to C4 played only the keys, with no
  drum pads firing on the shared note numbers.

**Pads can be set over USB** (koii's `set_pad`, or *pad settings* in the visualiser): each
pad is a node in the file tree (`3200 + (project − 1) × 1000 + group × 100 + n`, with `n`
counting the keypad from the top row: 7 8 9 = 1–3, 4 5 6 = 4–6, 1 2 3 = 7–9, . 0 ENTER =
10–12), and its settings are a small JSON object that merges like a sample's: `sym` (the
sample slot), `midi.channel` (0 = none), `sound.playmode` (with `envelope.release`),
`sound.amplitude`, `envelope.attack`, `sound.pan`. The open project is `/projects`'s
`active` value (3000 = project 1). **Tested on hardware (OS 2.5):** changes take effect
straight away, with no reload; reading a pad back shows exactly what was set by hand on
the device; and changing `sym` makes the pad take the new sample's own defaults (attack,
fine tune) except for anything written in the same change. System settings such as 111
can't be reached over USB and are set by hand.

A pad keeps its own copy of the level and play mode from when its sound was assigned, so
changing a sample's settings afterwards doesn't reach a pad that already uses it: set the
pad instead. Chords need the pad in **KEY** mode (ONESHOT plays one note at a time, and
retriggering it for every note of a chord sounds clicky and distorted) and a level of
about 50–60, since four notes at full level overload the output.

KEYS mode does something similar on the device itself: it spreads the selected pad's
sample chromatically across the 12 pads, and in that mode the EP-133 accepts the full
note range 0–127. Keys mode changes the note map, so drums sent alongside it won't
trigger their usual pads. Per-pad channels are the better route for full beats.

## Play modes (official)

Set per pad in Sound Edit: **ONESHOT** is monophonic and plays the whole sample (note-off
is ignored); **KEY** is polyphonic and stops on note-off; **LEGATO** is the third option.
The notation's `-` (hold) only changes the sound in KEY and LEGATO modes.

## Velocity (official, hardware-checked)

**Pad velocity is OFF by default** (system setting code 300). That only affects playing
the pads by hand: on hardware with it off, pad presses went out at a fixed velocity 100,
but **incoming MIDI velocity was still respected** (soft and loud kicks, and a 1–9 hat
ramp, were clearly audible). So `o`, `X` and `1`–`9` work without changing any setting.
To make the pads themselves velocity-sensitive: SHIFT + ERASE for system settings, type
**301**, then ENTER.

## Other MIDI facts

| Fact | Source |
|------|--------|
| MIDI over USB-C (class compliant) and 3.5 mm TRS **type A** in/out | official |
| Bank select (CC 0/32) can reach all sounds 1–999; identity request/reply SysEx | official (MIDI chart) |
| Program change is **no longer mapped** since OS 2.0.2 (can still be recorded/relayed) | official (release notes) |
| MIDI clock off / in / out (codes 100/101/102); sync in/out 1/8, 1/16, 24 PPQN | official |
| MIDI thru on/off (130/131); reset controllers at stop (140/141) | official |
| OS 2.5: CC 64 sustain for KEY/LEGATO pads; CC 12/13 control FX X/Y | official (what's new) |
| Polyphony: 16 mono / 12 stereo voices; fewer with time-stretched, stereo or high-pitched samples | official |
| A pad set to sound `000` sends/receives MIDI without using a voice | community |

## The kit (community)

`show_kit` lists each pad with the sound it holds in **factory Project 1**, and
`list_factory_sounds` lists the factory library. TE doesn't publish either; both were
transcribed from the device display and may contain typos. Projects 2–5 use different
layouts, and you'll change sounds anyway, so the built-in aliases are a starting point:

| Alias | Pad | Project 1 sound |
|-------|-----|-----------------|
| `kick` `bd` | A. | MICRO KICK |
| `kick2` | A0 | NT ALT KICK |
| `clap` `cp` | AEnter | NT CLAP |
| `snare` `sd` | A1 | NT SNARE |
| `snare2` | A2 | NT SNARE ALT |
| `rim` `rimshot` | A3 | NT RIMSHOT |
| `tambo` `tambourine` | A4 | NT TAMBO |
| `hat` `hh` `hihat` | A5 | NT HH CLOSED |
| `oh` `openhat` | A6 | NT HH OPEN |
| `perc` | A7 | NT PERC |
| `ride` | A8 | NT RIDE |
| `ride2` | A9 | NT RIDE C |
| `bass` | B. | NT BASS |
| `keys` | C. | BLUE |

If your pads differ, `audition("A7")` to hear a pad, then `set_alias("cowbell", "A7")`.
Aliases are saved in the library.

## Troubleshooting

- **No sound:** check the device volume and that it's in a project with sounds on those
  pads. `audition("kick")` sends a single hit.
- **Port not found:** use a data-capable USB-C cable; `list_midi_ports()` shows what the
  computer sees (the EP-133 appears as `EP-133`).
- **All hits the same volume:** check the pattern uses `o`, `X` or `1`–`9`; incoming MIDI velocity works even with pad velocity off.
- **Doubled or runaway notes:** if a DAW or MIDI router sends the EP-133's output back
  into it, it will replay its own notes. Disable that route or MIDI thru.
- **Bassline plays drum pads instead:** the pitched track's channel isn't assigned to a
  pad, or the device is in KEYS mode. See "Playing pitches".
