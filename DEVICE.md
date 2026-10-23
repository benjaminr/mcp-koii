# EP-133 K.O. II: MIDI reference

What this project relies on, where each fact comes from, and how sure we are.

- **Hardware** = checked on a real EP-133 over USB on macOS (October 2026).
- **Official** = Teenage Engineering's [EP-133 guide](https://teenage.engineering/guides/ep-133)
  or [product page](https://teenage.engineering/products/ep-133).
- **Community** = transcribed from the device or forum reports; not published by TE.

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
`1`–`9` → 39–47 on group A and `0` → 49 on group B. (`.` → 36 is from the official table;
it didn't show up in that capture.)

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

KEYS mode does something similar on the device itself: it spreads the selected pad's
sample chromatically across the 12 pads, and in that mode the EP-133 accepts the full
note range 0–127. Keys mode changes the note map, so drums sent alongside it won't
trigger their usual pads. Per-pad channels are the better route for full beats.

This setup follows the official guide but **hasn't been tested on hardware yet**.

## Play modes (official)

Set per pad in Sound Edit: **ONESHOT** is monophonic and plays the whole sample (note-off
is ignored); **KEY** is polyphonic and stops on note-off; **LEGATO** is the third option.
The notation's `-` (hold) only changes the sound in KEY and LEGATO modes.

## Velocity (official)

**Pad velocity is OFF by default** (system setting code 300). The guide doesn't say
whether this also flattens incoming MIDI velocity, so if `o`, `X` and `1`–`9` all sound
the same, turn it on: SHIFT + ERASE for system settings, type **301**, then ENTER.
(Hi/lo variants exist; check the system page for your OS version.)

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
- **All hits the same volume:** try turning pad velocity on (see above).
- **Doubled or runaway notes:** if a DAW or MIDI router sends the EP-133's output back
  into it, it will replay its own notes. Disable that route or MIDI thru.
- **Bassline plays drum pads instead:** the pitched track's channel isn't assigned to a
  pad, or the device is in KEYS mode. See "Playing pitches".
