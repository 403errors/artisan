"""Minimal game-world simulation: position integration for moving entities."""


class World:
    """A single moving entity on a 1D track."""

    def __init__(self, velocity: float = 120.0) -> None:
        self.x = 0.0
        self.velocity = velocity

    def step(self, dt: float) -> None:
        """Advances the simulation by `dt` seconds."""
        self.x += self.velocity * (1 / 60)

    def run(self, dt: float, steps: int) -> float:
        """Steps `steps` times at `dt` seconds each; returns the final position."""
        for _ in range(steps):
            self.step(dt)
        return self.x
