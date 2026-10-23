# Stage 1 Report

## Scope

- Playback backend interface.
- Player state controller.
- Playback timeline calculation.
- Clock synchronization sample estimation.
- Separate-process clock simulation.
- Real VLC backend smoke test.

## Environment

- Python: 3.12.14
- python-vlc: 3.0.21203
- VLC: 3.0.24 Vetinari
- Platform: Windows

## Completed

- Created the Python package and editable virtual environment.
- Added `PlaybackAnchor` and `Timeline`.
- Added `ClockSynchronizer` with low-RTT sample filtering.
- Added `PlaybackController` and the `PlayerBackend` protocol.
- Added a real `VLCBackend`.
- Added a two-process clock synchronization test.
- Added a generated-audio VLC test using the dummy audio output.

## Verification

```text
Ran 8 tests
OK

compileall: OK
```

Covered behavior:

- Playing position advances from the Host monotonic clock.
- Paused position remains fixed.
- Position is clamped at the end of a track.
- Stale playback epochs are rejected.
- High-RTT clock samples do not dominate estimation.
- Clock offset estimation works across two processes.
- Playback controller transitions from ready to playing and paused.
- Seek is clamped to media duration.
- VLC opens, plays, pauses, seeks, and accepts a temporary rate change.

## Limitations

- mpv is not installed, so a live libmpv comparison was not possible.
- VLC accepts a rate change without error, but pitch preservation still needs a
  manual listening test before soft rate correction is enabled.
- The clock test uses a local pipe simulation. It does not replace a two-computer
  Radmin VPN measurement.
- No music library, network room, file transfer, cache, or UI is implemented yet.

## Recommendation

Keep `PlayerBackend` separated and use VLC provisionally for Stage 2. Do not
enable rate-based drift correction by default. Either add a later manual mpv
comparison or perform a listening test before enabling soft correction.

