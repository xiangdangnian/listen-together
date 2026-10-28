class DriftCorrector:
    def __init__(
        self,
        *,
        threshold_ms: int = 500,
        required_hits: int = 5,
        cooldown_s: float = 3.0,
    ) -> None:
        self.threshold_ms = max(1, threshold_ms)
        self.required_hits = max(1, required_hits)
        self.cooldown_s = max(0.0, cooldown_s)
        self._hits = 0
        self._last_seek_s: float | None = None

    def update(self, drift_ms: int, *, now_s: float) -> bool:
        if abs(drift_ms) <= self.threshold_ms:
            self._hits = 0
            return False

        if (
            self._last_seek_s is not None
            and now_s - self._last_seek_s < self.cooldown_s
        ):
            return False

        self._hits += 1
        if self._hits < self.required_hits:
            return False

        self._hits = 0
        self._last_seek_s = now_s
        return True

    def reset(self) -> None:
        self._hits = 0
        self._last_seek_s = None

