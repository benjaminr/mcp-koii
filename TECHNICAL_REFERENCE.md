# KOII Technical Reference

This document provides a technical reference for the KOII MCP server implementation for controlling the Teenage Engineering EP-133 K.O. II.

## Architecture Overview

The KOII implementation consists of two main components:

1. **MIDI Interface (`midi_interface.py`)**: Core module that handles direct MIDI communication with the EP-133 K.O. II device.

2. **MCP Server (`koii_server.py`)**: Server that exposes the MIDI functionality to Claude through the Model Context Protocol (MCP).

## MIDI Interface

### Class: `MIDIInterface`

The main class that handles all MIDI communication with the EP-133 K.O. II device.

#### Key Methods

| Method | Description |
|--------|-------------|
| `list_ports()` | Returns a list of available MIDI output ports |
| `connect(port_name, port_index)` | Connects to a MIDI output port by name or index |
| `disconnect()` | Disconnects from the current MIDI port |
| `set_channel(channel)` | Sets the MIDI channel (1-16) |
| `play_note(note, velocity, duration)` | Plays a single MIDI note |
| `play_pattern(notes)` | Plays a pattern of MIDI notes |
| `parse_drum_pattern(pattern, bpm)` | Parses and plays a text-based drum pattern |
| `pad_to_note(pad_reference)` | Converts a pad reference (e.g., 'A2') to a MIDI note number |
| `interpret_trigger_reference(reference)` | Interprets a pad reference, MIDI note, instrument name, or sound name |
| `find_sound_by_name(name)` | Finds a sound ID by its name |
| `get_default_sound_for_pad(pad_reference)` | Gets the default sound ID for a pad |
| `get_scale_notes(scale_name, root_note, octave)` | Gets the MIDI note numbers for a musical scale |
| `map_pads_to_scale(channel, scale_name, root_note, octave)` | Maps pads in a channel to notes in a musical scale |
| `play_scale_sequence(channel, scale_name, root_note, sequence, ...)` | Plays a sequence of notes from a musical scale |

#### Important Data Structures

| Constant | Description |
|----------|-------------|
| `PAD_GROUPS` | Dictionary mapping channel letters to MIDI note ranges |
| `SOUND_CATEGORIES` | List of sound categories available on the EP-133 K.O. II |
| `SOUND_LIBRARY` | Dictionary of all available sounds organized by category |
| `DEFAULT_PAD_CONFIG` | Dictionary mapping channels to their default sound configurations |
| `NOTE_TO_NUMBER` | Dictionary mapping note names to semitone values |
| `VELOCITY_HIGH` | Default velocity for 'x' or 'X' hits in patterns (100) |
| `VELOCITY_LOW` | Default velocity for 'o' or 'O' hits in patterns (60) |
| `VELOCITY_DEFAULT` | Default velocity when not otherwise specified (80) |
| `SCALE_PATTERNS` | Dictionary mapping scale names to their interval patterns |

### Pad Layout and MIDI Mapping

The EP-133 K.O. II's pad layout is mapped to MIDI notes as follows:

```
+-----+-----+-----+  
| A7  | A8  | A9  |  = [45, 46, 47]  (Top row)
+-----+-----+-----+  
| A4  | A5  | A6  |  = [42, 43, 44]  (Middle row)
+-----+-----+-----+  
| A1  | A2  | A3  |  = [39, 40, 41]  (Bottom row)
+-----+-----+-----+  
| A.  | A0  | FX  |  = [36, 37, 38]  (Bottom special row)
+-----+-----+-----+  
```

The same pattern applies to channels B (starting at MIDI note 48), C (starting at MIDI note 60), and D (starting at MIDI note 72).

### Drum Pattern Parsing

The `parse_drum_pattern` method supports a text-based drum pattern syntax with the following features:

- Each line represents a different instrument
- Characters in the pattern:
  - 'x' or 'X': High-velocity hit (100)
  - 'o' or 'O': Low-velocity hit (60)
  - '1'-'9': Numeric velocity values (1=14, 9=127)
  - 'v' + digits (e.g., 'v64', 'v127'): Exact velocity values (1-127)
  - '.': No hit
- Each position represents a 16th note
- Comments after '#' specify what sound to trigger using one of four reference methods:
  1. Pad labels (A., A2, B3, etc.)
  2. MIDI note numbers (36, 40, 43, etc.)
  3. Instrument names (kick, snare, hi-hat, etc.)
  4. Sound names ("MICRO KICK", "NT SNARE", etc.)

#### Reference Method Details

1. **Pad References**:
   - Format: Channel letter (A-D) followed by a number (1-9) or special character (. or 0)
   - Examples: A., A0, A1, B3, C7, D9
   - Implementation: `pad_to_note()` method converts these to MIDI notes

2. **MIDI Note Numbers**:
   - Format: Direct MIDI note number (0-127)
   - Examples: 36, 40, 43, 60
   - Implementation: Used directly as MIDI note values

3. **Instrument Names**:
   - Format: Common drum/instrument name
   - Examples: kick, snare, hi-hat, bass

4. **Sound Names**:
   - Format: Exact sound name from the sound library (quoted if containing spaces)
   - Examples: "MICRO KICK", "NT SNARE", "NT HH CLOSED"
   - Implementation: `find_sound_by_name()` method searches for the sound in `SOUND_LIBRARY`, then finds which pad it's mapped to by default

### Scale Mode Implementation

The Scale Mode functionality allows musical scales to be mapped to the device pads and played melodically. The implementation includes:

#### Scale Patterns

The `SCALE_PATTERNS` dictionary defines interval patterns for various scales:
- Standard scales: major, minor
- Modes: dorian, phrygian, lydian, mixolydian, locrian
- Other scales: major_pentatonic, minor_pentatonic, blues, chromatic

#### Scale Generation

The `get_scale_notes` method:
1. Validates the scale name and root note
2. Calculates the base MIDI note from the root note and octave
3. Applies the scale pattern to generate a list of MIDI notes
4. Generates notes for two octaves to provide more range

#### Pad Mapping

The `map_pads_to_scale` method:
1. Defines a logical pad layout for playing scales (from bottom left to top right)
2. Maps each pad to the corresponding note in the scale
3. Returns a dictionary mapping pad references to MIDI notes

#### Scale Sequence Playback

The `play_scale_sequence` method:
1. Takes a list of scale degrees (1-based indices into the scale)
2. Supports rests (0) and negative values for notes in lower octaves
3. Plays each note in sequence with the specified velocity and timing

## MCP Server

### Server Tools

| Tool | Description |
|------|-------------|
| `list_midi_ports()` | Lists all available MIDI output ports |
| `connect_to_device(port_name, port_index)` | Connects to a MIDI device |
| `disconnect()` | Disconnects from the current MIDI device |
| `play_note(note, velocity, duration, channel)` | Plays a single note |
| `play_pattern(notes, channel)` | Plays a pattern of notes |
| `play_drum_pattern(pattern, bpm)` | Plays a text-based drum pattern |
| `list_sound_categories()` | Lists all available sound categories |
| `list_sounds_in_category(category)` | Lists all sounds in a specific category |
| `get_default_pad_configuration()` | Gets the default pad configuration |
| `list_available_scales()` | Lists all available musical scales with descriptions |
| `get_scale_mapping(channel, scale_name, root_note, octave)` | Gets a mapping of pads to notes in a scale |
| `play_scale_sequence(channel, scale_name, root_note, sequence, ...)` | Plays a sequence of notes from a scale |

### Server Prompts

| Prompt | Description |
|--------|-------------|
| `midi_info()` | Provides information about the EP-133 K.O. II MIDI implementation |
| `pad_configuration_help()` | Provides help on understanding the default pad configuration |
| `drum_pattern_help()` | Provides help on creating drum patterns |
| `scale_mode_help()` | Provides help on using scale mode |

### Log Capture

The server uses a `capture_logs` context manager to capture log messages from the `MIDIInterface` when processing drum patterns. This allows the server to extract information about recognized and unrecognized instruments and provide detailed feedback to the user.

## Technical Implementation Details

### Simultaneous Playback

The drum pattern parser can handle multiple instruments playing simultaneously by:

1. Collecting all notes that should play at each step
2. Sending the MIDI note-on messages for all instruments at once
3. Waiting for the step duration
4. Sending the MIDI note-off messages for all instruments

```python
# Collect all notes that should play on this step
notes_to_play = []
for i, line in enumerate(pattern_lines):
    if step < len(line):
        char = line[step]
        # Check basic note triggers (x/X, o/O)
        if char in ['x', 'X', 'o', 'O']:
            velocity = VELOCITY_HIGH if char in ['x', 'X'] else VELOCITY_LOW
            note = instrument_mapping.get(i, 36)
            notes_to_play.append((note, velocity))
        # Check numeric velocity values
        elif char.isdigit() and '1' <= char <= '9':
            velocity = int(char) * 14
            note = instrument_mapping.get(i, 36)
            notes_to_play.append((note, velocity))
        # Check for exact velocity notation (v64, v127)
        elif char == 'v' and step + 1 < len(line):
            # Process velocity value
            # ...

# Play all notes for this step simultaneously
for note, velocity in notes_to_play:
    self.port.send(mido.Message('note_on', note=note, velocity=velocity, channel=self.channel))

# Wait for the step duration
time.sleep(step_duration)

# Turn off all notes
for note, _ in notes_to_play:
    self.port.send(mido.Message('note_off', note=note, velocity=0, channel=self.channel))
```

### Instrument Reference Interpretation

The `interpret_trigger_reference` method tries to interpret a reference in the following order:

1. Direct MIDI note number
2. Pad reference (A., A2, B3, etc.)
3. Instrument name (kick, snare, etc.)
4. Sound name from library ("MICRO KICK", etc.)

If all methods fail, it defaults to the kick drum (pad A., MIDI note 36).

### Dynamic Velocity Control

The implementation supports three methods of velocity control:

1. **Basic Notation**: 
   - 'x' or 'X' for high velocity (100)
   - 'o' or 'O' for low velocity (60)

2. **Numeric Notation**:
   - Digits '1' through '9' map to velocities from gentle to hard
   - '1' = velocity 14, '9' = velocity 126

3. **Exact Velocity Notation**:
   - 'v' followed by 1-3 digits (e.g., 'v64', 'v127')
   - Allows precise control over velocity values (1-127)

This allows for expressive dynamics in drum patterns, such as accents, ghost notes, crescendos, and complex dynamic patterns.

### Sound Identification

For sound names, the `find_sound_by_name` method:

1. First tries to find an exact match
2. Then tries to find a partial match
3. If multiple matches are found, prefers the shortest name (likely more specific)

### Error Handling

The implementation includes robust error handling to:

1. Gracefully handle connection issues
2. Validate all input parameters
3. Provide informative error messages
4. Default to reasonable values when appropriate
5. Track unrecognized instruments and provide feedback

## Performance Considerations

- The implementation uses efficient data structures and algorithms to minimize latency
- Simultaneous note playback is supported for creating complex patterns
- The BPM setting can be adjusted to control the speed of pattern playback
- The EP-133 K.O. II has a limit on how many notes it can process simultaneously, so very complex patterns may require adjustments

## Dependencies

- **mido**: Python library for working with MIDI messages
- **mcp**: Model Context Protocol SDK for creating MCP servers