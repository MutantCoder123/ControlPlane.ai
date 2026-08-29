# ControlPlane.ai — Implementation Strategy

> **Status note (2026-08-29):** this document predates the route-profile model
> (IDEATION §5), the Round 2 brief, and the drawback triage. It remains useful
> as *approach trade-off analysis per technique* — which method to pick and why.
> For **what to build, in what order, and which drawback each part owns**, see
> [BUILD-PLAN.md](BUILD-PLAN.md).

This document details the technical implementation roadmap for the ControlPlane.ai gateway. It maps the architectural principles and presentation vision to concrete execution approaches, highlighting the pros, cons, and strategic tradeoffs for each.

---

## Step 1: The Stateless Gateway
**Objective:** Create a seamless interceptor where the enterprise application only changes its `base_url`. It must remain completely stateless.

### Approach A: Application-Layer Reverse Proxy (Python/FastAPI or Go)
*   **Implementation:** Build a web server that accepts standard LLM JSON payloads, processes them entirely in-memory, and uses an asynchronous HTTP client to forward requests upstream.
*   **Pros:** Extreme development velocity; easiest to hack together rapidly; trivial to integrate custom Python logic for buffering and LLM calls.
*   **Cons:** Higher baseline latency compared to compiled network proxies. Python’s Global Interpreter Lock (GIL) can bottleneck high-concurrency streaming.
*   **Tradeoff:** For a prototype or hackathon, this is the winning approach. The slight latency hit is negligible, and the iteration speed is unmatched.

### Approach B: Service-Mesh Sidecar (Envoy with `ext_proc`)
*   **Implementation:** Deploy Envoy proxy and use the External Processing (`ext_proc`) filter via gRPC to call out to a custom C++ or Rust mutation server on the hot path.
*   **Pros:** Enterprise-grade architecture; zero added network hops if run as a sidecar; written in C++ for absolute minimum latency overhead.
*   **Cons:** Overkill for a prototype. Setting up Envoy configurations, gRPC contracts, and compiling C++ filters will consume time better spent on the dashboard and demo loop.
*   **Tradeoff:** Excellent to mention as the "Production Architecture" roadmap, but avoid building it for the initial demo.

---

## Step 2: The Commit-Point Buffer
**Objective:** Solve the TOCTOU (Time-of-Check to Time-of-Use) problem by pausing the stream for ~250ms to scan for screen-recordable secrets before releasing them to the user's browser.

### Approach A: Strict Token/Time Chunking with Overlap Window
*   **Implementation:** Accumulate Server-Sent Events (SSE) from the LLM. Flush the buffer to the user when it hits exactly 40 tokens or 250ms. Maintain a trailing 50-character string from the previous chunk to scan against split secrets.
*   **Pros:** Highly deterministic; guarantees the LLM never stalls the stream indefinitely.
*   **Cons:** Can break mid-word or mid-sentence, which might look visually jarring to the user if the UI is rendering markdown dynamically.

### Approach B: Semantic Boundary Lexer
*   **Implementation:** Buffer the stream until you hit a natural punctuation mark (e.g., `.`, `?`, `!`, or `\n`).
*   **Pros:** Visually imperceptible to the user; sentences appear in natural chunks.
*   **Cons:** If the LLM generates a massive run-on sentence or a block of code, the buffer could swell, causing a noticeable perceived latency spike.
*   **Tradeoff:** Use a hybrid state machine: trigger the release on a semantic boundary, but enforce a hard time-out (e.g., 300ms) to flush the buffer forcefully if no punctuation arrives.

---

## Step 3: Pre-Flight Gate & Cost Control
**Objective:** Block expensive or redundant requests *before* dispatching them to the LLM to save compute and API costs.

### Approach A: In-Memory Prefix Hashing (Exact Match)
*   **Implementation:** Hash the inbound prompt string and check it against an in-memory dictionary of recently answered queries within the same tenant boundary.
*   **Pros:** Computationally practically free; zero latency overhead.
*   **Cons:** Fails immediately if the user adds a single extra space or typo to an identical question.

### Approach B: Local Vector Semantic Caching
*   **Implementation:** Run a highly optimized, lightweight embedding model locally to vectorize the incoming prompt. Compare the cosine distance against a cache vector database (like FAISS or Qdrant).
*   **Pros:** Catches variations of the same question ("What is my leave balance?" vs. "How much PTO do I have left?").
*   **Cons:** Embedding extraction costs TTFB (Time to First Byte); false positives can be catastrophic if tenant boundaries are breached.
*   **Tradeoff:** Build Approach A for the demo to show instantaneous cache hits, and explain how you would configure provider-level prompt caching (Approach B) in production to avoid local overhead.

---

## Step 4: Data Substitution & Known-Value Matching
**Objective:** Substitute internal PII and credentials deterministically without relying solely on destructive regex masking.

### Approach A: Bloom Filter + Fake CRM Seed
*   **Implementation:** Load a mock CSV of employee names and internal IDs into an in-memory Bloom filter. When a request comes in, tokenize the text and check the filter. If a match hits, swap "Priya" for `[USER_A]`. Store the mapping in a dictionary scoped to the request ID.
*   **Pros:** Deterministic; doesn't break arithmetic; bypasses the flaws of probabilistic NER models.
*   **Cons:** Only works for exact string matches. Normalization (handling "Priya" vs "priya") adds slight complexity.
*   **Tradeoff:** This is the absolute strongest demo you can build. Proving you can swap a real record deterministically without the model ever seeing it is a massive differentiator.

### Approach B: Local Small Language Model (SLM) for NER
*   **Implementation:** Use a local, fast model like GLiNER to identify unstructured entities before dispatch.
*   **Pros:** Catches unknown entities (e.g., a customer name not in the database).
*   **Cons:** Non-deterministic, prone to false positives, and adds heavy latency to the synchronous pre-flight path.
*   **Tradeoff:** Stick to Approach A for reliable, high-speed substitution.

---

## Step 5: Hallucination Cascade
**Objective:** Route claims based on how they fail to determine if the model actually knows the information or is improvising.

### Approach A: The Tiered Cascade (Recommended)
*   **Implementation:**
    *   *Tier 0:* Run a fast regex check for point facts (dates, numbers). If none exist, skip checking.
    *   *Tier 1:* If point facts exist, trigger an asynchronous background LLM call asking it to extract and verify *just* that fact (Consistency Sampling).
*   **Pros:** Costs scale with risk, not volume. You don't pay for verification on casual queries.
*   **Cons:** Requires managing background async tasks that might complete *after* the user has finished reading the stream.
*   **Tradeoff:** Implement the Tier 0 regex filter to prove the routing concept. For the demo, trigger a deliberate failure on a fake citation to show the UI annotation updating live.

---

## Step 6: Counterfactual Bias Probing
**Objective:** Measure outcome distribution without masking demographic terms.

### Approach A: Async Shadow Execution
*   **Implementation:** Write a background script that takes a sampled subset of production requests, swaps the demographic attribute (e.g., changes "Jane" to "John"), re-runs the request against the LLM, and compares the outcomes.
*   **Pros:** Measures actual algorithmic bias objectively rather than relying on flawed "fairness through unawareness" masking techniques.
*   **Cons:** Consumes additional API tokens for the background sampling.
*   **Tradeoff:** Real-time bias masking fails structurally. Do not attempt to build a real-time rewriter. Build a clean UI dashboard showing the aggregate divergence metrics of the shadow executions to prove the concept.
