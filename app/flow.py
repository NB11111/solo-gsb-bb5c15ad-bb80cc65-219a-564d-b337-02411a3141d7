"""Deterministic Dinic maximum-flow implementation.

The review assignment problem is modelled as a flow network (see
``app.matcher``).  Dinic is an *exact, global* algorithm: it computes the
maximum flow over the whole network at once, so no per-manuscript greedy
decision is ever made.

Determinism: adjacency lists preserve edge insertion order, and every
traversal iterates them in that order.  Two identical networks therefore
produce identical flows bit-for-bit.
"""

from collections import deque


class _Edge:
    __slots__ = ("to", "rev", "cap")

    def __init__(self, to: int, rev: int, cap: int):
        self.to = to
        self.rev = rev  # index of the reverse edge in g[to]
        self.cap = cap


class Dinic:
    def __init__(self, n: int):
        self.n = n
        self.g: list[list[_Edge]] = [[] for _ in range(n)]

    def add_edge(self, u: int, v: int, cap: int) -> _Edge:
        """Add u -> v with capacity ``cap``; return the forward edge object."""
        forward = _Edge(v, len(self.g[v]), cap)
        backward = _Edge(u, len(self.g[u]), 0)
        self.g[u].append(forward)
        self.g[v].append(backward)
        return forward

    def _bfs(self, s: int, t: int, level: list[int]) -> bool:
        for i in range(self.n):
            level[i] = -1
        level[s] = 0
        queue = deque([s])
        while queue:
            u = queue.popleft()
            for e in self.g[u]:
                if e.cap > 0 and level[e.to] < 0:
                    level[e.to] = level[u] + 1
                    queue.append(e.to)
        return level[t] >= 0

    def _dfs(
        self,
        u: int,
        t: int,
        pushed: int,
        level: list[int],
        it: list[int],
    ) -> int:
        if u == t:
            return pushed
        while it[u] < len(self.g[u]):
            e = self.g[u][it[u]]
            if e.cap > 0 and level[e.to] == level[u] + 1:
                tr = self._dfs(e.to, t, min(pushed, e.cap), level, it)
                if tr:
                    e.cap -= tr
                    self.g[e.to][e.rev].cap += tr
                    return tr
            it[u] += 1
        return 0

    def max_flow(self, s: int, t: int) -> int:
        flow = 0
        level = [-1] * self.n
        inf = 10**18
        # The assignment network is layered (s -> manuscript -> reviewer -> t)
        # so recursion depth is at most 3 regardless of input size.
        while self._bfs(s, t, level):
            it = [0] * self.n
            while True:
                pushed = self._dfs(s, t, inf, level, it)
                if pushed == 0:
                    break
                flow += pushed
        return flow

    def residual_reachable(self, s: int) -> list[bool]:
        """Nodes reachable from ``s`` along residual edges (the min-cut side)."""
        seen = [False] * self.n
        seen[s] = True
        queue = deque([s])
        while queue:
            u = queue.popleft()
            for e in self.g[u]:
                if e.cap > 0 and not seen[e.to]:
                    seen[e.to] = True
                    queue.append(e.to)
        return seen
