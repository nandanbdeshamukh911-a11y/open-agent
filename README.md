# Open Agent

Open Agent is a local chat and coding assistant for an OpenAI-compatible model server. Start a conversation without selecting a project, or open the coding workspace to plan a change, approve actions, and review test results. SQLite stores conversations, tasks, approvals, preferences, and tool metadata in the local `data/` directory.

## Start on Windows

1. Install Python 3.12, Node.js 24, Git, and a local model server. If you use Ollama, start it and check that your model appears in `ollama list`.
2. In PowerShell, from this folder, run:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   npm --prefix frontend ci
   npm --prefix frontend run build
   .\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
   ```

3. Open `http://127.0.0.1:8765` in your browser. Leave the terminal open while using the app. Stop it with Ctrl+C.
4. In **Settings**, check the connection and model name. The app discovers the first available GPT-OSS model from `http://127.0.0.1:11434/v1` by default. Another local OpenAI-compatible endpoint can be configured there. The model must support chat completions and follow the agent's JSON instructions; a model is never downloaded automatically.
5. Start in **Chat**. Choose Calculator, Format JSON, or Text statistics under **Tool** to run a local utility even when the model is offline. Conversations are saved and can be reopened.
6. In **Workspace**, enter an existing project directory and your task. Open **Approvals** to review each proposed edit, command, or download. Give the agent clarifications from the task view when it is paused or blocked.

For development, run `npm --prefix frontend run dev` in a separate terminal; the Vite server proxies `/api` to the backend. Use the production URL above for ordinary use. Run tests with `python -m pytest -q`.

## How it works and current limits

- The agent plans, gathers evidence, proposes one action at a time, reviews each requirement against recorded results, and separately checks its draft final response. An unsuccessful review can trigger a focused repair, up to the configured retry limit. A model's review is not a guarantee; inspect the evidence and output yourself. Model errors and unavailable tests are reported as blockers.
- File reads support inclusive line ranges. A targeted edit replaces one exact match after approval and rejects changes to a file made since the proposal. Git status and diff use fixed commands with approval. Approved terminal commands run with your user account's permissions and can affect paths outside the project. Pausing or cancelling cannot stop a command already executing.
- Restarted tasks are paused. Actions interrupted during execution are marked as uncertain and must be inspected and acknowledged before resuming; they are not replayed automatically.
- GitHub imports support repository URLs and file URLs in `github.com/owner/repo/blob/branch/path` form. Repository clones require Git. Files are saved in `data/skills`, disabled by default, and never installed or executed automatically. Inspect and enable a root `SKILL.md` to make its content available as untrusted reference material to the agent. Removing an imported tool requires approval. Branch names containing `/` are not supported in file URLs.
- Long-term memory can be added and edited in the Memory screen. Clear preferences stated in your own task messages (such as "I prefer Python") are also saved automatically; the Memory screen shows their source and lets you disable or delete them. Repository text and tool output are never automatically saved as memories. Retrieval prioritizes keyword matches and then recent enabled memories, so it may miss relevant context. Cloud synchronization is not implemented.
- Context and response sizes are limited to suit a laptop. The adapter requests JSON output and low reasoning effort when the runtime supports them, with a larger response budget to leave room for a final action. Large code changes may need to be broken into smaller tasks. The 16 GB RAM configuration may be slow or run out of memory depending on other applications, the model's context size, and GPU offloading.
- The app is intended for one trusted user on one computer. Keep it bound to `127.0.0.1`; it has no account system or remote-access authentication. Do not expose it to the network.

## Development and contributions

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow and checks. The optional `python tests/live_smoke.py` run exercises an isolated task against your configured local model. Its test harness approves only the expected fixture write.

Open Agent is distributed under the [MIT license](LICENSE).
