SELECT
    user_id,
    clicks / NULLIF(views, 0) AS ctr
FROM metrics;
