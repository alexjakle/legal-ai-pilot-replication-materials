You maintain the firm's knowledge stores. Below are the client stores, with each client's items listed under the client's name. Write firm-level patterns: items for a store that is available across all clients. Include a pattern only if at least ${k} different clients contribute to it, and list the ids of the items that contribute. Do not copy an item that comes from a single client.

You may give eligibility tags for a pattern: strings of the form "wall:<matter>", for matters that must not see it under the wall rules below. Use [] if there are none.

Wall rules:
${walls}

Client stores:
${stores}

Reply with JSON only, no other text:
{"patterns": [{"text": "...", "contributing_items": ["id", "id"], "tags": []}]}
