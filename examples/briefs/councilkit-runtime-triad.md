# CouncilKit Runtime Triad Brief

Run a bounded judgment session on the `CouncilKit` repository using the local skills:

- `fastapi`
- `langgraph`
- `llama-index`

Focus on one concrete question:

If CouncilKit evolves beyond a minimal review runtime, how should it add stateful execution and data-aware retrieval boundaries without collapsing into a general-purpose agent platform?

Requirements:

- preserve replayability and explicit turn contracts
- distinguish runtime state from retrieval/data state
- identify one boundary that must remain separate
- surface one migration risk if workflows or durable execution are added
