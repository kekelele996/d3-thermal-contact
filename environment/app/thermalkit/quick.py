"""Quick estimate used by the incoming-inspection station."""

BLOCK_THICKNESS_FRACTION = 0.02
FLASH_CONSTANT = 0.1388


def estimate(run):
    meta = run["meta"]
    sample = meta["sample"]
    thickness = float(sample["thickness_m"])
    rho_cp = float(sample["density_kg_m3"]) * float(sample["cp_j_kg_k"])

    times = run["time_s"]
    temp = run["temp_c"]
    rise = temp[-1] - temp[0]
    if rise <= 0.0:
        raise ValueError("temperature did not rise")

    target = temp[0] + 0.5 * rise
    index = 1
    while index < len(temp) and temp[index] < target:
        index += 1
    if index >= len(temp):
        raise ValueError("half-rise time not reached")
    t0, t1 = times[index - 1], times[index]
    y0, y1 = temp[index - 1], temp[index]
    half_time = t0 + (target - y0) * (t1 - t0) / (y1 - y0)

    alpha = FLASH_CONSTANT * thickness * thickness / half_time
    conductivity = alpha * rho_cp
    r_contact = BLOCK_THICKNESS_FRACTION * thickness / conductivity

    return {"alpha_m2_s": alpha, "r_m2k_w": r_contact}
