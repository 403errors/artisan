"""Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
visible to the coding agent. They fail on the seeded bug and pass on a correct fix."""

import pytest

from gamecore.world import World


def test_step_respects_dt():
    world = World(velocity=120.0)
    world.step(0.5)
    assert world.x == pytest.approx(60.0)


def test_low_frame_rate_same_distance():
    # 30 steps at 30fps must cover the same distance as 60 steps at 60fps.
    slow = World(velocity=100.0)
    fast = World(velocity=100.0)
    slow.run(1 / 30, 30)
    fast.run(1 / 60, 60)
    assert slow.x == pytest.approx(fast.x)


def test_variable_timesteps():
    world = World(velocity=50.0)
    world.step(0.25)
    world.step(0.75)
    assert world.x == pytest.approx(50.0)
