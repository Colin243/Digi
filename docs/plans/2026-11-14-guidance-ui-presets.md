# Guidance UI presets: note for tomorrow (2026-11-15)

## The thought
Subject tracking (brackets, person/face boxes), live head cues (yaw/chin), the level indicator, the
multi-cue row and the debug readout are useful to us as developers. For an average person it is a lot
of information on one viewfinder. We want **toggleable UI presets and styles** so the same guidance
engine can show a calm, friendly UI by default, with the full instrument view for us.

The engine does not change. This is a presentation layer on top of `Guidance` and `LiveGuidance`.

## What exists today (so we know what to gate)
All in `ios/Digi/`:

| Piece | Where | Today's control |
|---|---|---|
| Top live cue + "+N" count + subject cue line | `LiveCueRow` (LiveGuidance.swift), used in DirectorModel.swift:176 | subject line gated by `subjectCuesEnabled` |
| Horizon line + tilt dot | `LevelIndicator` (DigiApp.swift:720) | always on while running |
| Subject brackets, "Subject" label | `SubjectOverlay` (DigiApp.swift:719) | always on once locked |
| Person/face boxes + monospace readout | `SubjectOverlay(debug:)` | `@AppStorage("digi.guidanceDebug")` |
| Head status card ("Head looks right", cyan cues) | `liveHeadStatus` (DirectorModel.swift:257) | `subjectCuesEnabled` |
| "Live head cues (experimental)" toggle | `subjectCards` (DirectorModel.swift:281) | UserDefaults `digi.liveSubjectCues` |
| Haptics / read-aloud | not yet audited | |

So visibility is currently three unrelated flags plus hard-coded always-on pieces.

## Proposal

### 1. One model: `GuidanceDisplay`
A small `Codable` struct, one flag per visual element, stored in `UserDefaults` (or `@AppStorage` with
a raw-value preset plus an optional custom blob).

```
struct GuidanceDisplay: Codable, Equatable {
    var cueRow: CueRowStyle        // .off | .topOnly | .topPlusCount
    var level: LevelStyle          // .off | .minimal (dot only) | .full (line + dot)
    var subjectBrackets: Bool
    var detectionBoxes: Bool       // people / faces
    var headCues: Bool             // replaces the "experimental" toggle
    var debugReadout: Bool
    var haptics: Bool              // buzz on "in position"
    var voice: Bool                // read cues aloud (future)
}
```

Lives in `Digi/GuidanceDisplay.swift`. Inject through `LiveGuidance.shared` or an `EnvironmentObject`
so `LiveCueRow`, `LevelIndicator`, `SubjectOverlay` and `liveHeadStatus` all read the same value
instead of each reading its own flag. Migrate `digi.liveSubjectCues` and `digi.guidanceDebug` into it
on first launch so nobody loses their setting.

### 2. Presets (the thing the user picks)
Update after discussion: the product is for the average person taking well-made photos, so presets
are **audience / aesthetic modes**, not a tech ladder. The full-information view stays (it is today's
UI) for people who want everything; the other two are toned-down looks for different markets.

| Preset | Audience | Feel | Shows |
|---|---|---|---|
| **Full info** (today's UI) | people who want every number; also us | instrument panel | Everything: cue row with "+N", level line + tilt dot, subject brackets, detection boxes, head cues, optional debug readout. |
| **Soft (XHS)** | average user, XHS-style aesthetic | friendly, cute, encouraging | One simple cue at a time in plain, warm wording, pastel/rounded pill, small sticker-like icons, a cheerful "in position" moment, gentle haptic. No boxes, no numbers, no level line (maybe a soft "straight!" nudge). Head cues only as "turn a little this way". |
| **Minimal (Western)** | users who prefer sleek | quiet, premium, mostly invisible | Almost nothing on screen until it matters: thin level line that appears only when tilted, a single short monochrome cue, subtle haptic and a tiny dot/check when ready. Thin type, no colour except a green/white confirmation. |
| **Custom** | anyone | | Each toggle individually; becomes active automatically when a toggle diverges from a preset. |

#### Information level, per style (added idea)
Instead of one global Custom, **every style gets its own "how much help" control**, so a user can pick
a look (Soft / Minimal / Full) and then dial the amount of information to their skill level:

| Level | Meaning | Roughly shows |
|---|---|---|
| **Essentials** (beginner) | just tell me what to do | the single top cue + "in position" confirmation |
| **Helpful** (default) | a bit more context | + level indicator, subject brackets, head cues |
| **Detailed** (enthusiast) | show me how close I am | + "+N" remaining cues, tilt dot, target vs. current hints |
| **Everything** (expert / us) | all the numbers | + detection boxes, debug readout |

How it fits the model: style = `GuidanceTheme` (look and wording), level = a set of `GuidanceDisplay`
flags. A preset is just `(theme, level)`, so the matrix is 3 styles x 4 levels from two small tables, not
12 hand-built screens. Each style renders a level in its own way (e.g. at "Helpful", Soft shows a pastel
level hint, Minimal shows a hairline that fades in only when tilted). A style may cap the top end (Soft
probably tops out at "Detailed"; "Everything" is mainly for Full info).

UI: in settings, pick the style, then a slider/stepper "Amount of guidance" with a live preview. A
"Fine-tune" disclosure still exposes individual toggles, which marks the choice as Custom. Remember the
level separately per style, so switching style does not reset it. Possible later: suggest a level up as
the user takes more photos ("want more detail?"), never automatically.

Developer readout (yaw/chin/vision raw values) is not a preset: it is an extra toggle inside Full info,
hidden from normal settings.

Presets are named `GuidanceDisplay` values, so adding one later is a one-line change.

### 3. Styles are part of each preset (look, not just what is shown)
"What is shown" (the `GuidanceDisplay` flags) and "how it looks" (a `GuidanceTheme`) are separate types,
and each preset pairs one of each. That way Soft and Minimal can look completely different while sharing
the same engine, and a user could later mix them.

`GuidanceTheme` covers:
- **Cue wording**: terse/technical (today), warm/conversational (Soft), shortest possible (Minimal).
  This is the biggest difference, so copy for Soft and Minimal needs writing (and Chinese + English for
  XHS audiences). `Guidance` cues already carry a symbol, so wording can swap per theme without
  touching the engine.
- **Shape and type**: capsule/rounded + rounded font (Soft); hairline + light weight (Minimal); current
  look (Full).
- **Palette**: Soft = pastel accent, Minimal = white/black + green confirm, Full = current cyan/green.
  Always pair colour with a symbol so it is not colour-only.
- **Motion and haptics**: bouncy/playful (Soft), fade-only (Minimal), none extra (Full).
- **Size / opacity**: larger text option for accessibility; faint overlays in Minimal.

Order: ship the three presets with their themes together, since the look is what differentiates them.

### 4. Settings UI
- Settings sheet (next to the existing "When online" picker in `DirectorView`): a **Guidance display**
  segmented picker with the presets, and a "Customize" disclosure listing the toggles.
- Quick toggle on the viewfinder: a single small eye button that cycles Simple / Guided / Pro, so a
  user can change it without leaving the camera. Long-press opens the full settings.
- Developer preset hidden behind a tap-version-number-five-times style unlock (or a launch arg), so
  regular users never see "Developer".
- Live preview: a static mock viewfinder at the top of the settings page that redraws as toggles change.

### 5. Implementation order
1. Add `GuidanceDisplay` + `GuidanceTheme` + the three presets + migration from the two old keys. Unit
   tests (preset equality, migration, Custom detection). Pure logic, no UI.
2. Thread it through the four views; replace `subjectCuesEnabled`/`guidanceDebug` reads. **Full info**
   must behave exactly like today's UI with everything on (regression check).
3. Write the cue copy for Soft and Minimal (EN, plus zh for the XHS audience). Add a wording layer keyed
   by theme.
4. Build the Soft and Minimal looks (shapes, palette, motion, haptics).
5. Settings: style picker + per-style "amount of guidance" level (stored per style) with a live preview,
   plus the Fine-tune toggle list.
6. Viewfinder quick-switch button.
7. Try it on people who are not us: "can you tell what to do in 2 seconds?" Pick the first-run default
   from that (probably Soft or Minimal, not Full info).

### 6. Open questions
- Should existing users stay on Full info while new installs get a first-run choice (Soft / Minimal / Full)?
  Maybe pick by device region/language with an easy "change look" prompt, not a locked decision.
- Is "Soft (XHS)" the right name internally, and what do users see? Probably a neutral label like "Soft".
- Does head-cue accuracy justify showing it outside Pro until we trust it (see the yaw/pitch sign notes
  in `LiveGuidance.visionYawSign`)?
- Voice read-out: separate item, but the `voice` flag reserves the slot.
- Should presets also change how often cues update (calmer = more hysteresis)? That touches
  `GuidanceTracker`, not just the UI. Probably later.

## Not decided yet
Final preset names, exact visual design of Soft and Minimal (worth a few mockups before coding), and the
first-run default. Think on this tomorrow before coding step 1.

---

# Addendum (2026-11-15)

## Styling notes carried over from PR #33 ("UI styling notes")
- **Zoom readout feels too technical.** `ZoomReadout` (`ios/Digi/DigiApp.swift`, ~line 1096) shows
  `1.4× · 34 mm` plus a 0.1x tick ruler in a monospaced capsule. That reads as a pro-camera control.
  For the styling pass: drop the "mm", soften or remove the ruler, and show just `1.4×` in the camera's
  own font and colours (not monospaced, not the gold accent).
- This is a good first "style" example: Full info keeps mm + ruler, Soft and Minimal show only `1.4×`.
  So the zoom readout should read from the same `GuidanceDisplay`/`GuidanceTheme` as everything else
  (`zoomDetail: .full | .valueOnly`).
- Same kind of thing elsewhere on the main camera chrome: monospaced `AUTO` / `LOCK` / `STUDY` labels in
  the top bar, and the exposure/flash labels. Candidates to hide or restyle per style.

## Open item in the PR test plan
- [ ] **Pinch zoom with capture study turned OFF.** Only tested with capture study on. The plain main
  camera path is unchecked. Differences to watch: the `videoZoomFactor` code path in `DigiApp.swift`
  (~lines 160-185, 257; depth is only enabled in study mode, and there is a comment that depth forced the
  dual camera to its 100 mm view), `camera.setZoom`, the 1x/1.5x/2x haptic detents, and that the
  readout hides again at 1x. Needs a real device (pinch cannot be tested in a simulator reliably). Do
  this before the styling pass touches `ZoomReadout`, so we know the baseline works.

---

# UI implementation plan

Goal: ship Full info / Soft / Minimal styles with a per-style information level, without forking the
guidance engine. Work in small steps, each of which leaves the app working.

## Phase 0: baseline (before any styling)
1. Test pinch zoom with capture study off on device (open item above). Fix if broken.
2. Screenshot the current camera screen in each state (idle, pinned shot with live cue, subject locked,
   debug on, zoomed) so we can compare "Full info" before/after the refactor.

## Phase 1: settings model and plumbing (no visual change)
Files: new `ios/Digi/GuidanceDisplay.swift` (and a small unit-test target for the pure logic).
1. `GuidanceStyle` enum: `.full`, `.soft`, `.minimal`.
2. `GuidanceLevel` enum: `.essentials`, `.helpful`, `.detailed`, `.everything` (ordered, `Comparable`).
3. `GuidanceDisplay` struct of per-element flags (cue row style, level indicator, brackets, detection
   boxes, head cues, debug readout, zoom detail, haptics) with
   `static func make(style:level:)` built from one table, plus optional per-toggle overrides ("Custom").
4. `GuidanceSettings` (`ObservableObject`, `@AppStorage`-backed): current style, level remembered *per
   style*, overrides, developer-readout toggle. Migrates `digi.liveSubjectCues` and `digi.guidanceDebug`.
5. Inject once at the root (`DigiApp`) as an `EnvironmentObject`.
Tests: every (style, level) yields the expected flags; levels are monotonic (a higher level never hides
something a lower one showed, within a style); migration; Custom detection.

## Phase 2: thread flags through the existing views (Full info must look identical)
- `LiveCueRow`, `LevelIndicator`, `SubjectOverlay`, `liveHeadStatus`, the "Live head cues" toggle in
  `subjectCards`, and `ZoomReadout` read `GuidanceDisplay` instead of their own flags.
- Check: style `.full` + level `.everything` equals today's UI (compare with the Phase 0 screenshots).

## Phase 3: theme layer (the look and the words)
- `GuidanceTheme` (fonts, shapes, palette, motion, haptics) one per style, applied via an Environment
  value so views never hard-code `CameraStyle.accent` or `.monospaced`.
- **Cue copy**: a `GuidanceWording` layer keyed by style that maps the engine's cue (type + direction)
  to text. Full = current terse text; Soft = warm and conversational; Minimal = shortest possible.
  Engine and `Guidance` cues stay unchanged. Write EN first, then zh for the XHS audience.
- Zoom readout per style (see styling note above). Restyle the monospaced top-bar labels per style.

## Phase 4: Soft and Minimal visuals
- Soft: pastel capsule cue, rounded type, small icon, playful confirm, gentle haptic.
- Minimal: hairline level that fades in only when tilted, single monochrome cue, tiny check when ready.
- Do a quick mockup of each before building (a static SwiftUI preview is enough).

## Phase 5: settings UI and quick switch
- Settings: style picker with a small preview per style; "Amount of guidance" level control per style
  with a live preview; "Fine-tune" disclosure with individual toggles (sets Custom); developer readout
  toggle hidden for normal users.
- Viewfinder: one small button to cycle style; long-press opens settings.
- First-run: a short "pick your look" choice (Soft / Minimal / Full), changeable any time.

## Phase 6: verify
- Unit tests green, simulator screenshots for every style at a couple of levels, accessibility check
  (Dynamic Type, VoiceOver labels still present at low levels even when visuals are hidden, colour never
  the only signal), reduced-motion respected.
- Device test with 3-5 people who are not us: "can you tell what to do within 2 seconds?" Choose the
  default style from that.

## Order of risk
Phase 0 and 1 are cheap and safe. Phase 2 is the regression risk (watch Full info). Phase 3 copy is the
most time-consuming and the highest value, since wording is what makes Soft and Minimal feel different.

---

# UI review in the simulator (2026-11-15)

Ran the real flow on the iPhone 17 Pro simulator (no camera, so the viewfinder is black and live
tracking overlays could not be seen): Director sheet -> Plan my shots (real local server, on a sample
forest photo) -> "Use this shot on the camera" -> pinned-shot card.

## Default camera screen: keep
Clean and calm. Wordmark, G12 selector, wand, flash, shutter and gallery are easy to read. Small
polish only: the monospaced `AUTO` / `3:4 JPEG` labels read as technical (see styling notes above).

## Director sheet
- The flow itself is simple: Portrait / Scenery / Inspiration, place photo, style, Plan my shots.
- **Server address and client key sit on the same screen as the main controls.** Normal users should
  never see these; move them behind an Advanced section.
- Style label mixes Chinese and English ("松弛感 Relaxed candid"), fine for XHS but worth localizing
  deliberately per style/preset.

## Shot results: too much text
Each shot lists 12+ rows (Stand, Height, Angle, Subject, Framing, Light, Pose, Head, Gaze, Expression,
Check on site...) with long sentences, three near-identical shots titled "golden trail". A normal user
needs: where to stand, how low/high, and what to tell the person. Suggest a short summary by default
(3 lines) with "More detail" expanding the rest, tied to the information level.

## Pinned-shot card (over the viewfinder)
- Collapsed: title + one live cue. Good.
- Expanded: Camera/Subject tabs, 4 rows of text, a 5-step stepper and a "Show detection boxes" toggle
  all at once. Heavy for the viewfinder area and the toggle is developer-facing.
- Subject tab: big, readable one-card-at-a-time cues (Where to be / Pose / Head / Eyes / Expression)
  with dots and Back/Next. This is the best part and a good model for Soft. But "Live head cues
  (experimental)" is shown to everyone; it belongs at Detailed level or higher.
- Gold border + gold cue text is strong against the black viewfinder; Minimal should be quieter.

## Not verified (needs a real device)
Live level indicator, subject brackets, head-turn cues, detection boxes and pinch zoom: the simulator
has no camera or motion sensors. The pinch-zoom-with-capture-study-off test is still open.

## Dev notes from this session
- Headless "build" tool failed (compiled x86_64; MLX packages are arm64-only). Worked with
  `xcodebuild ... ARCHS=arm64 ONLY_ACTIVE_ARCH=YES -destination id=<sim>`.
- Added a DEBUG-only launch flag in `PinnedShotStore` (`-digiDebugPinShot YES`) that pins a sample shot
  without any engine. Uncommitted, compiled out of release builds.
- Local server: `photo-ai server keygen --label ...` then `photo-ai server serve` (127.0.0.1:8787);
  the simulator reaches it at 127.0.0.1:8787.

---

# Phone screen recording review (IMG_2395.mov, 2026-11-15)

Real device, pinned shot "quiet stillness", pointing at a bedroom. About 8 separate things compete for
attention on one screen:

1. Top bar: `STUDY` `AUTO` flash `3:4 JPEG` (monospaced, gold).
2. Pinned-shot card over the top quarter of the viewfinder (title, collapse, close).
3. Camera cue: "Tilt up 14° +1" (gold, with a hidden extra cue count).
4. Subject cue: "Can't see their face yet" (cyan, a second colour for a second system).
5. Rule-of-thirds grid.
6. `AF/AE` focus box.
7. Green horizon line plus a ring and a moving dot (the level/tilt indicator, which has no label).
8. Debug readout box: `people 0 · faces 0` / `pitch -3° (want 10°) · roll 1.8°`.

Points for the redesign:
- **Jargon.** Pitch, roll, yaw, AF/AE, STUDY, "faces 0" mean nothing to a normal person. The level
  indicator (line + ring + dot) is only understandable if you already know what it measures.
- **Two competing cue colours** (gold camera cue, cyan subject cue) with different meanings is not
  obvious to a new user. One cue at a time, one colour.
- **Cue text mixes units and instructions**: "Tilt up 14°" is good (one action), but the number
  changes every frame and the "+1" says there is more without saying what.
- **Debug readout was on** in this recording (the "Show detection boxes" toggle in the expanded card
  controls it). It should never be reachable from the normal card; move it to a developer setting.
- **Grid + focus box + horizon + card** all overlap the same area; the card hides the top quarter of
  the scene being composed.
- Negative: "Can't see their face yet" shows constantly when no person is in view; consider showing it
  only after the user has pointed at a person, or folding it into one "Find your subject" state.

Redesign mapping (feeds the preset table above):
- Full info: keeps all of it, but still replace `yaw`/`pitch` wording where a plain word exists.
- Soft: one instruction at a time ("Tilt the phone up a little"), a friendly check when level, no
  numbers, no grid by default.
- Minimal: nothing until something is wrong; then a hairline level and one short word-cue; no card.
- Wording rule everywhere except Everything: no degrees, no axis names. Say what to do with the phone
  or the person ("turn your head a little to the right", "lift your chin").

## Addendum (2026-11-15, later): Phase 1 status, Minimal thumbnail, cards, camera settings model

### Phase 1 status
Done: `GuidanceDisplay.swift` in DirectorKit (style, level, flags, per-style level, overrides, migration;
13 tests pass) and `Digi/GuidanceSettings.swift` (stores `digi.guidancePrefs`). Nothing reads it yet, so no
visual change. Existing users migrate to Full info; the old `headCues` default (off) shows up as one
override, so they will read as "Custom" until the settings UI explains it. `photoThumbnail` is on in
every preset, Minimal included.

### Where the cards go (the pinned-shot card and the subject cue cards)
Today the card covers the top quarter of the viewfinder. Proposal per style:
- Full info: unchanged.
- Soft: the card collapses to the small title pill. Tapping it opens a bottom sheet (half height,
  drag to dismiss) with the Camera tab and the Subject cards. Subject cards stay big and read-aloud,
  one at a time, since that was the best part of the screen. The viewfinder is never covered while framing.
- Minimal: no card at all. A small dot or the shot title in the corner opens the same sheet.
Rule: nothing from the card shows over the preview unless it is the single live hint.

### Camera settings: let the Director set them
Today the app is auto-exposure only: zoom, brightness (EV bias), AE/AF lock, flash, timer, aspect ratio.
The Shot schema has `zoom_or_lens` and `lighting_tip` as free text only, so nothing is applied.
Plan:
1. `CameraPreset` (DirectorKit, pure): zoom, EV bias, flash, aspect, timer, AE/AF lock, and later white
   balance warmth, shutter floor (to avoid blur), portrait/depth, look strength. Fields optional.
2. v1 rule table from scenario and style (backlit portrait: +0.7 EV, meter on face; moving subject: shutter floor;
   low light: night handling). Deterministic and testable, no model needed. Shown as "Set for you", one
   tap to undo.
3. v2: the model outputs the preset as structured fields. Needs labels, so add a `camera_settings` block
   to the Shot schema, relabel `datasets/train_v1` and `scenery_v1` (reviewers confirm or correct), then
   train a LoRA run and score against the rule table. Training is not started and needs a decision first.
4. Style only changes how settings are shown (Soft: "Brightened for the backlight"; Minimal: silent
   with a small badge; Full: values).

## Phase 6 results and device test script (2026-11-15)

### Checked here
- DirectorKit unit tests: 119 pass. Existing UI tests (5): pass.
- Simulator screenshots for soft 0 and 2, minimal 1 and 2, full 2 and 3 (debug flags, no camera). Full info still
  shows the gold card and cyan subject line as before.
- Accessibility changes: the floating hint now has a plain-words VoiceOver label in every style (so Minimal's
  icon-only confirmation is still spoken), uses Dynamic Type sizes, and skips its animation under Reduce Motion.
  Colour is never the only signal: every state has an icon.

### Not checked (needs a real phone)
- Live level line and subject corners with a moving camera; haptic on "looks right"; eye quick-switch and the
  first-run sheet; pinch zoom with capture study off (still open from PR #33).
- In one Soft screenshot the second hint ("Get their face in view") looked faint. It may have been mid-fade,
  check it on the phone.

### Device checklist (you, 10 minutes)
1. Fresh install: pin a shot, the "Pick your look" sheet appears once. Choose Soft.
2. Walk the three styles with the eye button; confirm Full info matches your old screen.
3. Raise and lower the level in Guidance for each style; confirm Basics shows one hint only.
4. Turn the phone away from level and back: the line should go green and, in Soft/Minimal, buzz once.
5. Zoom with a pinch: Soft/Minimal show only the multiplier.
6. VoiceOver on: each hint is read in plain words.
7. Set the phone to Chinese and re-check Soft and Minimal copy.

### Outsider test (3 to 5 people, 5 minutes each)
Give each person the phone with a shot pinned, no explanation, same order of styles rotated between people.
Ask them to take the photo, and note:
- Time to the first correct move after the first hint (target under 2 seconds).
- What they say a hint means before acting ("what does that tell you to do?").
- Which style they would keep, and why in one sentence.
- Anything they ignore or tap that does nothing.
Decide the default style for new installs from this (current default is Full for migrated users and the pick
sheet for new ones).
