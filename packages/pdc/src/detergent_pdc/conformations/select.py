"""Choosing K molecules from a pool: a deterministic stratified split, in numpy alone.

The pool is every whole molecule the source runs held, and K is a constant, so the choice cannot be "the first K"
or "a random K". The library has to cover the shapes the runs visited, and a rebuild from the same runs has to pick
the same molecules or the file digest a run pins changes for no reason.

The method is the standardised recursive median split: standardise each descriptor by its median and interquartile
range, split the widest cell at its median along its widest descriptor until there are K cells, and take the candidate
nearest each cell's centre. A cell narrower than the noise would otherwise dominate the split, which is why the
standardisation comes first and a zero interquartile range is read as a spread of one rather than as a division by
zero.

Every tie is broken by the candidate's place in the pool, and the pool is in canonical order, so the answer is a pure
function of the pool and K. `seed` is accepted because a library's identity records it, but this method draws nothing;
a future stochastic selection keeps the same signature and the same key spelling.
"""
import heapq

import numpy as np

#: How many descriptors a candidate carries: `length_nm`, `rg_nm`, `reach_nm`, `radial_nm`.
DESCRIPTOR_COUNT = 4


def stratified(descriptors, size, seed=0):
    """The indices of `size` candidates chosen from `descriptors`, ascending in the pool's own order.

    `descriptors` is an `(n, 4)` array in canonical candidate order. Exactly `size` distinct indices are returned;
    a pool smaller than `size` is refused rather than quietly shrunk, because K is what makes a library an ensemble
    rather than a handful of shapes.
    """
    values = np.asarray(descriptors, dtype=float)
    if values.ndim != 2 or values.shape[1] != DESCRIPTOR_COUNT:
        raise ValueError(f'descriptors must be an (n, {DESCRIPTOR_COUNT}) array, not {values.shape}')
    if not np.isfinite(values).all():
        raise ValueError('the descriptors hold a non-finite value: a molecule the extraction should have dropped')
    count = int(values.shape[0])
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError(f'size must be an integer of at least 1, not {size!r}')
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f'seed must be an integer, not {seed!r}')
    if count < size:
        raise ValueError(f'the pool holds {count} candidates, fewer than the {size} asked for')
    if count == size:
        return list(range(count))
    scaled = _standardise(values)
    chosen = [_nearest(scaled[members], members) for members in _split(scaled, size)]
    chosen.sort()
    return chosen


def _standardise(values):
    """Each descriptor in units of its own interquartile range about its median; a zero spread becomes one."""
    centre = np.median(values, axis=0)
    lower, upper = np.percentile(values, [25.0, 75.0], axis=0)
    spread = upper - lower
    spread = np.where(spread > 0.0, spread, 1.0)
    return (values - centre) / spread


def _split(scaled, size):
    """Split the widest cell at its median along its widest descriptor until there are exactly `size` cells.

    The widest cell is the heap's top; a one-candidate cell cannot split, so it is set aside while the next widest
    is taken. Ties between equally wide cells break by the cell's smallest member, then by the order cells were made,
    which is what keeps the partition reproducible without a random number.
    """
    heap = []
    counter = 0

    def push(members):
        nonlocal counter
        width = -1.0
        if len(members) > 1:
            axis = scaled[members]
            width = float((axis.max(axis=0) - axis.min(axis=0)).max())
        heapq.heappush(heap, (-width, int(members.min()), counter, members))
        counter += 1

    push(np.arange(len(scaled)))
    made = 1
    while made < size:
        held = []
        while True:
            widest = heapq.heappop(heap)
            if len(widest[3]) > 1:
                break
            held.append(widest)
        members = widest[3]
        cell = scaled[members]
        descriptor = int(np.argmax(cell.max(axis=0) - cell.min(axis=0)))
        ordered = members[np.argsort(cell[:, descriptor], kind='stable')]
        middle = len(ordered) // 2
        push(ordered[:middle])
        push(ordered[middle:])
        made += 1
        for entry in held:
            heapq.heappush(heap, entry)
    return [entry[3] for entry in heap]


def _nearest(values, members):
    """The cell's candidate nearest its centre, in standardised units, ties broken by pool order."""
    if len(members) == 1:
        return int(members[0])
    centre = values.mean(axis=0)
    distance = ((values - centre) ** 2).sum(axis=1)
    order = np.lexsort((members, distance))
    return int(members[order[0]])
