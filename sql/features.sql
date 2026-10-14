\timing on

DROP TABLE IF EXISTS cutoffs;
CREATE TEMP TABLE cutoffs AS
SELECT d::date AS cutoff_date
FROM (VALUES ('2026-03-31'), ('2026-04-30'), ('2026-05-31'),
             ('2026-06-30'), ('2026-07-31'), ('2026-08-31')) AS t(d);


DROP TABLE IF EXISTS population;
CREATE TEMP TABLE population AS
SELECT DISTINCT c.cutoff_date, a.subscriber_id
FROM cutoffs c
JOIN (
    SELECT subscriber_id, usage_date AS activity_date FROM daily_usage
    UNION ALL
    SELECT subscriber_id, recharge_date FROM recharges
) a ON a.activity_date BETWEEN c.cutoff_date - 29 AND c.cutoff_date;

ALTER TABLE population ADD PRIMARY KEY (cutoff_date, subscriber_id);
ANALYZE population;

DROP TABLE IF EXISTS f_recharge;
CREATE TEMP TABLE f_recharge AS
SELECT p.cutoff_date, p.subscriber_id,
    COUNT(*) FILTER (WHERE r.recharge_date > p.cutoff_date - 7)   AS recharges_7d,
    COUNT(*) FILTER (WHERE r.recharge_date > p.cutoff_date - 30)  AS recharges_30d,
    COUNT(*) FILTER (WHERE r.recharge_date >  p.cutoff_date - 60
                       AND r.recharge_date <= p.cutoff_date - 30) AS recharges_prev_30d,
    COUNT(r.recharge_id)                                          AS recharges_90d,
    COALESCE(SUM(r.amount_dzd) FILTER (WHERE r.recharge_date > p.cutoff_date - 30), 0)
                                                                  AS recharge_dzd_30d,
    COALESCE(SUM(r.amount_dzd), 0)                                AS recharge_dzd_90d,
    p.cutoff_date - MAX(r.recharge_date)                          AS days_since_last_recharge,
    AVG(r.amount_dzd)                                             AS avg_recharge_dzd_90d,
    AVG((r.channel = 'mobile_app')::int)                          AS share_app_recharges_90d
FROM population p
LEFT JOIN recharges r
       ON r.subscriber_id = p.subscriber_id
      AND r.recharge_date >  p.cutoff_date - 90
      AND r.recharge_date <= p.cutoff_date          -- never after the cutoff
GROUP BY p.cutoff_date, p.subscriber_id;

ALTER TABLE f_recharge ADD PRIMARY KEY (cutoff_date, subscriber_id);



DROP TABLE IF EXISTS f_gaps;
CREATE TEMP TABLE f_gaps AS
WITH gaps AS (
    SELECT p.cutoff_date, p.subscriber_id,
           r.recharge_date - LAG(r.recharge_date) OVER (
               PARTITION BY p.cutoff_date, p.subscriber_id
               ORDER BY r.recharge_date
           ) AS gap_days
    FROM population p
    JOIN recharges r
      ON r.subscriber_id = p.subscriber_id
     AND r.recharge_date >  p.cutoff_date - 90
     AND r.recharge_date <= p.cutoff_date
)
SELECT cutoff_date, subscriber_id,
       AVG(gap_days)    AS avg_gap_days_90d,
       MAX(gap_days)    AS max_gap_days_90d,
       STDDEV(gap_days) AS std_gap_days_90d
FROM gaps
WHERE gap_days IS NOT NULL          -- the first recharge has no previous one
GROUP BY cutoff_date, subscriber_id;

ALTER TABLE f_gaps ADD PRIMARY KEY (cutoff_date, subscriber_id);


DROP TABLE IF EXISTS f_usage;
CREATE TEMP TABLE f_usage AS
SELECT p.cutoff_date, p.subscriber_id,
    COUNT(u.usage_date) FILTER (WHERE u.usage_date > p.cutoff_date - 7)   AS active_days_7d,
    COUNT(u.usage_date) FILTER (WHERE u.usage_date > p.cutoff_date - 30)  AS active_days_30d,
    COUNT(u.usage_date) FILTER (WHERE u.usage_date >  p.cutoff_date - 60
                                  AND u.usage_date <= p.cutoff_date - 30) AS active_days_prev_30d,
    COALESCE(SUM(u.data_mb)       FILTER (WHERE u.usage_date > p.cutoff_date - 30), 0) AS data_mb_30d,
    COALESCE(SUM(u.data_mb)       FILTER (WHERE u.usage_date >  p.cutoff_date - 60
                                            AND u.usage_date <= p.cutoff_date - 30), 0) AS data_mb_prev_30d,
    COALESCE(SUM(u.call_minutes)  FILTER (WHERE u.usage_date > p.cutoff_date - 30), 0) AS call_min_30d,
    COALESCE(SUM(u.call_minutes)  FILTER (WHERE u.usage_date >  p.cutoff_date - 60
                                            AND u.usage_date <= p.cutoff_date - 30), 0) AS call_min_prev_30d,
    COALESCE(SUM(u.sms_count)     FILTER (WHERE u.usage_date > p.cutoff_date - 30), 0) AS sms_30d,
    COALESCE(SUM(u.data_mb_night) FILTER (WHERE u.usage_date > p.cutoff_date - 30), 0) AS data_mb_night_30d,
    COALESCE(SUM(u.dropped_calls), 0)                                     AS dropped_calls_90d,
    COALESCE(SUM(u.call_minutes), 0)                                      AS call_min_90d,
    p.cutoff_date - MAX(u.usage_date)                                     AS days_since_last_usage
FROM population p
LEFT JOIN daily_usage u
       ON u.subscriber_id = p.subscriber_id
      AND u.usage_date >  p.cutoff_date - 90
      AND u.usage_date <= p.cutoff_date
GROUP BY p.cutoff_date, p.subscriber_id;

ALTER TABLE f_usage ADD PRIMARY KEY (cutoff_date, subscriber_id);


DROP TABLE IF EXISTS f_offers;
CREATE TEMP TABLE f_offers AS
SELECT p.cutoff_date, p.subscriber_id,
    COUNT(sb.subscription_id)                                     AS offers_90d,
    COUNT(DISTINCT sb.offer_id)                                   AS distinct_offers_90d,
    COUNT(*) FILTER (WHERE sb.purchase_date > p.cutoff_date - 30) AS offers_30d,
    COALESCE(MAX((sb.expiry_date > p.cutoff_date)::int), 0)      AS has_active_offer,
    p.cutoff_date - MAX(sb.purchase_date)                         AS days_since_last_offer
FROM population p
LEFT JOIN subscriptions sb
       ON sb.subscriber_id = p.subscriber_id
      AND sb.purchase_date >  p.cutoff_date - 90
      AND sb.purchase_date <= p.cutoff_date
GROUP BY p.cutoff_date, p.subscriber_id;

ALTER TABLE f_offers ADD PRIMARY KEY (cutoff_date, subscriber_id);

ANALYZE f_recharge; ANALYZE f_gaps; ANALYZE f_usage; ANALYZE f_offers;


DROP TABLE IF EXISTS churn_features;
CREATE TABLE churn_features AS
SELECT
    p.cutoff_date,
    p.subscriber_id,

    -- profile (known at signup, never changes)
    s.plan, s.wilaya, s.age_band,
    p.cutoff_date - s.signup_date                                 AS tenure_days,

    -- recharges
    rf.recharges_7d, rf.recharges_30d, rf.recharges_prev_30d, rf.recharges_90d,
    rf.recharge_dzd_30d, rf.recharge_dzd_90d,
    ROUND(rf.avg_recharge_dzd_90d, 1)                             AS avg_recharge_dzd_90d,
    rf.days_since_last_recharge,
    ROUND(rf.share_app_recharges_90d, 3)                          AS share_app_recharges_90d,
    ROUND((rf.recharges_30d + 1.0) / (rf.recharges_prev_30d + 1), 3) AS recharge_trend,

    -- gaps between recharges
    ROUND(g.avg_gap_days_90d, 2)                                  AS avg_gap_days_90d,
    g.max_gap_days_90d,
    ROUND(g.std_gap_days_90d, 2)                                  AS std_gap_days_90d,
    -- "how late is the customer compared with their own habit?" (> 1 = late)
    ROUND(rf.days_since_last_recharge / NULLIF(g.avg_gap_days_90d, 0), 2) AS recharge_lateness,

    -- usage
    uf.active_days_7d, uf.active_days_30d, uf.active_days_prev_30d,
    uf.days_since_last_usage,
    ROUND(uf.data_mb_30d, 1)                                      AS data_mb_30d,
    ROUND(uf.call_min_30d, 1)                                     AS call_min_30d,
    uf.sms_30d,
    ROUND((uf.data_mb_30d + 1)  / (uf.data_mb_prev_30d + 1), 3)   AS data_trend,
    ROUND((uf.call_min_30d + 1) / (uf.call_min_prev_30d + 1), 3)  AS calls_trend,
    ROUND((uf.active_days_30d + 1.0) / (uf.active_days_prev_30d + 1), 3) AS active_days_trend,
    ROUND(uf.data_mb_night_30d / NULLIF(uf.data_mb_30d, 0), 3)    AS night_data_share_30d,

    -- network quality as the customer experiences it
    uf.dropped_calls_90d,
    ROUND(uf.dropped_calls_90d / NULLIF(uf.call_min_90d, 0) * 100, 3) AS dropped_per_100_min_90d,

    -- offers
    o.offers_30d, o.offers_90d, o.distinct_offers_90d,
    o.has_active_offer, o.days_since_last_offer

FROM population p
JOIN subscribers s   ON s.subscriber_id = p.subscriber_id
JOIN f_recharge  rf  ON rf.cutoff_date = p.cutoff_date AND rf.subscriber_id = p.subscriber_id
JOIN f_usage     uf  ON uf.cutoff_date = p.cutoff_date AND uf.subscriber_id = p.subscriber_id
JOIN f_offers    o   ON o.cutoff_date  = p.cutoff_date AND o.subscriber_id  = p.subscriber_id
LEFT JOIN f_gaps g   ON g.cutoff_date  = p.cutoff_date AND g.subscriber_id  = p.subscriber_id;

ALTER TABLE churn_features ADD PRIMARY KEY (cutoff_date, subscriber_id);



-- How many customers are scored at each cutoff?
SELECT cutoff_date, COUNT(*) AS customers
FROM churn_features
GROUP BY cutoff_date
ORDER BY cutoff_date;

-- Leakage check: nothing in the table can come from the future.
-- Both numbers must be 0.
SELECT COUNT(*) FILTER (WHERE days_since_last_recharge < 0) AS future_recharges,
       COUNT(*) FILTER (WHERE days_since_last_usage    < 0) AS future_usage
FROM churn_features;

-- What a typical customer looks like at the last cutoff
SELECT ROUND(AVG(recharges_30d), 2)     AS avg_recharges_30d,
       ROUND(AVG(active_days_30d), 1)   AS avg_active_days_30d,
       ROUND(AVG(data_mb_30d))          AS avg_data_mb_30d,
       ROUND(AVG(recharge_lateness), 2) AS avg_recharge_lateness,
       ROUND(AVG(has_active_offer), 2)  AS share_with_active_offer
FROM churn_features
WHERE cutoff_date = '2026-08-31';

