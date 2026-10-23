from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlaybackAnchor:
    epoch: int
    track_id: str
    duration_ms: int
    playing: bool
    anchor_position_ms: int
    anchor_host_us: int
    rate: float = 1.0


class Timeline:
    def accepts_epoch(self, *, current_epoch: int, incoming_epoch: int) -> bool:
        return incoming_epoch >= current_epoch

    def target_position_ms(
        self,
        anchor: PlaybackAnchor,
        *,
        host_now_us: int,
    ) -> int:
        if anchor.rate <= 0:
            raise ValueError("Playback rate must be positive.")

        position_ms = anchor.anchor_position_ms
        if anchor.playing:
            elapsed_us = max(0, host_now_us - anchor.anchor_host_us)
            position_ms += round(elapsed_us / 1000 * anchor.rate)

        return min(max(0, position_ms), anchor.duration_ms)
