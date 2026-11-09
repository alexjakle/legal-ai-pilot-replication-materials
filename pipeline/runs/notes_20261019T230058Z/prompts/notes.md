You are a legal assistant at a law firm. Below are the four documents for one matter. Write the matter notes: a numbered list of short items that a lawyer at the firm could consult later without opening the documents.

Each item has a type:
- fact: something established in the documents
- position: a stance taken by a party or by the firm
- lesson: something the team learned or would do differently

Write each item so that it makes sense on its own. Do not add anything that is not in the documents. Use as many items as the documents warrant.

Matter: ${matter}
Client: ${client}

${documents}

Reply with JSON only, no other text, in this form:
{"items": [{"type": "fact", "text": "..."}, {"type": "position", "text": "..."}]}
