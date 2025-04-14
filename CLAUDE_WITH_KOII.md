# Using Claude with KOII and EP-133 K.O. II

This guide demonstrates how to use Claude effectively with the KOII MCP server to control your Teenage Engineering EP-133 K.O. II sampler. It includes example prompts and expected interactions.

## Setup

1. Make sure your EP-133 K.O. II is connected to your computer via USB
2. Start the KOII MCP server: `python koii_server.py`
3. Connect Claude to the server: `/mcp add host=localhost`

## Example 1: Basic Connection and Sound Testing

**User Prompt:**
```
Hi Claude, I'd like to connect to my EP-133 K.O. II sampler. Can you list the available MIDI ports, connect to the device, and play a simple test pattern to make sure everything is working?
```

**Expected Claude Response:**
Claude will use the `list_midi_ports` function to show available MIDI devices, then connect to the one that matches the EP-133 K.O. II, and finally play a basic test pattern.

**Example Interaction:**
```
Claude: I'll help you connect to your EP-133 K.O. II and test it. Let me check for available MIDI ports.

[Claude lists MIDI ports]
Available MIDI ports:
0: EP-133
1: IAC Driver Bus 1
2: USB MIDI Interface

I'll connect to the EP-133 port.
[Claude connects to the device]
Successfully connected to MIDI device: EP-133

Let me play a simple test pattern to verify the connection:
[Claude plays a basic drum pattern]
Successfully played drum pattern at 120 BPM with kick, snare, and hi-hat.

The connection is working properly. What would you like to do next with your EP-133 K.O. II?
```

## Example 2: Exploring Sounds and Creating a Beat

**User Prompt:**
```
Could you help me explore the sounds on my EP-133 K.O. II? I'd like to see what sound categories are available, then look at some sounds in the "Kicks" category, and finally create a simple beat using one of those kicks, a snare, and a hi-hat.
```

**Expected Claude Response:**
Claude will use the server functions to list sound categories, show sounds in the "Kicks" category, and then create and play a pattern.

**Example Interaction:**
```
Claude: I'll help you explore sounds on your EP-133 K.O. II. Let me list the available sound categories.

[Claude lists sound categories]
Available sound categories:
- Kicks
- Snares
- Cymbals and Hats
- Percussion
- Bass
- Melodic & Synth

Now, let me show you the sounds in the "Kicks" category.

[Claude lists kicks sounds]
Kicks category sounds include:
1: MICRO KICK
2: NT KICK
3: NT KICK B
...
31: BOOMER KICK

Let me create a simple beat using MICRO KICK, a snare from the Snares category, and a hi-hat:

x...x...x...x...  # "MICRO KICK"
....x.......x...  # "NT SNARE"
x.x.x.x.x.x.x.x.  # "NT HH CLOSED"

[Claude plays the pattern]
Successfully played drum pattern at 120 BPM with 3 instruments.
```

## Example 3: Creating a Complex Pattern

**User Prompt:**
```
I'd like to create a more complex pattern on my EP-133 K.O. II. Could you help me make a pattern that includes:
1. A kick drum on beats 1 and 3
2. A snare on beats 2 and 4
3. A closed hi-hat playing 8th notes
4. An open hi-hat on the "and" of beat 4
5. A bass note on beat 1
6. A melodic sound triggered on beat 3

Then please play it at 110 BPM.
```

**Expected Claude Response:**
Claude will create a multi-instrument pattern across different channels and play it at the requested tempo.

**Example Interaction:**
```
Claude: I'll create a complex pattern with all the elements you requested. Let me craft it using instruments from different channels.

Here's the pattern I've created:

x.......x.......  # kick (A.)
....x.......x...  # snare (A2)
x.x.x.x.x.x.x.x.  # closed hi-hat (A5)
.............x..  # open hi-hat (A8)
x...............  # bass (B.)
........x.......  # melodic (C.)

[Claude plays the pattern]
Successfully played drum pattern at 110 BPM with 6 instruments.

The pattern includes:
- Kick drum on beats 1 and 3 (using pad A.)
- Snare on beats 2 and 4 (using pad A2)
- Closed hi-hat playing 8th notes (using pad A5)
- Open hi-hat on the "and" of beat 4 (using pad A8)
- Bass note on beat 1 (using pad B.)
- Melodic sound on beat 3 (using pad C.)
```

## Example 4: Working with Dynamic Velocities

**User Prompt:**
```
I want to create a more dynamic beat with varying velocities. Can you make a pattern where:
1. The kick has accents on beat 1 (loud) and lighter hits on beat 3
2. The snare has ghost notes before the main hits
3. The hi-hat alternates between soft and normal hits
```

**Expected Claude Response:**
Claude will create a pattern using different velocity notations to create a more dynamic feel.

**Example Interaction:**
```
Claude: I'll create a dynamic pattern with varying velocities as you requested. Here's what I've put together:

9...3...9...3...  # kick (A.) - accented on beats 1 and 3, lighter on "and" of 2 and 4
..o.X...o.o.X...  # snare (A2) - main hits on 2 and 4, ghost notes before
o.x.o.x.o.x.o.x.  # hi-hat (A5) - alternating between soft and normal

[Claude plays the pattern]
Successfully played drum pattern at 120 BPM with 3 instruments.

The pattern uses:
- '9' for very loud hits (velocity 126)
- '3' for lighter hits (velocity 42)
- 'X' for loud hits (high velocity 100)
- 'x' for normal hits (medium velocity)
- 'o' for soft hits (low velocity 60)
- '.' for no hits

This creates a more dynamic feel with the varying intensities.
```

## Example 5: Creating a Pattern with Precise Velocities

**User Prompt:**
```
I want to create a drum pattern that simulates a drummer playing with increasing intensity. Can you make a pattern where the kick and snare gradually get louder over 8 bars, like a crescendo effect?
```

**Expected Claude Response:**
Claude will create a pattern using the exact velocity notation ('v' prefix) to create a crescendo effect.

**Example Interaction:**
```
Claude: I'll create a crescendo pattern that simulates increasing intensity over 8 bars. I'll use precise velocity control to gradually increase the volume:

v20.v20.v40.v40.v60.v60.v80.v80.v100.v100.v120.v120.v127.v127.v127.v127.  # kick (A.)
....v30.....v50.....v70.....v90.....v110.....v127.....v127.....v127.  # snare (A2)
v20.v30.v40.v50.v60.v70.v80.v90.v100.v110.v120.v127.v127.v127.v127.v127.  # hi-hat (A5)

[Claude plays the pattern]
Successfully played drum pattern at 120 BPM with 3 instruments.

This pattern creates a crescendo effect by gradually increasing the velocity values from very soft (v20) to maximum intensity (v127) over the course of 8 bars. This simulates a drummer playing with increasing intensity.
```

## Example 6: Using Scale Mode

**User Prompt:**
```
I've set my EP-133 K.O. II to Keys Mode with a C minor scale on channel B. Can you show me which notes map to which pads, and then play a simple melody in that scale?
```

**Expected Claude Response:**
Claude will use the scale mode functions to show the pad-to-note mapping and then play a melodic sequence.

**Example Interaction:**
```
Claude: I'll help you with your C minor scale setup on channel B. Let me first show you which notes map to which pads.

[Claude gets the scale mapping]
Channel B - C minor scale mapping:
- B. = C3 (Root note)
- B0 = D3 (2nd note)
- B1 = Eb3 (3rd note/flat third)
- B2 = F3 (4th note)
- B3 = G3 (5th note)
- B4 = Ab3 (6th note/flat sixth)
- B5 = Bb3 (7th note/flat seventh)
- B6 = C4 (Octave)
- B7 = D4 (9th)
- B8 = Eb4 (10th)
- B9 = F4 (11th)

Now I'll play a simple melody in C minor:

[Claude plays scale sequence: 1, 3, 5, 8, 7, 5, 4, 3, 1]
Successfully played scale sequence using minor scale in C (channel B, octave 3).

This melody plays: C (root), Eb (flat third), G (fifth), C (octave), Bb (flat seventh), G, F, Eb, and back to C, creating a classic minor scale phrase.
```

## Example 7: Creating a Blues Riff

**User Prompt:**
```
I'd like to create a simple blues riff using the blues scale. Can you set up an E blues scale on channel C and create a blues riff for me?
```

**Expected Claude Response:**
Claude will set up a blues scale and play a characteristic blues sequence.

**Example Interaction:**
```
Claude: I'll create a blues riff using an E blues scale on channel C. First, let me show you the note mapping for this scale.

[Claude gets the scale mapping]
Channel C - E blues scale mapping:
- C. = E4 (Root note)
- C0 = G4 (Minor 3rd)
- C1 = A4 (4th)
- C2 = Bb4 (Flat 5th - blue note)
- C3 = B4 (5th)
- C4 = D5 (Minor 7th)
- C5 = E5 (Octave)

Now, I'll play a classic blues riff in E:

[Claude plays sequence: 1, 3, 4, 3, 1, 0, 5, 4, 3, 5, 1]
Successfully played scale sequence using blues scale in E (channel C, octave 4).

This blues riff incorporates the characteristic blues scale with the flat 5th (blue note) that gives blues its distinctive sound. The sequence creates that classic blues feel with a resolution back to the root.
```

## Example 8: Combining Drums and Melodic Elements

**User Prompt:**
```
I'd like to create a pattern that combines drums on channel A with a bassline on channel B. For the drums, I want a standard beat with kick, snare and hi-hat. For the bassline, I've set up channel B in C major scale. Can you create a pattern that puts these elements together?
```

**Expected Claude Response:**
Claude will create a combined pattern with drums on channel A and a melodic bassline on channel B.

**Example Interaction:**
```
Claude: I'll create a combined pattern with drums on channel A and a bassline using C major scale on channel B. Let me first get the scale mapping for channel B.

[Claude gets the scale mapping]
Channel B - C major scale mapping:
- B. = C3 (Root)
- B0 = D3 (2nd)
- B1 = E3 (3rd)
- B2 = F3 (4th)
- B3 = G3 (5th)
- B4 = A3 (6th)
- B5 = B3 (7th)
- B6 = C4 (Octave)

Now I'll create a pattern with drums and a bassline:

Drum pattern:
x...x...x...x...  # kick (A.)
....x.......x...  # snare (A2)
x.x.x.x.x.x.x.x.  # closed hi-hat (A5)

Bassline in C major:
[Claude plays sequence: 1, 0, 5, 0, 4, 0, 5, 0, 1, 0, 5, 0, 6, 0, 5, 0]

[Claude plays both patterns simultaneously]
Successfully played drum pattern at 120 BPM with 3 drum instruments.
Successfully played scale sequence using major scale in C (channel B, octave 3).

This combines a standard drum beat with a walking bassline in C major that follows a I-V-IV-V-I-V-VI-V progression, creating a rhythmic foundation with melodic movement.
```

## Tips for Working with Claude and KOII

1. **Be Specific**: When requesting sounds or patterns, be as specific as possible about what you want.

2. **Reference Pads Directly**: If you know exactly which pads you want to trigger, reference them directly (A., A1, B3, etc.) for more precise control.

3. **Use Sound Names**: When you want a specific sound, use its exact name in quotes (e.g., "MICRO KICK").

4. **Describe Rhythms Clearly**: Use standard terminology like "beats 1 and 3" or "the 'and' of beat 2" to describe where you want sounds to trigger.

5. **Specify Velocities**: For more expressive patterns, mention if you want dynamic control using velocity values.

6. **Scale Information**: When working with scales, always specify the scale type, root note, and channel.

7. **Sequence Notation**: For melodic sequences, use numbers (1-based) to reference scale degrees rather than absolute note names.

8. **Iterative Refinement**: Start with a simple pattern and then ask Claude to modify or expand it based on what you hear.

## Troubleshooting Common Issues

- **Claude Can't Find the Device**: Make sure the KOII server is running and that you've connected Claude to it using `/mcp add host=localhost`.

- **Sounds Not Triggering Correctly**: Double-check your pattern syntax and make sure you're referencing valid pads or sounds.

- **Velocity Control Not Working**: Ensure you're using the correct syntax for velocities: 'x'/'X' for high, 'o'/'O' for low, digits '1'-'9' for scaled values, or 'v' followed by digits for exact values.

- **Scale Mode Issues**: Verify that you've actually enabled Keys Mode on your device and set the correct scale before asking Claude to use scale mode functions.

- **Timing Issues**: If the pattern timing seems off, try adjusting the BPM, or make sure your pattern has the correct number of steps.