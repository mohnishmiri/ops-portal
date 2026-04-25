# Amortized sync notes

- 2026-04-10: Azure Cost Details `generateCostDetailsReport` requests can fail with HTTP 400 when the requested `timePeriod` crosses calendar-month boundaries. Keep amortized sync query windows within a single month even when the dashboard asks for multiple months.
- 2026-04-10: `CostService` now surfaces Azure Cost Details error bodies, retry-after hints, and request/correlation IDs in runtime errors and logs for create/poll/download failures.
