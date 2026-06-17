- use astral uv, ruff, ty tooling
- the upstream SDK (`msads`) is synchronous (requests/urllib3); tools are sync by design and
  FastMCP runs them in a worker thread. Do not bolt async onto the SDK calls.
- writes are gated by `READ_ONLY`; write tools are *not registered* when it is true.
