"""Known-value store - TRACK A owns this.

"Is this OUR secret?" rather than "does this look like a secret?"
(IDEATION section 9.2). Hash every governed identifier, Bloom filter in front,
scan inbound text for those hashes.

Store hashes, NEVER raw values: if someone dumps our memory they must not get
a customer list, or we become the concentration risk we sell protection from.

D9: exact-match only. Normalisation buys case, whitespace and punctuation -
not misspellings, nicknames or transliteration. That is a stated limitation,
not a TODO. Production uses NER for the unknown-entity case.
"""

# TODO(Track A): see TRACK-A.md step 2.
