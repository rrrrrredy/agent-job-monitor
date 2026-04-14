# Data Schema

## snapshots/{date}.json

```json
{
  "date": "2026-04-10",
  "collected_at": "2026-04-10T18:00:00+08:00",
  "companies": {
    "Tencent": {
      "total": 135,
      "jobs": [...]
    }
  },
  "total": 207,
  "jobs": [
    {
      "id": "Tencent:Researcher- Agent:51f92961",
      "company": "Tencent",
      "title": "Researcher- Agent",
      "department": "TEG",
      "location": "Shenzhen",
      "match_tier": "L1",
      "match_reason": "title:Agent"
    }
  ],
  "errors": []
}
```

## diffs/{date}-diff.json

```json
{
  "date": "2026-04-10",
  "yesterday": "2026-04-09",
  "first_run": false,
  "new_jobs": [...],
  "removed_jobs": [...],
  "unchanged_count": 134,
  "today_total": 207,
  "yesterday_total": 135,
  "summary": "New 73, removed 1, unchanged 134"
}
```

## Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| id | string | `Company:Title:location_hash(md5 first 8 chars)`; MiniMax Feishu jobs have no `job_id`, fallback to `url` field as unique key (format differs from other companies) |
| company | string | Company name |
| title | string | Job title (original, untrimmed) |
| department | string | Department/BU (Tencent has it, ByteDance usually empty) |
| location | string | City (ByteDance some jobs are empty) |
| match_tier | string | L1 (title match) / L2 (JD match, future version) |
| match_reason | string | Specific keyword that matched |
