"""FastAPI server - TRACK B owns this.

Routes:
  POST /v1/chat/completions   streaming and non-streaming
  POST /v1/embeddings         D2 - one extra route. A RAG rollout ships the
                              entire corpus through here at ingestion; a
                              chat-only proxy never sees the largest bulk
                              egress in the deployment.
  GET  /healthz

Wire-compatible with OpenAI: the test that matters is an unmodified `openai`
client with only base_url changed.
"""

# TODO(Track B): see TRACK-B.md part 2.
