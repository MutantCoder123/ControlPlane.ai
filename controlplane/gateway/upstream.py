"""Provider client - TRACK B owns this.

Async HTTP to the real provider, behind a small interface so a fake can be
injected. The test suite must not require a live API key or network.

D3, stated honestly: "one line" is literal for OpenAI-compatible endpoints,
and a config block for Bedrock (SigV4) and Azure OpenAI (deployment names).
Build the OpenAI-compatible path; the other two are a README config concern.
Do not overclaim.
"""

# TODO(Track B): see TRACK-B.md part 2.
