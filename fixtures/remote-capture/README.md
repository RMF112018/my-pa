# Remote Capture fixtures

These documents model the body an iOS Shortcut sends to the dedicated remote
Capture endpoint. They are synthetic and intentionally contain neither a
credential nor a principal identifier. Authentication belongs in the
`Authorization: ClientCredential …` header at an operator-authorized HTTPS
boundary; this repository does not issue credentials or activate that boundary.
