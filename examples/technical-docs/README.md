# Technical documentation example

The included Markdown files describe a fictional worker. They are original
synthetic fixtures, not documentation of Hilo's own defaults.

Initialize with `python3 scripts/init_config.py --example technical-docs`, add
your model API key to `backend/.env`, and follow the root quick start.
Initialization copies the documents to `knowledge/docs/` without overwriting
existing files and selects this domain profile on a fresh configuration.

Try these questions after indexing:

- What is the retry policy of the example worker?
- How many total attempts can an operation make?
- Does version 1.0 add jitter?
- Compare retryable and non-retryable failures, with source citations.
- What is the maximum indexing throughput? (The sources do not specify one.)

The last two questions exercise evidence coverage and honest handling of gaps.
