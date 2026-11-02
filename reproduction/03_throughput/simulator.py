"""Deterministic discrete-event simulator of one closed-loop SDL platform. SimPy 4.1.2, Python 3.12.3. Times are in
minutes.

Rules:
(1) A batch runs the platform's steps in step_order.
(2) A module is a resource of capacity `units` (default 1). A step of duration d and job size n splits a batch of b
    samples into ceil(b / n) jobs (n missing: one job); every job holds one unit of every module of the step at once for
    d minutes. Modules (and the human resource) are requested in a fixed order (module ids sorted, human last), so no
    two jobs can wait on each other. A step with duration 0 (covered by a joint duration of an earlier step) is skipped.
(3) A connection is a transfer placed before the step it leads to, once per batch: data_transfer takes no time and no
    resource; fixed_tubing is a delay; robot_arm_gantry and mobile_robot hold that mode's shared agent (capacity
    transfer_agent_count of the mode, default 1); human_transfer holds the human resource.
(4) A human step also holds the human resource (capacity transfer_agent_count of human, default 1). Human work (human
    steps and human transfers) runs only inside the human calendar (default Monday-Friday 09:00-17:00); other work runs
    inside the automated calendar (default 24 h, 7 days). Work outside its calendar pauses and resumes at the next
    working time; the job keeps its resources while paused. The clock starts on Monday 09:00 (t = 540, Monday 00:00 = 0).
(5) Closed loop: each batch starts with planning (planning minutes; the platform's plan step, if it has one, holds its
    modules during planning); the batch's experiments are complete when its last step ends, and only then does the next
    batch of the same stream start. parallel_units = k streams run at once. With a plan step at position p the batch
    runs the steps after p, then those before p.
(6) No failures, retries or randomness.
(7) Warm-up ends when every stream has completed 2 batches. The measurement window starts at the first Monday 09:00 at
    or after the end of warm-up and is 28 days long; if fewer than 5 batches complete in it, it grows by whole weeks up
    to 84 days; with still fewer than 5 the 84-day value is used and flagged. Throughput = experiments (b per batch)
    completed in the window / window length in days. Module utilisation = busy unit-minutes in the window / (units x
    window minutes); own share = minutes of work from the paper's own values / all minutes of work, over the work that
    ends inside the window.
"""
import math
from dataclasses import dataclass, field

import simpy

DAY = 1440.0
WEEK = 7 * DAY
START = 540.0                 # Monday 09:00
WARMUP_CAP = 3650 * DAY       # a platform whose warm-up does not end in ten simulated years is an error


class SimulationError(Exception):
    pass


@dataclass(frozen=True)
class Calendar:
    """Working windows: `days` days a week from Monday, `hours` hours a day from 09:00; hours >= 24 and days = 7 is
    always on."""
    hours: float = 24.0
    days: int = 7

    @property
    def always(self):
        return self.hours >= 24 and self.days >= 7

    def window(self, t):
        """(start, end) of the working window that contains t, or of the next one."""
        if self.always:
            return t, math.inf
        d = int(t // DAY)
        for k in range(d - 1, d + 9):
            if k % 7 >= self.days:
                continue
            ws = k * DAY + 540.0
            we = ws + self.hours * 60.0
            if we > t:
                return max(ws, t), we
        raise SimulationError("calendar has no working time")


HUMAN_DEFAULT = Calendar(8.0, 5)
AUTO_DEFAULT = Calendar(24.0, 7)


@dataclass
class Step:
    sid: str
    modules: tuple
    human: bool
    duration: float           # minutes per job
    job_size: float | None    # n; None = the whole batch is one job
    own: bool = True


@dataclass
class Transfer:
    before: int               # index in Platform.steps of the step the transfer leads to
    mode: str
    minutes: float
    own: bool = True


@dataclass
class Platform:
    steps: list
    units: dict = field(default_factory=dict)
    transfers: list = field(default_factory=list)
    batch_size: float = 1
    parallel_units: int = 1
    planning: float = 0.0
    planning_own: bool = True
    plan_index: int | None = None     # index of the plan step in steps, if any
    agents: dict = field(default_factory=dict)   # transfer_agent_count per mode ('robot_arm_gantry', 'mobile_robot', 'human')
    human_cal: Calendar = HUMAN_DEFAULT
    auto_cal: Calendar = AUTO_DEFAULT


@dataclass
class Result:
    throughput: float         # experiments per day in the window
    window_days: float
    batches_in_window: int
    flagged: bool
    warmup_end: float
    utilisation: dict
    own_share: float | None


def _work(env, minutes, cal):
    remaining = minutes
    while remaining > 1e-9:
        ws, we = cal.window(env.now)
        if ws > env.now:
            yield env.timeout(ws - env.now)
        run = min(remaining, we - env.now)
        yield env.timeout(run)
        remaining -= run


def simulate(p: Platform) -> Result:
    if p.plan_index is not None and not 0 <= p.plan_index < len(p.steps):
        raise SimulationError("plan_index outside the step list")
    if sum(s.duration for s in p.steps) + p.planning + sum(t.minutes for t in p.transfers) <= 0:
        raise SimulationError("a batch takes no time")
    env = simpy.Environment(initial_time=START)
    mods = {m: simpy.Resource(env, capacity=int(p.units.get(m, 1)))
            for s in p.steps for m in s.modules}
    human = simpy.Resource(env, capacity=int(p.agents.get("human", 1)))
    agent = {m: simpy.Resource(env, capacity=int(p.agents.get(m, 1))) for m in ("robot_arm_gantry", "mobile_robot")}
    busy = {m: [] for m in mods}          # (start, end, units) per module
    work_log = []                          # (end, minutes, own)
    completions = []                       # (time, experiments)
    before = {}
    for t in p.transfers:
        before.setdefault(t.before, []).append(t)
    if p.plan_index is None:
        order = list(range(len(p.steps)))
    else:
        order = list(range(p.plan_index + 1, len(p.steps))) + list(range(p.plan_index))
    b = p.batch_size if p.batch_size and p.batch_size > 0 else 1
    done_batches = [0] * max(1, int(p.parallel_units))
    warm = env.event()

    def hold(resources, minutes, cal, own, track):
        reqs = []
        for r in resources:
            req = r.request()
            reqs.append((r, req))
            yield req
        t0 = env.now
        yield from _work(env, minutes, cal)
        for m in track:
            busy[m].append((t0, env.now))
        for r, req in reqs:
            r.release(req)
        work_log.append((env.now, minutes, own))

    def job(step):
        res = [mods[m] for m in sorted(step.modules)] + ([human] if step.human else [])
        cal = p.human_cal if step.human else p.auto_cal
        yield from hold(res, step.duration, cal, step.own, sorted(step.modules))

    def transfer(t):
        if t.mode == "data_transfer" or t.minutes <= 0 and t.mode == "fixed_tubing":
            return
        if t.mode == "fixed_tubing":
            yield from _work(env, t.minutes, p.auto_cal)
            work_log.append((env.now, t.minutes, t.own))
        elif t.mode == "human_transfer":
            yield from hold([human], t.minutes, p.human_cal, t.own, [])
        elif t.mode in agent:
            yield from hold([agent[t.mode]], t.minutes, p.auto_cal, t.own, [])
        else:
            raise SimulationError(f"unknown transfer mode {t.mode}")

    def stream(k):
        while True:
            if p.plan_index is None:
                if p.planning > 0:
                    yield from _work(env, p.planning, p.auto_cal)
                    work_log.append((env.now, p.planning, p.planning_own))
            else:
                ps = p.steps[p.plan_index]
                res = [mods[m] for m in sorted(ps.modules)]
                yield from hold(res, p.planning, p.auto_cal, p.planning_own, sorted(ps.modules))
            for i in order:
                for t in before.get(i, []):
                    yield from transfer(t)
                s = p.steps[i]
                if s.duration <= 0:
                    continue
                n_jobs = math.ceil(b / s.job_size) if s.job_size else 1
                yield simpy.AllOf(env, [env.process(job(s)) for _ in range(n_jobs)])
            completions.append((env.now, b))
            done_batches[k] += 1
            if not warm.triggered and min(done_batches) >= 2:
                warm.succeed(env.now)

    for k in range(len(done_batches)):
        env.process(stream(k))
    env.run(until=simpy.AnyOf(env, [warm, env.timeout(WARMUP_CAP)]))
    if not warm.triggered:
        raise SimulationError("warm-up did not end within ten simulated years")
    warmup_end = warm.value
    w0 = START + math.ceil(max(0.0, warmup_end - START) / WEEK) * WEEK
    env.run(until=w0 + 12 * WEEK)
    length = 4 * WEEK
    in_win = lambda L: [c for c in completions if w0 <= c[0] < w0 + L]
    while len(in_win(length)) < 5 and length < 12 * WEEK:
        length += WEEK
    win = in_win(length)
    flagged = len(win) < 5
    w1 = w0 + length
    util = {}
    for m, spans in busy.items():
        used = sum(max(0.0, min(e, w1) - max(s, w0)) for s, e in spans)
        util[m] = used / (mods[m].capacity * length)
    logged = [(mins, own) for end, mins, own in work_log if w0 <= end < w1]
    total = sum(mins for mins, _ in logged)
    own_share = sum(mins for mins, own in logged if own) / total if total > 0 else None
    return Result(throughput=sum(e for _, e in win) / (length / DAY), window_days=length / DAY,
                  batches_in_window=len(win), flagged=flagged, warmup_end=warmup_end, utilisation=util,
                  own_share=own_share)
