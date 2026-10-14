SELECT plan, COUNT(*) AS customers
FROM subscribers
GROUP BY plan
ORDER BY customers DESC;

SELECT wilaya, COUNT(*) AS customers
FROM subscribers
GROUP BY wilaya
ORDER BY customers DESC
LIMIT 5;

-- 2. Monthly active subscribers: a customer is "active" in a month if they

SELECT DATE_TRUNC('month', usage_date)::date AS month,
       COUNT(DISTINCT subscriber_id)        AS active_subscribers
FROM daily_usage
GROUP BY 1
ORDER BY 1;

-- 3. Recharge revenue per month, in DZD

SELECT DATE_TRUNC('month', recharge_date)::date AS month,
       SUM(amount_dzd)                          AS recharge_dzd,
       ROUND(AVG(amount_dzd))                   AS avg_recharge_dzd
FROM recharges
GROUP BY 1
ORDER BY 1;

-- 4. Average days between recharges per customer (first window function!)
WITH gaps AS (
    SELECT subscriber_id,
           recharge_date - LAG(recharge_date) OVER (
               PARTITION BY subscriber_id ORDER BY recharge_date
           ) AS days_since_previous
    FROM recharges
)
SELECT ROUND(AVG(days_since_previous), 1)                                      AS avg_gap_days,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_since_previous)       AS median_gap_days
FROM gaps
WHERE days_since_previous IS NOT NULL;

-- 5. Customers silent for the last 30 days of the data (rough churn count)
SELECT COUNT(*) AS silent_last_30_days
FROM subscribers s
WHERE NOT EXISTS (
    SELECT 1 FROM daily_usage u
    WHERE u.subscriber_id = s.subscriber_id
      AND u.usage_date > DATE '2026-09-30' - 30
);

-- 6. Most bought offers and the revenue they bring
SELECT o.name, COUNT(*) AS purchases, SUM(sb.price_dzd) AS revenue_dzd
FROM subscriptions sb
JOIN offers o USING (offer_id)
GROUP BY o.name
ORDER BY revenue_dzd DESC;

-- 7. Integrity: no usage before signup, no expiry before purchase (both must be 0)
SELECT COUNT(*) AS usage_before_signup
FROM daily_usage u JOIN subscribers s USING (subscriber_id)
WHERE u.usage_date < s.signup_date;

SELECT COUNT(*) AS bad_expiry
FROM subscriptions
WHERE expiry_date < purchase_date;
