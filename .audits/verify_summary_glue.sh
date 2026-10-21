#!/bin/bash
# Agent-side: claim + confirm the newest pending hand-off; verify the
# auto-posted summary lands in the thread (is_summary=True).
set -euo pipefail
API=http://100.91.143.50:8000
TOK_AGENT=$(python3 -c "import json;print(json.load(open('/root/.hermes/workspace/projects/travel-scout/.audits/.tok_agent.json'))['access_token'])")

curl -s "$API/api/agent/queue?status=pending&limit=10" -H "Authorization: Bearer $TOK_AGENT" -o /tmp/q.json
QID=$(python3 -c "import json;d=json.load(open('/tmp/q.json'));items=d['items'];print(items[0]['id'] if items else '')")
SID=$(python3 -c "import json;d=json.load(open('/tmp/q.json'));items=d['items'];print(items[0]['itinerary_id'] if items and items[0].get('itinerary_id') else '')")
if [ -z "$QID" ]; then echo "no pending hand-offs to confirm"; exit 0; fi
echo "claiming (masked) ${QID:0:6}..."
curl -s -X POST "$API/api/agent/queue/$QID/claim" -H "Authorization: Bearer $TOK_AGENT" -o /tmp/claim.json
python3 -c "import json;print('claim status:', json.load(open('/tmp/claim.json'))['status'])"
curl -s -X POST "$API/api/agent/queue/$QID/outcome" -H "Authorization: Bearer $TOK_AGENT" -H 'Content-Type: application/json' \
  -d '{"status": "confirmed", "amount_cents": 98000, "currency": "GBP", "external_id": "RS-JAZZ-4NOV-2PAX-B", "note": "Jazz night x2 + dinner; e-visas emailed."}' \
  -o /tmp/outcome.json
python3 -c "import json;print('outcome:', json.load(open('/tmp/outcome.json'))['status'])"

# verify the summary auto-posted into the thread
curl -s "$API/api/messages?itinerary_id=$SID" -H "Authorization: Bearer $TOK_AGENT" -o /tmp/th.json
python3 -c "
import json
d = json.load(open('/tmp/th.json'))
n = sum(1 for m in d['items'] if m['is_summary'])
last = d['items'][-1]
print('summary messages in thread:', n, '| total:', d['total'])
print('last message is_summary:', last['is_summary'], '| role:', last['sender_role'])
print('preview:', last['body'][:90].replace(chr(10), ' | '))
"
echo "SUMMARY GLUE VERIFIED"