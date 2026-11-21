"""Unit test cho mo hinh tien nghi (pure Python, khong can database)."""
import math
import random
from dataclasses import replace

import pytest

import comfort as c
from comfort import ComfortModel, Situation, Vote, advise, load_prior, personalize

PRIOR, INFO = load_prior()
NOW = 2_000_000_000.0


def test_prior_file_is_documented():
    assert INFO["doi"] == "10.6078/D1F671" and INFO["n_votes"] > 1000
    assert PRIOR.w_t > 0 and PRIOR.theta0 < PRIOR.theta1


@pytest.mark.parametrize("ta", [18, 24, 26, 30, 36])
def test_probabilities_sum_to_one(ta):
    p = PRIOR.proba(ta, 60)
    assert all(x >= 0 for x in p) and math.isclose(sum(p), 1.0)


def test_hotter_room_means_more_want_cooler():
    cooler = [PRIOR.proba(t, 60)[2] for t in range(20, 34)]
    warmer = [PRIOR.proba(t, 60)[0] for t in range(20, 34)]
    assert cooler == sorted(cooler) and warmer == sorted(warmer, reverse=True)


def test_neutral_temp_balances_warmer_and_cooler():
    t = PRIOR.neutral_temp(60)
    p = PRIOR.proba(t, 60)
    assert math.isclose(p[0], p[2], abs_tol=1e-9)


def test_band_edges_have_30_percent_wish_to_change():
    lo, hi = PRIOR.comfort_band(60)
    assert math.isclose(PRIOR.proba(lo, 60)[0], 0.3, abs_tol=1e-9)
    assert math.isclose(PRIOR.proba(hi, 60)[2], 0.3, abs_tol=1e-9)


def test_shift_moves_everything_by_the_same_degrees():
    m = replace(PRIOR, shift=2.0)
    assert math.isclose(m.neutral_temp(60), PRIOR.neutral_temp(60) + 2.0)
    assert math.isclose(m.comfort_band(60)[1], PRIOR.comfort_band(60)[1] + 2.0)


def test_scale_keeps_neutral_and_narrows_band():
    m = replace(PRIOR, scale=2.0)
    assert math.isclose(m.neutral_temp(60), PRIOR.neutral_temp(60))
    lo, hi = m.comfort_band(60)
    plo, phi = PRIOR.comfort_band(60)
    assert lo > plo and hi < phi


def test_setpoint_is_warmest_comfortable_and_clamped():
    sp = PRIOR.setpoint(60, 16, 30)
    assert sp == math.floor(PRIOR.comfort_band(60)[1])
    assert replace(PRIOR, shift=-10).setpoint(60, 24, 29) == 24
    assert replace(PRIOR, shift=10).setpoint(60, 24, 29) == 29


def _simulate(shift, scale, n, seed=1, temps=(22, 33)):
    rng = random.Random(seed)
    person = replace(PRIOR, shift=shift, scale=scale)
    votes = []
    for i in range(n):
        ta, rh = rng.uniform(*temps), rng.uniform(50, 85)
        votes.append(Vote(NOW - (n - i) * 3600, rng.choices(range(3), weights=person.proba(ta, rh))[0], ta, rh))
    return votes


def test_no_votes_means_population_model():
    p = personalize(PRIOR, [], NOW)
    assert (p.shift, p.scale, p.n_votes) == (0.0, 1.0, 0)
    assert p.model == PRIOR


@pytest.mark.parametrize("true_shift", [-2.0, 2.0])
def test_personalization_recovers_preference(true_shift):
    p = personalize(PRIOR, _simulate(true_shift, 2.5, 150), NOW)
    assert abs(p.shift - true_shift) < 2.5 * p.shift_sd + 0.3
    assert p.scale > 1.2


def test_few_votes_stay_close_to_population():
    p = personalize(PRIOR, _simulate(3.0, 2.5, 3), NOW)
    assert abs(p.shift) < 3.0 and p.shift_sd > 0.8


def test_old_votes_count_less():
    assert c.vote_weight(NOW, NOW) == 1.0
    assert math.isclose(c.vote_weight(NOW - 30 * 86400, NOW), 0.5)
    old = [replace(v, ts=v.ts - 365 * 86400) for v in _simulate(-3.0, 2.5, 60, seed=2)]
    new = _simulate(+2.0, 2.5, 60, seed=3)
    assert personalize(PRIOR, old + new, NOW).shift > 0


# ------------------------------------------------------------------ advise()
def sit(**kw):
    base = dict(node_online=True, telemetry_fresh=True, ta=27.0, rh=65.0, presence=True, empty_for_s=None,
                ac_power="off", ac_mode="cool", ac_temp=26, ac_fan="auto")
    base.update(kw)
    return Situation(**base)


def test_no_data_no_advice():
    assert advise(PRIOR, sit(node_online=False), 24, 29).action == c.NONE
    assert advise(PRIOR, sit(telemetry_fresh=False), 24, 29).reason == "NO_DATA"


def test_hot_room_with_ac_off_suggests_turn_on_at_setpoint():
    a = advise(PRIOR, sit(ta=31.0), 24, 29)
    assert a.action == c.TURN_ON and a.target == {"power": "on", "mode": "cool",
                                                  "temp": PRIOR.setpoint(65, 24, 29), "fan": "auto"}


def test_mild_room_with_ac_off_no_advice():
    assert advise(PRIOR, sit(ta=25.0), 24, 29).action == c.NONE


def test_ac_on_moves_one_degree_toward_setpoint():
    sp = PRIOR.setpoint(65, 24, 29)
    a = advise(PRIOR, sit(ac_power="on", ac_temp=sp - 3), 24, 29)
    assert (a.action, a.target["temp"], a.reason) == (c.SET_TEMP, sp - 2, "WARMER_SETPOINT")
    assert advise(PRIOR, sit(ac_power="on", ac_temp=sp), 24, 29).reason == "SETPOINT_OK"


def test_empty_room_turns_off_only_after_15_minutes():
    on = dict(presence=False, ac_power="on", ac_temp=25)
    assert advise(PRIOR, sit(empty_for_s=600, **on), 24, 29).action == c.NONE
    a = advise(PRIOR, sit(empty_for_s=900, **on), 24, 29)
    assert (a.action, a.target["power"]) == (c.TURN_OFF, "off")
    assert advise(PRIOR, sit(presence=False, ta=33), 24, 29).action == c.NONE     # khong bat khi vang


def test_unknown_presence_is_treated_as_occupied():
    assert advise(PRIOR, sit(presence=None, ta=31.0), 24, 29).action == c.TURN_ON


def test_heat_or_fan_mode_is_left_alone():
    assert advise(PRIOR, sit(ac_power="on", ac_mode="heat"), 24, 29).reason == "MODE_NOT_SUPPORTED"


def test_model_dict_roundtrip():
    m = replace(PRIOR, shift=1.0, scale=2.0)
    assert ComfortModel(**m.as_dict()) == m
