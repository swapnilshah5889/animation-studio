# Staging
> Who is on screen, where they stand and what the camera frames: establishing shot, two-shots, close-ups, eyeline, who is in frame when a line is spoken.

**When to use:** when you plan each shot's characters, `where`, `framing` and the line's `to`.

**The rules (code checks all of them, `director/taste.py`):**
1. **Open with an establishing shot.** Shot 1 of the film (and the first shot of any scene in a *new*
   place) is `framing: wide`, every character of the scene is in it, 3 to 5 seconds, and usually nobody speaks
   (a tight film with many lines may say its first line here: both friends are on screen, so it still works).
   The audience learns *where* we are and *who* is here before anything is said. Small figures in the
   big place, a slow pan or none, a quiet motion (`look_around`, `wave`).
2. **A line is spoken to someone, and that someone is in the shot.** `line.to` names the listener
   (or "" when the character talks to the world: "Up, up, up!"). Never say "Look, Bo!" with Bo off
   screen: a child sees a character talking to the air. If the text contains another character's
   name, that character is in the shot.
3. **Two characters in a scene means a two-shot.** When Kit and Bo talk, show both: speaker and
   listener, `framing: medium`. The listener's reaction (a nod, a head tilt) is half the scene.
   Our puppets are flat front views, so a two-shot is how we get "over the shoulder": the speaker
   and the listener share the frame, the listener a little off to the side.
4. **Close-up is for a feeling, not for talking.** `framing: close` (one character, bigger) once per
   scene at most, on the peak of an emotion: the surprise, the goodbye, the proud grin. A close-up
   where someone talks about nothing special wastes the frame and hides the listener.
5. **Eyeline.** Within a scene each character keeps their side: Kit left, Bo right in every shot.
   If the sides swap between cuts, the characters seem to jump through each other. In a two-shot
   the code makes them face each other (the left one faces right).
6. **Reaction shot.** After a surprise or a big line, give the listener a shot of their own:
   silent (`line` empty), `close` or `medium`, 2 to 3 seconds, the emotion visible (`wonder`, `joy`).
   Talking is not the only thing a shot is for.
7. **Spacing.** One character: centre or toward the open space they face. Two: `left` and `right`.
   Three: left, centre, right. Characters closer than 0.2 of the frame overlap.

**What fails and why:** a film of one-character shots has no relationships: the audience cannot
tell who Kit is talking to. A wide shot with a close-up feeling (a tiny face) loses the emotion.
Characters at the frame edge are cropped (QA reports it).
