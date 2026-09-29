# Memory diagnostics

Periodic bot reports retain process RSS, OS memory statistics, GC counts and object-type counts. Allocation tracing is disabled by default because it adds substantial work to every Python allocation and delays the shared Telegram/Mini App event loop.

For a bounded diagnostic session, set MEMORY_TRACING_ENABLED=1 in the server environment and restart through the normal deployment process. MEMORY_TRACING_FRAMES defaults to1; values are clamped to1..25, invalid values use1. Increasing traceback depth increases CPU and memory overhead. Remove the opt-in and restart when finished.

The JSON report exposes memory.tracemalloc.enabled and traceback_limit. With tracing disabled, allocation sizes are0 and top_allocations is empty; those zeros do not mean process memory usage is0. Use proc_status, smaps_rollup and resource_rusage for process memory. Periodic report generation does not silently turn tracing on. Tracing explicitly enabled by the Python runtime remains respected.
