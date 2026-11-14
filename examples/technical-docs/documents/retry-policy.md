# Example worker: retry policy

This is synthetic documentation for the Hilo example worker, version 1.0.
It describes a fictional service for testing document-grounded answers. These
settings are not Hilo runtime defaults.

## Retry attempts

The example worker retries transient network errors at most three times after
the initial request. An operation can therefore make at most four attempts.
Authentication failures and invalid input are non-retryable errors: the worker
returns them immediately and does not consume the retry budget.

## Retry delay

The first retry waits one second. The delay doubles after each failed retry,
so the three retry delays are one, two, and four seconds. The worker does not
add random jitter in version 1.0. A proposal to add jitter is under discussion;
it has not been implemented and must not be described as current behavior.

## Scope

This policy applies only to the example worker's outbound HTTP requests. It
does not specify database retries or Hilo's own model-provider retry behavior.
