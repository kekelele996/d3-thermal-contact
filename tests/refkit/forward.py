"""Crank-Nicolson solver for the heated-block / sample stack.

Unknowns, per unit area: one lumped block temperature and ``nodes`` sample
temperatures. The block and the first sample node exchange heat through a
series resistance; the last sample node loses heat to ambient with a fixed
coefficient.

Pure standard library: the tridiagonal system is solved with the Thomas
algorithm so the reference forward model has no third-party dependency.
"""


def _solve_tridiagonal(lower, diag, upper, rhs):
    n = len(diag)
    c = [0.0] * n
    d = [0.0] * n
    c[0] = upper[0] / diag[0] if n > 1 else 0.0
    d[0] = rhs[0] / diag[0]
    for i in range(1, n):
        den = diag[i] - lower[i - 1] * c[i - 1]
        c[i] = upper[i] / den if i < n - 1 else 0.0
        d[i] = (rhs[i] - lower[i - 1] * d[i - 1]) / den
    x = [0.0] * n
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


def _interp(t, ts, vs):
    if t <= ts[0]:
        return vs[0]
    if t >= ts[-1]:
        return vs[-1]
    lo, hi = 0, len(ts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ts[mid] <= t:
            lo = mid
        else:
            hi = mid
    span = ts[hi] - ts[lo]
    if span <= 0.0:
        return vs[hi]
    w = (t - ts[lo]) / span
    return vs[lo] * (1.0 - w) + vs[hi] * w


def simulate(
    alpha,
    r_contact,
    *,
    thickness,
    rho_cp,
    block_c,
    h_back,
    t_amb,
    times,
    power_t,
    power_q,
    nodes=161,
    dt=0.25,
):
    dx = thickness / (nodes - 1)
    n = nodes + 1

    cap = [0.0] * n
    cap[0] = block_c
    for i in range(1, n):
        cap[i] = rho_cp * dx * 0.5
    # 端点半格：首末节点各半格热容（内部节点已在循环里给了整格）
    for i in range(2, n - 1):
        cap[i] = rho_cp * dx

    kinv = 1.0 / r_contact
    g = alpha * rho_cp / dx

    a_diag = [0.0] * n
    a_lower = [0.0] * (n - 1)
    a_upper = [0.0] * (n - 1)

    a_diag[0] += kinv
    a_upper[0] -= kinv
    if n > 1:
        a_lower[0] -= kinv
        a_diag[1] += kinv
    for i in range(1, nodes):
        a_diag[i] += g
        a_diag[i + 1] += g
        a_upper[i] -= g
        a_lower[i] -= g
    a_diag[-1] += h_back

    inv_dt = 1.0 / dt
    lhs_diag = [cap[i] * inv_dt + 0.5 * a_diag[i] for i in range(n)]
    lhs_lower = [0.5 * v for v in a_lower]
    lhs_upper = [0.5 * v for v in a_upper]
    rhs_diag = [cap[i] * inv_dt - 0.5 * a_diag[i] for i in range(n)]
    rhs_lower = [-0.5 * v for v in a_lower]
    rhs_upper = [-0.5 * v for v in a_upper]

    temp = [t_amb] * n
    out = [t_amb] * len(times)

    b_prev = [0.0] * n
    b_prev[-1] = h_back * t_amb
    b_prev[0] = _interp(0.0, power_t, power_q)

    index = 1
    steps = int(times[-1] / dt + 1e-9)
    for k in range(1, steps + 1):
        t = k * dt
        q = _interp(t, power_t, power_q)
        rhs = [0.0] * n
        for i in range(n):
            value = rhs_diag[i] * temp[i]
            if i > 0:
                value += rhs_lower[i - 1] * temp[i - 1]
            if i < n - 1:
                value += rhs_upper[i] * temp[i + 1]
            rhs[i] = value
        rhs[0] += 0.5 * (b_prev[0] + q)
        rhs[-1] += 0.5 * (b_prev[-1] + h_back * t_amb)
        temp = _solve_tridiagonal(lhs_lower, lhs_diag, lhs_upper, rhs)
        b_prev = [0.0] * n
        b_prev[-1] = h_back * t_amb
        b_prev[0] = q
        while index < len(times) and times[index] <= t + 1e-9:
            out[index] = temp[-1]
            index += 1
    while index < len(times):
        out[index] = temp[-1]
        index += 1
    return out
