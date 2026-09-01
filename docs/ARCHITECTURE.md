# Architecture

```text
Copilot hook
   |
   | POST /v1/copilot/events
   v
Collector API
   |
   v
Event store
   |
   +---- session/repository attribution telemetry
   |
   +---- Reconciler <---- GitHub billing API
   |                         |
   |                         +-- AI credit usage (authoritative credits)
   |                         +-- usage summary (repository-filterable)
   v
Allocations
   |
   +-- repository / user / day / credits / USD / confidence
   v
GET /v1/report
```

The reconciler imports the GitHub organization AI-credit report and optionally queries the repository-filterable billing usage summary for exact repository records. Where an exact repository billing record is not available, the service falls back to allocating authoritative organization credits across observed repository activity for the day. Fallback allocations are explicitly marked medium/low confidence.

The service never derives a billable AI-credit value from prompt length or tool counts.
