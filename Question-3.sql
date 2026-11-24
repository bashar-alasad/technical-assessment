WITH daily AS (
  SELECT
    model_name,
    created_at::date AS day,
    COUNT(*) AS n,
    SUM(CASE WHEN predicted = actual THEN 1 ELSE 0 END) AS correct,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency
  FROM inferences
  GROUP BY model_name, created_at::date
),

windowed AS (
  SELECT
    *,
    100.0 * correct / n AS acc_raw,
    100.0 * SUM(correct) OVER w7 / SUM(n) OVER w7 AS rolling_raw,
    LAG(100.0 * correct / n) OVER (PARTITION BY model_name ORDER BY day) AS prev_acc_raw
  FROM daily
  WINDOW w7 AS (
    PARTITION BY model_name
    ORDER BY day
    RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
  )
)

SELECT
  model_name,
  day,
  n,
  ROUND(acc_raw, 2) AS daily_acc,
  ROUND(rolling_raw, 2) AS rolling_acc_7d,
  ROUND(acc_raw - prev_acc_raw, 2) AS acc_delta,
  p95_latency,
  CASE WHEN acc_raw - prev_acc_raw < -10 THEN 1 ELSE 0 END AS drift_flag
FROM windowed
WHERE n >= 100
ORDER BY model_name, day;