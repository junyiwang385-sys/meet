# Runtime adapters

`adapters/` contains the current Board and Windows Gateway service code extracted from the former `scripts/` entrypoints.

- `board/`: Board Agent, cancellable Harness Worker, ASR/minutes tools and smoke entrypoints.
- `gateway/`: Windows Gateway, meeting library, settings, storage and result projection.

The old `scripts/board` and `scripts/pc` paths remain unchanged during the transition.
