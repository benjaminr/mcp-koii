# Using KOII with EP-133 K.O. II

This guide explains how to control your Teenage Engineering EP-133 K.O. II sampler using Claude through the KOII MCP server.

## Device Overview

The EP-133 K.O. II is a portable sampler and drum machine from Teenage Engineering featuring:

- 12 pads arranged in a 4×3 grid (per channel)
- 4 channels (A, B, C, D) with 12 pads each
- Over 300 built-in sounds
- MIDI input/output via USB
- Keys Mode for playing melodic scales

## Pad Layout

The physical pad layout of the EP-133 K.O. II is as follows:

```
+-----+-----+-----+  
| A7  | A8  | A9  |  ← Top row
+-----+-----+-----+  
| A4  | A5  | A6  |  ← Middle row
+-----+-----+-----+  
| A1  | A2  | A3  |  ← Bottom row
+-----+-----+-----+  
| A.  | A0  | FX  |  ← Special bottom row
+-----+-----+-----+  
```

The same layout applies to channels B, C, and D, with their respective labels.

## MIDI Implementation

Each pad on the EP-133 K.O. II corresponds to a specific MIDI note:

| Channel | MIDI Note Range | Description           |
|---------|----------------|-----------------------|
| A       | 36-47 (C2-B2)  | Primarily drum sounds |
| B       | 48-59 (C3-B3)  | Bass sounds          |
| C       | 60-71 (C4-B4)  | Melodic/synth sounds |
| D       | 72-83 (C5-B5)  | User samples         |

Within each channel, the pads map to MIDI notes in this order:

| Pad Label | MIDI Note Offset | Note (for Channel A) |
|-----------|-----------------|---------------------|
| A.        | +0              | 36 (C2)             |
| A0        | +1              | 37 (C#2)            |
| AFX       | +2              | 38 (D2)             |
| A1        | +3              | 39 (D#2)            |
| A2        | +4              | 40 (E2)             |
| A3        | +5              | 41 (F2)             |
| A4        | +6              | 42 (F#2)            |
| A5        | +7              | 43 (G2)             |
| A6        | +8              | 44 (G#2)            |
| A7        | +9              | 45 (A2)             |
| A8        | +10             | 46 (A#2)            |
| A9        | +11             | 47 (B2)             |

## Getting Started

### 1. Connect your EP-133 K.O. II

Connect your device to your computer via USB.

### 2. Start the MCP Server

Run the KOII server:

```bash
python koii_server.py
```

### 3. Connect Claude to the KOII Server

In your Claude conversation, enter:

```
/mcp add host=localhost
```

## Basic Commands

Here are the basic commands you can use with Claude to control your EP-133 K.O. II:

### Connecting to the Device

```
Could you list available MIDI ports and connect to my EP-133 K.O. II?
```

Claude will list available MIDI ports and attempt to connect to your device.

### Playing a Single Note

```
Please play note A2 (the snare drum pad) with velocity 100 for 0.2 seconds.
```

### Playing a Pattern

```
Could you play this pattern on the device?
x...x...x...x...  # kick
....x.......x...  # snare
x.x.x.x.x.x.x.x.  # hi-hat
```

### Exploring Sounds

```
What sound categories are available on the EP-133 K.O. II?
```

```
Please list all the sounds in the "Kicks" category.
```

### Getting Pad Configuration

```
Could you show me the default pad configuration for channel A?
```

## Drum Pattern Syntax

The KOII server supports a text-based drum pattern syntax that makes it easy to create rhythms:

- Each line represents a different instrument/sound
- 'x' or 'X' indicates a hit (high velocity, 100)
- 'o' or 'O' indicates a softer hit (lower velocity, 60)
- Digits '1'-'9' for velocity values from gentle to hard
- 'v' followed by digits (e.g., 'v64', 'v127') for exact velocity values
- '.' indicates no hit
- Each position represents a 16th note
- Comments after '#' specify what sound to trigger

You can reference sounds in four different ways:

1. **Pad Labels**: Direct references to physical pads
   ```
   x...x...x...x...  # A.
   ....x.......x...  # A2
   x.x.x.x.x.x.x.x.  # A5
   ```

2. **MIDI Notes**: Direct MIDI note numbers
   ```
   x...x...x...x...  # 36
   ....x.......x...  # 40
   x.x.x.x.x.x.x.x.  # 43
   ```

3. **Sound Names**: Actual sound names from the library
   ```
   x...x...x...x...  # "MICRO KICK"
   ....x.......x...  # "NT SNARE"
   x.x.x.x.x.x.x.x.  # "NT HH CLOSED"
   ```

### Dynamic Velocity Examples

Using numeric velocity values (1-9):
```
9...5...3...1...  # "MICRO KICK"     (velocity decreasing)
....6.......8...  # "NT SNARE"    (medium then hard)
5.3.5.7.5.9.5.1.  # "NT HH CLOSED"   (changing accents)
```

Using exact velocity values:
```
v120....v80....v40....v10....  # "MICRO KICK"    (precise velocities)
....v64.......v96...          # "NT SNARE"   (medium then harder)
v30.v30.v100...v30.v30.v127.  # "NT HH CLOSED"  (ghost notes with accents)
```

Combining different velocity notations:
```
x...5...o...1...       # "MICRO KICK"     (mix of notation styles)
....v100...v64...v32.  # "NT SNARE"    (decaying echo effect)
x.o.3.5.7.9.v127.v10.  # "NT HH CLOSED"   (complex pattern)
```

## Scale Mode

The EP-133 K.O. II can be used in Keys Mode to play melodic patterns using musical scales.

### Setting Up Scale Mode

1. Enable Keys Mode on your EP-133 K.O. II using the device's interface
2. Configure your desired scale on the device
3. Tell Claude which channel, scale, and root note you've configured

### Using Scale Mode

Explore available scales:
```
Could you list the available musical scales for the EP-133 K.O. II?
```

Get a mapping of pads to notes for a specific scale:
```
Could you show me which pads would play which notes if I set channel A to C minor scale?
```

Play a melodic sequence:
```
Please play this sequence in G major scale on channel A: 1, 3, 5, 8, 5, 3, 1
```

## Default Drum Mappings

The EP-133 K.O. II has these default drum mappings:

| Instrument      | Pad | MIDI Note | Default Sound     |
|-----------------|-----|-----------|-------------------|
| kick            | A.  | 36 (C2)   | MICRO KICK        |
| snare           | A2  | 40 (E2)   | NT SNARE ALT      |
| clap            | A3  | 41 (F2)   | NT CLAP           |
| low tom         | A4  | 42 (F#2)  | NT TAMBO          |
| closed hi-hat   | A5  | 43 (G2)   | NT HH CLOSED      |
| mid tom         | A6  | 44 (G#2)  | NT RIDE           |
| high tom/perc   | A7  | 45 (A2)   | NT PERC           |
| open hi-hat/ride| A8  | 46 (A#2)  | NT HH OPEN        |
| crash/cymbal    | A9  | 47 (B2)   | NT RIDE C         |
| bass            | B.  | 48 (C3)   | NT BASS           |
| melodic         | C.  | 60 (C4)   | BLUE              |

## Example Workflows

### Workflow 1: Creating a Basic Beat

```
Could you please help me create a basic house beat for my EP-133 K.O. II? I'd like to use the kick, snare, clap, and hi-hat pads.
```

Claude might respond:

"I'll create a basic house beat for your EP-133 K.O. II. Let me first connect to the device."

Claude then lists MIDI ports and connects to your device:

"Connected to your EP-133 K.O. II. Let's create a house beat at 128 BPM with kick, snare, clap, and hi-hat."

Claude creates and plays a pattern like:

```
x...x...x...x...  # kick      (A., 36)
....x.......x...  # snare     (A2, 40)
..x...x...x...x.  # clap      (A3, 41)
x.x.x.x.x.x.x.x.  # closed HH (A5, 43)
```

### Workflow 2: Creating a Dynamic Drum Pattern

```
I'd like to create a drum pattern with varying velocities to make it more expressive. Could you help me create a pattern with accents and ghost notes?
```

Claude might respond:

"I'll help you create a more expressive drum pattern with dynamic velocities. Let me connect to your device."

Claude then creates and plays a pattern using various velocity notations:

```
9...5...7...3...  # kick (A.) - strong, medium, stronger, softer
o.o.X.o.o.o.X.o.  # snare (A2) - ghost notes with accents
v30.v60.v90.v127. # hi-hat (A5) - crescendo effect
```

### Workflow 3: Creating a Melodic Sequence

```
I've set my EP-133 K.O. II to Keys Mode with an E minor scale on channel A. Could you help me create a simple melody using that scale?
```

Claude might respond:

"I'll help you create a melody using the E minor scale on channel A. Let me get the note mapping first."

Claude then shows the scale mapping and creates a melodic sequence:

"Here's a simple melodic sequence in E minor:"

```
[Claude plays sequence: 1, 3, 4, 5, 7, 5, 4, 3, 1]
```

"This plays the root note (E), then G, A, B, D, and back down, creating a melancholic phrase that explores the E minor scale."

### Workflow 4: Sound Design Exploration

```
I'd like to create an interesting pattern that uses some unusual sounds from the EP-133 K.O. II. Could you suggest some interesting sounds and create a pattern that shows them off?
```

Claude might respond:

"I'll help you create a pattern with some of the more unusual sounds on the EP-133 K.O. II. Let me explore the sound library first."

Claude then creates a pattern using unique sounds:

```
x...x...x...x...  # "BOOMER KICK"    (channel A)
....x.......x...  # "DETROIT CLAP 2" (channel A)
..x...x...x...x.  # "GUZHENG"        (channel C)
x.....x.....x...  # "FX BIRDS TAPE"  (channel C)
```

## Troubleshooting

- **No MIDI ports found**: Make sure your EP-133 K.O. II is connected and powered on
- **Connection issues**: Try reconnecting the USB cable or restarting your device
- **Multiple instruments not playing simultaneously**: Try using a higher BPM setting
- **Unknown instruments**: Use exact pad references (A., A2, etc.) if instrument names aren't recognized
- **Velocity notation not working**: Double-check the syntax (v64, 5, x, o) and ensure there are no spaces

## Advanced Features

### Creating Polyrhythms

You can create polyrhythms by using patterns of different lengths:

```
x..x..x..x..x..  # 12/8 bass pattern (triplet feel)
x...x...x...x...  # 4/4 kick pattern
```

### Using Multiple Channels

You can reference pads from different channels in the same pattern:

```
x...x...x...x...  # A. (kick drum)
....x.......x...  # A2 (snare drum)
x...............  # B. (bass note)
........x.......  # C5 (melodic hit)
```

This allows you to create rich, multi-layered patterns that leverage sounds from across the EP-133 K.O. II's channels.