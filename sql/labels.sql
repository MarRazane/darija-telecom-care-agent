\timing on


DROP TABLE IF EXISTS active_after;
CREATE TEMP TABLE active_after AS
SELECT DISTINCT f.cutoff_date, f.subscriber_id
FROM churn_features f
JOIN (
    SELECT subscriber_id, usage_date AS activity_date FROM daily_usage
    UNION ALL
    SELECT subscriber_id, recharge_date FROM recharges
) a ON a.subscriber_id = f.subscriber_id
   AND a.activity_date >  f.cutoff_date          -- strictly AFTER the cutoff
   AND a.activity_date <= f.cutoff_date + 30;

ALTER TABLE active_after ADD PRIMARY KEY (cutoff_date, subscriber_id);
ANALYZE active_after;

DROP TABLE IF EXISTS churn_labels;
CREATE TABLE churn_labels AS
SELECT f.cutoff_date,
       f.subscriber_id,
       (a.subscriber_id IS NULL)::int AS churned
FROM churn_features f
LEFT JOIN active_after a
       ON a.cutoff_date   = f.cutoff_date
      AND a.subscriber_id = f.subscriber_id;

ALTER TABLE churn_labels ADD PRIMARY KEY (cutoff_date, subscriber_id);


-- Same number of rows as churn_features? (must be 89,350)
SELECT (SELECT COUNT(*) FROM churn_labels)   AS labels,
       (SELECT COUNT(*) FROM churn_features) AS features;

-- Churn rate per cutoff
SELECT cutoff_date,
       COUNT(*)                      AS customers,
       SUM(churned)                  AS churners,
       ROUND(AVG(churned) * 100, 2)  AS churn_rate_pct
FROM churn_labels
GROUP BY cutoff_date
ORDER BY cutoff_date;