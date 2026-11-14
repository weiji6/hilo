# Example worker: indexing guide

This is synthetic documentation for the Hilo example worker, version 1.0.
The values below describe a fictional pipeline and are not Hilo runtime defaults.

## Ingestion and chunking

The example pipeline accepts UTF-8 Markdown documents. It splits text into
chunks of 800 characters with 100 characters of overlap. Each chunk retains
the document filename and its original heading so retrieved evidence can be
traced back to the source. A successful upload does not mean indexing is complete.

## Retrieval availability

New documents become searchable only after the indexing job reports success.
If indexing fails, the worker keeps the previous index available. It records
the failure and asks the operator to retry the indexing job after resolving
the underlying problem. It never presents an unindexed document as searchable.

## Missing information

This guide does not define throughput, latency, embedding dimensions, or a
production capacity limit. Those values require measurement and must not be
invented when answering questions about this example pipeline.
