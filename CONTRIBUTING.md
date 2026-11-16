# Contributing to Open Agent

Open an issue with the behavior you observed and a small reproduction. Include the OS and model runtime version when they affect the result. Use disposable sample projects and redact local paths, chat history, credentials, and machine-specific logs.

Create a branch from `main` for a focused change. Keep the approval boundary intact and describe any change to filesystem, network, or command access in the pull request. Run these checks locally before opening it:

```sh
python -m pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
```

The automated suite uses simulated model responses. See the README for optional live-model checks. By submitting a contribution, you agree to license it under the project's MIT license.
