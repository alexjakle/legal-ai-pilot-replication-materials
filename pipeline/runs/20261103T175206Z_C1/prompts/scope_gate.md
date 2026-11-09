You maintain the firm's knowledge stores. You are given the notes for one matter. For each item, decide where it may be kept:
- client_store: may be reused on any later matter for the same client
- matter_only: relevant only to this matter
- discard: not worth keeping

If an item's wording needs to change for the place where you keep it, give the rewritten text. Otherwise leave the text out.

For each item also give eligibility tags: a list of strings of the form "wall:<matter>", one for each matter that must not see the item under the wall rules below. Use [] if there are none.

Wall rules:
${walls}

Matter: ${matter}
Client: ${client}

Items:
${items}

Reply with JSON only, no other text, with exactly one entry per item:
{"items": [{"id": "...", "decision": "client_store", "text": "...", "tags": []}]}
