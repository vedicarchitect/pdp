## 2024-06-29 - [HIGH] Fix nested secret redaction in logging
**Vulnerability:** The logging mechanism only redacted top-level keys matching secret patterns. Any secrets nested within structures like dictionaries or lists bypassed redaction and were logged in plaintext, exposing sensitive information in logs.
**Learning:** Logging filters need to traverse nested collections deeply to ensure all configurations and payloads are sanitized before logging.
**Prevention:** When developing custom log filters or sanitizers, ensure they apply recursive techniques to traverse composite data types to sanitize all secret-shaped keys completely.
