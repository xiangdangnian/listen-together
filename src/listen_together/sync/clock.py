from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True, slots=True)
class ClockSample:
    offset_us: int
    rtt_us: int


@dataclass(frozen=True, slots=True)
class ClockEstimate:
    offset_us: int
    rtt_us: int
    sample_count: int


class ClockSynchronizer:
    MAX_SAMPLES = 7

    def __init__(self) -> None:
        self._samples: list[ClockSample] = []
        self._estimate: ClockEstimate | None = None

    def add_sample(
        self,
        *,
        t0_us: int,
        t1_us: int,
        t2_us: int,
        t3_us: int,
    ) -> ClockSample:
        if t3_us < t0_us or t2_us < t1_us:
            raise ValueError("Timestamps must be monotonic.")

        rtt_us = (t3_us - t0_us) - (t2_us - t1_us)
        if rtt_us < 0:
            raise ValueError("Round-trip time cannot be negative.")

        offset_us = round(((t1_us - t0_us) + (t2_us - t3_us)) / 2)
        sample = ClockSample(offset_us=offset_us, rtt_us=rtt_us)
        self._samples.append(sample)
        del self._samples[: -self.MAX_SAMPLES]
        self._estimate = None
        return sample

    def estimate(self) -> ClockEstimate:
        if not self._samples:
            raise ValueError("No clock samples have been recorded.")
        if self._estimate is not None:
            return self._estimate

        min_rtt_us = min(sample.rtt_us for sample in self._samples)
        rtt_allowance_us = max(2_000, min_rtt_us // 2)
        reliable = [
            sample
            for sample in self._samples
            if sample.rtt_us <= min_rtt_us + rtt_allowance_us
        ]
        self._estimate = ClockEstimate(
            offset_us=round(median(sample.offset_us for sample in reliable)),
            rtt_us=min_rtt_us,
            sample_count=len(reliable),
        )
        return self._estimate

    def host_now_us(self, local_now_us: int) -> int:
        return local_now_us + self.estimate().offset_us
