"""Crank-Nicolson solver for the heated-block / sample stack.

Unknowns, per unit area: one lumped block temperature and ``nodes`` sample
temperatures. The block and the first sample node exchange heat through a
series resistance; the last sample node loses heat to ambient with a fixed
coefficient.
"""

import numpy as np
from scipy.linalg import solve_banded


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
    cap = np.zeros(n)
    cap[0] = block_c
    cap[1:] = rho_cp * dx
    cap[1] *= 0.5
    cap[-1] *= 0.5

    a = np.zeros((n, n))
    a[0, 0] += 1.0 / r_contact
    a[0, 1] -= 1.0 / r_contact
    a[1, 0] -= 1.0 / r_contact
    a[1, 1] += 1.0 / r_contact
    g = alpha * rho_cp / dx
    for i in range(1, nodes):
        a[i, i] += g
        a[i + 1, i + 1] += g
        a[i, i + 1] -= g
        a[i + 1, i] -= g
    a[-1, -1] += h_back

    lhs = np.diag(cap / dt) + 0.5 * a
    rhs = np.diag(cap / dt) - 0.5 * a
    ab = np.zeros((3, n))
    ab[0, 1:] = np.diag(lhs, 1)
    ab[1, :] = np.diag(lhs)
    ab[2, :-1] = np.diag(lhs, -1)

    temp = np.full(n, t_amb)
    out = np.empty(len(times))
    out[0] = t_amb

    def power(t):
        return float(np.interp(t, power_t, power_q))

    b_prev = np.zeros(n)
    b_prev[-1] = h_back * t_amb
    b_prev[0] = power(0.0)

    index = 1
    steps = int(np.floor(times[-1] / dt + 1e-9))
    for k in range(1, steps + 1):
        t = k * dt
        b = np.zeros(n)
        b[-1] = h_back * t_amb
        b[0] = power(t)
        temp = solve_banded((1, 1), ab, rhs @ temp + 0.5 * (b_prev + b))
        b_prev = b
        while index < len(times) and times[index] <= t + 1e-9:
            out[index] = temp[-1]
            index += 1
    while index < len(times):
        out[index] = temp[-1]
        index += 1
    return out
