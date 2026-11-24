import heapq
from collections import defaultdict

def build_graph(tasks):
    info = {}
    remaining = {}
    dependents = defaultdict(list)

    for tid, dur, pri, deps in tasks:
        info[tid] = (dur, pri) 
        remaining[tid] = len(deps)

        for d in deps:
            dependents[d].append(tid)

    return info, remaining, dependents


def schedule(W, tasks):
    info,remaining, dependents = build_graph(tasks)
    ready = [(-info[t][1], t) for t in info if remaining[t] == 0]  #negate priority so highest is on top, ties go to smallest id
    heapq.heapify(ready)
    free = list(range(W))

    running = [] # (finish_time, task_id, worker)
    sched = [] # (task_id, start_time, worker)
    t = 0
    makespan = 0

    while True:
        changed = True
        while changed: #loop again at the same t in case a 0 duration task finishes right away
            changed = False
            while running and running[0][0] == t:
                _, tid, w = heapq.heappop(running)
                heapq.heappush(free, w) # shows that worker is free again
                makespan = t

                for nxt in dependents[tid]:
                    remaining[nxt] -= 1
                    if remaining[nxt] == 0:
                        heapq.heappush(ready, (-info[nxt][1], nxt))
                changed = True

            while ready and free:
                _, tid = heapq.heappop(ready)
                w = heapq.heappop(free)
                sched.append((tid, t, w))
                heapq.heappush(running, (t + info[tid][0], tid, w))
                changed = True
        if not running:
            break
        t = running[0][0] #jump straight to the next event

    if len(sched) != len(info):
        raise ValueError("some tasks not run: cycle or missing dependency")
    
    sched.sort(key=lambda x: (x[1], x[0]))

    return makespan, sched


if __name__ == "__main__":
    W = 2
    tasks = [
        (1, 3, 5, []),
        (2, 2, 1, []),
        (3, 4, 9, [1]),
        (4, 1, 1, [1, 2]),
    ]

    makespan, sched = schedule(W, tasks)
    print(f"makespan: {makespan}")
    print(f"schedule: {sched}")