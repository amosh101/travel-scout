#!/bin/bash
# Seed a concierge-customer fixture + real-thread data through the live API.
# Secrets come from files; nothing is echoed.
set -euo pipefail
API=http://100.91.143.50:8000
STAGE=/root/.hermes/workspace/projects/travel-scout/.audits

pw_super=$(cat /tmp/fx_pw | tr -d '\n')
pw_cust="concierge-fixture-2026-pass"

# 1) login as superadmin (token -> file, never printed)
curl -s -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\": \"superadmin@travel-scout-audit.local\", \"password\": \"$pw_super\"}" \
  -o "$STAGE/.tok_super.json"
TOK_SUPER=$(python3 -c "import json;print(json.load(open('$STAGE/.tok_super.json'))['access_token'])")

# 2) create the concierge customer (public register + tier patch by super)
CODE=$(curl -s -o /tmp/reg.json -w '%{http_code}' -X POST "$API/api/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\": \"concierge@travel-scout-audit.local\", \"password\": \"$pw_cust\", \"name\": \"Fixture Concierge\"}")
if [ "$CODE" != "201" ] && [ "$CODE" != "409" ]; then echo "register failed: $CODE"; cat /dev/stdin < /tmp/reg.json; exit 1; fi
UID_=$(curl -s "$API/api/admin/users?limit=200" -H "Authorization: Bearer $TOK_SUPER" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print([u['id'] for u in d['items'] if u['email']=='concierge@travel-scout-audit.local'][0])")
curl -s -X PATCH "$API/api/admin/users/$UID_" -H "Authorization: Bearer $TOK_SUPER" -H 'Content-Type: application/json' \
  -d '{"tier": "concierge"}' -o /tmp/patch.json
python3 -c "import json;d=json.load(open('/tmp/patch.json'));assert d.get('tier')=='concierge',d"
echo "concierge fixture ready (masked id ${UID_:0:6}...)"

# 3) login as the customer (token -> file)
curl -s -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\": \"concierge@travel-scout-audit.local\", \"password\": \"$pw_cust\"}" \
  -o "$STAGE/.tok_cust.json"
TOK_CUST=$(python3 -c "import json;print(json.load(open('$STAGE/.tok_cust.json'))['access_token'])")

# 4) REAL discover -> save result #1 as the customer's itinerary
curl -s -m 120 "$API/api/itineraries/discover?origin=Maputo&destination=London&interests=jazz,food-wine&date_from=2026-11-01&date_to=2026-11-12&top_n=1" \
  -H "Authorization: Bearer $TOK_CUST" -o /tmp/disc.json
python3 - <<'EOF'
import json
d = json.load(open('/tmp/disc.json'))
r = d['results'][0]
ev = r.get('interest_events') or []
hol = r.get('holiday_alerts') or []
out = {
  "title": f"London — {r.get('start_date')} → {r.get('end_date')}",
  "starts_at": (r.get('start_date') or r.get('date_from')) + 'T00:00:00Z',
  "ends_at": (r.get('end_date') or r.get('date_to')) + 'T00:00:00Z',
  "destination_country": r.get('destination_country'),
  "destination_name": r.get('destination') or r.get('destination_name'),
  "interests": ["jazz", "food-wine"],
  "anchor_event_ids": [(x.get('id') or str(x.get('round') or x.get('name'))) for x in (r.get('races_in_window') or [])[:2] if isinstance(x, dict)],
  "suggested_event_ids": [(x.get('id') or f"nager:{x.get('date')}:{x.get('name')}") for x in hol[:6] if isinstance(x, dict)],
  "search_params": {"origin": "Maputo", "date_from": "2026-11-01", "date_to": "2026-11-12"},
  "candidates": [r],
  "notes": "\n".join(r.get('missing') or [])[:1000],
  "origin": "Maputo",
  "origin_iata": r.get('origin_iata'),
  "destination_iata": r.get('destination_iata'),
  "destination_country_alpha2": r.get('destination_country_alpha2') or "GB",
  "anchor_events": r.get('races_in_window') or [],
  "suggested_events": hol,
  "event_window": r.get('event_window'),
  "flights": [],
  "hotels": r.get('hotels') or [],
  "route": r.get('route'),
  "pitch": [r.get('pitch') or "London in the jazz-and-food season"],
  "score": r.get('score'),
  "sources_used": r.get('sources') or [],
  "currency": "USD",
  "total_price_cents": 0,
}
json.dump(out, open('/tmp/save_body.json', 'w'))
print("save body built: events:", len(out['anchor_event_ids']), "holidays:", len(hol))
EOF
curl -s -X POST "$API/api/itineraries" -H "Authorization: Bearer $TOK_CUST" -H 'Content-Type: application/json' \
  -d @/tmp/save_body.json -o /tmp/saved.json
python3 -c "
import json
d = json.load(open('/tmp/saved.json'))
assert 'id' in d, d
print('saved itinerary id masked:', d['id'][:6], '...')
open('/tmp/saved_id.txt','w').write(d['id'])
"

# 5) hand off + chat message (customer side, real APIs)
SID=$(cat /tmp/saved_id.txt)
curl -s -X POST "$API/api/agent/queue" -H "Authorization: Bearer $TOK_CUST" -H 'Content-Type: application/json' \
  -d "{\"itinerary_id\": \"$SID\", \"note\": \"Two of us, window seat if possible; ask me about the jazz clubs before booking.\"}" \
  -o /tmp/handoff.json
python3 -c "import json;d=json.load(open('/tmp/handoff.json'));print('handoff:', d.get('status'), '-', d.get('message'))"
curl -s -X POST "$API/api/messages" -H "Authorization: Bearer $TOK_CUST" -H 'Content-Type: application/json' \
  -d "{\"itinerary_id\": \"$SID\", \"body\": \"Hi — we'd like the jazz nights plus a food itinerary. Our dates are flexible by a day either side.\"}" \
  -o /tmp/msg1.json
python3 -c "import json;d=json.load(open('/tmp/msg1.json'));print('customer message posted:', d.get('sender_role'))"

# 6) agent replies (agent fixture token)
curl -s -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"email": "agent@travel-scout-audit.local", "password": "agent-fixture-2026-pass"}' \
  -o "$STAGE/.tok_agent.json"
TOK_AGENT=$(python3 -c "import json;print(json.load(open('$STAGE/.tok_agent.json'))['access_token'])")
curl -s "$API/api/messages/threads?limit=10" -H "Authorization: Bearer $TOK_AGENT" -o /tmp/threads.json
python3 -c "
import json
d = json.load(open('/tmp/threads.json'))
print('agent thread list total:', d['total'])
for t in d['items'][:3]:
    print('  -', (t['itinerary_title'] or '?')[:28], '| count', t['message_count'], '| last by', t['last_sender_role'], '| hand-off', t['queue_status'])
"
curl -s -X POST "$API/api/messages" -H "Authorization: Bearer $TOK_AGENT" -H 'Content-Type: application/json' \
  -d "{\"itinerary_id\": \"$SID\", \"body\": \"Thanks! I can hold 4 November for the jazz night at Ronnie Scott's and a table at St John — shall I confirm?\"}" \
  -o /tmp/msg2.json
python3 -c "import json;d=json.load(open('/tmp/msg2.json'));print('agent message posted:', d.get('sender_role'))"

# 6b) agent-side: claim -> record CUSTOMER payment (off-platform) -> outcome.
# The queue dedupe returns the EXISTING open row for this itinerary; claim it.
curl -s "$API/api/agent/queue?status=pending&limit=10" -H "Authorization: Bearer $TOK_AGENT" -o /tmp/q2.json
QID2=$(python3 -c "import json;d=json.load(open('/tmp/q2.json'));items=[i for i in d['items'] if i.get('itinerary_id')=='$SID'];print(items[0]['id'] if items else '')")
if [ -n "$QID2" ]; then
  curl -s -X POST "$API/api/agent/queue/$QID2/claim" -H "Authorization: Bearer $TOK_AGENT" -o /tmp/claim2.json
  python3 -c "import json;print('claim:', json.load(open('/tmp/claim2.json')).get('status'))"
  curl -s -X POST "$API/api/agent/queue/$QID2/payment" -H "Authorization: Bearer $TOK_AGENT" -H 'Content-Type: application/json' \
    -d '{"amount_cents": 125000, "currency": "GBP", "commission_cents": 12500, "method": "bank transfer", "note": "Deposit received from customer."}' \
    -o /tmp/payment.json
  python3 -c "import json;d=json.load(open('/tmp/payment.json'));print('payment:', d.get('payment_status'), '| row status:', d.get('status'), '| delivery:', json.dumps((d.get('metadata') or {}).get('delivery') or {}))"
  curl -s -X POST "$API/api/agent/queue/$QID2/outcome" -H "Authorization: Bearer $TOK_AGENT" -H 'Content-Type: application/json' \
    -d '{"status": "confirmed", "amount_cents": 125000, "currency": "GBP", "external_id": "RS-JAZZ-4NOV-2PAX", "commission_cents": 12500, "note": "Ronnie Scotts 4 Nov x2 + St John. E-tickets emailed."}' \
    -o /tmp/outcome.json
  python3 -c "import json;d=json.load(open('/tmp/outcome.json'));print('outcome:', d.get('status'), '| payment:', d.get('payment_status'), '| commission:', d.get('commission_cents'))"
fi

echo "SEEDING COMPLETE"