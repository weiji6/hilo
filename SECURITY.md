# Security

Please report vulnerabilities privately using the Security tab of
https://github.com/weiji6/hilo. Do not include credentials, user documents,
or conversation contents in public issues.

The supplied Docker configuration is a local development setup bound to
127.0.0.1. It is not a hardened public hosting configuration. Direct backend
APIs are not a complete authentication/authorization boundary. Before exposing
an installation, add authentication and authorization at the API boundary,
TLS, access controls for external tools, and your own operational controls.

Local sandbox execution runs with the backend process's privileges. The default
configuration includes document retrieval, file reading, shell execution, web fetch,
and image search. Use execution tools only in trusted workflows. Domain profiles
and Skills are administrator configuration, and should be reviewed before installation.
