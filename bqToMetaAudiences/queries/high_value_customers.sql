-- Any query works as long as its output columns match the `columns` mapping
-- in config.yaml. Parameters (@min_ltv) come from the audience's `params`.
SELECT
  email,
  phone,
  first_name,
  last_name,
  city,
  state,
  postal_code,
  country_code,
  birth_date,          -- DATE; expanded into DOBY/DOBM/DOBD
  CAST(customer_id AS STRING) AS customer_id
FROM `my-gcp-project.crm.customers`
WHERE lifetime_value >= @min_ltv
  AND marketing_opt_in = TRUE
