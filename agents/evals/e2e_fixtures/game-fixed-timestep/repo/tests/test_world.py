import pytest

from gamecore.world import World


def test_step_at_sixty_fps():
    world = World(velocity=120.0)
    world.step(1 / 60)
    assert world.x == pytest.approx(2.0)


def test_run_accumulates():
    world = World(velocity=60.0)
    assert world.run(1 / 60, 60) == pytest.approx(60.0)


def test_stationary_world_stays_put():
    world = World(velocity=0.0)
    world.step(1 / 60)
    assert world.x == 0.0
