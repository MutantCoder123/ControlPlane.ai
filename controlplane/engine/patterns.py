"""Structured-secret tier - TRACK A owns this.

Pattern PLUS checksum, never pattern alone (IDEATION section 9.1). Luhn for
cards, Verhoeff for Aadhaar, mod-97 for IBAN. Without the checksum every long
order number looks like a card and we drown the user in false positives -
which is exactly the alert fatigue the Round 2 brief calls out.

Credentials -> block. Customer/employee PII -> substitute (IDEATION 9.5).

D10: this tier is a prototype stand-in for a real NER model. It catches
unstructured PII only when the value is in the known-value store. Stated
openly rather than hidden.
"""

# TODO(Track A): see TRACK-A.md step 3.
