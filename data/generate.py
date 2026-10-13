
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. Configuration — every number here is an assumption you can explain
# ---------------------------------------------------------------------------

START = pd.Timestamp("2025-10-01")
END = pd.Timestamp("2026-09-30")  # inclusive: 365 days of history

# (wilaya, share of customers, network quality 0..1)
# Network quality is INVENTED for this fictional operator; it only drives
# dropped calls and churn risk. Big northern cities get better coverage.
WILAYAS = [
    ("Alger", 0.20, 0.95), ("Oran", 0.11, 0.92), ("Constantine", 0.08, 0.90),
    ("Sétif", 0.08, 0.88), ("Batna", 0.07, 0.85), ("Blida", 0.06, 0.92),
    ("Annaba", 0.05, 0.90), ("Tizi Ouzou", 0.05, 0.84), ("Béjaïa", 0.05, 0.86),
    ("Tlemcen", 0.05, 0.87), ("Djelfa", 0.05, 0.75), ("Biskra", 0.05, 0.80),
    ("Ouargla", 0.04, 0.72), ("Ghardaïa", 0.03, 0.74), ("Tamanrasset", 0.03, 0.62),
]

# Hidden behaviour segments.
#   data_mb / minutes / sms : typical value on a day the customer is active
#   use_prob                : chance of using the network on a given day
#   recharge_every          : average days between top-ups
#   amounts                 : top-up amounts (DZD) and their probabilities
#   offer_prob              : chance a top-up is (partly) spent on a bundle
#   base_churn              : chance of leaving during the 12 months, before
#                             hidden satisfaction / network effects
SEGMENTS = {
    "heavy_data": dict(share=0.20, plan="DzMobile Data", age=["18-24", "25-34", "35-44"],
                       age_p=[0.35, 0.45, 0.20], data_mb=1100, minutes=8, sms=0.4,
                       use_prob=0.96, recharge_every=7, amounts=[500, 1000, 2000],
                       amounts_p=[0.30, 0.50, 0.20], offer_prob=0.85, base_churn=0.28,
                       night_beta=(3, 6)),
    "student": dict(share=0.25, plan="DzMobile Jeune", age=["18-24"], age_p=[1.0],
                    data_mb=450, minutes=6, sms=1.5, use_prob=0.92, recharge_every=4,
                    amounts=[100, 200, 500], amounts_p=[0.45, 0.40, 0.15],
                    offer_prob=0.75, base_churn=0.38, night_beta=(4, 5)),
    "balanced": dict(share=0.27, plan="DzMobile Classic", age=["25-34", "35-44", "45-54"],
                     age_p=[0.35, 0.40, 0.25], data_mb=320, minutes=14, sms=1.0,
                     use_prob=0.90, recharge_every=8, amounts=[200, 500, 1000],
                     amounts_p=[0.30, 0.50, 0.20], offer_prob=0.60, base_churn=0.24,
                     night_beta=(2, 8)),
    "calls_only": dict(share=0.18, plan="DzMobile Classic", age=["35-44", "45-54", "55+"],
                       age_p=[0.25, 0.40, 0.35], data_mb=15, minutes=25, sms=2.0,
                       use_prob=0.85, recharge_every=9, amounts=[100, 200, 500],
                       amounts_p=[0.35, 0.45, 0.20], offer_prob=0.40, base_churn=0.20,
                       night_beta=(1, 12)),
    "occasional": dict(share=0.10, plan="DzMobile Classic", age=["25-34", "45-54", "55+"],
                       age_p=[0.30, 0.30, 0.40], data_mb=40, minutes=4, sms=0.5,
                       use_prob=0.45, recharge_every=20, amounts=[100, 200],
                       amounts_p=[0.60, 0.40], offer_prob=0.30, base_churn=0.42,
                       night_beta=(1, 10)),
}

# Offer catalogue — names and prices are INVENTED for the fictional operator.
OFFERS = pd.DataFrame(
    [
        (1, "Mini Net 24h", 100, 1_000, 0, 1, False, "student"),
        (2, "Nuit Jeune", 150, 3_000, 0, 7, True, "student"),
        (3, "Appels 200", 200, 0, 120, 7, False, "calls_only"),
        (4, "Net Semaine", 300, 5_000, 0, 7, False, "balanced"),
        (5, "Mix 500", 500, 8_000, 60, 15, False, "balanced"),
        (6, "Net Mois 1000", 1000, 30_000, 0, 30, False, "heavy_data"),
        (7, "Mix 1500", 1500, 40_000, 300, 30, False, "heavy_data"),
        (8, "Net Mois 2000", 2000, 80_000, 60, 30, False, "heavy_data"),
    ],
    columns=["offer_id", "name", "price_dzd", "data_mb", "minutes",
             "validity_days", "night_only", "target_segment"],
)

# Which offers each segment prefers (weights over offer_id 1..8).
OFFER_PREFS = {
    "heavy_data": [0.02, 0.03, 0.00, 0.05, 0.10, 0.40, 0.20, 0.20],
    "student":    [0.35, 0.35, 0.02, 0.18, 0.08, 0.02, 0.00, 0.00],
    "balanced":   [0.08, 0.02, 0.10, 0.30, 0.35, 0.10, 0.05, 0.00],
    "calls_only": [0.02, 0.00, 0.80, 0.03, 0.15, 0.00, 0.00, 0.00],
    "occasional": [0.30, 0.00, 0.50, 0.15, 0.05, 0.00, 0.00, 0.00],
}

CHANNELS = ["retailer_topup", "scratch_card", "mobile_app", "bank_card"]
CHANNEL_PREFS = {
    "heavy_data": [0.35, 0.10, 0.40, 0.15],
    "student":    [0.45, 0.15, 0.35, 0.05],
    "balanced":   [0.50, 0.15, 0.25, 0.10],
    "calls_only": [0.55, 0.35, 0.07, 0.03],
    "occasional": [0.55, 0.40, 0.04, 0.01],
}

# Approximate Ramadan 2026 window (data use rises in the evenings and at night).
RAMADAN = (pd.Timestamp("2026-02-18"), pd.Timestamp("2026-03-19"))


# ---------------------------------------------------------------------------
# 2. Small helpers
# ---------------------------------------------------------------------------

def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def logit(p):
    return np.log(p / (1.0 - p))


# ---------------------------------------------------------------------------
# 3. Subscribers and their hidden truth
# ---------------------------------------------------------------------------

def make_subscribers(n: int, rng: np.random.Generator, n_days: int):
    seg_names = list(SEGMENTS)
    seg_p = np.array([SEGMENTS[s]["share"] for s in seg_names])
    segment = rng.choice(seg_names, size=n, p=seg_p / seg_p.sum())

    w_names = [w[0] for w in WILAYAS]
    w_p = np.array([w[1] for w in WILAYAS])
    w_quality = {w[0]: w[2] for w in WILAYAS}
    wilaya = rng.choice(w_names, size=n, p=w_p / w_p.sum())
    quality = np.array([w_quality[w] for w in wilaya])

    # 30% join during the year (this replaces the customers lost to churn and
    # keeps the active base roughly flat, as at a real operator); the rest
    # joined 1 month to 4 years before START.
    is_new = rng.random(n) < 0.30
    signup_day = np.where(
        is_new,
        rng.integers(0, n_days - 7, size=n),           # day index inside window
        -rng.integers(30, 1460, size=n),               # negative = before START
    )
    signup_date = START + pd.to_timedelta(signup_day, unit="D")

    plan = np.array([SEGMENTS[s]["plan"] for s in segment])
    age_band = np.array([rng.choice(SEGMENTS[s]["age"], p=SEGMENTS[s]["age_p"]) for s in segment])

    # Hidden satisfaction: partly caused by network quality, partly personal.
    satisfaction = 2.5 * (quality - 0.85) + rng.normal(0, 1, size=n)

    # Personal multipliers so two customers in one segment still differ.
    data_factor = rng.lognormal(0, 0.5, size=n)
    call_factor = rng.lognormal(0, 0.5, size=n)
    recharge_factor = rng.lognormal(0, 0.3, size=n)

    # Who churns during the window?
    tenure_at_start = np.maximum(-signup_day, 0)
    base = np.array([SEGMENTS[s]["base_churn"] for s in segment])
    churn_logit = (
        logit(base)
        - 0.9 * satisfaction                     # unhappy customers leave
        + 0.5 * (tenure_at_start < 180)          # new customers are less loyal
        + rng.normal(0, 0.5, size=n)             # pure luck
    )
    churns = rng.random(n) < sigmoid(churn_logit)

    # When do they stop? At least 21 days after signup, inside the window.
    first_day = np.maximum(signup_day, 0)
    churn_day = np.full(n, n_days + 1000)  # "never" for non-churners
    lo = np.minimum(first_day + 21, n_days - 1)
    churn_day[churns] = rng.integers(lo[churns], n_days)

    # 70% fade gradually over 3–10 weeks, 30% leave abruptly (≤3 days).
    gradual = rng.random(n) < 0.70
    drift_len = np.where(gradual, rng.integers(21, 71, size=n), rng.integers(0, 4, size=n))

    # 12% of everyone has a temporary dip (travel, money trouble) and recovers.
    has_dip = rng.random(n) < 0.12
    dip_start = rng.integers(0, n_days - 40, size=n)
    dip_len = rng.integers(14, 41, size=n)

    subscribers = pd.DataFrame({
        "subscriber_id": np.arange(1, n + 1),
        "phone": [f"09{i:08d}" for i in range(1, n + 1)],  # fake prefix, never a real number
        "signup_date": signup_date.date,
        "wilaya": wilaya,
        "plan": plan,
        "age_band": age_band,
    })

    churn_date = pd.Series(pd.NaT, index=range(n))
    churn_date[churns] = START + pd.to_timedelta(churn_day[churns], unit="D")

    truth = pd.DataFrame({
        "subscriber_id": subscribers["subscriber_id"],
        "segment": segment,
        "network_quality": quality,
        "satisfaction": satisfaction.round(3),
        "churned": churns,
        "churn_date": churn_date.dt.date,
        "churn_style": np.where(churns, np.where(gradual, "gradual", "abrupt"), ""),
        "drift_days": np.where(churns, drift_len, 0),
        "had_temporary_dip": has_dip,
    })

    hidden = dict(segment=segment, quality=quality, satisfaction=satisfaction,
                  signup_day=signup_day, churn_day=churn_day, drift_len=drift_len,
                  has_dip=has_dip, dip_start=dip_start, dip_len=dip_len,
                  data_factor=data_factor, call_factor=call_factor,
                  recharge_factor=recharge_factor)
    return subscribers, truth, hidden


# ---------------------------------------------------------------------------
# 4. Daily activity level: a (subscribers × days) matrix between 0 and 1
# ---------------------------------------------------------------------------

def activity_matrix(h: dict, n_days: int) -> np.ndarray:
    days = np.arange(n_days)[None, :]                    # shape (1, D)
    signup = np.maximum(h["signup_day"], 0)[:, None]     # shape (N, 1)
    churn = h["churn_day"][:, None]
    drift = h["drift_len"][:, None]

    act = np.ones((len(signup), n_days))
    act[days < signup] = 0.0                              # not a customer yet

    # Fading before churn: linear from 1 down to 0.15 over the drift window.
    drift_start = churn - drift
    in_drift = (days >= drift_start) & (days < churn)
    progress = np.clip((days - drift_start) / np.maximum(drift, 1), 0, 1)
    act = np.where(in_drift, act * (1 - 0.85 * progress), act)

    act[days >= churn] = 0.0                              # gone

    # Temporary dips that recover (false alarms for the model).
    dip_s = h["dip_start"][:, None]
    dip_e = dip_s + h["dip_len"][:, None]
    in_dip = h["has_dip"][:, None] & (days >= dip_s) & (days < dip_e)
    act = np.where(in_dip, act * 0.3, act)
    return act


# ---------------------------------------------------------------------------
# 5. Daily usage
# ---------------------------------------------------------------------------

def make_daily_usage(h: dict, act: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    n, n_days = act.shape
    dates = pd.date_range(START, periods=n_days, freq="D")
    seg = h["segment"]

    def seg_arr(key):
        return np.array([SEGMENTS[s][key] for s in seg])[:, None]

    # Algerian weekend = Friday (4) and Saturday (5): more data, fewer calls.
    weekend = np.isin(dates.dayofweek, [4, 5])[None, :]
    ramadan = ((dates >= RAMADAN[0]) & (dates <= RAMADAN[1]))[None, :]
    data_season = np.where(weekend, 1.15, 1.0) * np.where(ramadan, 1.12, 1.0)
    call_season = np.where(weekend, 0.85, 1.0)

    # Does the customer use the network today? Less likely when activity is low.
    p_use = seg_arr("use_prob") * np.clip(act * 1.1, 0, 1)
    active = rng.random((n, n_days)) < p_use

    data = (seg_arr("data_mb") * h["data_factor"][:, None] * data_season * act
            * rng.lognormal(0, 0.6, size=(n, n_days)))
    minutes = (seg_arr("minutes") * h["call_factor"][:, None] * call_season * act
               * rng.gamma(2.0, 0.5, size=(n, n_days)))
    sms = rng.poisson(seg_arr("sms") * act)

    # Share of data used at night, per subscriber (students stay up late).
    a = np.array([SEGMENTS[s]["night_beta"][0] for s in seg])
    b = np.array([SEGMENTS[s]["night_beta"][1] for s in seg])
    night_share = rng.beta(a, b)[:, None] * rng.uniform(0.7, 1.3, size=(n, n_days))
    data_night = data * np.clip(night_share, 0, 1)

    # Dropped calls: worse network + unhappy customers experience more of them.
    drop_rate = (1 - h["quality"])[:, None] * 0.12 * np.exp(-0.25 * h["satisfaction"])[:, None]
    dropped = rng.poisson(minutes / 3.0 * drop_rate)

    idx_sub, idx_day = np.nonzero(active)
    usage = pd.DataFrame({
        "subscriber_id": idx_sub + 1,
        "usage_date": dates[idx_day].date,
        "data_mb": data[idx_sub, idx_day].round(1),
        "data_mb_night": data_night[idx_sub, idx_day].round(1),
        "call_minutes": minutes[idx_sub, idx_day].round(1),
        "sms_count": sms[idx_sub, idx_day],
        "dropped_calls": dropped[idx_sub, idx_day],
    })
    return usage


# ---------------------------------------------------------------------------
# 6. Recharges and offer purchases (event by event, per subscriber)
# ---------------------------------------------------------------------------

def make_recharges_and_subscriptions(h: dict, act: np.ndarray, rng: np.random.Generator):
    n, n_days = act.shape
    offer_price = OFFERS.set_index("offer_id")["price_dzd"].to_dict()
    offer_valid = OFFERS.set_index("offer_id")["validity_days"].to_dict()
    offer_ids = OFFERS["offer_id"].to_numpy()

    recharge_rows, sub_rows = [], []
    for i in range(n):
        seg = h["segment"][i]
        cfg = SEGMENTS[seg]
        mean_gap = cfg["recharge_every"] * h["recharge_factor"][i]
        prefs = np.array(OFFER_PREFS[seg])

        # First top-up: on signup day for new customers, otherwise somewhere
        # in the first recharge cycle of the window.
        t = max(h["signup_day"][i], 0)
        if h["signup_day"][i] < 0:
            t += int(rng.integers(0, max(int(mean_gap), 1) + 1))

        while t < n_days and act[i, t] > 0:
            level = act[i, t]
            amount = rng.choice(cfg["amounts"], p=cfg["amounts_p"])
            if rng.random() < (1 - level):              # fading customers top up less
                amount = min(cfg["amounts"])
            channel = str(rng.choice(CHANNELS, p=CHANNEL_PREFS[seg]))
            recharge_rows.append((i + 1, t, int(amount), channel))

            # Spend part of the top-up on a bundle the customer can afford.
            if rng.random() < cfg["offer_prob"] * min(1.0, level + 0.2):
                affordable = np.array([offer_price[o] <= amount for o in offer_ids])
                w = prefs * affordable
                if w.sum() > 0:
                    oid = int(rng.choice(offer_ids, p=w / w.sum()))
                    sub_rows.append((i + 1, oid, t, t + offer_valid[oid], offer_price[oid]))

            # Next top-up: longer gaps when activity is low (renewal process).
            gap = mean_gap * rng.gamma(3.0, 1 / 3.0) / max(level, 0.12)
            t += max(1, int(round(gap)))

    rech = pd.DataFrame(recharge_rows, columns=["subscriber_id", "day", "amount_dzd", "channel"])
    rech.insert(0, "recharge_id", np.arange(1, len(rech) + 1))
    rech["recharge_date"] = (START + pd.to_timedelta(rech.pop("day"), unit="D")).dt.date
    rech = rech[["recharge_id", "subscriber_id", "recharge_date", "amount_dzd", "channel"]]

    subs = pd.DataFrame(sub_rows, columns=["subscriber_id", "offer_id", "day", "end", "price_dzd"])
    subs.insert(0, "subscription_id", np.arange(1, len(subs) + 1))
    subs["purchase_date"] = (START + pd.to_timedelta(subs.pop("day"), unit="D")).dt.date
    subs["expiry_date"] = (START + pd.to_timedelta(subs.pop("end"), unit="D")).dt.date
    subs = subs[["subscription_id", "subscriber_id", "offer_id", "purchase_date",
                 "expiry_date", "price_dzd"]]
    return rech, subs


# ---------------------------------------------------------------------------
# 7. Summary — look at it every time you generate data
# ---------------------------------------------------------------------------

def print_summary(subscribers, truth, usage, rech, subs):
    print("\n=== DzMobile synthetic data summary ===")
    print(f"subscribers      : {len(subscribers):>10,}")
    print(f"daily_usage rows : {len(usage):>10,}")
    print(f"recharges        : {len(rech):>10,}")
    print(f"subscriptions    : {len(subs):>10,}")

    churned = truth["churned"].mean()
    monthly = 1 - (1 - churned) ** (1 / 12)
    print(f"\nchurned in 12 months : {churned:.1%}  (≈ {monthly:.1%} per month)")
    print("churn style          :", truth.loc[truth.churned, "churn_style"]
          .value_counts(normalize=True).round(2).to_dict())
    print("churn rate by segment:", truth.groupby("segment")["churned"].mean().round(2).to_dict())

    print("\nrecharge amounts (share):",
          rech["amount_dzd"].value_counts(normalize=True).round(2).sort_index().to_dict())
    print("recharge channels (share):",
          rech["channel"].value_counts(normalize=True).round(2).to_dict())

    per_sub = usage.groupby("subscriber_id")["data_mb"].mean()
    print(f"\nmean data per active day: median subscriber {per_sub.median():.0f} MB, "
          f"90th percentile {per_sub.quantile(0.9):.0f} MB")
    print("top offers:", subs["offer_id"].map(OFFERS.set_index("offer_id")["name"])
          .value_counts().head(4).to_dict())


# ---------------------------------------------------------------------------
# 8. Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate DzMobile synthetic data")
    parser.add_argument("--n-subscribers", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "raw")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)   # same seed = same data, always
    n_days = (END - START).days + 1

    print(f"Generating {args.n_subscribers:,} subscribers over {n_days} days...")
    subscribers, truth, hidden = make_subscribers(args.n_subscribers, rng, n_days)
    act = activity_matrix(hidden, n_days)
    usage = make_daily_usage(hidden, act, rng)
    rech, subs = make_recharges_and_subscriptions(hidden, act, rng)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "_hidden").mkdir(exist_ok=True)
    subscribers.to_csv(args.out / "subscribers.csv", index=False)
    OFFERS.to_csv(args.out / "offers.csv", index=False)
    rech.to_csv(args.out / "recharges.csv", index=False)
    subs.to_csv(args.out / "subscriptions.csv", index=False)
    usage.to_csv(args.out / "daily_usage.csv", index=False)
    truth.to_csv(args.out / "_hidden" / "truth.csv", index=False)

    print_summary(subscribers, truth, usage, rech, subs)
    print(f"\nFiles written to {args.out.resolve()}")


if __name__ == "__main__":
    main()
